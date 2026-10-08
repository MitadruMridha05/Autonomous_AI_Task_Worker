"""Command-line interface.

    python -m agent.cli "Priya Sharma got a damaged item. Refund her latest order and let her know."
    python -m agent.cli --auto-approve "..."      # skip the y/N prompts (demos, CI)
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_env, opspilot_url
from .core.guard import ApprovalPolicy
from .core.llm import LLMError, make_llm
from .core.loop import Agent
from .tools.api_client import OpsPilotClient
from .tools.api_tools import build_api_tools
from .tools.base import Tool, ToolError
from .tools.registry import ToolRegistry


def _short(value, limit: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def print_event(e: dict) -> None:
    kind = e["kind"]
    if kind == "llm" and e["text"].strip():
        print(f"  [agent] {_short(e['text'].strip(), 300)}")
    elif kind == "tool_call":
        args = ", ".join(f"{k}={_short(repr(v), 60)}" for k, v in e["arguments"].items())
        print(f"  -> {e['name']}({args})")
    elif kind == "tool_result":
        print(f"     {'ok' if e['ok'] else 'ERROR'}: {_short(e['preview'])}")
    elif kind == "approval":
        print(f"     approval: {'APPROVED' if e['approved'] else 'DENIED'} ({e['how']})")
    elif kind == "nudge":
        print("  [loop] model replied without a tool call; nudging it to use tools / finish")
    elif kind == "error":
        print(f"  [error] {e['message']}")


def ask_human_to_approve(tool: Tool, arguments: dict, rationale: str) -> bool:
    print("\n" + "=" * 60 + "\nAPPROVAL REQUIRED\n" + "=" * 60)
    print(f"Action : {tool.name}")
    for key, value in arguments.items():
        print(f"  {key}: {value}")
    if rationale:
        print(f"Agent  : {rationale}")
    try:
        return input("Approve this action? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def ask_human_question(question: str) -> str:
    print("\n" + "=" * 60 + "\nAGENT NEEDS CLARIFICATION\n" + "=" * 60)
    print(question)
    try:
        return input("> ").strip()
    except EOFError:
        return ""


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # avoid crashes on Windows consoles
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    load_env()
    p = argparse.ArgumentParser(description="OpsPilot: an autonomous AI task worker")
    p.add_argument("task", nargs="+", help="The task, in plain English")
    p.add_argument("--provider", help="anthropic | openai_compat (default: $LLM_PROVIDER or anthropic)")
    p.add_argument("--model", help="Model name (default: $LLM_MODEL)")
    p.add_argument("--url", default=opspilot_url(), help="Base URL of the mock app")
    p.add_argument("--auto-approve", action="store_true", help="Approve risky actions without asking")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--runs-dir", default="runs", help="Where run traces (JSON) are saved")
    args = p.parse_args(argv)
    task = " ".join(args.task)

    client = OpsPilotClient(args.url)
    try:
        client.health()
    except ToolError as exc:
        print(f"Cannot reach the mock app at {args.url}: {exc.message}\n"
              f"Start it first:  uvicorn app.main:app --port 8000", file=sys.stderr)
        return 2
    try:
        llm = make_llm(args.provider, args.model)
    except LLMError as exc:
        print(f"LLM setup problem: {exc}", file=sys.stderr)
        return 2

    registry = ToolRegistry()
    registry.register_all(build_api_tools(client))
    guard = ApprovalPolicy("auto" if args.auto_approve else "ask", ask_human_to_approve)
    agent = Agent(llm, registry, guard, ask_human_question, max_steps=args.max_steps,
                  runs_dir=args.runs_dir, on_event=print_event)

    print(f"Task: {task}\nModel: {llm.provider}/{llm.model}\n")
    result = agent.run(task)

    print("\n" + "=" * 60 + "\nRESULT\n" + "=" * 60)
    print(f"Status  : {result.status}\nSummary : {result.summary}")
    if result.evidence:
        print("Evidence:")
        for line in result.evidence:
            print(f"  - {line}")
    u = result.usage
    print(f"\nSteps: {result.steps} | LLM calls: {u['llm_calls']} | tool calls: {u['tool_calls']} | "
          f"tokens in/out: {u['input_tokens']}/{u['output_tokens']} | {result.duration_s}s")
    if result.trace_path:
        print(f"Trace saved: {result.trace_path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
