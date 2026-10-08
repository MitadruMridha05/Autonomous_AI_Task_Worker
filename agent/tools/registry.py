"""Tool registry: the single place where tool calls are looked up, validated and executed.

Nothing here raises to the caller. Every failure (unknown tool, bad arguments, tool error,
unexpected crash) becomes a ToolResult(ok=False) the LLM can read and react to.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .base import Tool, ToolError, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def check_arguments(self, tool: Tool, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Return an error dict if the arguments are invalid, else None."""
        try:
            tool.params(**arguments)
        except (ValidationError, TypeError) as exc:
            if isinstance(exc, ValidationError):
                problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
            else:
                problems = str(exc)
            return {"type": "invalid_arguments", "message": f"Invalid arguments for {tool.name}: {problems}",
                    "retryable": False}
        return None

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(False, error={"type": "unknown_tool", "retryable": False,
                                            "message": f"No tool named '{name}'. Available: {', '.join(self.names())}"})
        bad = self.check_arguments(tool, arguments)
        if bad:
            return ToolResult(False, error=bad)
        args = tool.params(**arguments).model_dump()
        try:
            return ToolResult(True, data=tool.func(**args))
        except ToolError as exc:
            return ToolResult(False, error=exc.to_dict())
        except Exception as exc:  # a bug in a tool must not kill the run
            return ToolResult(False, error={"type": "tool_crashed", "retryable": False,
                                            "message": f"{type(exc).__name__}: {exc}"})
