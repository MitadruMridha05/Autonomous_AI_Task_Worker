"""Run the deterministic Day 3 evaluation suite.

The suite uses the real FastAPI application, HTTP client, SQLite database, tool
registry, approval policy, and agent loop. Only the model is scripted so runs
are safe and reproducible without credentials.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
from typing import Any
import yaml
from app.seed import reset_db
from agent.core.guard import ApprovalPolicy
from agent.core.loop import Agent
from agent.core.scripted import ScriptedLLM
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.day2_tools import build_day2_invoice_tools
from agent.tools.registry import ToolRegistry
from tests.helpers import task1_steps, call, last_error

def load_tasks(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("Task file must contain a top-level tasks list")
    return data["tasks"]

def _steps(scenario: str) -> tuple[list, str]:
    if scenario == "refund_priya": return task1_steps(), "auto"
    if scenario == "export_invoices": return [call("export_overdue_invoices", {"path": "runs/eval_overdue.csv", "overdue_days_gt": 30}), call("finish", {"status": "completed", "summary": "Exported overdue invoices.", "evidence": ["3 rows exported"]})], "auto"
    if scenario == "ambiguous_john": return [call("search_customers", {"query": "John"}), call("ask_user", {"question": "Which customer: John Mathew (id 2) or John D'Souza (id 3)?"}), call("finish", {"status": "needs_clarification", "summary": "A customer choice is required.", "evidence": []})], "auto"
    if scenario == "already_refunded": return [call("get_order", {"order_id": 1005}), call("finish", {"status": "no_action_needed", "summary": "Order 1005 was already refunded.", "evidence": ["Order 1005 status=refunded"]})], "auto"
    if scenario == "non_refundable": return [call("issue_refund", {"order_id": 1006, "reason": "Customer request"}), lambda h: call("finish", {"status": "failed", "summary": "Order is not delivered and cannot be refunded.", "evidence": [last_error(h).get("code", "not_refundable")]}),], "auto"
    if scenario == "ui_failure_api_recovery": return [call("issue_refund", {"order_id": 1004, "reason": "Temporary UI failure recovery"}), call("get_order", {"order_id": 1004}), call("finish", {"status": "completed", "summary": "Refund completed through the API fallback.", "evidence": ["Order 1004 status=refunded"]})], "auto"
    if scenario == "approval_declined": return task1_steps()[:4] + [call("finish", {"status": "declined", "summary": "Refund declined; no state changed.", "evidence": []})], "deny"
    if scenario == "malformed_arguments": return [call("issue_refund", {"order_id": "not-an-id", "reason": "x"}), lambda h: call("finish", {"status": "failed", "summary": "The refund request was invalid.", "evidence": [last_error(h)["type"]]})], "auto"
    if scenario == "step_limit": return [call("get_order", {"order_id": 1004})] * 3, "auto"
    raise ValueError(f"Unknown evaluation scenario: {scenario}")

def _check_expected(task: dict, result, client: OpsPilotClient) -> tuple[bool, list[str]]:
    expected, evidence = task.get("expected", {}), []
    ok = result.status == task["expected_status"]
    if "order_id" in expected:
        order = client.get_order(expected["order_id"]); actual = order.get("status")
        evidence.append(f"order {expected['order_id']} status={actual}"); ok = ok and actual == expected.get("order_status", actual)
    if "notification_customer_id" in expected:
        notifications = client._request("GET", f"/api/customers/{expected['notification_customer_id']}/notifications")
        ok = ok and bool(notifications); evidence.append(f"notifications={len(notifications)}")
    if "rows" in expected:
        csv_path = Path("runs/eval_overdue.csv"); rows = sum(1 for _ in csv_path.open(encoding="utf-8")) - 1 if csv_path.exists() else -1
        ok = ok and rows == expected["rows"]; evidence.append(f"csv_rows={rows}")
    if expected.get("question_required"): ok = ok and any(e.get("kind") == "ask_user" for e in result.trace)
    return ok, evidence

def run_evaluations(tasks: list[dict], *, db_path: str, output: str | Path = "runs/eval_results.json", base_url: str) -> list[dict]:
    client = OpsPilotClient(base_url); records = []
    for task in tasks:
        reset_db(db_path); scenario = task["scenario"]; steps, mode = _steps(scenario)
        registry = ToolRegistry(); registry.register_all(build_api_tools(client))
        if scenario == "export_invoices": registry.register_all(build_day2_invoice_tools(client))
        if scenario == "ui_failure_api_recovery":
            os.environ["OPSPILOT_UI_REFUND_FAILURES"] = "1"
            from app import chaos
            chaos.reset()
            injected = client._http.post("/orders/1004/refund", data={"reason": "Injected UI failure"}, follow_redirects=False)
            if injected.status_code != 500:
                raise AssertionError(f"UI failure injection did not return 500: {injected.status_code}")
            os.environ.pop("OPSPILOT_UI_REFUND_FAILURES", None)
        agent = Agent(ScriptedLLM(steps), registry, ApprovalPolicy(mode), lambda _: "", max_steps=3 if scenario == "step_limit" else 20, runs_dir="runs")
        started = time.perf_counter(); result = agent.run(task["description"]); passed, evidence = _check_expected(task, result, client)
        records.append({"task_id": task["id"], "scenario": scenario, "status": result.status, "expected_status": task["expected_status"], "passed": passed, "steps": result.steps, "tool_calls": result.usage["tool_calls"], "duration_s": round(time.perf_counter() - started, 4), "retries": sum(1 for e in result.trace if e.get("kind") == "tool_result" and (e.get("error") or {}).get("retryable")), "evidence": evidence, "trace_path": result.trace_path})
    out = Path(output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(records, indent=2), encoding="utf-8"); _log_mlflow(records); return records

def _log_mlflow(records: list[dict]) -> None:
    try: import mlflow
    except ImportError: return
    try:
        uri = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///runs/mlflow.db")
        mlflow.set_tracking_uri(uri)
        with mlflow.start_run(run_name="opspilot-day3-evals"):
            mlflow.log_param("task_count", len(records)); mlflow.log_metric("success_rate", sum(r["passed"] for r in records) / len(records))
            for r in records: mlflow.log_metric(f"task_{r['task_id']}_passed", int(r["passed"]))
            path = Path("runs/eval_results.json")
            if path.exists(): mlflow.log_artifact(str(path))
    except Exception as exc:
        # Evaluation correctness must not depend on a tracking server or local DB.
        print(f"MLflow logging unavailable; JSON results retained: {exc}")

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--tasks", default="evals/tasks/day3_tasks.yaml"); p.add_argument("--db", default=os.getenv("OPSPILOT_DB", "data/opspilot-eval.db")); p.add_argument("--output", default="runs/eval_results.json"); a = p.parse_args()
    os.environ["OPSPILOT_DB"] = a.db
    from tests.helpers import LiveServer
    with LiveServer() as server: records = run_evaluations(load_tasks(a.tasks), db_path=a.db, output=a.output, base_url=server.url)
    passed = sum(r["passed"] for r in records); print(json.dumps({"passed": passed, "total": len(records), "output": a.output}, indent=2)); return 0 if passed == len(records) else 1
if __name__ == "__main__": raise SystemExit(main())
