"""Safe authentication/credential-handling regression tests.

These tests use dummy keys and fake provider/client responses only. The application has no
user-authentication endpoint, so app-level valid/expired session tests are intentionally not
invented; the 401/403 cases below cover how an upstream API client's auth failures are mapped.
"""
from types import SimpleNamespace as NS

import pytest

from agent.core.llm import AnthropicLLM, LLMError, OpenAICompatLLM
from agent.tools.api_client import OpsPilotClient


class FakeAuthenticationError(Exception):
    pass


class FakeAPIError(Exception):
    pass


class FakeAnthropicMessages:
    def create(self, **_kwargs):
        raise FakeAuthenticationError("dummy provider rejection")


class FakeOpenAICompletions:
    def create(self, **_kwargs):
        raise FakeAuthenticationError("dummy provider rejection")


def test_anthropic_rejected_key_is_redacted_from_user_error():
    client = AnthropicLLM.__new__(AnthropicLLM)
    client._sdk = NS(AuthenticationError=FakeAuthenticationError, APIError=FakeAPIError)
    client._client = NS(messages=FakeAnthropicMessages())
    client.model, client.max_tokens = "dummy-model", 10

    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY") as exc_info:
        client.generate("system", [], [])
    assert "dummy provider rejection" not in str(exc_info.value)


def test_openai_rejected_key_is_redacted_from_user_error():
    client = OpenAICompatLLM.__new__(OpenAICompatLLM)
    client._sdk = NS(AuthenticationError=FakeAuthenticationError, APIError=FakeAPIError)
    client._client = NS(chat=NS(completions=FakeOpenAICompletions()))
    client.model = "dummy-model"

    with pytest.raises(LLMError, match="OPENAI_API_KEY") as exc_info:
        client.generate("system", [], [])
    assert "dummy provider rejection" not in str(exc_info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_upstream_auth_and_permission_statuses_are_non_retryable(status):
    response = NS(status_code=status, text='{"error":{"message":"denied","code":"auth_failure"}}')
    response.json = lambda: {"error": {"message": "denied", "code": "auth_failure"}}

    error = OpsPilotClient._to_error(response)

    assert error.kind == "permission_denied"
    assert error.status == status
    assert error.retryable is False
