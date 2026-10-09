from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable

from .failures import handle_failure
from .guard import ApprovalPolicy
from .memory import WorkingMemory
from .planner import Goal, Planner
from ..tools.base import Tool, ToolError, ToolRegistry


class Agent:
    """Plan-act-observe agent loop with approvals, retries, verification, and report."""

    def __init__(
        self,
        planner: Planner,
        llm: Any,
        verifier: Any,
        tools: ToolRegistry | dict[str, Any],
        *,
        guard: ApprovalPolicy | None = None,
        approval_callback: Callable[[str, dict], Any] | None = None,
        max_steps: int = 20,
        max_retries_per_action: int = 3,
    ):
        self.planner = planner
        self.llm = llm
        self.verifier = verifier
        self.tools = tools
        self.guard = guard or ApprovalPolicy()
        self.approval_callback = approval_callback
        self.max_steps = max_steps
        self.max_retries_per_action = max_retries_per_action
        self._tool_retries: dict[str, int] = {}

    async def run(self, task: str) -> dict:
        goal: Goal = await _await(self.planner.extract_goal(task))
        plan = await _await(self.planner.make_plan(goal))
        memory = WorkingMemory()
        status = "max_steps_reached"
        final_summary = "The agent reached its step limit before confirming completion."

        # Give the model a concise, current registry description when supported.
        if hasattr(self.llm, "tool_descriptions"):
            self.llm.tool_descriptions = self._describe_tools()

        for step in range(1, self.max_steps + 1):
            observation = memory.get_context()
            try:
                tool_call = await _await(self.llm.decide_next_action(goal, plan, observation, memory))
                name, arguments = _normalise_tool_call(tool_call)
                if name == "ask_user":
                    status = "needs_user_input"
                    final_summary = str(arguments.get("question") or tool_call.get("rationale") or "The task needs clarification.")
                    memory.log_action(name, final_summary, arguments)
                    break
                if name == "finish":
                    status = "finished"
                    final_summary = str(arguments.get("summary", "The agent requested completion verification."))
                    memory.log_action(name, final_summary, arguments)
                    break

                approval = self.guard.should_approve(name, arguments)
                if approval == "ask":
                    if self.approval_callback is None:
                        status = "approval_required"
                        final_summary = f"Human approval is required before executing {name}."
                        memory.log_action("approval_required", final_summary, {"tool": name, **arguments})
                        break
                    approved = await _await(self.approval_callback(name, arguments))
                    if not approved:
                        status = "approval_denied"
                        final_summary = f"Approval was not granted for {name}; the action was not executed."
                        memory.log_action("approval_denied", final_summary, {"tool": name, **arguments})
                        break

                try:
                    result = await self.execute(name, arguments)
                    self._tool_retries[name] = 0
                    memory.log_action(name, result, arguments)
                    self._update_memory_from_result(memory, name, result)
                    if isinstance(result, dict) and result.get("page_text"):
                        memory.update_page_text(str(result["page_text"]))
                    elif isinstance(result, str) and any(token in name for token in ("navigate", "click", "fill_form")):
                        memory.update_page_text(result)
                except Exception as exc:
                    retry_number = self._tool_retries.get(name, 0) + 1
                    decision = handle_failure(exc, name, retry_number, self.max_retries_per_action)
                    memory.log_action(name, {"error": str(exc), "decision": decision}, arguments)
                    if decision["action"] == "retry":
                        self._tool_retries[name] = retry_number
                        await asyncio.sleep(float(decision.get("backoff_seconds", 1)))
                        continue
                    if decision["action"] == "ask_user":
                        status = "needs_user_input"
                        final_summary = decision["message"]
                        break
                    if decision["action"] == "skip":
                        continue
                    status = "failed"
                    final_summary = decision["message"]
                    break

            except Exception as exc:
                status = "failed"
                final_summary = f"Agent decision failed: {exc}"
                memory.log_action("agent_error", str(exc))
                break

        try:
            verification = await _await(self.verifier.check_success(goal, memory))
        except Exception as exc:
            verification = {"success": False, "results": {}, "error": str(exc)}
        verified_success = bool(verification.get("success", False)) if isinstance(verification, dict) else False
        if verified_success:
            status = "success"
            final_summary = "The goal was verified against the application API."
        elif status == "finished":
            status = "unverified"
            final_summary = "The agent stopped, but the requested outcome could not be verified."

        return self.make_report(goal, plan, memory, status, final_summary, verification)

    async def execute(self, tool_name: str, arguments: dict) -> Any:
        if isinstance(self.tools, ToolRegistry):
            tool = self.tools.get(tool_name)
            return await _await(tool.run(**arguments))
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            if isinstance(tool, Tool):
                return await _await(tool.run(**arguments))
            if hasattr(tool, "run"):
                return await _await(tool.run(**arguments))
            if callable(tool):
                return await _await(tool(**arguments))
        # Support a BrowserTool object registered under "browser".
        if "." in tool_name:
            prefix, method_name = tool_name.split(".", 1)
            obj = self.tools.get(prefix) if isinstance(self.tools, dict) else None
            if obj is not None and hasattr(obj, method_name):
                return await _await(getattr(obj, method_name)(**arguments))
        raise ToolError(f"Unknown tool: {tool_name}")

    def make_report(self, goal, plan, memory, status, summary, verification) -> dict:
        return {
            "status": status,
            "summary": summary,
            "goal": goal.model_dump() if hasattr(goal, "model_dump") else str(goal),
            "plan": plan,
            "verification": verification,
            "facts": memory.facts,
            "actions": memory.actions,
        }

    def _describe_tools(self) -> list[dict]:
        if isinstance(self.tools, ToolRegistry):
            return self.tools.describe()
        descriptions = []
        for key, value in self.tools.items():
            if hasattr(value, "describe"):
                descriptions.extend(value.describe())
            elif key == "browser":
                descriptions.extend([
                    {"name": "browser.navigate", "description": "Navigate to a URL; returns visible text and interactive controls.", "arguments": {"url": "string"}},
                    {"name": "browser.click", "description": "Click a visible interactive control using its returned selector.", "arguments": {"selector": "string"}},
                    {"name": "browser.fill_form", "description": "Fill visible form fields by selector.", "arguments": {"fields": "object"}},
                    {"name": "browser.screenshot", "description": "Save a screenshot and return its path.", "arguments": {}},
                ])
            else:
                descriptions.append({"name": key, "description": getattr(value, "description", ""), "arguments": getattr(value, "schema", {})})
        return descriptions

    @staticmethod
    def _update_memory_from_result(memory: WorkingMemory, tool_name: str, result: Any) -> None:
        if isinstance(result, dict):
            facts = result.get("facts")
            if isinstance(facts, dict):
                for key, value in facts.items():
                    memory.remember_fact(str(key), value)
            for key in ("customer_id", "order_id"):
                if key in result:
                    memory.remember_fact(key, result[key])


async def _await(value):
    return await value if inspect.isawaitable(value) else value


def _normalise_tool_call(value):
    if isinstance(value, dict):
        name = value.get("name")
        arguments = value.get("arguments", {})
    else:
        name = getattr(value, "name", None)
        arguments = getattr(value, "arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        raise ToolError("LLM returned an invalid tool call; expected name and object arguments.")
    return name, arguments
