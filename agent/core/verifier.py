
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
        has_refund = status == "refunded"
        return {
            "action": "refund",
            "order_id": int(order_id),
            "success": has_refund,
            "evidence": f"Order status: {status or 'unknown'}",
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
