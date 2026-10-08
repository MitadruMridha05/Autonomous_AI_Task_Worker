"""Simulated company environment: invoice files plus a JSON payment ledger.

``CompanySystem`` plays the role of an ERP. Invoices are text files, payments
live in ``payments.json``. The LLM reaches it through three tool methods
(``search_invoices``, ``read_invoice``, ``enter_payment``); the fourth tool,
``verify_payment``, lives in ``app.verifier`` and is built on the typed helpers
(``get_invoice``, ``find_payment``, ``list_payments``) that are not exposed to
the LLM.

Design notes:
    * The LLM never supplies a filesystem path. Invoices are looked up by the
      id parsed from file *contents*, which rules out path traversal.
    * Tool arguments are validated by ``pydantic.validate_call``, so a string
      ``"45000"`` or an ISO date string is coerced and ``-5`` is rejected before
      any state changes.
    * The ledger is replaced atomically (temp file + ``os.replace``) so a crash
      mid-write cannot leave a truncated ``payments.json``.
    * Failures are raised as ``ToolError`` subclasses; see ``app.exceptions``.
"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError, validate_call

from app.exceptions import (
    DuplicatePaymentError,
    InvoiceNotFoundError,
    InvoiceParseError,
    LedgerCorruptedError,
    ToolError,
    TransientSystemError,
)
from app.models import (
    Invoice,
    PaymentRecord,
    PositiveAmount,
    format_validation_error,
)

logger = logging.getLogger(__name__)

# "Label: value" lines. Labels are matched case-insensitively after parsing.
_FIELD_PATTERN = re.compile(
    r"^[ \t]*(?P<label>[A-Za-z][A-Za-z ]*?)[ \t]*:[ \t]*(?P<value>\S.*?)[ \t]*$",
    re.MULTILINE,
)
# First number in a string such as "₹45,000", "Rs. 45,000.50" or "25000".
_AMOUNT_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _parse_amount(raw: str) -> Decimal:
    """Extract a Decimal from text that may carry a currency symbol or commas."""
    match = _AMOUNT_PATTERN.search(raw)
    if match is None:
        raise ValueError(f"no number found in amount {raw!r}")
    return Decimal(match.group().replace(",", ""))


def _parse_invoice(text: str, source: str) -> Invoice:
    """Turn the text of one invoice file into an ``Invoice``.

    ``source`` is only used to make error messages point at the right file.
    """
    fields = {
        m["label"].strip().lower(): m["value"].strip()
        for m in _FIELD_PATTERN.finditer(text)
    }
    try:
        return Invoice(
            invoice_id=fields["invoice number"],
            company=fields["company"],
            invoice_date=fields.get("invoice date") or fields["date"],
            amount=_parse_amount(fields["amount"]),
            due_date=fields["due date"],
        )
    except KeyError as exc:
        raise InvoiceParseError(f"{source}: missing field {exc}") from exc
    except ValueError as exc:  # includes pydantic.ValidationError
        detail = (
            format_validation_error(exc)
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        raise InvoiceParseError(f"{source}: {detail}") from exc


class CompanySystem:
    """Invoice store and payment ledger rooted at ``data_dir``.

    Args:
        data_dir: Directory containing ``invoices/`` and ``payments.json``.
        simulated_payment_failures: Number of initial ``enter_payment`` calls
            that fail with a transient error. Lets the demo exercise the
            agent's retry behaviour without a genuinely flaky backend.
    """

    def __init__(
        self, data_dir: Path, *, simulated_payment_failures: int = 0
    ) -> None:
        self._invoices_dir = Path(data_dir) / "invoices"
        self._ledger_path = Path(data_dir) / "payments.json"
        self._remaining_failures = simulated_payment_failures
        # Guards the read-modify-write cycle against concurrent threads. It does
        # not protect against other processes; use a real database for that.
        self._ledger_lock = threading.Lock()

    # ------------------------------------------------------------------
    # LLM-facing tools
    # ------------------------------------------------------------------

    @validate_call
    def search_invoices(self, company: str) -> list[dict[str, str]]:
        """Return the id and date of every invoice issued to ``company``.

        Results are deliberately not sorted by date: deciding which invoice is
        the latest is the planner's job.
        """
        wanted = company.strip().casefold()
        return [
            {
                "invoice_id": invoice.invoice_id,
                "date": invoice.invoice_date.isoformat(),
            }
            for invoice in self._load_invoices().values()
            if invoice.company.casefold() == wanted
        ]

    @validate_call
    def read_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Return the parsed fields of one invoice.

        Structured fields are returned instead of raw file text so that stray
        instructions inside an invoice are less likely to reach the planner.
        """
        return self.get_invoice(invoice_id).model_dump(mode="json")

    @validate_call
    def enter_payment(
        self, invoice_id: str, amount: PositiveAmount, due_date: date
    ) -> dict[str, Any]:
        """Record a payment for an existing invoice.

        Raises:
            TransientSystemError: While simulated outages remain.
            InvoiceNotFoundError: The invoice id is unknown.
            DuplicatePaymentError: A payment already exists for the invoice.
            LedgerCorruptedError: ``payments.json`` is unreadable.
        """
        with self._ledger_lock:
            self._maybe_inject_failure()
            invoice = self.get_invoice(invoice_id)
            record = PaymentRecord(
                invoice_id=invoice.invoice_id, amount=amount, due_date=due_date
            )
            records = self._read_ledger()
            if any(r.invoice_id == record.invoice_id for r in records):
                raise DuplicatePaymentError(
                    f"Payment already exists for invoice {record.invoice_id}."
                )
            self._write_ledger([*records, record])

        logger.info("payment_entered invoice=%s amount=%s", record.invoice_id, amount)
        return {
            "message": "Payment entered successfully.",
            "payment": record.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------
    # Typed helpers for Python callers (not exposed to the LLM)
    # ------------------------------------------------------------------

    def get_invoice(self, invoice_id: str) -> Invoice:
        """Look up an invoice by id.

        Raises:
            InvoiceNotFoundError: No invoice file declares this id.
        """
        invoice = self._load_invoices().get(invoice_id.strip())
        if invoice is None:
            raise InvoiceNotFoundError(f"No invoice with id '{invoice_id}'.")
        return invoice

    def find_payment(self, invoice_id: str) -> PaymentRecord | None:
        """Return the ledger entry for ``invoice_id`` or ``None``."""
        wanted = invoice_id.strip()
        return next(
            (r for r in self._read_ledger() if r.invoice_id == wanted), None
        )

    def list_payments(self) -> list[PaymentRecord]:
        """Return every ledger entry; raises if the ledger is corrupt."""
        return self._read_ledger()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_inject_failure(self) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise TransientSystemError("Internal system temporarily unavailable.")

    def _load_invoices(self) -> dict[str, Invoice]:
        """Parse every invoice file, skipping (and logging) unreadable ones.

        Invoices are re-read on each call so the tools always see current files.
        With a handful of invoices this is cheap; add a cache keyed on file
        mtimes if the directory grows large.
        """
        if not self._invoices_dir.is_dir():
            raise ToolError(f"Invoice directory not found: {self._invoices_dir}")

        invoices: dict[str, Invoice] = {}
        for path in sorted(self._invoices_dir.glob("*.txt")):
            try:
                invoice = _parse_invoice(
                    path.read_text(encoding="utf-8-sig"), path.name
                )
            except (InvoiceParseError, OSError) as exc:
                logger.warning("invoice_skipped file=%s reason=%s", path.name, exc)
                continue
            if invoice.invoice_id in invoices:
                logger.warning(
                    "invoice_duplicate id=%s file=%s", invoice.invoice_id, path.name
                )
                continue
            invoices[invoice.invoice_id] = invoice
        return invoices

    def _read_ledger(self) -> list[PaymentRecord]:
        """Load the ledger. A missing or blank file is an empty ledger."""
        if not self._ledger_path.exists():
            return []
        text = self._ledger_path.read_text(encoding="utf-8-sig")
        if not text.strip():
            return []
        try:
            raw = json.loads(text)
            if not isinstance(raw, list):
                raise LedgerCorruptedError("payments.json must contain a JSON list.")
            return [PaymentRecord.model_validate(entry) for entry in raw]
        except json.JSONDecodeError as exc:
            raise LedgerCorruptedError(
                f"payments.json contains invalid JSON: {exc}"
            ) from exc
        except ValidationError as exc:
            raise LedgerCorruptedError(
                f"payments.json holds a malformed record: {format_validation_error(exc)}"
            ) from exc

    def _write_ledger(self, records: list[PaymentRecord]) -> None:
        """Replace the ledger atomically so readers never see a partial file."""
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([r.model_dump(mode="json") for r in records], indent=4)
        fd, tmp_name = tempfile.mkstemp(
            dir=self._ledger_path.parent, prefix=".payments-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(payload)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_name, self._ledger_path)
        except BaseException:
            # BaseException on purpose: clean up the temp file even on Ctrl-C.
            Path(tmp_name).unlink(missing_ok=True)
            raise
