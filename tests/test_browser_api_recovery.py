import json
import os

from agent.core.guard import ApprovalPolicy
from agent.core.loop import Agent
from agent.core.scripted import ScriptedLLM
from agent.core.verifier import BackendVerifier
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.browser import SyncBrowserTool, build_sync_browser_tools
from agent.tools.registry import ToolRegistry
from app import chaos
from .helpers import call, last_data, last_error, LiveServer


def test_agent_switches_from_failed_browser_refund_to_api_fallback(query, db_path, monkeypatch):
    monkeypatch.setenv("OPSPILOT_UI_REFUND_FAILURES", "1")
    chaos.reset()
    with LiveServer() as server:
        client = OpsPilotClient(server.url)
        browser = SyncBrowserTool(server.url, runs_dir="runs")
        try:
            registry = ToolRegistry()
            registry.register_all(build_sync_browser_tools(browser))
            registry.register_all(build_api_tools(client))

            def choose_fallback(history):
                error = last_error(history)
                assert error["type"] == "server_error"
                assert error["retryable"] is True
                return call("issue_refund", {"order_id": 1004, "reason": "Temporary UI failure recovery"})

            agent = Agent(
                ScriptedLLM([
                    call("browser_issue_refund", {"order_id": 1004, "reason": "Damaged item"}),
                    choose_fallback,
                    call("get_order", {"order_id": 1004}),
                    lambda h: call("finish", {
                        "status": "completed",
                        "summary": "The browser refund failed, so I used the API fallback and verified the order.",
                        "evidence": [f"API refund order status={last_data(h, 'get_order')['status']}"],
                    }),
                ]),
                registry,
                ApprovalPolicy("auto"),
                verifier=BackendVerifier(client),
                runs_dir="runs",
            )
            result = agent.run("Refund order 1004; recover if the browser fails.")
        finally:
            browser.close()
            monkeypatch.delenv("OPSPILOT_UI_REFUND_FAILURES", raising=False)

    browser_failure = next(e for e in result.trace if e.get("name") == "browser_issue_refund" and e["kind"] == "tool_result")
    api_call = next(e for e in result.trace if e.get("name") == "issue_refund" and e["kind"] == "tool_result")
    assert result.status == "completed"
    assert browser_failure["error"]["type"] == "server_error"
    assert api_call["ok"] is True
    assert any(e["kind"] == "verification" and e["status"] == "passed" for e in result.trace)
    assert query("SELECT status FROM orders WHERE id=1004")[0]["status"] == "refunded"
    refund = query("SELECT order_id, amount, reason FROM refunds WHERE order_id=1004")
    assert len(refund) == 1
    assert refund[0]["order_id"] == 1004
    assert refund[0]["amount"] == 1198.0
    assert "recovery" in refund[0]["reason"].lower()
