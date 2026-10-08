"""The agent loop: act -> observe -> decide, until the model calls `finish`.

    task -> [ LLM decides ] -> tool call(s) -> [ guard / registry executes ] -> result back to LLM -> ...

Design notes
  * The loop is generic. It knows nothing about refunds or customers; all domain knowledge lives
    in the tools and the system prompt.
  * Nothing a tool does can crash the loop: failures come back as structured error results.
  * Every event (LLM turn, tool call, approval, result) is appended to a trace that is saved as JSON.
    Day 3 turns these traces into MLflow artifacts and metrics.
  * Day 2 plugs the verifier in at the end of run(): a "completed" claim will be checked against the
    backend state before it is reported as success.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry
from .control import ASK_USER, CONTROL_TOOLS, FINISH, FinishArgs
from .guard import ApprovalPolicy
from .llm import LLMClient, LLMError

PROMPT_VERSION = "system_v1"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / f"{PROMPT_VERSION}.md"
MAX_TOOL_CHARS = 6000  # keeps one huge tool result from flooding the context window
MAX_NUDGES = 2         # times we remind a text-only model to use tools / call finish
SUCCESS_STATUSES = ("completed", "no_action_needed")


@dataclass
class RunResult:
    run_id: str
    task: str
    status: str
    summary: str
    evidence: list[str]
    steps: int
    usage: dict[str, int]
    duration_s: float
    model: str
    prompt_version: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    trace_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in SUCCESS_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("{{today}}", date.today().isoformat())


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        guard: ApprovalPolicy | None = None,
        ask_user: Callable[[str], str] | None = None,
        *,
        max_steps: int = 20,
        runs_dir: str | Path | None = "runs",
        on_event: Callable[[dict], None] | None = None,
    ):
        self.llm, self.registry = llm, registry
        self.guard = guard or ApprovalPolicy("deny")
        self.ask_user = ask_user
        self.max_steps, self.runs_dir, self.on_event = max_steps, runs_dir, on_event
        self.control = ToolRegistry()
        self.control.register_all(CONTROL_TOOLS)
        self._trace: list[dict[str, Any]] = []
        self._t0 = 0.0

    # ------------------------------------------------------------ public API
    def run(self, task: str) -> RunResult:
        run_id = uuid.uuid4().hex[:8]
        self._trace, self._t0 = [], time.perf_counter()
        system = load_system_prompt()
        specs = self.registry.specs() + [t.spec() for t in CONTROL_TOOLS]
        history: list[dict] = [{"role": "user", "content": f"Task: {task}"}]
        usage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "tool_calls": 0}
        status, summary, evidence, steps, nudges = "failed", "", [], 0, 0
        self._emit("start", task=task, model=self.llm.model, provider=self.llm.provider, prompt_version=PROMPT_VERSION)

        for step in range(1, self.max_steps + 1):
            steps = step
            try:
                resp = self.llm.generate(system, history, specs)
            except LLMError as exc:
                summary = f"LLM error: {exc}"
                self._emit("error", step=step, message=summary)
                break
            usage["llm_calls"] += 1
            usage["input_tokens"] += resp.usage.get("input_tokens", 0)
            usage["output_tokens"] += resp.usage.get("output_tokens", 0)
            self._emit("llm", step=step, text=resp.text, usage=resp.usage,
                       tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in resp.tool_calls])
            history.append({"role": "assistant", "text": resp.text, "tool_calls": [asdict(tc) for tc in resp.tool_calls]})

            if not resp.tool_calls:
                if nudges < MAX_NUDGES:
                    nudges += 1
                    history.append({"role": "user", "content": (
                        "You must act through tools. If the task is complete, impossible, or needs "
                        "clarification, call `finish` with the right status. Do not reply with plain text only.")})
                    self._emit("nudge", step=step, count=nudges)
                    continue
                summary = "The model stopped without calling finish."
                break

            results: list[dict] = []
            final: FinishArgs | None = None
            for tc in resp.tool_calls:
                usage["tool_calls"] += 1
                if final is not None:  # `finish` already seen this turn: still answer every call, but don't act
                    content, is_error = json.dumps({"ok": False, "error": {
                        "type": "skipped", "message": "Run already finished; call not executed."}}), True
                else:
                    content, is_error, fin = self._handle_call(tc.name, tc.arguments, resp.text, step)
                    final = fin or final
                results.append({"tool_call_id": tc.id, "name": tc.name, "content": content, "is_error": is_error})
            history.append({"role": "tool", "results": results})

            if final is not None:
                status, summary, evidence = final.status, final.summary, final.evidence
                break
        else:
            status, summary = "max_steps_exceeded", f"Stopped after {self.max_steps} steps without finishing."

        duration = round(time.perf_counter() - self._t0, 2)
        self._emit("finish", status=status, summary=summary)
        result = RunResult(run_id, task, status, summary, evidence, steps, usage, duration,
                           self.llm.model, PROMPT_VERSION, list(self._trace))
        result.trace_path = self._save(result)
        return result

    # --------------------------------------------------------------- internals
    def _handle_call(self, name: str, args: dict, rationale: str, step: int) -> tuple[str, bool, FinishArgs | None]:
        self._emit("tool_call", step=step, name=name, arguments=args)
        final: FinishArgs | None = None

        if name in (FINISH, ASK_USER):
            tool = self.control.get(name)
            bad = self.control.check_arguments(tool, args)
            if bad:
                res = ToolResult(False, error=bad)
            elif name == FINISH:
                final = FinishArgs(**args)
                res = ToolResult(True, data={"recorded": True})
            elif self.ask_user is None:
                res = ToolResult(False, error={"type": "no_user_available", "retryable": False, "message": (
                    "No user is available to answer. Call finish with status needs_clarification "
                    "and put your question in the summary.")})
            else:
                answer = self.ask_user(args["question"])
                self._emit("ask_user", step=step, question=args["question"], answer=answer)
                res = ToolResult(True, data={"user_answer": answer})
        else:
            tool = self.registry.get(name)
            if tool is not None and tool.risky:
                bad = self.registry.check_arguments(tool, args)  # don't bother the human with a call that can't run
                if bad:
                    res = ToolResult(False, error=bad)
                else:
                    approved, how = self.guard.approve(tool, args, rationale)
                    self._emit("approval", step=step, name=name, approved=approved, how=how)
                    res = self.registry.execute(name, args) if approved else ToolResult(False, error={
                        "type": "denied_by_user", "retryable": False,
                        "message": "The user declined this action. Do not retry it or work around it; "
                                   "call finish with status 'declined'."})
            else:
                res = self.registry.execute(name, args)

        content = res.to_json()
        if len(content) > MAX_TOOL_CHARS:
            content = content[:MAX_TOOL_CHARS] + f'... [truncated {len(content) - MAX_TOOL_CHARS} chars]'
        self._emit("tool_result", step=step, name=name, ok=res.ok, error=res.error, preview=content[:300])
        return content, not res.ok, final

    def _emit(self, kind: str, **data: Any) -> None:
        event = {"t": round(time.perf_counter() - self._t0, 3), "kind": kind, **data}
        self._trace.append(event)
        if self.on_event:
            self.on_event(event)

    def _save(self, result: RunResult) -> str | None:
        if not self.runs_dir:
            return None
        path = Path(self.runs_dir)
        path.mkdir(parents=True, exist_ok=True)
        file = path / f"{datetime.now():%Y%m%d-%H%M%S}_{result.run_id}.json"
        file.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        return str(file)
