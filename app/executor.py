"""Executes the tool chosen by the planner and reports what happened.

The executor never decides *which* tool to run; it only looks the name up in a
registry, calls it, and converts the outcome into an ``Observation``.

Flow::

    Action("read_invoice", {"invoice_id": "INV-1002"})
        --> ToolExecutor.execute()
        --> CompanySystem.read_invoice(invoice_id="INV-1002")
        --> Observation(success=True, result={...})

The same registry that dispatches calls also produces the tool descriptions
shown to the planner, so the two can never drift apart.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError, validate_call

from app.exceptions import ToolError
from app.models import Action, Observation, format_validation_error
from app.tools import CompanySystem
from app.verifier import PaymentVerifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    """A callable tool together with the description the LLM sees."""

    name: str
    description: str
    parameters: dict[str, str]
    handler: Callable[..., Any]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": dict(self.parameters),
        }


class ToolExecutor:
    """Dispatches ``Action`` objects to registered tools."""

    def __init__(self, system: CompanySystem, verifier: PaymentVerifier) -> None:
        self._verifier = verifier
        specs = [
            ToolSpec(
                name="search_invoices",
                description=(
                    "Search for invoices belonging to a company. "
                    "Returns each invoice's id and date."
                ),
                parameters={"company": "string"},
                handler=system.search_invoices,
            ),
            ToolSpec(
                name="read_invoice",
                description=(
                    "Read a specific invoice by id. "
                    "Returns company, amount, invoice date and due date."
                ),
                parameters={"invoice_id": "string"},
                handler=system.read_invoice,
            ),
            ToolSpec(
                name="enter_payment",
                description="Enter an invoice payment into the internal payment system.",
                parameters={
                    "invoice_id": "string",
                    "amount": "number",
                    "due_date": "string, YYYY-MM-DD",
                },
                handler=system.enter_payment,
            ),
            ToolSpec(
                name="verify_payment",
                description=(
                    "Check the internal system against the invoice to confirm a "
                    "payment was entered correctly. Returns verified and evidence."
                ),
                parameters={"invoice_id": "string"},
                handler=self._verify_payment,
            ),
        ]
        self._tools = {spec.name: spec for spec in specs}

    def describe_tools(self) -> list[dict[str, Any]]:
        """Tool descriptions in the shape the planner prompt expects."""
        return [spec.describe() for spec in self._tools.values()]

    def execute(self, action: Action) -> Observation:
        """Run ``action`` and return its observation. Never raises.

        The final ``except Exception`` is deliberate: this is the boundary
        between an LLM-driven loop and arbitrary tool code, and one crashing
        tool should become an observation the planner can react to, not kill
        the whole run.
        """
        spec = self._tools.get(action.action)
        if spec is None:
            return Observation(
                success=False,
                error=(
                    f"Unknown tool '{action.action}'. "
                    f"Available tools: {', '.join(self._tools)}."
                ),
            )

        logger.info("tool_call tool=%s arguments=%s", spec.name, action.arguments)
        try:
            result = spec.handler(**action.arguments)
        except ValidationError as exc:
            observation = Observation(
                success=False, error=f"Invalid arguments: {format_validation_error(exc)}"
            )
        except ToolError as exc:
            observation = Observation(
                success=False, error=str(exc), retryable=exc.retryable
            )
        except Exception as exc:
            logger.exception("tool_crashed tool=%s", spec.name)
            observation = Observation(
                success=False, error=f"Unexpected tool failure: {exc!r}"
            )
        else:
            observation = Observation(success=True, result=result)

        logger.info(
            "tool_result tool=%s success=%s error=%s",
            spec.name,
            observation.success,
            observation.error,
        )
        return observation

    @validate_call
    def _verify_payment(self, invoice_id: str) -> dict[str, Any]:
        return self._verifier.verify(invoice_id).model_dump(mode="json")
