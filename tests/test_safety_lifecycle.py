from agent.core.guard import ApprovalPolicy
from agent.core.loop import Agent
from agent.core.scripted import ScriptedLLM
from agent.core.verifier import BackendVerifier
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry
from .helpers import call
import threading


def make_registry(http):
    registry = ToolRegistry()
    registry.register_all(build_api_tools(OpsPilotClient(http=http)))
    return registry


def test_completed_refund_claim_requires_backend_state(http, query):
    # The model claims success after the risky action was denied. The order must
    # remain delivered and the lifecycle must reject the false success.
    agent = Agent(
        ScriptedLLM([
            call("issue_refund", {"order_id": 1004, "reason": "damaged"}),
            call("finish", {"status": "completed", "summary": "Refunded", "evidence": ["done"]}),
        ]),
        make_registry(http), ApprovalPolicy("deny"),
        verifier=BackendVerifier(OpsPilotClient(http=http)), runs_dir=None,
    )
    result = agent.run("Refund order 1004")
    assert result.status == "failed"
    assert any(event["kind"] == "verification" and event["status"] == "failed" for event in result.trace)
    assert query("SELECT status FROM orders WHERE id=1004")[0]["status"] == "delivered"


def test_cancellation_prevents_model_and_tool_execution(http):
    cancelled = threading.Event()
    cancelled.set()
    agent = Agent(
        ScriptedLLM([call("get_order", {"order_id": 1004})]),
        make_registry(http), cancel_event=cancelled, runs_dir=None,
    )
    result = agent.run("Inspect order 1004")
    assert result.status == "cancelled"
    assert not any(event["kind"] == "tool_result" for event in result.trace)
