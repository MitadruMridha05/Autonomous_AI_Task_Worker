"""Provider adapters: pure translation functions, tested without any network access."""
import json
from types import SimpleNamespace as NS

import pytest

from agent.core.llm import (LLMError, from_anthropic_response, from_openai_response, make_llm,
                            to_anthropic_messages, to_openai_messages, to_openai_tools)

HISTORY = [
    {"role": "user", "content": "Task: refund"},
    {"role": "assistant", "text": "Looking up.", "tool_calls": [{"id": "t1", "name": "get_order", "arguments": {"order_id": 1}}]},
    {"role": "tool", "results": [{"tool_call_id": "t1", "name": "get_order", "content": '{"ok": true}', "is_error": False}]},
    {"role": "assistant", "text": "", "tool_calls": []},
]


def test_anthropic_message_translation():
    msgs = to_anthropic_messages(HISTORY)
    assert msgs[0] == {"role": "user", "content": "Task: refund"}
    assert msgs[1]["content"] == [{"type": "text", "text": "Looking up."},
                                  {"type": "tool_use", "id": "t1", "name": "get_order", "input": {"order_id": 1}}]
    assert msgs[2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                    "content": '{"ok": true}', "is_error": False}]}
    assert msgs[3]["content"][0]["text"] == "(no output)"  # empty assistant turns are not allowed by the API


def test_anthropic_response_parsing():
    resp = NS(content=[NS(type="text", text="Checking."),
                       NS(type="tool_use", id="tu_1", name="get_order", input={"order_id": 7})],
              usage=NS(input_tokens=11, output_tokens=5), stop_reason="tool_use")
    out = from_anthropic_response(resp)
    assert out.text == "Checking." and out.stop_reason == "tool_use"
    assert (out.tool_calls[0].id, out.tool_calls[0].name, out.tool_calls[0].arguments) == ("tu_1", "get_order", {"order_id": 7})
    assert out.usage == {"input_tokens": 11, "output_tokens": 5}


def test_openai_message_and_tool_translation():
    msgs = to_openai_messages("SYS", HISTORY)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assistant = msgs[2]
    assert assistant["tool_calls"][0]["function"] == {"name": "get_order", "arguments": json.dumps({"order_id": 1})}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"ok": true}'}
    assert "tool_calls" not in msgs[4] and msgs[4]["content"] is None
    tools = to_openai_tools([{"name": "x", "description": "d", "input_schema": {"type": "object"}}])
    assert tools == [{"type": "function", "function": {"name": "x", "description": "d", "parameters": {"type": "object"}}}]


def _openai_resp(tool_calls, content=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls), finish_reason="tool_calls")],
              usage=NS(prompt_tokens=20, completion_tokens=8))


def test_openai_response_parsing_including_bad_json_and_missing_ids():
    good = NS(id="c1", function=NS(name="get_order", arguments='{"order_id": 3}'))
    no_id = NS(id=None, function=NS(name="get_order", arguments='{"order_id": 4}'))  # some providers omit ids
    bad = NS(id="c3", function=NS(name="get_order", arguments="{not json"))
    out = from_openai_response(_openai_resp([good, no_id, bad], "hi"))
    assert out.text == "hi" and out.usage == {"input_tokens": 20, "output_tokens": 8}
    assert out.tool_calls[0].arguments == {"order_id": 3}
    assert out.tool_calls[1].id.startswith("call_") and out.tool_calls[1].arguments == {"order_id": 4}
    assert "__unparseable_arguments__" in out.tool_calls[2].arguments  # surfaces as invalid_arguments, not a crash


def test_make_llm_gives_actionable_errors(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        make_llm()
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    with pytest.raises(LLMError, match="LLM_MODEL"):
        make_llm("openai_compat")
    with pytest.raises(LLMError, match="Unknown"):
        make_llm("nonsense")


def test_make_llm_builds_clients_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = make_llm("anthropic")
    assert llm.provider == "anthropic" and llm.model == "claude-haiku-5-5"
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")  # e.g. Ollama: no key needed
    monkeypatch.setenv("LLM_MODEL", "some-model")
    assert make_llm("openai_compat").model == "some-model"
