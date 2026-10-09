from __future__ import annotations

from typing import Literal


class ApprovalPolicy:
    RISKY_ACTIONS = {"refund_order", "delete_order", "send_email"}

    def should_approve(self, tool_name: str, arguments: dict) -> bool | Literal["ask"]:
        """Return 'ask' for risky actions; caller must obtain explicit approval."""
        normalized = tool_name.rsplit(".", 1)[-1].lower()
        if normalized in self.RISKY_ACTIONS:
            return "ask"
        return True

    def detect_ambiguity(self, llm_response: str) -> str | None:
        text = (llm_response or "").lower()
        phrases = ("which john", "not clear", "ambiguous", "need clarification",
                   "which customer", "which order", "more information")
        return llm_response if any(phrase in text for phrase in phrases) else None
