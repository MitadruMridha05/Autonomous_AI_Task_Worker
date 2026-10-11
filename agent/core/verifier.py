
from __future__ import annotations

import inspect
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
    """Synchronous verifier for the synchronous agent loop and dashboard."""
    def __init__(self, client: Any):
        self.client = client

    def __call__(self, finish: Any, trace: list[dict[str, Any]]) -> dict[str, Any]:
        calls = [event for event in trace if event.get("kind") == "tool_call"]
        refund_ids = [int(event["arguments"]["order_id"]) for event in calls
                      if event.get("name") == "issue_refund"
                      and str(event.get("arguments", {}).get("order_id", "")).isdigit()]
        order_ids = refund_ids or [int(event["arguments"]["order_id"]) for event in calls
                                   if event.get("name") == "get_order"
                                   and str(event.get("arguments", {}).get("order_id", "")).isdigit()]
        customer_ids = [int(event["arguments"]["customer_id"]) for event in calls
                        if event.get("name") == "send_customer_email"
                        and str(event.get("arguments", {}).get("customer_id", "")).isdigit()]
        evidence: list[str] = []
        for order_id in order_ids:
            try:
                order = self.client.get_order(order_id)
            except Exception as exc:
                return {"success": False, "evidence": [f"Order {order_id} could not be read: {exc}"]}
            status = str(order.get("status", "unknown"))
            evidence.append(f"Order {order_id} status={status}")
            if (refund_ids or finish.status == "no_action_needed") and status != "refunded":
                return {"success": False, "evidence": evidence,
                        "summary": f"Backend verification failed: order {order_id} is {status}, not refunded."}
        for customer_id in customer_ids:
            try:
                notifications = self.client._request("GET", f"/api/customers/{customer_id}/notifications")
            except Exception as exc:
                return {"success": False, "evidence": evidence + [f"Notifications could not be read: {exc}"]}
            count = len(notifications) if isinstance(notifications, list) else 0
            evidence.append(f"Customer {customer_id} notifications={count}")
            if count == 0:
                return {"success": False, "evidence": evidence,
                        "summary": f"Backend verification failed: no notification exists for customer {customer_id}."}
        return {"success": True, "evidence": evidence or list(getattr(finish, "evidence", []))}
