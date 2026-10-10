from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Type
from pydantic import BaseModel


class ToolError(RuntimeError):
    """Raised when a tool cannot complete an action."""


@dataclass
class Tool:
    name: str
    params: Type[BaseModel]
    description: str = ""
    handler: Callable[..., Any] | None = None
    risky: bool = False
    schema: dict[str, Any] = field(default_factory=dict)

    async def run(self, **arguments):
        if self.handler is None:
            raise ToolError(f"No handler configured for tool {self.name!r}")
        import inspect
        result = self.handler(**arguments)
        return await result if inspect.isawaitable(result) else result


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "arguments": t.schema, "risky": t.risky}
            for t in self._tools.values()
        ]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
