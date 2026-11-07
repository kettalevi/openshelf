# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Stock movement history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ...models import Product, StockMovement, User
from ...services.parsing import to_int
from ..deps import csrf_protect, get_db, require_user
from ..render import paginate, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


@router.get("/movements")
def list_movements(
    request: Request,
    product: str = "",
    page: str = "1",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    stmt = select(StockMovement).options(
        joinedload(StockMovement.product), joinedload(StockMovement.user)
    )
    product_id = to_int(product)
    filtered = None
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
        filtered = db.get(Product, product_id)
    stmt = stmt.order_by(StockMovement.id.desc())
    result = paginate(db, stmt, to_int(page, 1) or 1, per_page=50)
    return render(request, "movements.html", {"result": result, "filtered": filtered})
