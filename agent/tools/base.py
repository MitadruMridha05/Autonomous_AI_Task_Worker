"""Core tool abstractions.

A Tool = name + description + a Pydantic model for its arguments + a plain Python function.
The Pydantic model does double duty: it produces the JSON schema the LLM sees, and it validates
whatever the LLM sends back. Adding a new capability means adding a Tool; no core code changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Type

from pydantic import BaseModel


class ToolError(Exception):
    """A tool failed in a way the agent should be able to see and reason about.

    kind: not_found | conflict | invalid_request | permission_denied | server_error | timeout | network
    """

    def __init__(self, kind: str, message: str, *, status: int | None = None, code: str | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.kind, self.message, self.status, self.code, self.retryable = kind, message, status, code, retryable

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.kind, "message": self.message, "retryable": self.retryable}
        if self.status is not None:
            d["status"] = self.status
        if self.code:
            d["code"] = self.code
        return d


def _strip_titles(node: Any) -> Any:
    """Pydantic adds noisy 'title' keys; some providers' schema validators dislike them."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: Type[BaseModel]
    func: Callable[..., Any]
    risky: bool = False  # risky tools change the outside world and need human approval

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": _strip_titles(self.params.model_json_schema())}


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": True, "data": self.data} if self.ok else {"ok": False, "error": self.error}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)
