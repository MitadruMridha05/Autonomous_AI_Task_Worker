"""Request bodies for the REST API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RefundRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    amount: float | None = Field(default=None, gt=0, description="Defaults to the full order total")


class NotificationRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
