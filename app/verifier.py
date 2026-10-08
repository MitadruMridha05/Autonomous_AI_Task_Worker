"""Independent verification that a payment really landed in the ledger.

The verifier never decides what to do next; it only inspects state. Crucially it
compares the ledger against the *invoice file* rather than against values the
caller supplies. If the LLM mis-transcribed an amount, both the payment and a
caller-supplied "expected" value would carry the same mistake and a naive check
would pass. Re-reading the source of truth closes that loop.
"""

import logging

from app.exceptions import ToolError
from app.models import VerificationResult
from app.tools import CompanySystem

logger = logging.getLogger(__name__)

EXPECTED_STATUS = "entered"


class PaymentVerifier:
    """Checks ledger entries against the invoices they were entered for."""

    def __init__(self, system: CompanySystem) -> None:
        self._system = system

    def verify(self, invoice_id: str) -> VerificationResult:
        """Verify the payment recorded for ``invoice_id``.

        Never raises for domain errors: anything that prevents the check from
        running is reported as ``verified=False`` with the reason as evidence.
        """
        try:
            invoice = self._system.get_invoice(invoice_id)
            payment = self._system.find_payment(invoice_id)
        except ToolError as exc:
            return self._report(
                VerificationResult(
                    invoice_id=invoice_id,
                    verified=False,
                    evidence=f"Verification could not be completed: {exc}",
                )
            )

        if payment is None:
            return self._report(
                VerificationResult(
                    invoice_id=invoice_id,
                    verified=False,
                    evidence=f"No payment record for {invoice_id} found in the internal system.",
                )
            )

        problems: list[str] = []
        if payment.amount != invoice.amount:
            problems.append(
                f"amount is {payment.amount} but the invoice says {invoice.amount}"
            )
        if payment.due_date != invoice.due_date:
            problems.append(
                f"due date is {payment.due_date} but the invoice says {invoice.due_date}"
            )
        if payment.status != EXPECTED_STATUS:
            problems.append(f"status is '{payment.status}', expected '{EXPECTED_STATUS}'")

        if problems:
            return self._report(
                VerificationResult(
                    invoice_id=invoice_id,
                    verified=False,
                    evidence=(
                        f"Payment record for {invoice_id} does not match the invoice: "
                        + "; ".join(problems)
                        + "."
                    ),
                    payment=payment,
                )
            )

        return self._report(
            VerificationResult(
                invoice_id=invoice_id,
                verified=True,
                evidence=(
                    f"Payment record for {invoice_id} exists in the internal system and "
                    f"matches the invoice (amount {payment.amount:f}, due {payment.due_date}, "
                    f"status '{payment.status}')."
                ),
                payment=payment,
            )
        )

    @staticmethod
    def _report(result: VerificationResult) -> VerificationResult:
        logger.info(
            "verification invoice=%s verified=%s", result.invoice_id, result.verified
        )
        return result
