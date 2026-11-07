# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
import csv
import io

from conftest import add_product
from sqlalchemy import func, select

from openshelf.models import Category, Product, StockMovement
from openshelf.services.parsing import format_money, parse_money


def _upload(browser, text, name="products.csv"):
    return browser.post(
        "/products/import", files={"file": (name, text.encode(), "text/csv")}
    )


def _by_sku(app, sku):
    with app.state.session_factory() as db:
        return db.scalar(select(Product).where(Product.sku == sku))


def test_export_has_header_and_rows(admin):
    add_product(admin, sku="A1", name="Apple", price="1.50", quantity="7")
    response = admin.get("/products/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["sku"] == "A1" and rows[0]["price"] == "1.50" and rows[0]["quantity"] == "7"


def test_export_neutralises_spreadsheet_formulas(admin):
    add_product(admin, sku="F1", name='=HYPERLINK("http://evil","x")')
    rows = list(csv.DictReader(io.StringIO(admin.get("/products/export.csv").text)))
    assert rows[0]["name"].startswith("'=")


def test_import_creates_and_updates(admin, app):
    add_product(admin, sku="OLD", name="Old name", quantity="5", price="2.00")
    text = (
        "sku,name,category,price,quantity,reorder_level\n"
        "NEW1,Brand new,Drinks,3.25,20,5\n"
        "OLD,Renamed,,,8,\n"
    )
    response = _upload(admin, text)
    assert response.status_code == 200
    new, old = _by_sku(app, "NEW1"), _by_sku(app, "OLD")
    assert (new.name, new.price_cents, new.quantity, new.reorder_level) == ("Brand new", 325, 20, 5)
    assert (old.name, old.price_cents, old.quantity) == ("Renamed", 200, 8)  # blank price kept
    with app.state.session_factory() as db:
        assert db.scalar(select(Category.name)) == "Drinks"
        assert db.scalar(select(StockMovement.change).where(StockMovement.product_id == old.id, StockMovement.reason == "import")) == 3
    assert "1 added, 1 updated" in response.text


def test_import_is_all_or_nothing(admin, app):
    text = (
        "sku,name,price,quantity\n"
        "OK1,Fine,1.00,5\n"
        "BAD,Broken,not-money,5\n"
        "OK1,Duplicate,1.00,5\n"
        ",No sku,1.00,1\n"
    )
    response = _upload(admin, text)
    assert response.status_code == 400
    for message in ("Row 3", "not a valid amount", "Row 4", "more than once", "Row 5", "SKU is required"):
        assert message in response.text
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 0


def test_import_rejects_missing_columns_and_bad_files(admin):
    assert "Missing required" in _upload(admin, "name,price\nA,1\n").text
    bad = admin.post("/products/import", files={"file": ("x.csv", b"\xff\xfe\x00bad", "text/csv")})
    assert bad.status_code == 400 and "UTF-8" in bad.text
    assert admin.post("/products/import").status_code == 400  # no file at all
    big = admin.post("/products/import", files={"file": ("big.csv", b"x" * (2 * 1024 * 1024 + 10), "text/csv")})
    assert big.status_code == 400 and "larger than 2 MB" in big.text


def test_export_then_import_is_a_noop(admin, app):
    add_product(admin, sku="R1", name='=weird, "quoted"', description="line\nbreak")
    exported = admin.get("/products/export.csv").text
    before = _by_sku(app, "R1")
    response = _upload(admin, exported)
    assert response.status_code == 200
    after = _by_sku(app, "R1")
    assert (after.name, after.description, after.quantity) == (before.name, before.description, before.quantity)
    assert "0 added, 0 updated, 1 unchanged" in response.text


def test_import_handles_bom_and_blank_lines(admin, app):
    _upload(admin, "﻿sku,name\n\nB1,With BOM\n\n")
    assert _by_sku(app, "B1").name == "With BOM"


def test_staff_cannot_import(staff):
    assert staff.post("/products/import", files={"file": ("a.csv", b"sku,name\nA,B\n", "text/csv")}).status_code == 403


def test_money_helpers():
    assert parse_money("1,234.567") == 123457
    assert parse_money("") == 0 and parse_money("0.005") == 1
    for bad in ("-1", "abc", "NaN", "inf", "1e30"):
        try:
            parse_money(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")
    assert format_money(123457) == "1,234.57" and format_money(5) == "0.05"
