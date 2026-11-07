# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Stock level changes. Every change is recorded as a StockMovement."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Product, StockMovement, User, utcnow
from ..plugins import STOCK_CHANGED, STOCK_LOW, PluginRegistry

# Reasons a person may pick in the UI.
UI_REASONS = ("purchase", "sale", "return", "damaged", "adjustment", "stocktake")
# All valid reasons ("initial" and "import" are set by the system).
REASONS = UI_REASONS + ("initial", "import")


class StockError(ValueError):
    """A stock change that cannot be made (e.g. it would go below zero)."""


def apply_change(
    db: Session,
    product: Product,
    change: int,
    reason: str,
    note: str = "",
    user: User | None = None,
) -> tuple[StockMovement, list[tuple[str, dict]]]:
    """Apply a change inside the caller's transaction (no commit, no hooks).

    Returns the movement and the events to emit once the caller has committed.
    The quantity is updated with a single atomic SQL statement, so concurrent
    requests cannot lose updates or drive stock below zero.
    """
    if reason not in REASONS:
        raise StockError(f"Unknown reason '{reason}'")
    if change == 0:
        raise StockError("The quantity change cannot be zero")

    result = db.execute(
        update(Product)
        .where(Product.id == product.id, Product.quantity + change >= 0)
        .values(quantity=Product.quantity + change, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise StockError(
            f"Not enough stock of {product.sku}: cannot remove {-change} "
            f"({product.quantity} on hand)"
        )
    db.refresh(product)

    movement = StockMovement(
        product_id=product.id,
        change=change,
        quantity_after=product.quantity,
        reason=reason,
        note=(note or "")[:500],
        user_id=user.id if user else None,
    )
    db.add(movement)
    db.flush()

    events: list[tuple[str, dict]] = [
        (
            STOCK_CHANGED,
            dict(
                product_id=product.id,
                sku=product.sku,
                change=change,
                quantity_after=product.quantity,
                reason=reason,
                movement_id=movement.id,
            ),
        )
    ]
    previous = product.quantity - change
    if previous > product.reorder_level >= product.quantity:
        events.append(
            (
                STOCK_LOW,
                dict(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    quantity=product.quantity,
                    reorder_level=product.reorder_level,
                ),
            )
        )
    return movement, events


def emit_all(registry: PluginRegistry | None, events: list[tuple[str, dict]]) -> None:
    if registry is None:
        return
    for name, payload in events:
        registry.emit(name, **payload)


def adjust_stock(
    db: Session,
    registry: PluginRegistry | None,
    product: Product,
    change: int,
    reason: str,
    note: str = "",
    user: User | None = None,
) -> StockMovement:
    """Change stock, commit, then notify plugins."""
    try:
        movement, events = apply_change(db, product, change, reason, note, user)
        db.commit()
    except StockError:
        db.rollback()
        raise
    emit_all(registry, events)
    return movement
