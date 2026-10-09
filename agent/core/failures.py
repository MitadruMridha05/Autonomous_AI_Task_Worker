from __future__ import annotations

from enum import Enum


class ErrorType(Enum):
    TRANSIENT = "retry"
    NOT_FOUND = "fail"
    PERMISSION = "ask"
    NO_OP = "skip"


def classify_error(exception: Exception) -> ErrorType:
    """Classify common HTTP/browser errors without treating unknown errors as success."""
    message = str(exception).lower()
    status = getattr(exception, "status_code", None)
    response = getattr(exception, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)

    if status == 404 or "404" in message or "not found" in message:
        return ErrorType.NOT_FOUND
    if status in (401, 403) or any(term in message for term in ("permission", "forbidden", "unauthorized", "ambiguous", "clarification")):
        return ErrorType.PERMISSION
    if status is not None and status >= 500:
        return ErrorType.TRANSIENT
    if any(term in message for term in ("timeout", "temporarily unavailable", "connection reset", "network", "429")):
        return ErrorType.TRANSIENT
    if any(term in message for term in ("already refunded", "already completed", "no-op", "no op")):
        return ErrorType.NO_OP
    return ErrorType.NO_OP


def handle_failure(error: Exception, tool_name: str, step_count: int, max_retries: int = 3) -> dict:
    """Return a decision; step_count is the current attempt number (1-based)."""
    error_type = classify_error(error)
    if error_type is ErrorType.TRANSIENT and step_count < max_retries:
        return {"action": "retry", "backoff_seconds": min(2 ** max(0, step_count - 1), 8),
                "message": str(error), "tool": tool_name}
    if error_type is ErrorType.PERMISSION:
        return {"action": "ask_user", "message": str(error), "tool": tool_name}
    if error_type is ErrorType.NO_OP:
        return {"action": "skip", "message": str(error), "tool": tool_name}
    return {"action": "fail", "message": str(error), "tool": tool_name}