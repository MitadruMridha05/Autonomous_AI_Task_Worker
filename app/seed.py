"""Deterministic seed data. Run `python -m app.seed` to (re)create data/opspilot.db.

The data is designed so that each scenario in the assignment has something to bite on:
  * Priya Sharma (id 1)      -> Task 1: damaged item, latest order 1004 is refundable
  * John Mathew / John D'Souza -> ambiguity: "Refund John's order" must trigger a question
  * Order 1005 (Ananya Rao)  -> already refunded: the agent must report "no action needed"
  * Orders 1006-1008         -> shipped / placed / cancelled: not refundable
  * Invoices                 -> Day 2 task: export invoices overdue by more than 30 days
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from .db import connect, db_path, drop_all, init_schema

CUSTOMERS = [
    (1, "Priya Sharma", "priya.sharma@example.com", "+91 90000 00001", "Hyderabad"),
    (2, "John Mathew", "john.mathew@example.com", "+91 90000 00002", "Kochi"),
    (3, "John D'Souza", "john.dsouza@example.com", "+91 90000 00003", "Mumbai"),
    (4, "Ananya Rao", "ananya.rao@example.com", "+91 90000 00004", "Bengaluru"),
    (5, "Rahul Verma", "rahul.verma@example.com", "+91 90000 00005", "Delhi"),
    (6, "Sneha Iyer", "sneha.iyer@example.com", "+91 90000 00006", "Chennai"),
]

# (order_id, customer_id, status, placed_days_ago, delivered_days_ago, [(product, qty, unit_price)])
ORDERS = [
    (1001, 1, "delivered", 40, 35, [("Wireless Earbuds", 1, 2499.0)]),
    (1002, 2, "delivered", 20, 16, [("Running Shoes", 1, 3999.0)]),
    (1003, 3, "delivered", 18, 14, [("Bluetooth Speaker", 1, 1799.0), ("Phone Case", 2, 299.0)]),
    (1004, 1, "delivered", 9, 5, [("Glass Water Bottle", 2, 599.0)]),  # Priya's latest order
    (1005, 4, "refunded", 30, 26, [("Yoga Mat", 1, 1299.0)]),
    (1006, 3, "shipped", 3, None, [("USB-C Cable", 3, 249.0)]),
    (1007, 5, "placed", 1, None, [("Desk Lamp", 1, 1599.0)]),
    (1008, 5, "cancelled", 12, None, [("Notebook Set", 4, 150.0)]),
    (1009, 6, "delivered", 25, 21, [("Ceramic Mug Set", 1, 899.0)]),
]

# (invoice_id, customer_id, amount, issued_days_ago, due_days_ago, status); negative due_days_ago = due in future
INVOICES = [
    (5001, 1, 12500.0, 75, 45, "unpaid"),
    (5002, 2, 8200.0, 50, 20, "unpaid"),
    (5003, 3, 15400.0, 100, 70, "unpaid"),
    (5004, 4, 4300.0, 60, 30, "paid"),
    (5005, 5, 9900.0, 45, 35, "unpaid"),
    (5006, 6, 2750.0, 10, -20, "unpaid"),
]


def _ts(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def seed(conn: sqlite3.Connection) -> None:
    today = date.today()
    for cid, name, email, phone, city in CUSTOMERS:
        conn.execute(
            "INSERT INTO customers (id, name, email, phone, city, created_at) VALUES (?,?,?,?,?,?)",
            (cid, name, email, phone, city, _ts(200)),
        )
    for oid, cid, status, placed, delivered, items in ORDERS:
        total = round(sum(q * p for _, q, p in items), 2)
        conn.execute(
            "INSERT INTO orders (id, customer_id, status, total_amount, currency, placed_at, delivered_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (oid, cid, status, total, "INR", _ts(placed), _ts(delivered) if delivered is not None else None),
        )
        for product, qty, price in items:
            conn.execute(
                "INSERT INTO order_items (order_id, product, quantity, unit_price) VALUES (?,?,?,?)",
                (oid, product, qty, price),
            )
    # Order 1005 is already refunded, with a matching refund record (consistent state).
    conn.execute(
        "INSERT INTO refunds (order_id, amount, reason, created_at, created_by) VALUES (?,?,?,?,?)",
        (1005, 1299.0, "Item not as described", _ts(25), "seed"),
    )
    for iid, cid, amount, issued, due, status in INVOICES:
        conn.execute(
            "INSERT INTO invoices (id, customer_id, amount, issued_date, due_date, status) VALUES (?,?,?,?,?,?)",
            (iid, cid, amount, (today - timedelta(days=issued)).isoformat(),
             (today - timedelta(days=due)).isoformat(), status),
        )
    conn.commit()


def reset_db(path: str | None = None) -> str:
    """Drop everything and re-seed. Returns the DB path used."""
    conn = connect(path)
    try:
        drop_all(conn)
        init_schema(conn)
        seed(conn)
    finally:
        conn.close()
    return path or db_path()


if __name__ == "__main__":
    print(f"Seeded database at {reset_db()}")
