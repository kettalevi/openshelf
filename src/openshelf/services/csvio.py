# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""CSV export and import of products."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from itertools import islice

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..models import Category, Product, User
from ..plugins import PRODUCT_CREATED, PRODUCT_UPDATED, PluginRegistry
from .parsing import money_input, parse_nonneg_int
from .products import validate_product
from .stock import StockError, apply_change, emit_all

COLUMNS = [
    "sku",
    "name",
    "barcode",
    "category",
    "price",
    "cost",
    "quantity",
    "reorder_level",
    "unit",
    "description",
    "active",
]
MAX_ROWS = 5000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(text: str) -> str:
    """Stop spreadsheets from running text such as '=HYPERLINK(...)' as a formula."""
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _unsafe_cell(text: str) -> str:
    """Undo _safe_cell for values that came from our own export."""
    if len(text) > 1 and text[0] == "'" and text[1] in _FORMULA_PREFIXES:
        return text[1:]
    return text


def export_products(db: Session) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    products = db.scalars(
        select(Product).options(joinedload(Product.category)).order_by(Product.sku)
    )
    for p in products:
        writer.writerow(
            [
                _safe_cell(p.sku),
                _safe_cell(p.name),
                _safe_cell(p.barcode or ""),
                _safe_cell(p.category.name if p.category else ""),
                money_input(p.price_cents),
                money_input(p.cost_cents),
                p.quantity,
                p.reorder_level,
                _safe_cell(p.unit),
                _safe_cell(p.description),
                "yes" if p.is_active else "no",
            ]
        )
    return out.getvalue()


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


_TEXT_COLUMNS = ("sku", "name", "barcode", "category", "unit", "description")


def import_products(
    db: Session,
    registry: PluginRegistry | None,
    text: str,
    user: User | None,
) -> ImportResult:
    """Create or update products by SKU.

    All rows are validated first; if any row is invalid, nothing is changed.
    Empty cells leave existing values untouched. A ``quantity`` that differs
    from the current stock is recorded as a stock movement.
    """
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = {"sku", "name"} - headers
    if missing:
        result.errors.append(
            "Missing required column(s): " + ", ".join(sorted(missing)) + "."
        )
        return result

    rows = list(islice(reader, MAX_ROWS + 1))
    if len(rows) > MAX_ROWS:
        result.errors.append(f"Too many rows (the limit is {MAX_ROWS} per file).")
        return result

    plan: list[tuple[Product | None, dict, str, int | None]] = []
    seen: set[str] = set()
    for line, raw in enumerate(rows, start=2):
        row = {
            k.strip().lower(): (v or "").strip()
            for k, v in raw.items()
            if k and isinstance(v, (str, type(None)))
        }
        for col in _TEXT_COLUMNS:
            if col in row:
                row[col] = _unsafe_cell(row[col])
        if not any(row.values()):
            continue  # blank line

        sku = row.get("sku", "")
        if sku.lower() in seen:
            result.errors.append(f"Row {line}: SKU '{sku}' appears more than once.")
            continue
        seen.add(sku.lower())

        existing = (
            db.scalar(select(Product).where(func.lower(Product.sku) == sku.lower()))
            if sku
            else None
        )
        values = dict(row)
        if existing is not None:
            # Empty cells mean "keep what is already stored".
            current = {
                "name": existing.name,
                "barcode": existing.barcode or "",
                "description": existing.description,
                "unit": existing.unit,
                "price": money_input(existing.price_cents),
                "cost": money_input(existing.cost_cents),
                "reorder_level": str(existing.reorder_level),
                "category_id": str(existing.category_id or ""),
            }
            for key, stored in current.items():
                if not values.get(key):
                    values[key] = stored

        category_name = row.get("category", "")
        if category_name:
            values["category_id"] = ""  # resolved at apply time
        data, errors = validate_product(
            db,
            values,
            creating=False,
            product_id=existing.id if existing else None,
        )
        target_qty: int | None = None
        if row.get("quantity"):
            try:
                target_qty = parse_nonneg_int(row["quantity"], "Quantity")
            except ValueError as exc:
                errors.append(f"{exc}.")
        active_text = row.get("active", "").lower()
        if active_text and active_text not in {"yes", "no", "true", "false", "1", "0"}:
            errors.append("Active must be yes or no.")

        if errors:
            for message in errors:
                result.errors.append(f"Row {line}: {message}")
            continue
        if active_text:
            data["is_active"] = active_text in {"yes", "true", "1"}
        plan.append((existing, data, category_name, target_qty))

    if result.errors:
        return result

    events: list = []
    created_ids: list[int] = []
    updated_ids: list[int] = []
    try:
        categories = {c.name.lower(): c for c in db.scalars(select(Category))}
        for existing, data, category_name, target_qty in plan:
            if category_name:
                category = categories.get(category_name.lower())
                if category is None:
                    category = Category(name=category_name[:100])
                    db.add(category)
                    db.flush()
                    categories[category_name.lower()] = category
                data["category_id"] = category.id

            if existing is None:
                product = Product(**data, quantity=0)
                db.add(product)
                db.flush()
                if target_qty:
                    _, ev = apply_change(
                        db, product, target_qty, "import", "CSV import", user
                    )
                    events.extend(ev)
                created_ids.append(product.id)
                result.created += 1
            else:
                changed = any(getattr(existing, k) != v for k, v in data.items())
                for key, value in data.items():
                    setattr(existing, key, value)
                if target_qty is not None and target_qty != existing.quantity:
                    _, ev = apply_change(
                        db,
                        existing,
                        target_qty - existing.quantity,
                        "import",
                        "CSV import",
                        user,
                    )
                    events.extend(ev)
                    changed = True
                if changed:
                    updated_ids.append(existing.id)
                    result.updated += 1
                else:
                    result.unchanged += 1
        db.commit()
    except (IntegrityError, StockError) as exc:
        db.rollback()
        result.created = result.updated = result.unchanged = 0
        result.errors.append(f"Import failed and was rolled back: {exc}")
        return result

    if registry is not None:
        for pid in created_ids:
            registry.emit(PRODUCT_CREATED, product_id=pid, sku=db.get(Product, pid).sku)
        for pid in updated_ids:
            registry.emit(PRODUCT_UPDATED, product_id=pid, sku=db.get(Product, pid).sku)
    emit_all(registry, events)
    return result
