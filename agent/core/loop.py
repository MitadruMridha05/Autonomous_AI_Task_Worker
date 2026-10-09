'''"""The agent loop: act -> observe -> decide, until the model calls `finish`.

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
        return str(file)'''

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable

from .failures import handle_failure
from .guard import ApprovalPolicy
from .memory import WorkingMemory
from .planner import Goal, Planner
from ..tools.base import Tool, ToolError, ToolRegistry


class Agent:
    """Plan-act-observe agent loop with approvals, retries, verification, and report."""

    def __init__(
        self,
        planner: Planner,
        llm: Any,
        verifier: Any,
        tools: ToolRegistry | dict[str, Any],
        *,
        guard: ApprovalPolicy | None = None,
        approval_callback: Callable[[str, dict], Any] | None = None,
        max_steps: int = 20,
        max_retries_per_action: int = 3,
    ):
        self.planner = planner
        self.llm = llm
        self.verifier = verifier
        self.tools = tools
        self.guard = guard or ApprovalPolicy()
        self.approval_callback = approval_callback
        self.max_steps = max_steps
        self.max_retries_per_action = max_retries_per_action
        self._tool_retries: dict[str, int] = {}

    async def run(self, task: str) -> dict:
        goal: Goal = await _await(self.planner.extract_goal(task))
        plan = await _await(self.planner.make_plan(goal))
        memory = WorkingMemory()
        status = "max_steps_reached"
        final_summary = "The agent reached its step limit before confirming completion."

        # Give the model a concise, current registry description when supported.
        if hasattr(self.llm, "tool_descriptions"):
            self.llm.tool_descriptions = self._describe_tools()

        for step in range(1, self.max_steps + 1):
            observation = memory.get_context()
            try:
                tool_call = await _await(self.llm.decide_next_action(goal, plan, observation, memory))
                name, arguments = _normalise_tool_call(tool_call)
                if name == "ask_user":
                    status = "needs_user_input"
                    final_summary = str(arguments.get("question") or tool_call.get("rationale") or "The task needs clarification.")
                    memory.log_action(name, final_summary, arguments)
                    break
                if name == "finish":
                    status = "finished"
                    final_summary = str(arguments.get("summary", "The agent requested completion verification."))
                    memory.log_action(name, final_summary, arguments)
                    break

                approval = self.guard.should_approve(name, arguments)
                if approval == "ask":
                    if self.approval_callback is None:
                        status = "approval_required"
                        final_summary = f"Human approval is required before executing {name}."
                        memory.log_action("approval_required", final_summary, {"tool": name, **arguments})
                        break
                    approved = await _await(self.approval_callback(name, arguments))
                    if not approved:
                        status = "approval_denied"
                        final_summary = f"Approval was not granted for {name}; the action was not executed."
                        memory.log_action("approval_denied", final_summary, {"tool": name, **arguments})
                        break

                try:
                    result = await self.execute(name, arguments)
                    self._tool_retries[name] = 0
                    memory.log_action(name, result, arguments)
                    self._update_memory_from_result(memory, name, result)
                    if isinstance(result, dict) and result.get("page_text"):
                        memory.update_page_text(str(result["page_text"]))
                    elif isinstance(result, str) and any(token in name for token in ("navigate", "click", "fill_form")):
                        memory.update_page_text(result)
                except Exception as exc:
                    retry_number = self._tool_retries.get(name, 0) + 1
                    decision = handle_failure(exc, name, retry_number, self.max_retries_per_action)
                    memory.log_action(name, {"error": str(exc), "decision": decision}, arguments)
                    if decision["action"] == "retry":
                        self._tool_retries[name] = retry_number
                        await asyncio.sleep(float(decision.get("backoff_seconds", 1)))
                        continue
                    if decision["action"] == "ask_user":
                        status = "needs_user_input"
                        final_summary = decision["message"]
                        break
                    if decision["action"] == "skip":
                        continue
                    status = "failed"
                    final_summary = decision["message"]
                    break

            except Exception as exc:
                status = "failed"
                final_summary = f"Agent decision failed: {exc}"
                memory.log_action("agent_error", str(exc))
                break

        try:
            verification = await _await(self.verifier.check_success(goal, memory))
        except Exception as exc:
            verification = {"success": False, "results": {}, "error": str(exc)}
        verified_success = bool(verification.get("success", False)) if isinstance(verification, dict) else False
        if verified_success:
            status = "success"
            final_summary = "The goal was verified against the application API."
        elif status == "finished":
            status = "unverified"
            final_summary = "The agent stopped, but the requested outcome could not be verified."

        return self.make_report(goal, plan, memory, status, final_summary, verification)

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        if isinstance(self.tools, ToolRegistry):
            tool = self.tools.get(tool_name)
            return await _await(tool.run(**arguments))
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            if isinstance(tool, Tool):
                return await _await(tool.run(**arguments))
            if hasattr(tool, "run"):
                return await _await(tool.run(**arguments))
            if callable(tool):
                return await _await(tool(**arguments))
        # Support a BrowserTool object registered under "browser".
        if "." in tool_name:
            prefix, method_name = tool_name.split(".", 1)
            obj = self.tools.get(prefix) if isinstance(self.tools, dict) else None
            if obj is not None and hasattr(obj, method_name):
                return await _await(getattr(obj, method_name)(**arguments))
        raise ToolError(f"Unknown tool: {tool_name}")

    def make_report(self, goal, plan, memory, status, summary, verification) -> dict:
        return {
            "status": status,
            "summary": summary,
            "goal": goal.model_dump() if hasattr(goal, "model_dump") else str(goal),
            "plan": plan,
            "verification": verification,
            "facts": memory.facts,
            "actions": memory.actions,
        }

    def _describe_tools(self) -> list[dict]:
        if isinstance(self.tools, ToolRegistry):
            return self.tools.describe()
        descriptions = []
        for key, value in self.tools.items():
            if hasattr(value, "describe"):
                descriptions.extend(value.describe())
            elif key == "browser":
                descriptions.extend([
                    {"name": "browser.navigate", "description": "Navigate to a URL; returns visible text and interactive controls.", "arguments": {"url": "string"}},
                    {"name": "browser.click", "description": "Click a visible interactive control using its returned selector.", "arguments": {"selector": "string"}},
                    {"name": "browser.fill_form", "description": "Fill visible form fields by selector.", "arguments": {"fields": "object"}},
                    {"name": "browser.screenshot", "description": "Save a screenshot and return its path.", "arguments": {}},
                ])
            else:
                descriptions.append({"name": key, "description": getattr(value, "description", ""), "arguments": getattr(value, "schema", {})})
        return descriptions

    @staticmethod
    def _update_memory_from_result(memory: WorkingMemory, tool_name: str, result: Any) -> None:
        if isinstance(result, dict):
            facts = result.get("facts")
            if isinstance(facts, dict):
                for key, value in facts.items():
                    memory.remember_fact(str(key), value)
            for key in ("customer_id", "order_id"):
                if key in result:
                    memory.remember_fact(key, result[key])


async def _await(value):
    return await value if inspect.isawaitable(value) else value


def _normalise_tool_call(value):
    if isinstance(value, dict):
        name = value.get("name")
        arguments = value.get("arguments", {})
    else:
        name = getattr(value, "name", None)
        arguments = getattr(value, "arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        raise ToolError("LLM returned an invalid tool call; expected name and object arguments.")
    return name, arguments
