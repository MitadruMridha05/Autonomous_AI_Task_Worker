"""A scripted stand-in for an LLM, used ONLY to test the plumbing (loop, tools, approvals, error
paths) deterministically and without an API key. It proves nothing about the agent's intelligence;
that is what the real-LLM runs and the Day 3 eval suite are for."""
from __future__ import annotations

from typing import Callable, Union

from .llm import LLMClient, LLMResponse

Step = Union[LLMResponse, Callable[[list[dict]], LLMResponse]]


class ScriptedLLM(LLMClient):
    provider = "scripted"
    model = "scripted"

    def __init__(self, steps: list[Step]):
        self._steps = list(steps)
        self.calls: list[dict] = []  # recorded (system, history length, tool names) for assertions

    def generate(self, system, history, tool_specs):
        self.calls.append({"system": system, "history_len": len(history), "tools": [s["name"] for s in tool_specs]})
        if not self._steps:
            raise AssertionError("ScriptedLLM ran out of scripted steps")
        step = self._steps.pop(0)
        return step(history) if callable(step) else step
