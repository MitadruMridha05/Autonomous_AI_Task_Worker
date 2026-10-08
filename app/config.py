"""Runtime configuration, read once from environment variables.

Variable                    Default            Meaning
--------------------------  -----------------  -------------------------------------
COMPANY_DATA_DIR            ./company_data     Folder with invoices/ and payments.json
OPENAI_MODEL                gpt-4o-mini        Chat model used by the planner
MAX_STEPS                   10                 Step budget per run
APPROVAL_THRESHOLD          100000             Payments above this need human approval
SIMULATED_PAYMENT_FAILURES  0                  Initial enter_payment calls that fail
LOG_LEVEL                   INFO               Python logging level name
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeVar

from app.exceptions import ConfigError

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_env(name: str, default: T, cast: Callable[[str], T]) -> T:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except (ValueError, InvalidOperation) as exc:
        raise ConfigError(f"Invalid value for {name}: {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    data_dir: Path = PROJECT_ROOT / "company_data"
    openai_model: str = "gpt-4o-mini"
    max_steps: int = 10
    approval_threshold: Decimal = Decimal("100000")
    simulated_payment_failures: int = 0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ConfigError("MAX_STEPS must be at least 1.")
        if self.simulated_payment_failures < 0:
            raise ConfigError("SIMULATED_PAYMENT_FAILURES cannot be negative.")
        if not self.approval_threshold > 0:
            raise ConfigError("APPROVAL_THRESHOLD must be greater than 0.")
        if not isinstance(getattr(logging, self.log_level.upper(), None), int):
            raise ConfigError(f"Unknown LOG_LEVEL: {self.log_level!r}")

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            data_dir=_read_env("COMPANY_DATA_DIR", defaults.data_dir, Path),
            openai_model=_read_env("OPENAI_MODEL", defaults.openai_model, str),
            max_steps=_read_env("MAX_STEPS", defaults.max_steps, int),
            approval_threshold=_read_env(
                "APPROVAL_THRESHOLD", defaults.approval_threshold, Decimal
            ),
            simulated_payment_failures=_read_env(
                "SIMULATED_PAYMENT_FAILURES", defaults.simulated_payment_failures, int
            ),
            log_level=_read_env("LOG_LEVEL", defaults.log_level, str),
        )
