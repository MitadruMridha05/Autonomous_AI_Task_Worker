"""Tool layer: schemas, validation, error classification. No LLM involved."""
import httpx
import pytest

from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.base import Tool, ToolError
from agent.tools.registry import ToolRegistry
from pydantic import BaseModel


@pytest.fixture
def client(http):
    return OpsPilotClient(http=http)


@pytest.fixture
def registry(client):
    r = ToolRegistry()
    r.register_all(build_api_tools(client))
    return r


def test_specs_are_llm_ready(registry):
    specs = {s["name"]: s for s in registry.specs()}
    assert set(specs) == {"search_customers", "get_customer", "list_orders", "get_order", "issue_refund",
                          "send_customer_email"}
    schema = specs["issue_refund"]["input_schema"]
    assert schema["required"] == ["order_id", "reason"]
    assert "title" not in schema and "title" not in schema["properties"]["order_id"]
    assert specs["issue_refund"]["description"]


def test_only_state_changing_tools_are_risky(registry):
    risky = {n for n in registry.names() if registry.get(n).risky}
    assert risky == {"issue_refund", "send_customer_email"}


def test_successful_execution(registry):
    res = registry.execute("search_customers", {"query": "priya"})
    assert res.ok and res.data[0]["id"] == 1


def test_string_numbers_are_coerced(registry):
    assert registry.execute("get_order", {"order_id": "1004"}).ok  # LLMs often send "1004"


def test_invalid_arguments_come_back_as_error_not_exception(registry):
    res = registry.execute("get_order", {"order_id": "abc"})
    assert not res.ok and res.error["type"] == "invalid_arguments" and "order_id" in res.error["message"]
    assert registry.execute("get_order", {}).error["type"] == "invalid_arguments"


def test_unknown_tool_lists_available_ones(registry):
    res = registry.execute("delete_everything", {})
    assert res.error["type"] == "unknown_tool" and "get_order" in res.error["message"]


def test_http_errors_are_classified(registry):
    assert registry.execute("get_order", {"order_id": 9999}).error["type"] == "not_found"
    conflict = registry.execute("issue_refund", {"order_id": 1005, "reason": "again please"})
    assert conflict.error["type"] == "conflict" and conflict.error["code"] == "already_refunded"
    assert conflict.error["retryable"] is False
    invalid = registry.execute("issue_refund", {"order_id": 1006, "reason": "not delivered"})
    assert invalid.error["type"] == "invalid_request" and invalid.error["code"] == "not_refundable"


def test_server_errors_and_network_failures_are_retryable():
    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(503, text="upstream down")

    c = OpsPilotClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x"))
    with pytest.raises(ToolError) as exc:
        c.get_order(1)
    assert exc.value.kind == "server_error" and exc.value.retryable is True

    def boom(request):
        raise httpx.ConnectError("refused")

    c2 = OpsPilotClient(http=httpx.Client(transport=httpx.MockTransport(boom), base_url="http://x"))
    with pytest.raises(ToolError) as exc2:
        c2.health()
    assert exc2.value.kind == "network" and exc2.value.retryable is True


def test_a_crashing_tool_does_not_crash_the_registry():
    class NoArgs(BaseModel):
        pass

    r = ToolRegistry()
    r.register(Tool("buggy", "always raises", NoArgs, lambda: 1 / 0))
    res = r.execute("buggy", {})
    assert not res.ok and res.error["type"] == "tool_crashed" and "ZeroDivisionError" in res.error["message"]


def test_duplicate_registration_is_an_error(registry, client):
    with pytest.raises(ValueError):
        registry.register(build_api_tools(client)[0])
