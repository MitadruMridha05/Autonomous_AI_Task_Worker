from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class Goal(BaseModel):
    objective: str
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)


class Planner:
    """Turns a natural-language task into a structured goal and plan."""

    def __init__(self, llm: Any):
        self.llm = llm

    async def extract_goal(self, task: str) -> Goal:
        prompt = f"""
Convert the user task into a structured goal.
Do not invent identifiers or claim an action has already happened.
Success criteria must be observable and verifiable. Include constraints for
ambiguity, authorization, and avoiding duplicate non-idempotent actions.

Task:
{task}

Return only JSON matching:
{{"objective":"...", "success_criteria":{{}}, "constraints":[]}}
"""
        response = await _maybe_await(self.llm.call(prompt, schema=Goal))
        return _as_goal(response)

    async def make_plan(self, goal: Goal) -> list[str]:
        prompt = f"""
Create a concise, high-level plan for this task.
Goal: {goal.model_dump_json()}
Return only a JSON array of ordered step strings. Do not assume unknown IDs.
Ask for clarification when identity or intent is ambiguous. Risky actions require
human approval. Prefer checking current state before performing a mutation.
"""
        response = await _maybe_await(self.llm.call(prompt, schema=list[str]))
        if isinstance(response, list):
            return [str(step) for step in response]
        if isinstance(response, str):
            parsed = _parse_json(response)
            if isinstance(parsed, list):
                return [str(step) for step in parsed]
        raise ValueError("Planner returned an invalid plan; expected a JSON list of steps.")

    async def replan(self, goal: Goal, observation: str, previous_plan: list[str] | None = None) -> list[str]:
        """Create a replacement plan from current observations instead of stale assumptions."""
        prompt = f"""
Re-plan the task using the latest observation. Preserve completed work, do not repeat
non-idempotent actions, and use a fallback tool when the primary path failed.
Goal: {goal.model_dump_json()}
Previous plan: {json.dumps(previous_plan or [])}
Latest observation:
{observation}
Return only a JSON array of ordered step strings.
"""
        response = await _maybe_await(self.llm.call(prompt, schema=list[str]))
        if isinstance(response, list):
            return [str(step) for step in response]
        if isinstance(response, str):
            parsed = _parse_json(response)
            if isinstance(parsed, list):
                return [str(step) for step in parsed]
        raise ValueError("Planner returned an invalid re-plan; expected a JSON list of steps.")


async def _maybe_await(value):
    import inspect
    return await value if inspect.isawaitable(value) else value


def _parse_json(value: str):
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([p for p in (text.find("{"), text.find("[")) if p >= 0], default=-1)
        if start >= 0:
            end = max(text.rfind("}"), text.rfind("]"))
            if end >= start:
                return json.loads(text[start:end + 1])
        raise


def _as_goal(value: Any) -> Goal:
    if isinstance(value, Goal):
        return value
    if isinstance(value, dict):
        return Goal.model_validate(value)
    if isinstance(value, str):
        return Goal.model_validate(_parse_json(value))
    if hasattr(value, "model_dump"):
        return Goal.model_validate(value.model_dump())
    raise TypeError(f"Unsupported goal response type: {type(value).__name__}")
