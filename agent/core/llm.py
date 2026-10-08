"""Provider-neutral LLM layer.

The agent loop only ever sees three things: a neutral conversation history, a list of tool specs,
and an LLMResponse. Each provider adapter translates to/from its own wire format, so swapping
Anthropic for Gemini/OpenAI/Ollama changes configuration, not the loop.

Neutral history entries (plain dicts, so a whole run can be dumped to JSON):
  {"role": "user",      "content": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "arguments"}]}
  {"role": "tool",      "results": [{"tool_call_id", "name", "content": str, "is_error": bool}]}
"""
from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Configuration or provider failure (missing key, rejected key, API down...)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None


class LLMClient(ABC):
    provider: str = "unknown"
    model: str = "unknown"

    @abstractmethod
    def generate(self, system: str, history: list[dict], tool_specs: list[dict]) -> LLMResponse: ...


# --------------------------------------------------------------- Anthropic
def to_anthropic_messages(history: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in history:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks: list[dict] = []
            if m.get("text"):
                blocks.append({"type": "text", "text": m["text"]})
            for tc in m.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
            if not blocks:  # the API rejects empty assistant turns
                blocks = [{"type": "text", "text": "(no output)"}]
            out.append({"role": "assistant", "content": blocks})
        elif m["role"] == "tool":
            out.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": r["tool_call_id"], "content": r["content"],
                     "is_error": r["is_error"]}
                    for r in m["results"]
                ],
            })
    return out


def from_anthropic_response(resp: Any) -> LLMResponse:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(block.id, block.name, dict(block.input)))
    usage = {"input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
             "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0}
    return LLMResponse("\n".join(text_parts).strip(), calls, usage, getattr(resp, "stop_reason", None))


class AnthropicLLM(LLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int = 2048):
        import anthropic  # imported lazily so the other provider works without this package

        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model, self.max_tokens = model, max_tokens

    def generate(self, system: str, history: list[dict], tool_specs: list[dict]) -> LLMResponse:
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                tools=tool_specs, messages=to_anthropic_messages(history),
            )
        except self._sdk.AuthenticationError as exc:
            raise LLMError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY in your .env file.") from exc
        except self._sdk.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc
        return from_anthropic_response(resp)


# ------------------------------------------------- OpenAI-compatible APIs
# Works with OpenAI, Google Gemini (OpenAI-compatible endpoint), Groq, Ollama, etc.
def to_openai_tools(tool_specs: list[dict]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
            for s in tool_specs]


def to_openai_messages(system: str, history: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("text") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif m["role"] == "tool":
            for r in m["results"]:
                out.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]})
    return out


def from_openai_response(resp: Any) -> LLMResponse:
    choice = resp.choices[0]
    msg = choice.message
    calls: list[ToolCall] = []
    for tc in (msg.tool_calls or []):
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError:
            args = {"__unparseable_arguments__": raw}  # registry validation will report this back to the model
        calls.append(ToolCall(tc.id or f"call_{uuid.uuid4().hex[:8]}", tc.function.name, args))
    usage = {"input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
             "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0} if resp.usage else {}
    return LLMResponse((msg.content or "").strip(), calls, usage, choice.finish_reason)


class OpenAICompatLLM(LLMClient):
    provider = "openai_compat"

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        import openai

        self._sdk = openai
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, system: str, history: list[dict], tool_specs: list[dict]) -> LLMResponse:
        try:
            resp = self._client.chat.completions.create(
                model=self.model, messages=to_openai_messages(system, history), tools=to_openai_tools(tool_specs),
            )
        except self._sdk.AuthenticationError as exc:
            raise LLMError("The provider rejected the API key. Check OPENAI_API_KEY in your .env file.") from exc
        except self._sdk.APIError as exc:
            raise LLMError(f"LLM API error: {exc}") from exc
        return from_openai_response(resp)


# ------------------------------------------------------------------ factory
def make_llm(provider: str | None = None, model: str | None = None) -> LLMClient:
    provider = (provider or os.getenv("LLM_PROVIDER") or "anthropic").lower()
    model = model or os.getenv("LLM_MODEL")
    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        return AnthropicLLM(key, model or "claude-haiku-5-5")
    if provider in ("openai", "openai_compat"):
        base_url = os.getenv("OPENAI_BASE_URL") or None
        key = os.getenv("OPENAI_API_KEY") or ("not-needed" if base_url else None)  # local servers need no key
        if not key:
            raise LLMError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        if not model:
            raise LLMError("Set LLM_MODEL in .env (the model name from your provider's docs).")
        return OpenAICompatLLM(key, model, base_url)
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use 'anthropic' or 'openai_compat'.")
