"""Optional tools for Day 2's invoice-export task.

Kept separate from ``build_api_tools`` so existing integrations that rely on its
small refund/customer contract remain backward compatible.
"""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from .api_client import OpsPilotClient
from .base import Tool
from .files import export_csv


class OverdueInvoicesArgs(BaseModel):
    overdue_days_gt: int = Field(default=30, ge=0, description="Only unpaid invoices more than this many days overdue")


class ExportInvoicesArgs(BaseModel):
    path: str = Field(description="Destination CSV path")
    overdue_days_gt: int = Field(default=30, ge=0)


def build_day2_invoice_tools(client: OpsPilotClient) -> list[Tool]:
    def list_overdue(overdue_days_gt: int = 30):
        return client.list_invoices(overdue_days_gt)

    def export_overdue(path: str, overdue_days_gt: int = 30):
        rows = client.list_invoices(overdue_days_gt)
        selected = ["id", "customer_id", "customer_name", "amount", "issued_date", "due_date", "status", "days_overdue"]
        return {"path": export_csv(rows, Path(path), fieldnames=selected), "rows": len(rows), "columns": selected}

    return [
        Tool("list_overdue_invoices", "List unpaid invoices overdue by more than a number of days.", OverdueInvoicesArgs, list_overdue),
        Tool("export_overdue_invoices", "Export overdue invoices to a CSV file.", ExportInvoicesArgs, export_overdue),
    ]
