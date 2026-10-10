"""Deterministic, opt-in failure injection for reliability demonstrations."""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_remaining: dict[str, int] = {}


def _configured_failures(name: str) -> int:
    try:
        return max(0, int(os.getenv(f"OPSPILOT_{name.upper()}_FAILURES", "0")))
    except ValueError:
        return 0


def reset() -> None:
    """Clear cached counters; useful for tests and local demos."""
    with _lock:
        _remaining.clear()


def should_fail(name: str) -> bool:
    """Return whether this invocation should fail, consuming one configured failure."""
    with _lock:
        remaining = _remaining.setdefault(name, _configured_failures(name))
        if remaining <= 0:
            return False
        _remaining[name] = remaining - 1
        return True


def remaining(name: str) -> int:
    with _lock:
        return _remaining.setdefault(name, _configured_failures(name))
