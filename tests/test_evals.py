from pathlib import Path
import json
from evals.report import build_report
from evals.run_evals import load_tasks, run_evaluations
from tests.helpers import LiveServer


def test_day3_manifest_has_nine_reproducible_scenarios():
    tasks = load_tasks("evals/tasks/day3_tasks.yaml")
    assert len(tasks) == 9
    assert {task["scenario"] for task in tasks} >= {"ambiguous_john", "ui_failure_api_recovery", "malformed_arguments"}


def test_harness_runs_a_real_http_scenario(tmp_path, monkeypatch):
    db = str(tmp_path / "eval.db")
    monkeypatch.setenv("OPSPILOT_DB", db)
    task = load_tasks("evals/tasks/day3_tasks.yaml")[3:4]  # already-refunded no-op
    with LiveServer() as server:
        records = run_evaluations(task, db_path=db, output=tmp_path / "results.json", base_url=server.url)
    assert records[0]["passed"] is True
    assert records[0]["status"] == "no_action_needed"
    assert records[0]["verification_status"] in {"passed", "not_requested"}
    assert isinstance(records[0]["tool_results"], list)
    assert isinstance(records[0]["final_state"], dict)


def test_report_contains_summary_and_chart(tmp_path):
    result_file = tmp_path / "results.json"
    result_file.write_text(json.dumps([{"task_id": "x", "status": "completed", "expected_status": "completed", "passed": True, "steps": 2, "duration_s": 0.1, "retries": 0, "verification_status": "passed", "failure_reason": None}]), encoding="utf-8")
    md, chart = build_report(result_file, tmp_path / "report")
    assert "Success rate: 100.0%" in md.read_text(encoding="utf-8")
    assert "Verification" in md.read_text(encoding="utf-8")
    assert chart.exists()


def test_export_scenario_records_final_csv_state(tmp_path, monkeypatch):
    db = str(tmp_path / "eval.db")
    monkeypatch.setenv("OPSPILOT_DB", db)
    task = load_tasks("evals/tasks/day3_tasks.yaml")[1:2]  # export_overdue_invoices
    with LiveServer() as server:
        records = run_evaluations(task, db_path=db, output=tmp_path / "results.json", base_url=server.url)
    state = records[0]["final_state"]["invoice_export"]
    assert state["rows"] == 3
    assert state["path"].endswith("runs/eval_overdue.csv")
