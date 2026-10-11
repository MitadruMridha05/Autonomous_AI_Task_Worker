import csv

from agent.core.control import FinishArgs
from agent.core.verifier import BackendVerifier
from agent.tools.api_client import OpsPilotClient
from agent.tools.day2_tools import build_day2_invoice_tools
from agent.tools.registry import ToolRegistry


def _trace(task: str, calls: list[tuple[str, dict]]) -> list[dict]:
    events: list[dict] = [{"kind": "start", "task": task}]
    for name, arguments in calls:
        events.append({"kind": "tool_call", "name": name, "arguments": arguments})
    return events


def _finish_completed() -> FinishArgs:
    return FinishArgs(status="completed", summary="done", evidence=[])


def test_invoice_export_verification_success(http, tmp_path):
    client = OpsPilotClient(http=http)
    registry = ToolRegistry()
    registry.register_all(build_day2_invoice_tools(client))
    destination = tmp_path / "overdue.csv"
    result = registry.execute("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30})
    assert result.ok

    check = BackendVerifier(client)(
        _finish_completed(),
        _trace("Export invoices overdue by more than 30 days to CSV.", [("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30})]),
    )
    assert check["success"] is True


def test_invoice_export_verification_fails_when_artifact_missing(http, tmp_path):
    missing = tmp_path / "missing.csv"
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Export invoices overdue by more than 30 days to CSV.", [("export_overdue_invoices", {"path": str(missing), "overdue_days_gt": 30})]),
    )
    assert check["success"] is False
    assert "artifact does not exist" in check["summary"]


def test_invoice_export_verification_fails_on_wrong_headers(http, tmp_path):
    path = tmp_path / "bad_headers.csv"
    path.write_text("invoice_id,customer_id\n5001,1\n", encoding="utf-8")
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Export invoices overdue by more than 30 days to CSV.", [("export_overdue_invoices", {"path": str(path), "overdue_days_gt": 30})]),
    )
    assert check["success"] is False
    assert "headers are incorrect" in check["summary"]


def test_invoice_export_verification_fails_on_wrong_row_count(http, tmp_path):
    client = OpsPilotClient(http=http)
    registry = ToolRegistry()
    registry.register_all(build_day2_invoice_tools(client))
    destination = tmp_path / "overdue.csv"
    assert registry.execute("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30}).ok

    lines = destination.read_text(encoding="utf-8").splitlines()
    destination.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    check = BackendVerifier(client)(
        _finish_completed(),
        _trace("Export invoices overdue by more than 30 days to CSV.", [("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30})]),
    )
    assert check["success"] is False
    assert "row count is incorrect" in check["summary"]


def test_invoice_export_verification_fails_on_wrong_invoice_ids(http, tmp_path):
    client = OpsPilotClient(http=http)
    registry = ToolRegistry()
    registry.register_all(build_day2_invoice_tools(client))
    destination = tmp_path / "overdue.csv"
    assert registry.execute("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30}).ok

    with destination.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = reader.fieldnames
    rows[0]["id"] = "999999"
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    check = BackendVerifier(client)(
        _finish_completed(),
        _trace("Export invoices overdue by more than 30 days to CSV.", [("export_overdue_invoices", {"path": str(destination), "overdue_days_gt": 30})]),
    )
    assert check["success"] is False
    assert "identifiers do not match" in check["summary"]


def test_refund_verification_success(http):
    http.post("/api/orders/1004/refund", json={"reason": "Damaged item"})
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Refund order 1004.", [("issue_refund", {"order_id": 1004, "reason": "Damaged item"})]),
    )
    assert check["success"] is True


def test_refund_verification_fails_when_order_or_refund_missing(http):
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Refund order 1004.", [("issue_refund", {"order_id": 1004, "reason": "Damaged item"})]),
    )
    assert check["success"] is False
    assert "not refunded" in check["summary"] or "missing" in check["summary"]


def test_notification_verification_success(http):
    payload = {"subject": "Your refund has been issued", "body": "Refund complete."}
    http.post("/api/customers/1/notifications", json=payload)
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Send a notification email to customer 1.", [("send_customer_email", {"customer_id": 1, **payload})]),
    )
    assert check["success"] is True


def test_notification_verification_fails_on_missing_or_mismatched_record(http):
    check_missing = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Send a notification email to customer 1.", [("send_customer_email", {"customer_id": 1, "subject": "A", "body": "B"})]),
    )
    assert check_missing["success"] is False
    assert "not found" in check_missing["summary"] or "could not read notifications" in check_missing["summary"]

    http.post("/api/customers/1/notifications", json={"subject": "Different", "body": "Different"})
    check_mismatch = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Send a notification email to customer 1.", [("send_customer_email", {"customer_id": 1, "subject": "Expected", "body": "Expected"})]),
    )
    assert check_mismatch["success"] is False
    assert "matching notification" in check_mismatch["summary"]


def test_unknown_outcome_fails_closed(http):
    check = BackendVerifier(OpsPilotClient(http=http))(
        _finish_completed(),
        _trace("Summarize yesterday's dashboard metrics.", []),
    )
    assert check["success"] is False
    assert "unsupported or unknown requested outcome" in check["summary"]