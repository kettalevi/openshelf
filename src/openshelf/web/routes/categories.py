# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Product categories. Anyone can view; only admins change them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models import Category, Product, User
from ..deps import csrf_protect, get_db, get_form, require_admin, require_user
from ..render import flash, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


@router.get("/categories")
def list_categories(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    rows = db.execute(
        select(Category, func.count(Product.id))
        .outerjoin(Product, Product.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
    ).all()
    return render(request, "categories.html", {"rows": rows})


@router.post("/categories")
def create_category(
    request: Request,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    name = form.get("name", "").strip()
    if not name or len(name) > 100:
        flash(request, "Category name is required (100 characters at most).", "error")
    else:
        existing = db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
        if existing:
            flash(request, f"Category '{existing.name}' already exists.", "error")
        else:
            db.add(Category(name=name))
            try:
                db.commit()
                flash(request, f"Added category '{name}'.", "success")
            except IntegrityError:
                db.rollback()
                flash(request, f"Category '{name}' already exists.", "error")
    return RedirectResponse("/categories", status_code=303)


@router.post("/categories/{category_id:int}/delete")
def delete_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found.")
    # Products keep existing; they simply become uncategorised.
    db.execute(
        update(Product).where(Product.category_id == category.id).values(category_id=None)
    )
    db.delete(category)
    db.commit()
    flash(request, f"Deleted category '{category.name}'.", "success")
    return RedirectResponse("/categories", status_code=303)
