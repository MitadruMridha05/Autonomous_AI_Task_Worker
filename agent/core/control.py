"""Control tools: they steer the run instead of touching the outside world.
Handled by the loop itself, never by the tool registry."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..tools.base import Tool

FINISH = "finish"
ASK_USER = "ask_user"

FINAL_STATUSES = ("completed", "no_action_needed", "needs_clarification", "declined", "failed")


class FinishArgs(BaseModel):
    status: Literal["completed", "no_action_needed", "needs_clarification", "declined", "failed"] = Field(
        description="completed = goal achieved and verified; no_action_needed = goal was already true; "
                    "needs_clarification = could not proceed without more info; declined = user refused an action; "
                    "failed = could not achieve the goal"
    )
    summary: str = Field(description="1-3 plain sentences for a non-technical user: what happened and the outcome")
    evidence: list[str] = Field(
        default_factory=list,
        description="Short factual lines you actually observed, e.g. 'Order 1004 status=refunded, refund id 2'",
    )


class AskUserArgs(BaseModel):
    question: str = Field(description="One specific question. List the candidate options when there are several.")


CONTROL_TOOLS = [
    Tool(
        ASK_USER,
        "Ask the human a clarifying question and wait for the answer. Use when the request is ambiguous "
        "(e.g. several customers share a name) or you lack information you cannot look up. Never guess instead.",
        AskUserArgs, lambda **_: None,
    ),
    Tool(
        FINISH,
        "End the run. Call exactly once, when the task is done, impossible, declined, or needs clarification "
        "you could not obtain. Report only what you verified.",
        FinishArgs, lambda **_: None,
    ),
]
