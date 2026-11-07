# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
from conftest import add_product
from sqlalchemy import select

from openshelf.models import Product, StockMovement


def _product(app, product_id):
    with app.state.session_factory() as db:
        return db.get(Product, product_id)


def test_create_product_records_initial_stock(admin, app):
    pid = add_product(admin, quantity="12", price="1,299.50")
    product = _product(app, pid)
    assert (product.quantity, product.price_cents, product.cost_cents) == (12, 129950, 400)
    with app.state.session_factory() as db:
        move = db.scalars(select(StockMovement)).one()
    assert (move.change, move.quantity_after, move.reason) == (12, 12, "initial")
    page = admin.get(f"/products/{pid}").text
    assert "Widget" in page and "1,299.50" in page


def test_product_validation_errors(admin):
    response = admin.post("/products", {"sku": "", "name": "", "price": "abc", "quantity": "-2"})
    assert response.status_code == 400
    for message in ("SKU is required", "Name is required", "not a valid amount", "cannot be negative"):
        assert message in response.text


def test_duplicate_sku_rejected_case_insensitively(admin):
    add_product(admin, sku="ABC-1")
    response = admin.post("/products", {"sku": "abc-1", "name": "Other"})
    assert response.status_code == 400 and "already exists" in response.text


def test_html_in_names_is_escaped(admin):
    pid = add_product(admin, sku="X", name="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in admin.get(f"/products/{pid}").text
    assert "&lt;script&gt;" in admin.get("/products").text


def test_edit_product(admin, app):
    pid = add_product(admin)
    page = admin.get(f"/products/{pid}/edit").text
    assert 'value="Widget"' in page and 'value="9.99"' in page
    response = admin.post(
        f"/products/{pid}/edit",
        {"sku": "SKU-1", "name": "Widget Pro", "price": "12", "cost": "5", "reorder_level": "4", "unit": "box"},
    )
    assert response.status_code == 303
    product = _product(app, pid)
    assert (product.name, product.price_cents, product.unit, product.quantity) == ("Widget Pro", 1200, "box", 10)


def test_stock_add_remove_set(admin, app):
    pid = add_product(admin, quantity="10")
    base = {"reason": "sale", "note": "till 1"}
    admin.post(f"/products/{pid}/stock", {**base, "action": "remove", "quantity": "4"})
    assert _product(app, pid).quantity == 6
    admin.post(f"/products/{pid}/stock", {**base, "reason": "purchase", "action": "add", "quantity": "5"})
    assert _product(app, pid).quantity == 11
    admin.post(f"/products/{pid}/stock", {**base, "reason": "stocktake", "action": "set", "quantity": "7"})
    assert _product(app, pid).quantity == 7
    with app.state.session_factory() as db:
        changes = [m.change for m in db.scalars(select(StockMovement).order_by(StockMovement.id))]
    assert changes == [10, -4, 5, -4]


def test_cannot_remove_more_than_on_hand(admin, app):
    pid = add_product(admin, quantity="3")
    response = admin.post(
        f"/products/{pid}/stock", {"action": "remove", "quantity": "5", "reason": "sale"}
    )
    assert response.status_code == 303
    assert _product(app, pid).quantity == 3
    assert "Not enough stock" in admin.get(f"/products/{pid}").text


def test_invalid_stock_input_is_rejected(admin, app):
    pid = add_product(admin, quantity="3")
    for payload in (
        {"action": "add", "quantity": "-1", "reason": "purchase"},
        {"action": "add", "quantity": "abc", "reason": "purchase"},
        {"action": "add", "quantity": "1", "reason": "bogus"},
        {"action": "explode", "quantity": "1", "reason": "purchase"},
    ):
        admin.post(f"/products/{pid}/stock", payload)
    assert _product(app, pid).quantity == 3


def test_dashboard_flags_low_stock(admin):
    add_product(admin, sku="A", name="Plenty", quantity="50", reorder_level="5")
    add_product(admin, sku="B", name="Scarce", quantity="2", reorder_level="5")
    dashboard = admin.get("/").text
    assert "Scarce" in dashboard
    assert "Plenty" not in dashboard.split("Needs restocking")[1].split("Recent activity")[0]
    low = admin.get("/products?low=1").text
    assert "Scarce" in low and "Plenty" not in low


def test_search_treats_wildcards_literally(admin):
    add_product(admin, sku="A1", name="100% Cotton")
    add_product(admin, sku="B2", name="Wool")
    assert "Wool" not in admin.get("/products?q=%25").text  # '%' matches only the literal
    assert "100% Cotton" in admin.get("/products?q=%25").text
    assert "Wool" in admin.get("/products?q=b2").text  # SKU, case-insensitive


def test_inactive_products_hidden_and_locked(admin, staff, app):
    pid = add_product(admin, name="Retired")
    assert staff.post(f"/products/{pid}/deactivate").status_code == 403
    admin.post(f"/products/{pid}/deactivate")
    admin.get(f"/products/{pid}")  # follow the redirect, consuming the flash message
    assert "Retired" not in admin.get("/products").text
    assert "Retired" in admin.get("/products?inactive=1").text
    admin.post(f"/products/{pid}/stock", {"action": "add", "quantity": "1", "reason": "purchase"})
    assert _product(app, pid).quantity == 10
    admin.post(f"/products/{pid}/activate")
    assert "Retired" in admin.get("/products").text


def test_deleting_category_keeps_products(admin, app):
    admin.post("/categories", {"name": "Snacks"})
    admin.post("/categories", {"name": "snacks"})  # duplicate, ignored
    with app.state.session_factory() as db:
        from openshelf.models import Category

        category = db.scalars(select(Category)).one()
    pid = add_product(admin, category_id=str(category.id))
    assert _product(app, pid).category_id == category.id
    admin.post(f"/categories/{category.id}/delete")
    assert _product(app, pid).category_id is None


def test_unknown_product_is_404_page(admin):
    response = admin.get("/products/999")
    assert response.status_code == 404 and "Product not found" in response.text


def test_pagination(admin):
    for i in range(30):
        add_product(admin, sku=f"P{i:02d}", name=f"Item {i:02d}", quantity="0")
    page1, page2 = admin.get("/products").text, admin.get("/products?page=2").text
    assert "Item 00" in page1 and "Item 29" not in page1
    assert "Item 29" in page2 and "Page 2 of 2" in page2
    assert admin.get("/products?page=junk").status_code == 200


def test_movement_history_filter(admin):
    a = add_product(admin, sku="A", name="Alpha")
    add_product(admin, sku="B", name="Beta")
    page = admin.get(f"/movements?product={a}").text
    assert "Alpha" in page and "Beta" not in page
