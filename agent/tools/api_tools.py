"""The agent's API tools for the OpsPilot mock app. Descriptions are written for the LLM:
they say what the tool does, what it returns, and how it can fail."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .api_client import OpsPilotClient
from .base import Tool


class SearchCustomersArgs(BaseModel):
    query: str = Field(description="Name or email fragment, e.g. 'Priya' or 'priya sharma'. Every word must match.")


class CustomerIdArgs(BaseModel):
    customer_id: int = Field(description="Numeric customer ID from search_customers")


class OrderIdArgs(BaseModel):
    order_id: int = Field(description="Numeric order ID, e.g. 1004")


class RefundArgs(BaseModel):
    order_id: int = Field(description="Numeric order ID to refund in full")
    reason: str = Field(min_length=3, description="Short reason recorded on the refund, e.g. 'Item arrived damaged'")


class EmailArgs(BaseModel):
    customer_id: int = Field(description="Numeric customer ID to email")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Plain-text email body. Polite, specific, no promises the system did not make.")


def build_api_tools(client: OpsPilotClient) -> list[Tool]:
    return [
        Tool(
            "search_customers",
            "Find customers by name or email. Returns a list of {id, name, email, phone, city}. "
            "More than one result means the name is ambiguous.",
            SearchCustomersArgs, lambda query: client.search_customers(query),
        ),
        Tool(
            "get_customer", "Get one customer's profile by ID.",
            CustomerIdArgs, lambda customer_id: client.get_customer(customer_id),
        ),
        Tool(
            "list_orders",
            "List a customer's orders, NEWEST FIRST. Each has id, status (placed|shipped|delivered|cancelled|"
            "refunded), total_amount, currency, placed_at, delivered_at, items_summary.",
            CustomerIdArgs, lambda customer_id: client.list_orders(customer_id),
        ),
        Tool(
            "get_order",
            "Get full details of one order: items, status, customer, and the refund record if one exists. "
            "Use this to check preconditions before acting and to verify results afterwards.",
            OrderIdArgs, lambda order_id: client.get_order(order_id),
        ),
        Tool(
            "issue_refund",
            "Refund the FULL amount of one delivered order. Irreversible and requires user approval. "
            "Fails with type 'conflict' (code already_refunded) if already refunded, or 'invalid_request' "
            "(code not_refundable) if the order is not 'delivered'.",
            RefundArgs, lambda order_id, reason: client.refund_order(order_id, reason), risky=True,
        ),
        Tool(
            "send_customer_email",
            "Send an email to a customer. Visible to the customer and cannot be unsent; requires user approval.",
            EmailArgs, lambda customer_id, subject, body: client.send_notification(customer_id, subject, body),
            risky=True,
        ),
    ]
