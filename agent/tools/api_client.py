"""Thin HTTP client for the mock company app's REST API.

Its one job beyond making requests: turn every failure into a ToolError with a *kind* the agent
can reason about (not_found, conflict, server_error, ...) and a `retryable` flag.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import ToolError

_KIND_BY_STATUS = {400: "invalid_request", 401: "permission_denied", 403: "permission_denied",
                   404: "not_found", 409: "conflict", 422: "invalid_request"}


class OpsPilotClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", http: httpx.Client | None = None, timeout: float = 10.0):
        # `http` can be injected (tests pass FastAPI's TestClient, which is an httpx.Client).
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ToolError("timeout", f"Request timed out: {method} {path}", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ToolError("network", f"Could not reach the app ({type(exc).__name__}). Is it running?",
                            retryable=True) from exc
        if resp.status_code >= 400:
            raise self._to_error(resp)
        return resp.json()

    @staticmethod
    def _to_error(resp: httpx.Response) -> ToolError:
        status = resp.status_code
        message, code = resp.text[:300], None
        try:
            body = resp.json()
            if isinstance(body, dict) and "error" in body:
                message, code = body["error"].get("message", message), body["error"].get("code")
            elif isinstance(body, dict) and "detail" in body:  # FastAPI validation errors
                message = str(body["detail"])[:300]
        except ValueError:
            pass
        if status >= 500:
            return ToolError("server_error", message or "Server error", status=status, code=code, retryable=True)
        kind = _KIND_BY_STATUS.get(status, "invalid_request")
        return ToolError(kind, message, status=status, code=code, retryable=False)

    # ---- endpoints
    def health(self) -> Any:
        return self._request("GET", "/api/health")

    def search_customers(self, query: str) -> Any:
        return self._request("GET", "/api/customers", params={"q": query})

    def get_customer(self, customer_id: int) -> Any:
        return self._request("GET", f"/api/customers/{customer_id}")

    def list_orders(self, customer_id: int) -> Any:
        return self._request("GET", "/api/orders", params={"customer_id": customer_id})

    def get_order(self, order_id: int) -> Any:
        return self._request("GET", f"/api/orders/{order_id}")

    def refund_order(self, order_id: int, reason: str) -> Any:
        return self._request("POST", f"/api/orders/{order_id}/refund", json={"reason": reason})

    def send_notification(self, customer_id: int, subject: str, body: str) -> Any:
        return self._request("POST", f"/api/customers/{customer_id}/notifications",
                             json={"subject": subject, "body": body})
