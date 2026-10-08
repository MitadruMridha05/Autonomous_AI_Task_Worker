"""Environment loading. Secrets live in .env (git-ignored), never in code."""
from __future__ import annotations

import os

from dotenv import load_dotenv


def load_env() -> None:
    load_dotenv(override=False)


def opspilot_url() -> str:
    return os.getenv("OPSPILOT_URL", "http://127.0.0.1:8000")
