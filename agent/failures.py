"""Backward-compatible failure-handler imports.

Older local copies imported ``agent.failures`` directly. The maintained
implementation lives in ``agent.core.failures``; re-exporting it here keeps
those checkouts runnable while they update their CLI module.
"""
from .core.failures import ErrorType, classify_error, handle_failure

__all__ = ["ErrorType", "classify_error", "handle_failure"]
