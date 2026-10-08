"""Shared test helpers: tiny builders for scripted LLM turns."""
from __future__ import annotations

import json
import uuid

from agent.core.llm import LLMResponse, ToolCall


def call(name: str, arguments: dict, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[ToolCall(f"call_{uuid.uuid4().hex[:6]}", name, arguments)],
                       usage={"input_tokens": 100, "output_tokens": 20})


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text, usage={"input_tokens": 50, "output_tokens": 10})


def last_data(history: list[dict], tool_name: str):
    """The `data` of the most recent successful result of `tool_name`: this is how the scripted
    'model' uses what it observed (IDs flow from earlier tool results into later calls)."""
    for msg in reversed(history):
        if msg["role"] == "tool":
            for r in reversed(msg["results"]):
                if r["name"] == tool_name:
                    return json.loads(r["content"]).get("data")
    raise AssertionError(f"no result for {tool_name} in history")


def last_error(history: list[dict]):
    for msg in reversed(history):
        if msg["role"] == "tool":
            for r in reversed(msg["results"]):
                parsed = json.loads(r["content"])
                if not parsed["ok"]:
                    return parsed["error"]
    return None


def task1_steps() -> list:
    """The sequence a competent model should follow for Task 1, driven by observed data."""
    return [
        lambda h: call("search_customers", {"query": "Priya Sharma"}),
        lambda h: call("list_orders", {"customer_id": last_data(h, "search_customers")[0]["id"]}),
        lambda h: call("get_order", {"order_id": last_data(h, "list_orders")[0]["id"]}),  # newest first
        lambda h: call("issue_refund", {"order_id": last_data(h, "get_order")["id"], "reason": "Item arrived damaged"},
                       text="Order is delivered and not refunded; issuing the refund."),
        lambda h: call("send_customer_email", {
            "customer_id": last_data(h, "search_customers")[0]["id"],
            "subject": "Your refund has been issued",
            "body": f"Hi, we have refunded order {last_data(h, 'issue_refund')['order_id']} "
                    f"({last_data(h, 'issue_refund')['amount']} INR). We're sorry about the damaged item."}),
        lambda h: call("get_order", {"order_id": last_data(h, "issue_refund")["order_id"]}),  # verify
        lambda h: call("finish", {
            "status": "completed",
            "summary": "Refunded Priya Sharma's latest order (#1004) and emailed her.",
            "evidence": [f"Order {last_data(h, 'get_order')['id']} status={last_data(h, 'get_order')['status']}"]}),
    ]


class LiveServer:
    """Runs the mock app under a real uvicorn server in a background thread (real HTTP, free port)."""

    def __init__(self) -> None:
        import socket
        import threading

        import uvicorn

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=self.port,
                                                    log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LiveServer":
        import time

        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("mock app did not start in time")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
