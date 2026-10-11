"""Live-provider smoke evaluation for OpsPilot.

Unlike evals/run_evals.py, this runner uses a configured OpenAI-compatible
provider and records the complete agent trace. It intentionally keeps the task
set small and safe; risky actions use auto approval only inside the seeded local
mock application.
"""
from __future__ import annotations
import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from app.seed import reset_db
from agent.config import load_env
from agent.core.guard import ApprovalPolicy
from agent.core.llm import LLMError, make_llm
from agent.core.loop import Agent
from agent.core.verifier import BackendVerifier
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry
from tests.helpers import LiveServer

TASKS = [
    {
        "id": "live_inspect_latest_order",
        "description": "Find Priya Sharma's latest order and report its current status and total. Do not change anything.",
        "expected": "completed",
    },
    {
        "id": "live_refund_and_notify",
        "description": "Priya Sharma received a damaged item. Refund her latest delivered order and send her a concise email explaining that the refund was issued. Verify both outcomes.",
        "expected": "completed",
    },
    {
        "id": "live_ambiguous_customer",
        "description": "Refund John's order. If more than one John exists, do not guess; ask me which customer I mean.",
        "expected": "needs_clarification",
    },
]


def run_live(tasks: list[dict[str, Any]], *, db_path: str, output: str | Path, model: str, max_steps: int = 20) -> list[dict[str, Any]]:
    os.environ["OPSPILOT_DB"] = db_path
    records: list[dict[str, Any]] = []
    with LiveServer() as server:
        client = OpsPilotClient(server.url)
        for task in tasks:
            reset_db(db_path)
            registry = ToolRegistry()
            registry.register_all(build_api_tools(client))
            started = time.perf_counter()
            try:
                llm = make_llm("openai_compat", model)
                agent = Agent(
                    llm,
                    registry,
                    ApprovalPolicy("auto"),
                    ask_user=None,
                    max_steps=max_steps,
                    runs_dir="runs/live",
                    verifier=BackendVerifier(client),
                )
                result = agent.run(task["description"])
                records.append({
                    "task_id": task["id"],
                    "description": task["description"],
                    "expected_status": task["expected"],
                    "status": result.status,
                    "passed": result.status == task["expected"],
                    "steps": result.steps,
                    "usage": result.usage,
                    "duration_s": round(time.perf_counter() - started, 3),
                    "model": model,
                    "trace_path": result.trace_path,
                    "trace": result.trace,
                    "summary": result.summary,
                    "evidence": result.evidence,
                })
            except (LLMError, Exception) as exc:
                records.append({
                    "task_id": task["id"], "description": task["description"],
                    "expected_status": task["expected"], "status": "error", "passed": False,
                    "duration_s": round(time.perf_counter() - started, 3), "model": model,
                    "error": f"{type(exc).__name__}: {exc}",
                })
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("LIVE_LLM_MODEL", "gpt-5-mini"))
    parser.add_argument("--db", default="data/live-eval.db")
    parser.add_argument("--output", default="runs/live_eval_results.json")
    args = parser.parse_args()
    load_env()
    records = run_live(TASKS, db_path=args.db, output=args.output, model=args.model)
    print(json.dumps({
        "model": args.model,
        "passed": sum(bool(record.get("passed")) for record in records),
        "total": len(records),
        "output": args.output,
        "tasks": [{"id": r["task_id"], "status": r["status"], "passed": r.get("passed", False), "steps": r.get("steps")} for r in records],
    }, indent=2))
    return 0 if all(record.get("passed") for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
