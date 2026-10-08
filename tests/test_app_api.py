"""The mock company app: REST rules, HTML pages, and the seed data the scenarios rely on."""


def test_health(http):
    assert http.get("/api/health").json() == {"status": "ok"}


def test_search_is_case_insensitive_and_multiword(http):
    assert [c["id"] for c in http.get("/api/customers", params={"q": "priya sharma"}).json()] == [1]
    assert [c["id"] for c in http.get("/api/customers", params={"q": "SHARMA priya"}).json()] == [1]


def test_ambiguous_name_returns_two_johns(http):
    names = {c["name"] for c in http.get("/api/customers", params={"q": "john"}).json()}
    assert names == {"John Mathew", "John D'Souza"}


def test_orders_are_newest_first(http):
    orders = http.get("/api/orders", params={"customer_id": 1}).json()
    assert [o["id"] for o in orders] == [1004, 1001]
    assert orders[0]["items_summary"] == "2x Glass Water Bottle"


def test_unknown_customer_and_order_are_404(http):
    assert http.get("/api/customers/999").status_code == 404
    assert http.get("/api/orders", params={"customer_id": 999}).status_code == 404
    r = http.get("/api/orders/9999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_refund_happy_path_changes_state_everywhere(http, query):
    r = http.post("/api/orders/1004/refund", json={"reason": "Item arrived damaged"})
    assert r.status_code == 201
    assert r.json()["amount"] == 1198.0
    order = http.get("/api/orders/1004").json()
    assert order["status"] == "refunded" and order["refund"]["reason"] == "Item arrived damaged"
    assert query("SELECT COUNT(*) AS n FROM refunds WHERE order_id = 1004")[0]["n"] == 1
    assert query("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1")[0]["action"] == "refund_issued"


def test_refund_twice_is_rejected_and_not_duplicated(http, query):
    assert http.post("/api/orders/1004/refund", json={"reason": "damaged"}).status_code == 201
    again = http.post("/api/orders/1004/refund", json={"reason": "damaged"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_refunded"
    assert query("SELECT COUNT(*) AS n FROM refunds WHERE order_id = 1004")[0]["n"] == 1


def test_seeded_refunded_order_cannot_be_refunded_again(http):
    r = http.post("/api/orders/1005/refund", json={"reason": "again please"})
    assert r.status_code == 409


def test_non_delivered_orders_are_not_refundable(http):
    for oid in (1006, 1007, 1008):  # shipped, placed, cancelled
        r = http.post(f"/api/orders/{oid}/refund", json={"reason": "not delivered"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "not_refundable"


def test_refund_amount_cannot_exceed_total(http):
    r = http.post("/api/orders/1004/refund", json={"reason": "too much", "amount": 99999})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_amount"


def test_refund_requires_a_reason(http):
    assert http.post("/api/orders/1004/refund", json={}).status_code == 422


def test_notifications_roundtrip(http):
    r = http.post("/api/customers/1/notifications", json={"subject": "Your refund", "body": "Done."})
    assert r.status_code == 201
    assert http.get("/api/customers/1/notifications").json()[0]["subject"] == "Your refund"
    assert http.post("/api/customers/999/notifications", json={"subject": "x", "body": "y"}).status_code == 404


def test_overdue_invoice_filter(http):
    ids = {i["id"] for i in http.get("/api/invoices", params={"overdue_days_gt": 30}).json()}
    assert ids == {5001, 5003, 5005}  # unpaid and more than 30 days past due


def test_html_pages_render_and_refund_form_works(http):
    assert "Priya Sharma" in http.get("/customers").text
    assert "Glass Water Bottle" in http.get("/customers/1").text
    page = http.get("/orders/1004").text
    assert 'id="refund-submit"' in page
    done = http.post("/orders/1004/refund", data={"reason": "Damaged in transit"})  # follows the redirect
    assert done.status_code == 200 and "Refund issued" in done.text
    assert 'id="refund-record"' in done.text and 'id="refund-submit"' not in done.text


def test_html_refund_error_is_shown_with_status_code(http):
    r = http.post("/orders/1005/refund", data={"reason": "again please"})
    assert r.status_code == 409 and "already been refunded" in r.text
