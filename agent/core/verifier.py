
from __future__ import annotations

import csv
import inspect
from pathlib import Path
from typing import Any

from .memory import WorkingMemory
from .planner import Goal


class Verifier:
    """Verifies outcomes against the application API, not LLM statements."""

    def __init__(self, client: Any):
        self.client = client

    async def _get_json(self, path: str) -> Any:
        response = self.client.get(path)
        if inspect.isawaitable(response):
            response = await response
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        if hasattr(response, "json"):
            data = response.json()
            if inspect.isawaitable(data):
                data = await data
            return data
        return response

    async def verify_refund(self, order_id: int) -> dict:
        order = await self._get_json(f"/api/orders/{int(order_id)}")
        status = str(order.get("status", "")).lower() if isinstance(order, dict) else ""
        refund = order.get("refund") if isinstance(order, dict) else None
        has_refund = status == "refunded" and isinstance(refund, dict) and refund.get("order_id", order_id) == order_id
        return {
            "action": "refund",
            "order_id": int(order_id),
            "success": has_refund,
            "evidence": f"Order status: {status or 'unknown'}; refund record: {'present' if refund else 'missing'}",
        }

    async def verify_notification(self, customer_id: int) -> dict:
        notifs = await self._get_json(f"/api/customers/{int(customer_id)}/notifications")
        if isinstance(notifs, dict):
            notifs = notifs.get("notifications", notifs.get("items", []))
        count = len(notifs) if isinstance(notifs, (list, tuple)) else 0
        return {
            "action": "notification",
            "customer_id": int(customer_id),
            "success": count > 0,
            "evidence": f"Found {count} notifications",
        }

    async def verify_all(self, goal: Goal, memory: WorkingMemory) -> dict:
        results: dict[str, dict] = {}
        facts = memory.facts
        for criterion, expected in goal.success_criteria.items():
            if criterion == "refund_issued":
                order_id = facts.get("order_id")
                if order_id is None:
                    results["refund"] = {"action": "refund", "success": False,
                                         "evidence": "Cannot verify: order_id is missing from memory"}
                else:
                    results["refund"] = await self.verify_refund(int(order_id))
            elif criterion == "notification_sent":
                customer_id = facts.get("customer_id")
                if customer_id is None:
                    results["notification"] = {"action": "notification", "success": False,
                                               "evidence": "Cannot verify: customer_id is missing from memory"}
                else:
                    results["notification"] = await self.verify_notification(int(customer_id))
            else:
                # Unknown criteria must not silently pass.
                results[criterion] = {"action": criterion, "success": False,
                                      "evidence": "No verifier is registered for this success criterion"}
        return results

    async def check_success(self, goal: Goal, memory: WorkingMemory) -> dict:
        results = await self.verify_all(goal, memory)
        success = all(item.get("success", False) for item in results.values()) if results else False
        return {"success": success, "results": results}


class BackendVerifier:
    """Synchronous verifier for the synchronous agent loop and dashboard.

    Contract:
      - verification is outcome-specific (refund, notification, invoice export)
      - every verification is independent from model claims
      - unknown or unverifiable outcomes fail closed
    """

    INVOICE_HEADERS = [
        "id",
        "customer_id",
        "customer_name",
        "amount",
        "issued_date",
        "due_date",
        "status",
        "days_overdue",
    ]

    def __init__(self, client: Any):
        self.client = client

    def __call__(self, finish: Any, trace: list[dict[str, Any]]) -> dict[str, Any]:
        calls = [event for event in trace if event.get("kind") == "tool_call"]
        task = self._task_text(trace)
        requested = self._requested_outcomes(task, calls)
        if not requested:
            return {"success": False, "evidence": [], "summary": "Backend verification failed: unsupported or unknown requested outcome."}

        results: list[dict[str, Any]] = []
        for outcome in sorted(requested):
            if outcome == "refund":
                results.append(self._verify_refund(calls))
            elif outcome == "notification":
                results.append(self._verify_notification(calls))
            elif outcome == "invoice_export":
                results.append(self._verify_invoice_export(calls))
            else:
                return {"success": False, "evidence": [], "summary": f"Backend verification failed: unsupported outcome '{outcome}'."}

        evidence = [line for result in results for line in result.get("evidence", [])]
        failed = next((result for result in results if not result.get("success")), None)
        if failed:
            return {"success": False, "evidence": evidence, "summary": failed.get("summary", "Backend verification failed.")}
        return {"success": True, "evidence": evidence or list(getattr(finish, "evidence", []))}

    @staticmethod
    def _task_text(trace: list[dict[str, Any]]) -> str:
        for event in trace:
            if event.get("kind") == "start":
                return str(event.get("task", ""))
        return ""

    def _requested_outcomes(self, task_text: str, calls: list[dict[str, Any]]) -> set[str]:
        text = (task_text or "").lower()
        outcomes: set[str] = set()
        if "refund" in text:
            outcomes.add("refund")
        if any(token in text for token in ("email", "notification", "notify")):
            outcomes.add("notification")
        if "invoice" in text and "export" in text:
            outcomes.add("invoice_export")
        call_names = {str(event.get("name", "")) for event in calls}
        if "issue_refund" in call_names:
            outcomes.add("refund")
        if "send_customer_email" in call_names:
            outcomes.add("notification")
        if "export_overdue_invoices" in call_names:
            outcomes.add("invoice_export")
        return outcomes

    @staticmethod
    def _ids_from_calls(calls: list[dict[str, Any]], *, name: str, key: str) -> list[int]:
        values: list[int] = []
        for event in calls:
            if event.get("name") != name:
                continue
            raw = event.get("arguments", {}).get(key, "")
            if str(raw).isdigit():
                values.append(int(raw))
        return values

    def _verify_refund(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        refund_ids = self._ids_from_calls(calls, name="issue_refund", key="order_id")
        order_ids = refund_ids or self._ids_from_calls(calls, name="get_order", key="order_id")
        if not order_ids:
            return {
                "success": False,
                "evidence": [],
                "summary": "Backend verification failed: refund outcome is requested but no refundable order identifier was captured.",
            }
        evidence: list[str] = []
        for order_id in order_ids:
            try:
                order = self.client.get_order(order_id)
            except Exception:
                return {"success": False, "evidence": evidence, "summary": f"Backend verification failed: could not read order {order_id}."}
            status = str(order.get("status", "unknown")).lower()
            refund = order.get("refund") if isinstance(order, dict) else None
            customer = order.get("customer") if isinstance(order, dict) else None
            evidence.append(f"Order {order_id} status={status}")
            if status != "refunded":
                return {
                    "success": False,
                    "evidence": evidence,
                    "summary": f"Backend verification failed: order {order_id} is not refunded.",
                }
            if not isinstance(refund, dict):
                return {
                    "success": False,
                    "evidence": evidence,
                    "summary": f"Backend verification failed: refund record for order {order_id} is missing.",
                }
            if not refund.get("id"):
                return {
                    "success": False,
                    "evidence": evidence,
                    "summary": f"Backend verification failed: refund record for order {order_id} is incomplete.",
                }
            if not isinstance(customer, dict) or not customer.get("id"):
                return {
                    "success": False,
                    "evidence": evidence,
                    "summary": f"Backend verification failed: order {order_id} is missing customer linkage.",
                }
            evidence.append(f"Order {order_id} refund_id={refund.get('id')} customer_id={customer.get('id')}")
        return {"success": True, "evidence": evidence}

    def _verify_notification(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        notification_calls = [
            event for event in calls
            if event.get("name") == "send_customer_email" and str(event.get("arguments", {}).get("customer_id", "")).isdigit()
        ]
        if not notification_calls:
            return {
                "success": False,
                "evidence": [],
                "summary": "Backend verification failed: notification outcome is requested but no customer notification call was captured.",
            }
        evidence: list[str] = []
        for event in notification_calls:
            customer_id = int(event["arguments"]["customer_id"])
            expected_subject = str(event.get("arguments", {}).get("subject", "")).strip()
            expected_body = str(event.get("arguments", {}).get("body", "")).strip()
            try:
                notifications = self.client._request("GET", f"/api/customers/{customer_id}/notifications")
            except Exception:
                return {"success": False, "evidence": evidence, "summary": f"Backend verification failed: could not read notifications for customer {customer_id}."}
            if not isinstance(notifications, list):
                return {"success": False, "evidence": evidence, "summary": f"Backend verification failed: notification list for customer {customer_id} is unavailable."}
            count = len(notifications)
            matched = next(
                (
                    item for item in notifications
                    if isinstance(item, dict)
                    and str(item.get("subject", "")).strip() == expected_subject
                    and str(item.get("body", "")).strip() == expected_body
                    and str(item.get("channel", "")).lower() == "email"
                ),
                None,
            )
            evidence.append(f"Customer {customer_id} notifications={count}")
            if matched is None:
                return {
                    "success": False,
                    "evidence": evidence,
                    "summary": f"Backend verification failed: matching notification for customer {customer_id} was not found.",
                }
        return {"success": True, "evidence": evidence}

    def _verify_invoice_export(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        export_calls = [event for event in calls if event.get("name") == "export_overdue_invoices"]
        if not export_calls:
            return {
                "success": False,
                "evidence": [],
                "summary": "Backend verification failed: invoice export outcome is requested but no export call was captured.",
            }
        export_call = export_calls[-1]
        arguments = export_call.get("arguments", {}) if isinstance(export_call.get("arguments"), dict) else {}
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return {
                "success": False,
                "evidence": [],
                "summary": "Backend verification failed: requested export path is missing.",
            }
        overdue_days_gt = arguments.get("overdue_days_gt", 30)
        try:
            overdue_days_gt = int(overdue_days_gt)
        except (TypeError, ValueError):
            return {
                "success": False,
                "evidence": [],
                "summary": "Backend verification failed: export filter parameters are invalid.",
            }
        artifact_path = Path(raw_path).expanduser().resolve()
        evidence = [f"Invoice export path={artifact_path}"]
        if not artifact_path.exists() or not artifact_path.is_file():
            return {
                "success": False,
                "evidence": evidence,
                "summary": "Backend verification failed: exported invoice artifact does not exist.",
            }
        try:
            with artifact_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = reader.fieldnames or []
                rows = list(reader)
        except Exception:
            return {
                "success": False,
                "evidence": evidence,
                "summary": "Backend verification failed: exported invoice artifact could not be read.",
            }
        if headers != self.INVOICE_HEADERS:
            return {
                "success": False,
                "evidence": evidence + [f"CSV headers={headers}"],
                "summary": "Backend verification failed: invoice export headers are incorrect.",
            }
        try:
            expected_rows = self.client.list_invoices(overdue_days_gt)
        except Exception:
            return {
                "success": False,
                "evidence": evidence,
                "summary": "Backend verification failed: expected invoice rows could not be loaded for comparison.",
            }
        if not isinstance(expected_rows, list):
            return {
                "success": False,
                "evidence": evidence,
                "summary": "Backend verification failed: expected invoice rows are unavailable.",
            }
        if len(rows) != len(expected_rows):
            return {
                "success": False,
                "evidence": evidence + [f"CSV rows={len(rows)} expected={len(expected_rows)}"],
                "summary": "Backend verification failed: invoice export row count is incorrect.",
            }
        expected_ids = {str(int(row["id"])) for row in expected_rows if isinstance(row, dict) and str(row.get("id", "")).isdigit()}
        csv_ids = {str(int(row["id"])) for row in rows if isinstance(row, dict) and str(row.get("id", "")).isdigit()}
        if expected_ids != csv_ids:
            return {
                "success": False,
                "evidence": evidence + [f"CSV invoice_ids={sorted(csv_ids)} expected_ids={sorted(expected_ids)}"],
                "summary": "Backend verification failed: invoice identifiers do not match expected overdue invoices.",
            }
        evidence.append(f"CSV rows={len(rows)} invoices={sorted(csv_ids)}")
        return {"success": True, "evidence": evidence}
