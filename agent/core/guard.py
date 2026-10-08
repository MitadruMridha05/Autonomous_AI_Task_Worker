"""Human-in-the-loop approval for risky tools.

Day 1: a simple policy (ask / auto-approve / deny). Day 2 grows this into the full guard:
ambiguity detection, per-tool policies and a Streamlit approval UI.
"""
from __future__ import annotations

from typing import Callable, Literal

from ..tools.base import Tool

PromptFn = Callable[[Tool, dict, str], bool]


class ApprovalPolicy:
    def __init__(self, mode: Literal["ask", "auto", "deny"] = "ask", prompt_fn: PromptFn | None = None):
        self.mode = mode
        self.prompt_fn = prompt_fn

    def approve(self, tool: Tool, arguments: dict, rationale: str = "") -> tuple[bool, str]:
        """Returns (approved, how). Non-risky tools never reach this method."""
        if self.mode == "auto":
            return True, "auto_approved"
        if self.mode == "deny" or self.prompt_fn is None:
            return False, "auto_denied" if self.mode == "deny" else "no_interactive_user"
        approved = bool(self.prompt_fn(tool, arguments, rationale))
        return approved, "user_approved" if approved else "user_denied"
