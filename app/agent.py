"""The autonomous loop: plan, (maybe ask a human), act, observe, verify.

    while steps remain:
        action = planner.plan_next_action(task, history, tools)
        if action is COMPLETE:   re-verify every payment this run entered;
                                 accept only if all of them check out
        else:                    ask a human first when the payment is large,
                                 then execute and record the observation

The agent contains no task-specific sequence. Which tool runs next is the
planner's decision; the agent only enforces the guardrails the planner cannot
be trusted to enforce on itself: a step budget, a failure budget, human
approval for large payments, and independent verification before accepting
COMPLETE.
"""

import logging
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.exceptions import PlannerError
from app.executor import ToolExecutor
from app.models import (
    Action,
    AgentResult,
    AgentState,
    Observation,
    RunStatus,
    VerificationResult,
)
from app.verifier import PaymentVerifier

logger = logging.getLogger(__name__)

PAYMENT_TOOL = "enter_payment"
VERIFICATION_STEP = "final_verification"

#: Receives a description of the risky action; returns True to allow it.
Approver = Callable[[str], bool]


class Planner(Protocol):
    """What the agent needs from a planner. Defined here, by its consumer, so
    tests can pass a fake without importing the OpenAI SDK."""

    def plan_next_action(
        self,
        task: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Action: ...


class AutonomousAgent:
    """Runs a task to completion through a planner, an executor and a verifier.

    Args:
        planner: Chooses the next action.
        executor: Runs tools and turns outcomes into observations.
        verifier: Independently checks the ledger before COMPLETE is accepted.
        max_steps: Hard cap on loop iterations, including rejected COMPLETEs.
        max_consecutive_failures: Abort after this many failed steps in a row.
        approval_threshold: Payments strictly above this need human approval.
        approver: Callback that asks a human. When ``None`` any payment that
            needs approval is denied, which is the safe default for
            unattended runs.
    """

    def __init__(
        self,
        planner: Planner,
        executor: ToolExecutor,
        verifier: PaymentVerifier,
        *,
        max_steps: int = 10,
        max_consecutive_failures: int = 3,
        approval_threshold: Decimal = Decimal("100000"),
        approver: Approver | None = None,
    ) -> None:
        if max_steps < 1 or max_consecutive_failures < 1:
            raise ValueError("max_steps and max_consecutive_failures must be >= 1")
        self._planner = planner
        self._executor = executor
        self._verifier = verifier
        self._max_steps = max_steps
        self._max_consecutive_failures = max_consecutive_failures
        self._approval_threshold = approval_threshold
        self._approver = approver

    def run(self, task: str) -> AgentResult:
        """Work on ``task`` until it is verified complete or a budget runs out."""
        state = AgentState(task=task)
        logger.info("run_started max_steps=%d", self._max_steps)

        for _ in range(self._max_steps):
            result = self._step(state)
            if result is not None:
                logger.info("run_finished status=%s steps=%d", result.status.value, result.steps_taken)
                return result

        return self._finish(
            state,
            RunStatus.MAX_STEPS_EXCEEDED,
            f"Stopped after {self._max_steps} steps without a verified completion.",
        )

    # ------------------------------------------------------------------
    # One iteration of the loop
    # ------------------------------------------------------------------

    def _step(self, state: AgentState) -> AgentResult | None:
        """Advance one step; return a result only when the run is over."""
        try:
            action = self._planner.plan_next_action(
                state.task, state.prompt_history(), self._executor.describe_tools()
            )
        except PlannerError as exc:
            return self._finish(state, RunStatus.FAILED, f"Planner failed: {exc}")

        logger.info(
            "decision step=%d action=%s arguments=%s reason=%s",
            state.step_count + 1,
            action.action,
            action.arguments,
            action.reason,
        )

        if action.is_complete:
            finished = self._handle_complete(state, action)
        else:
            finished = self._handle_tool_action(state, action)
        if finished is not None:
            return finished

        if state.trailing_failures() >= self._max_consecutive_failures:
            return self._finish(
                state,
                RunStatus.FAILED,
                f"Aborted after {self._max_consecutive_failures} consecutive failed steps.",
            )
        return None

    def _handle_tool_action(self, state: AgentState, action: Action) -> AgentResult | None:
        approval_prompt = self._approval_prompt(action)
        if approval_prompt is not None and not self._request_approval(approval_prompt):
            state.record(
                action,
                Observation(success=False, error="Rejected by human approver; nothing was executed."),
            )
            return self._finish(
                state,
                RunStatus.REJECTED_BY_HUMAN,
                f"A human declined the action. {approval_prompt}",
            )

        state.record(action, self._executor.execute(action))
        return None

    def _handle_complete(self, state: AgentState, action: Action) -> AgentResult | None:
        """Accept COMPLETE only if every payment entered in this run verifies.

        A rejected COMPLETE is recorded as a failed step so the planner sees
        why and can fix the problem. It still consumes one step of the budget,
        which keeps a stubborn planner from looping forever.
        """
        evidence = self._verify_entered_payments(state)
        failures = [item for item in evidence if not item.verified]
        if not failures:
            message = (
                "Task completed and verified."
                if evidence
                else "Task completed. No payments were entered, so there was nothing to verify."
            )
            return self._finish(state, RunStatus.COMPLETED, message, evidence)

        state.record(
            Action(
                action=VERIFICATION_STEP,
                arguments={"invoice_ids": [item.invoice_id for item in failures]},
                reason="Automatic check before accepting COMPLETE.",
            ),
            Observation(
                success=False,
                error="COMPLETE rejected. " + " ".join(item.evidence for item in failures),
            ),
        )
        return None

    # ------------------------------------------------------------------
    # Guardrails
    # ------------------------------------------------------------------

    def _approval_prompt(self, action: Action) -> str | None:
        """Describe the action if it needs human approval, else ``None``.

        Malformed amounts are not escalated: the tool rejects them without
        touching any state, so there is nothing for a human to approve.
        """
        if action.action != PAYMENT_TOOL:
            return None
        try:
            amount = Decimal(str(action.arguments.get("amount")))
            if not amount > self._approval_threshold:
                return None
        except InvalidOperation:
            return None
        return (
            f"Payment of {amount:f} for invoice {action.arguments.get('invoice_id')} "
            f"exceeds the approval threshold of {self._approval_threshold:f}."
        )

    def _request_approval(self, prompt: str) -> bool:
        if self._approver is None:
            logger.warning("approval_denied reason=no_approver_configured")
            return False
        approved = self._approver(prompt)
        logger.info("approval_decision approved=%s", approved)
        return approved

    def _verify_entered_payments(self, state: AgentState) -> list[VerificationResult]:
        """Verify each invoice this run successfully entered a payment for."""
        invoice_ids = dict.fromkeys(
            str(step.action.arguments["invoice_id"])
            for step in state.history
            if step.action.action == PAYMENT_TOOL and step.observation.success
        )
        return [self._verifier.verify(invoice_id) for invoice_id in invoice_ids]

    # ------------------------------------------------------------------

    @staticmethod
    def _finish(
        state: AgentState,
        status: RunStatus,
        message: str,
        evidence: list[VerificationResult] | None = None,
    ) -> AgentResult:
        return AgentResult(
            status=status,
            message=message,
            steps_taken=state.step_count,
            evidence=evidence or [],
            history=state.history,
        )
