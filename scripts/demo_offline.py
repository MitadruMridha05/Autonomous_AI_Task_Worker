"""Run a deterministic offline demo and generate a concise evidence bundle."""
from __future__ import annotations

import argparse
import json
import os

from evals.report import build_report
from evals.run_evals import load_tasks, run_evaluations
from tests.helpers import LiveServer


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic offline demo scenarios")
    parser.add_argument("--tasks", default="evals/tasks/day3_tasks.yaml")
    parser.add_argument("--db", default=os.getenv("OPSPILOT_DB", "data/opspilot-eval.db"))
    parser.add_argument("--output", default="runs/eval_results.json")
    parser.add_argument("--report-dir", default="runs/report")
    args = parser.parse_args()
    os.environ["OPSPILOT_DB"] = args.db

    with LiveServer() as server:
        records = run_evaluations(load_tasks(args.tasks), db_path=args.db, output=args.output, base_url=server.url)
    report_md, report_chart = build_report(args.output, args.report_dir)

    passed = sum(1 for r in records if r["passed"])
    summary = {
        "mode": "deterministic_offline",
        "tasks_passed": passed,
        "tasks_total": len(records),
        "results_path": args.output,
        "report_markdown": str(report_md),
        "report_chart": str(report_chart),
        "scenarios": [
            {
                "task_id": r["task_id"],
                "status": r["status"],
                "passed": r["passed"],
                "retries": r["retries"],
                "verification_status": r["verification_status"],
                "final_state": r["final_state"],
            }
            for r in records
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
