"""OpsPilot mock company app: a tiny support/orders admin portal.

  REST API  -> /api/...   (what API tools use; interactive docs at /docs)
  HTML UI   -> /customers, /orders/{id}   (what the Day 2 browser tools will click through)

Run:  uvicorn app.main:app --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import chaos, services
from .db import connect, db_path, init_schema
from .schemas import NotificationRequest, RefundRequest
from .seed import reset_db, seed
from .services import DomainError

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    """First start: create the schema and seed it, so `uvicorn app.main:app` just works."""
    conn = connect()
    try:
        init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            seed(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="OpsPilot Mock Company App", version="0.1.0", lifespan=lifespan)


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


# ------------------------------------------------------------------ REST API
api = APIRouter(prefix="/api", tags=["api"])


@api.get("/health")
def health():
    return {"status": "ok"}


@api.get("/customers")
def api_search_customers(q: str | None = Query(None, description="Words matched against name/email"), db=Depends(get_db)):
    return services.search_customers(db, q)


@api.get("/customers/{customer_id}")
def api_get_customer(customer_id: int, db=Depends(get_db)):
    return services.get_customer(db, customer_id)


@api.get("/orders")
def api_list_orders(customer_id: int | None = None, status: str | None = None, db=Depends(get_db)):
    return services.list_orders(db, customer_id, status)


@api.get("/orders/{order_id}")
def api_get_order(order_id: int, db=Depends(get_db)):
    return services.get_order(db, order_id)


@api.post("/orders/{order_id}/refund", status_code=201)
def api_refund_order(order_id: int, body: RefundRequest, db=Depends(get_db)):
    return services.refund_order(db, order_id, body.reason, body.amount, actor="api")


@api.post("/customers/{customer_id}/notifications", status_code=201)
def api_send_notification(customer_id: int, body: NotificationRequest, db=Depends(get_db)):
    return services.send_notification(db, customer_id, body.subject, body.body, actor="api")


@api.get("/customers/{customer_id}/notifications")
def api_list_notifications(customer_id: int, db=Depends(get_db)):
    return services.list_notifications(db, customer_id)


@api.get("/invoices")
def api_list_invoices(overdue_days_gt: int | None = None, db=Depends(get_db)):
    return services.list_invoices(db, overdue_days_gt)

@api.get("/audit")
def api_audit(limit: int = 20, db=Depends(get_db)):
    return services.list_audit(db, limit)


@api.post("/admin/reset")
def api_reset():
    """Test helper: restore the seed data. Not exposed to the agent as a tool."""
    reset_db()
    return {"status": "reset", "db": db_path()}


app.include_router(api)


# ------------------------------------------------------------------ HTML UI
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/customers", status_code=303)


@app.get("/customers", include_in_schema=False)
def ui_customers(request: Request, q: str = "", db=Depends(get_db)):
    return templates.TemplateResponse(request, "customers.html", {"customers": services.search_customers(db, q), "q": q})


@app.get("/customers/{customer_id}", include_in_schema=False)
def ui_customer(request: Request, customer_id: int, db=Depends(get_db)):
    customer = services.get_customer(db, customer_id)
    return templates.TemplateResponse(
        request,
        "customer.html",
        {
            "customer": customer,
            "orders": services.list_orders(db, customer_id),
            "notifications": services.list_notifications(db, customer_id),
        },
    )


@app.get("/orders/{order_id}", include_in_schema=False)
def ui_order(request: Request, order_id: int, msg: str = "", db=Depends(get_db)):
    return templates.TemplateResponse(request, "order.html", {"order": services.get_order(db, order_id), "msg": msg, "error": ""})


@app.post("/orders/{order_id}/refund", include_in_schema=False)
def ui_refund(request: Request, order_id: int, reason: str = Form(...), db=Depends(get_db)):
    if chaos.should_fail("ui_refund"):
        return templates.TemplateResponse(
            request,
            "order.html",
            {"order": services.get_order(db, order_id), "msg": "", "error": "Temporary UI failure; try the API fallback."},
            status_code=500,
        )
    try:
        services.refund_order(db, order_id, reason.strip(), actor="ui")
    except DomainError as exc:
        if exc.status == 404:
            raise
        order = services.get_order(db, order_id)
        return templates.TemplateResponse(
            request, "order.html", {"order": order, "msg": "", "error": exc.message}, status_code=exc.status
        )
    return RedirectResponse(f"/orders/{order_id}?msg={quote('Refund issued')}", status_code=303)
