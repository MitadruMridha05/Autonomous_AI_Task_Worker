from pathlib import Path

from agent.tools.api_client import OpsPilotClient
from agent.tools.day2_tools import build_day2_invoice_tools
from agent.tools.files import export_csv
from agent.tools.registry import ToolRegistry


def test_ui_chaos_is_opt_in_and_api_remains_available(http, monkeypatch):
    monkeypatch.setenv("OPSPILOT_UI_REFUND_FAILURES", "1")
    from app import chaos
    chaos.reset()
    failed = http.post("/orders/1004/refund", data={"reason": "damaged"}, follow_redirects=False)
    assert failed.status_code == 500
    # The fallback API path is independent of UI chaos injection.
    recovered = http.post("/api/orders/1004/refund", json={"reason": "damaged"})
    assert recovered.status_code == 201


def test_invoice_tools_export_reproducible_csv(http, tmp_path):
    registry = ToolRegistry()
    registry.register_all(build_day2_invoice_tools(OpsPilotClient(http=http)))
    destination = tmp_path / "overdue.csv"
    result = registry.execute("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30})
    assert result.ok and result.data["rows"] == 3
    lines = destination.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("id,customer_id,customer_name")
    assert len(lines) == 4


def test_empty_csv_requires_explicit_columns(tmp_path):
    output = tmp_path / "empty.csv"
    assert export_csv([], output, fieldnames=["id"]) == str(Path(output).resolve())
    assert output.read_text(encoding="utf-8") == "id\n"
