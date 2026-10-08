"""Business rules of the mock company app. Shared by the REST API and the HTML pages,
so the browser path and the API path can never disagree about what is allowed."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any


class DomainError(Exception):
    """A business-rule failure with an HTTP status and a stable machine-readable code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rows(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def audit(db: sqlite3.Connection, actor: str, action: str, entity: str, entity_id: int | None, details: str = "") -> None:
    db.execute(
        "INSERT INTO audit_log (ts, actor, action, entity, entity_id, details) VALUES (?,?,?,?,?,?)",
        (now_iso(), actor, action, entity, entity_id, details),
    )


# ---------------------------------------------------------------- customers
def search_customers(db: sqlite3.Connection, q: str | None = None) -> list[dict]:
    """Every word in `q` must appear in the name or email (case-insensitive)."""
    sql = "SELECT id, name, email, phone, city FROM customers"
    params: list[str] = []
    tokens = (q or "").split()
    if tokens:
        sql += " WHERE " + " AND ".join("(name LIKE ? OR email LIKE ?)" for _ in tokens)
        for t in tokens:
            params += [f"%{t}%", f"%{t}%"]
    sql += " ORDER BY name"
    return _rows(db.execute(sql, params))


def get_customer(db: sqlite3.Connection, customer_id: int) -> dict:
    row = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise DomainError(404, "not_found", f"Customer {customer_id} not found")
    return dict(row)


# ------------------------------------------------------------------- orders
def list_orders(db: sqlite3.Connection, customer_id: int | None = None, status: str | None = None) -> list[dict]:
    """Newest first (by placed_at)."""
    if customer_id is not None:
        get_customer(db, customer_id)  # 404 if the customer does not exist
    sql = (
        "SELECT o.id, o.customer_id, o.status, o.total_amount, o.currency, o.placed_at, o.delivered_at,"
        " (SELECT group_concat(quantity || 'x ' || product, ', ') FROM order_items WHERE order_id = o.id)"
        "   AS items_summary"
        " FROM orders o WHERE 1=1"
    )
    params: list[Any] = []
    if customer_id is not None:
        sql += " AND o.customer_id = ?"
        params.append(customer_id)
    if status:
        sql += " AND o.status = ?"
        params.append(status)
    sql += " ORDER BY o.placed_at DESC, o.id DESC"
    return _rows(db.execute(sql, params))


def get_order(db: sqlite3.Connection, order_id: int) -> dict:
    row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise DomainError(404, "not_found", f"Order {order_id} not found")
    order = dict(row)
    order["items"] = _rows(
        db.execute("SELECT product, quantity, unit_price FROM order_items WHERE order_id = ?", (order_id,))
    )
    refund = db.execute(
        "SELECT id, amount, reason, created_at, created_by FROM refunds WHERE order_id = ?", (order_id,)
    ).fetchone()
    order["refund"] = dict(refund) if refund else None
    cust = db.execute("SELECT id, name, email FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    order["customer"] = dict(cust) if cust else None
    return order


def refund_order(
    db: sqlite3.Connection, order_id: int, reason: str, amount: float | None = None, actor: str = "api"
) -> dict:
    """Refund a delivered order. Refusing is part of the contract:
    404 unknown order, 409 already refunded, 422 not delivered / bad amount."""
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise DomainError(404, "not_found", f"Order {order_id} not found")
    if order["status"] == "refunded":
        raise DomainError(409, "already_refunded", f"Order {order_id} has already been refunded")
    if order["status"] != "delivered":
        raise DomainError(
            422, "not_refundable",
            f"Order {order_id} is '{order['status']}'; only delivered orders can be refunded",
        )
    total = order["total_amount"]
    refund_amount = total if amount is None else amount
    if refund_amount > total + 1e-9:
        raise DomainError(422, "invalid_amount", f"Refund amount {refund_amount} exceeds order total {total}")
    try:
        cur = db.execute(
            "INSERT INTO refunds (order_id, amount, reason, created_at, created_by) VALUES (?,?,?,?,?)",
            (order_id, refund_amount, reason, now_iso(), actor),
        )
        db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
        audit(db, actor, "refund_issued", "order", order_id, f"amount={refund_amount}; reason={reason}")
        db.commit()
    except sqlite3.IntegrityError as exc:  # lost a race with another refund request
        db.rollback()
        raise DomainError(409, "already_refunded", f"Order {order_id} has already been refunded") from exc
    return {
        "refund_id": cur.lastrowid,
        "order_id": order_id,
        "amount": refund_amount,
        "currency": order["currency"],
        "order_status": "refunded",
    }


# ------------------------------------------------------------ notifications
def send_notification(db: sqlite3.Connection, customer_id: int, subject: str, body: str, actor: str = "api") -> dict:
    get_customer(db, customer_id)
    cur = db.execute(
        "INSERT INTO notifications (customer_id, channel, subject, body, sent_at) VALUES (?,?,?,?,?)",
        (customer_id, "email", subject, body, now_iso()),
    )
    audit(db, actor, "notification_sent", "customer", customer_id, f"subject={subject}")
    db.commit()
    return {"notification_id": cur.lastrowid, "customer_id": customer_id, "channel": "email", "subject": subject}


def list_notifications(db: sqlite3.Connection, customer_id: int) -> list[dict]:
    get_customer(db, customer_id)
    return _rows(
        db.execute(
            "SELECT id, channel, subject, body, sent_at FROM notifications WHERE customer_id = ? ORDER BY id DESC",
            (customer_id,),
        )
    )


# ----------------------------------------------------------------- invoices
def list_invoices(db: sqlite3.Connection, overdue_days_gt: int | None = None) -> list[dict]:
    today = date.today()
    out = []
    for r in db.execute(
        "SELECT i.*, c.name AS customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id ORDER BY i.due_date"
    ):
        d = dict(r)
        due = date.fromisoformat(d["due_date"])
        d["days_overdue"] = max((today - due).days, 0) if d["status"] == "unpaid" else 0
        out.append(d)
    if overdue_days_gt is not None:
        out = [d for d in out if d["status"] == "unpaid" and d["days_overdue"] > overdue_days_gt]
    return out


def list_audit(db: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return _rows(db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)))
