# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Dashboard with headline numbers, low-stock list and recent activity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ...models import Product, StockMovement, User
from ..deps import csrf_protect, get_db, require_user
from ..render import render

router = APIRouter(dependencies=[Depends(csrf_protect)])


@router.get("/")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    active = Product.is_active.is_(True)
    count, units, cost_value, retail_value = db.execute(
        select(
            func.count(Product.id),
            func.coalesce(func.sum(Product.quantity), 0),
            func.coalesce(func.sum(Product.quantity * Product.cost_cents), 0),
            func.coalesce(func.sum(Product.quantity * Product.price_cents), 0),
        ).where(active)
    ).one()
    low_filter = (active, Product.quantity <= Product.reorder_level)
    low_total = db.scalar(select(func.count(Product.id)).where(*low_filter))
    low_stock = db.scalars(
        select(Product)
        .where(*low_filter)
        .order_by(Product.quantity, Product.name)
        .limit(10)
    ).all()
    recent = db.scalars(
        select(StockMovement)
        .options(joinedload(StockMovement.product), joinedload(StockMovement.user))
        .order_by(StockMovement.id.desc())
        .limit(10)
    ).all()
    return render(
        request,
        "dashboard.html",
        {
            "product_count": count,
            "units": units,
            "cost_value": cost_value,
            "retail_value": retail_value,
            "low_total": low_total,
            "low_stock": low_stock,
            "recent": recent,
        },
    )
