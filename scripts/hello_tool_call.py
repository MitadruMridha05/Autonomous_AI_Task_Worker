"""Day 1, step 1: prove your LLM provider + API key can do a full tool-calling round trip.

    python -m scripts.hello_tool_call

Expected: the model asks to call `add_numbers`, we run it locally, send the result back,
and the model answers with the sum (9999).
"""
from __future__ import annotations

import sys

from agent.config import load_env
from agent.core.llm import LLMError, make_llm

TOOLS = [{
    "name": "add_numbers",
    "description": "Add two integers and return the sum.",
    "input_schema": {"type": "object",
                     "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                     "required": ["a", "b"]},
}]


def main() -> int:
    load_env()
    try:
        llm = make_llm()
        print(f"Provider: {llm.provider} | model: {llm.model}")
        history = [{"role": "user", "content": "What is 1234 + 8765? You must use the add_numbers tool."}]
        first = llm.generate("You are a helpful assistant.", history, TOOLS)
        if not first.tool_calls:
            print(f"FAIL: the model did not call the tool. It said: {first.text!r}")
            return 1
        call = first.tool_calls[0]
        print(f"1) Model requested tool: {call.name}({call.arguments})")
        total = call.arguments["a"] + call.arguments["b"]
        history.append({"role": "assistant", "text": first.text, "tool_calls": [call.__dict__]})
        history.append({"role": "tool", "results": [
            {"tool_call_id": call.id, "name": call.name, "content": str(total), "is_error": False}]})
        second = llm.generate("You are a helpful assistant.", history, TOOLS)
        print(f"2) Tool returned {total}; model's final answer: {second.text!r}")
        print("\nSUCCESS: tool calling works end to end.")
        return 0
    except LLMError as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
