"""Exception hierarchy for the autonomous worker.

Tools signal failure by raising a ``ToolError`` subclass rather than returning
``{"success": False}`` dictionaries. The ``retryable`` flag travels with the
exception so the executor can tell the planner whether trying again is
worthwhile (a flaky backend) or pointless (a duplicate payment).
"""


class WorkerError(Exception):
    """Base class for every error this package raises on purpose."""


class ConfigError(WorkerError):
    """An environment variable or setting is missing or malformed."""


class PlannerError(WorkerError):
    """The LLM could not be reached or returned something unusable."""


class ToolError(WorkerError):
    """A tool could not complete its job.

    Attributes:
        retryable: True when repeating the identical call may succeed.
    """

    retryable: bool = False


class InvalidArgumentError(ToolError):
    """A tool received arguments that are well-typed but semantically wrong."""


class InvoiceNotFoundError(ToolError):
    """No invoice matches the requested identifier."""


class InvoiceParseError(ToolError):
    """An invoice file exists but cannot be interpreted."""


class DuplicatePaymentError(ToolError):
    """A payment is already recorded for the invoice."""


class LedgerCorruptedError(ToolError):
    """The payment ledger cannot be parsed; refusing to touch it."""


class TransientSystemError(ToolError):
    """The internal system is temporarily unavailable."""

    retryable = True
