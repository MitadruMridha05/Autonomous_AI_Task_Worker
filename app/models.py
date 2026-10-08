"""Typed data contracts shared by every module of the worker.

Pydantic models sit at the trust boundaries (LLM output, files on disk, tool
arguments), where untrusted data has to be validated. The only plain dataclass
is ``AgentState``, which is internal, mutable bookkeeping.

Data flow::

    LLM JSON --> Action --> ToolExecutor --> Observation
                                  |
              Step(action, observation) appended to AgentState.history
                                  |
              history is rendered back into the next planner prompt
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
    field_validator,
)

#: Sentinel action name the planner uses to say "the goal has been achieved".
COMPLETE = "COMPLETE"


def _json_number(amount: Decimal) -> int | float:
    """Render a Decimal as a JSON number, keeping whole amounts as ints.

    Money is held as ``Decimal`` in memory to avoid float drift, but the ledger
    and the LLM both expect ``45000`` rather than ``"45000"`` or ``45000.0``.
    """
    return int(amount) if amount == amount.to_integral_value() else float(amount)


PositiveAmount = Annotated[Decimal, Field(gt=0), PlainSerializer(_json_number)]


def format_validation_error(exc: ValidationError) -> str:
    """Condense a pydantic error into one line that is safe to show an LLM."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'input'}: {err['msg']}"
        for err in exc.errors()
    )


# ----------------------------------------------------------------------------
# Domain objects
# ----------------------------------------------------------------------------


class Invoice(BaseModel):
    """An invoice parsed from a file in ``company_data/invoices``."""

    model_config = ConfigDict(frozen=True)

    invoice_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    invoice_date: date
    amount: PositiveAmount
    due_date: date


class PaymentRecord(BaseModel):
    """One row of ``payments.json``."""

    model_config = ConfigDict(frozen=True)

    invoice_id: str = Field(min_length=1)
    amount: PositiveAmount
    due_date: date
    status: str = "entered"


class VerificationResult(BaseModel):
    """Outcome of independently checking the ledger against the invoice."""

    invoice_id: str
    verified: bool
    evidence: str
    payment: PaymentRecord | None = None


# ----------------------------------------------------------------------------
# Planner <-> executor contracts
# ----------------------------------------------------------------------------


class Action(BaseModel):
    """The next step chosen by the planner (validated LLM output)."""

    action: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    @field_validator("arguments", mode="before")
    @classmethod
    def _null_arguments_as_empty(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("reason", mode="before")
    @classmethod
    def _null_reason_as_empty(cls, value: Any) -> Any:
        return "" if value is None else value

    @property
    def is_complete(self) -> bool:
        return self.action == COMPLETE


class Observation(BaseModel):
    """What happened when an action was executed."""

    success: bool
    result: Any = None
    error: str | None = None
    retryable: bool = False


class Step(BaseModel):
    """An action paired with the observation it produced."""

    action: Action
    observation: Observation

    def to_prompt_entry(self, index: int) -> dict[str, Any]:
        """Flatten into the JSON shape shown to the planner."""
        return {
            "step": index,
            "action": self.action.action,
            "arguments": self.action.arguments,
            "reason": self.action.reason,
            **self.observation.model_dump(mode="json"),
        }


# ----------------------------------------------------------------------------
# Agent run state and result
# ----------------------------------------------------------------------------


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED_BY_HUMAN = "rejected_by_human"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"


class AgentResult(BaseModel):
    """Final report returned to the caller of ``AutonomousAgent.run``."""

    status: RunStatus
    message: str
    steps_taken: int
    evidence: list[VerificationResult] = Field(default_factory=list)
    history: list[Step] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.COMPLETED


@dataclass
class AgentState:
    """Mutable bookkeeping for a single run; discarded when the run ends."""

    task: str
    history: list[Step] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.history)

    def record(self, action: Action, observation: Observation) -> Step:
        step = Step(action=action, observation=observation)
        self.history.append(step)
        return step

    def prompt_history(self) -> list[dict[str, Any]]:
        return [step.to_prompt_entry(i) for i, step in enumerate(self.history, start=1)]

    def trailing_failures(self) -> int:
        """Count failed steps at the end of the history, stopping at a success."""
        count = 0
        for step in reversed(self.history):
            if step.observation.success:
                break
            count += 1
        return count
