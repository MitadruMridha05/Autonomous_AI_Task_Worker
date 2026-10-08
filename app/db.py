"""SQLite access for the mock company app (no ORM on purpose: the SQL is the documentation)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "opspilot.db"


def db_path() -> str:
    """Resolve the DB location at call time so tests can point OPSPILOT_DB at a temp file."""
    return os.environ.get("OPSPILOT_DB", str(DEFAULT_DB))


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    phone       TEXT,
    city        TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    status        TEXT NOT NULL CHECK (status IN ('placed','shipped','delivered','cancelled','refunded')),
    total_amount  REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'INR',
    placed_at     TEXT NOT NULL,
    delivered_at  TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product     TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL
);

-- UNIQUE(order_id): the database itself refuses a second refund for the same order.
CREATE TABLE IF NOT EXISTS refunds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    amount      REAL NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    channel      TEXT NOT NULL DEFAULT 'email',
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    sent_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    amount       REAL NOT NULL,
    issued_date  TEXT NOT NULL,
    due_date     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('paid','unpaid'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    details    TEXT
);
"""

TABLES_DROP_ORDER = [
    "audit_log", "notifications", "refunds", "order_items", "invoices", "orders", "customers",
]


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or db_path()
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def drop_all(conn: sqlite3.Connection) -> None:
    for table in TABLES_DROP_ORDER:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
