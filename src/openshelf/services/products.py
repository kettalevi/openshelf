# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Validation of product input, shared by the web forms and CSV import."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, Product
from .parsing import parse_money, parse_nonneg_int, to_int


def validate_product(
    db: Session,
    values: dict[str, str],
    *,
    creating: bool,
    product_id: int | None = None,
) -> tuple[dict, list[str]]:
    """Validate raw form values. Returns (clean data, error messages)."""
    errors: list[str] = []
    data: dict = {}

    sku = values.get("sku", "").strip()
    if not sku:
        errors.append("SKU is required.")
    elif len(sku) > 64:
        errors.append("SKU must be 64 characters or fewer.")
    else:
        clash = db.scalar(
            select(Product.id).where(
                func.lower(Product.sku) == sku.lower(),
                Product.id != (product_id or -1),
            )
        )
        if clash:
            errors.append(f"A product with SKU '{sku}' already exists.")
    data["sku"] = sku

    name = values.get("name", "").strip()
    if not name:
        errors.append("Name is required.")
    elif len(name) > 200:
        errors.append("Name must be 200 characters or fewer.")
    data["name"] = name

    barcode = values.get("barcode", "").strip()
    if len(barcode) > 64:
        errors.append("Barcode must be 64 characters or fewer.")
    data["barcode"] = barcode or None

    data["description"] = values.get("description", "").strip()[:5000]

    unit = values.get("unit", "").strip() or "pcs"
    if len(unit) > 32:
        errors.append("Unit must be 32 characters or fewer.")
    data["unit"] = unit

    category_raw = values.get("category_id", "").strip()
    data["category_id"] = None
    if category_raw:
        category_id = to_int(category_raw)
        if category_id is None or db.get(Category, category_id) is None:
            errors.append("Selected category does not exist.")
        else:
            data["category_id"] = category_id

    for field, label in (("price", "Price"), ("cost", "Cost")):
        try:
            data[f"{field}_cents"] = parse_money(values.get(field, ""))
        except ValueError as exc:
            errors.append(f"{label}: {exc}.")
            data[f"{field}_cents"] = 0

    try:
        data["reorder_level"] = parse_nonneg_int(
            values.get("reorder_level", ""), "Reorder level"
        )
    except ValueError as exc:
        errors.append(f"{exc}.")
        data["reorder_level"] = 0

    if creating:
        try:
            data["quantity"] = parse_nonneg_int(
                values.get("quantity", ""), "Starting quantity"
            )
        except ValueError as exc:
            errors.append(f"{exc}.")
            data["quantity"] = 0

    return data, errors
