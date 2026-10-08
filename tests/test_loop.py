"""The agent loop, exercised end to end: real tools -> real HTTP client -> real FastAPI app -> real SQLite.
Only the LLM is scripted. Assertions on the *database* are the ground truth."""
import pytest

from agent.core.guard import ApprovalPolicy
from agent.core.llm import LLMError
from agent.core.loop import Agent
from agent.core.scripted import ScriptedLLM
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry

from .helpers import call, last_data, last_error, say, task1_steps


@pytest.fixture
def make_agent(http, tmp_path):
    def _make(steps, mode="auto", ask_user=None, max_steps=20):
        registry = ToolRegistry()
        registry.register_all(build_api_tools(OpsPilotClient(http=http)))
        llm = ScriptedLLM(steps)
        agent = Agent(llm, registry, ApprovalPolicy(mode), ask_user, max_steps=max_steps, runs_dir=tmp_path / "runs")
        return agent, llm
    return _make


def test_task1_end_to_end(make_agent, query):
    agent, llm = make_agent(task1_steps())
    result = agent.run("Priya Sharma got a damaged item. Refund her latest order and let her know.")

    assert result.status == "completed" and result.ok
    # Ground truth, straight from SQLite (not from what the agent said):
    assert query("SELECT status FROM orders WHERE id = 1004")[0]["status"] == "refunded"
    refunds = query("SELECT * FROM refunds WHERE order_id = 1004")
    assert len(refunds) == 1 and refunds[0]["amount"] == 1198.0
    mails = query("SELECT subject FROM notifications WHERE customer_id = 1")
    assert len(mails) == 1 and "refund" in mails[0]["subject"].lower()
    # Untouched: Priya's older order and the other customers.
    assert query("SELECT status FROM orders WHERE id = 1001")[0]["status"] == "delivered"
    assert query("SELECT COUNT(*) AS n FROM refunds")[0]["n"] == 2  # seed refund (1005) + ours

    assert result.steps == 7 and result.usage["tool_calls"] == 7
    assert [e["approved"] for e in result.trace if e["kind"] == "approval"] == [True, True]
    assert result.evidence == ["Order 1004 status=refunded"]
    assert "finish" in llm.calls[0]["tools"] and "ask_user" in llm.calls[0]["tools"]


def test_trace_is_saved_as_json(make_agent, tmp_path):
    import json

    agent, _ = make_agent(task1_steps())
    result = agent.run("task")
    saved = json.loads(open(result.trace_path).read())
    assert saved["status"] == "completed" and saved["trace"][0]["kind"] == "start"
    assert {e["kind"] for e in saved["trace"]} >= {"start", "llm", "tool_call", "tool_result", "approval", "finish"}


def test_denied_approval_changes_nothing_and_run_ends_declined(make_agent, query):
    steps = task1_steps()[:4] + [
        lambda h: call("finish", {"status": "declined", "summary": "You declined the refund, so nothing was changed.",
                                  "evidence": ["Refund not issued"]}),
    ]
    agent, _ = make_agent(steps, mode="deny")
    result = agent.run("Refund Priya's latest order")
    assert result.status == "declined"
    assert query("SELECT status FROM orders WHERE id = 1004")[0]["status"] == "delivered"
    assert query("SELECT COUNT(*) AS n FROM refunds WHERE order_id = 1004")[0]["n"] == 0
    denial = [e for e in result.trace if e["kind"] == "tool_result" and e["name"] == "issue_refund"][0]
    assert denial["error"]["type"] == "denied_by_user"


def test_conflict_error_reaches_the_model_and_nothing_is_duplicated(make_agent, query):
    steps = [
        call("issue_refund", {"order_id": 1005, "reason": "customer asked again"}),
        lambda h: call("finish", {
            "status": "no_action_needed",
            "summary": "Order 1005 was already refunded.",
            "evidence": [f"Server said: {last_error(h)['code']}"]}),
    ]
    agent, _ = make_agent(steps)
    result = agent.run("Refund order 1005")
    assert result.status == "no_action_needed" and result.ok
    assert result.evidence == ["Server said: already_refunded"]
    assert query("SELECT COUNT(*) AS n FROM refunds WHERE order_id = 1005")[0]["n"] == 1


def test_invalid_args_on_a_risky_tool_do_not_trigger_an_approval_prompt(make_agent):
    prompts = []
    agent, _ = make_agent([
        call("issue_refund", {"order_id": "not-a-number", "reason": "x"}),
        call("finish", {"status": "failed", "summary": "gave up", "evidence": []}),
    ], mode="ask")
    agent.guard.prompt_fn = lambda *a: prompts.append(a) or True
    result = agent.run("bad call")
    assert prompts == []  # the human is never asked to approve a call that could not run anyway
    err = [e for e in result.trace if e["kind"] == "tool_result"][0]["error"]
    assert err["type"] == "invalid_arguments"


def test_ask_user_answer_flows_back_into_the_run(make_agent):
    asked = []

    def human(question):
        asked.append(question)
        return "John Mathew"

    steps = [
        call("search_customers", {"query": "John"}),
        call("ask_user", {"question": "Two customers match 'John': John Mathew (id 2), John D'Souza (id 3). Which one?"}),
        lambda h: call("finish", {"status": "needs_clarification",
                                  "summary": f"User chose {last_data(h, 'ask_user')['user_answer']}", "evidence": []}),
    ]
    agent, _ = make_agent(steps, ask_user=human)
    result = agent.run("Refund John's order")
    assert len(asked) == 1 and "John Mathew" in asked[0]
    assert result.summary == "User chose John Mathew"


def test_ask_user_without_a_human_is_reported_not_crashed(make_agent):
    agent, _ = make_agent([call("ask_user", {"question": "which John?"}),
                           call("finish", {"status": "needs_clarification", "summary": "Which John?", "evidence": []})])
    result = agent.run("Refund John's order")
    assert result.status == "needs_clarification"
    assert [e for e in result.trace if e["kind"] == "tool_result"][0]["error"]["type"] == "no_user_available"


def test_text_only_replies_are_nudged_then_the_run_fails_cleanly(make_agent):
    agent, llm = make_agent([say("Sure, I'll do that."), say("Done!"), say("All done."), say("unreachable")])
    result = agent.run("anything")
    assert result.status == "failed" and "without calling finish" in result.summary
    assert sum(e["kind"] == "nudge" for e in result.trace) == 2 and len(llm.calls) == 3


def test_a_nudged_model_can_recover(make_agent):
    agent, _ = make_agent([say("I'll look into it."),
                           call("finish", {"status": "failed", "summary": "nothing to do", "evidence": []})])
    assert agent.run("anything").status == "failed"  # reached `finish` after one nudge


def test_step_limit_stops_a_looping_model(make_agent):
    agent, llm = make_agent([call("get_order", {"order_id": 1004}) for _ in range(10)], max_steps=3)
    result = agent.run("loop forever")
    assert result.status == "max_steps_exceeded" and result.steps == 3 and len(llm.calls) == 3


def test_unknown_tool_is_reported_to_the_model(make_agent):
    agent, _ = make_agent([call("drop_database", {}),
                           lambda h: call("finish", {"status": "failed", "summary": last_error(h)["type"], "evidence": []})])
    assert agent.run("x").summary == "unknown_tool"


def test_invalid_finish_arguments_are_rejected_and_model_can_retry(make_agent):
    agent, _ = make_agent([call("finish", {"status": "great_success", "summary": "yay"}),
                           call("finish", {"status": "completed", "summary": "ok", "evidence": []})])
    result = agent.run("x")
    assert result.status == "completed" and result.steps == 2


def test_extra_calls_after_finish_in_the_same_turn_are_not_executed(make_agent, query):
    from agent.core.llm import LLMResponse, ToolCall

    both = LLMResponse(tool_calls=[
        ToolCall("c1", "finish", {"status": "completed", "summary": "done", "evidence": []}),
        ToolCall("c2", "issue_refund", {"order_id": 1004, "reason": "sneaky refund"}),
    ])
    agent, _ = make_agent([both])
    agent.run("x")
    assert query("SELECT status FROM orders WHERE id = 1004")[0]["status"] == "delivered"


def test_llm_failure_is_reported_not_raised(make_agent):
    def broken(history):
        raise LLMError("provider is down")

    agent, _ = make_agent([broken])
    result = agent.run("x")
    assert result.status == "failed" and "provider is down" in result.summary


def test_oversized_tool_results_are_truncated(make_agent, monkeypatch):
    import agent.core.loop as loop_mod

    monkeypatch.setattr(loop_mod, "MAX_TOOL_CHARS", 200)
    seen = {}

    def finish(history):
        seen["observation"] = history[-1]["results"][0]["content"]  # what the model actually received
        return call("finish", {"status": "completed", "summary": "ok", "evidence": []})

    agent, _ = make_agent([call("search_customers", {"query": ""}), finish])
    agent.run("x")
    assert "[truncated" in seen["observation"] and len(seen["observation"]) < 300
