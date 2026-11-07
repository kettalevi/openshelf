# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Products: list, create, edit, stock changes, activate/deactivate, CSV."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ...models import Category, Product, StockMovement, User, utcnow
from ...plugins import PRODUCT_CREATED, PRODUCT_UPDATED
from ...services import csvio
from ...services.parsing import money_input, parse_nonneg_int, to_int
from ...services.products import validate_product
from ...services.stock import UI_REASONS, StockError, adjust_stock
from ..deps import csrf_protect, get_db, get_form, require_admin, require_user
from ..render import flash, paginate, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

FORM_FIELDS = (
    "sku", "name", "barcode", "description", "category_id",
    "price", "cost", "quantity", "reorder_level", "unit",
)  # fmt: skip
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def _get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found.")
    return product


def _categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.name)))


def _values_from_product(p: Product) -> dict[str, str]:
    return {
        "sku": p.sku,
        "name": p.name,
        "barcode": p.barcode or "",
        "description": p.description,
        "category_id": str(p.category_id or ""),
        "price": money_input(p.price_cents),
        "cost": money_input(p.cost_cents),
        "reorder_level": str(p.reorder_level),
        "unit": p.unit,
    }


def _render_form(request, db, values, errors, product=None, status_code=200):
    return render(
        request,
        "product_form.html",
        {
            "values": values,
            "errors": errors,
            "product": product,
            "categories": _categories(db),
        },
        status_code=status_code,
    )


@router.get("/products")
def list_products(
    request: Request,
    q: str = "",
    category: str = "",
    low: str = "",
    inactive: str = "",
    page: str = "1",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    stmt = select(Product).options(joinedload(Product.category))
    q = q.strip()
    if q:
        stmt = stmt.where(
            or_(
                Product.name.icontains(q, autoescape=True),
                Product.sku.icontains(q, autoescape=True),
                Product.barcode.icontains(q, autoescape=True),
            )
        )
    category_id = to_int(category)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if low:
        stmt = stmt.where(Product.quantity <= Product.reorder_level)
    if not inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    stmt = stmt.order_by(Product.name, Product.id)
    result = paginate(db, stmt, to_int(page, 1) or 1)
    return render(
        request,
        "products.html",
        {
            "result": result,
            "categories": _categories(db),
            "q": q,
            "category": category_id,
            "low": bool(low),
            "inactive": bool(inactive),
        },
    )


@router.get("/products/new")
def new_product_form(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    return _render_form(request, db, {"unit": "pcs"}, [])


@router.post("/products")
def create_product(
    request: Request,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    values = {f: form.get(f, "") for f in FORM_FIELDS}
    data, errors = validate_product(db, values, creating=True)
    if errors:
        return _render_form(request, db, values, errors, status_code=400)

    quantity = data.pop("quantity")
    product = Product(**data)
    db.add(product)
    try:
        db.flush()
    except IntegrityError:  # two people creating the same SKU at once
        db.rollback()
        return _render_form(
            request, db, values, [f"A product with SKU '{data['sku']}' already exists."], status_code=400
        )
    registry = request.app.state.registry
    if quantity:
        adjust_stock(db, registry, product, quantity, "initial", "Starting stock", user)
    else:
        db.commit()
    registry.emit(PRODUCT_CREATED, product_id=product.id, sku=product.sku)
    flash(request, f"Added {product.name}.", "success")
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@router.get("/products/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(require_user)):
    filename = f"openshelf-products-{datetime.now():%Y%m%d}.csv"
    return Response(
        csvio.export_products(db),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/products/import")
def import_form(request: Request, user: User = Depends(require_admin)):
    return render(request, "import.html", {"result": None, "columns": csvio.COLUMNS})


@router.post("/products/import")
def import_csv(
    request: Request,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    upload = form.get("file")
    ctx = {"result": None, "columns": csvio.COLUMNS}
    if upload is None or isinstance(upload, str) or not upload.filename:
        flash(request, "Choose a CSV file to import.", "error")
        return render(request, "import.html", ctx, status_code=400)
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        flash(request, "That file is larger than 2 MB.", "error")
        return render(request, "import.html", ctx, status_code=400)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        flash(request, "The file must be UTF-8 encoded text.", "error")
        return render(request, "import.html", ctx, status_code=400)

    result = csvio.import_products(db, request.app.state.registry, text, user)
    if result.ok:
        flash(
            request,
            f"Import complete: {result.created} added, {result.updated} updated, "
            f"{result.unchanged} unchanged.",
            "success",
        )
    ctx["result"] = result
    return render(request, "import.html", ctx, status_code=200 if result.ok else 400)


@router.get("/products/{product_id:int}")
def product_detail(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    product = _get_product(db, product_id)
    movements = db.scalars(
        select(StockMovement)
        .options(joinedload(StockMovement.user))
        .where(StockMovement.product_id == product.id)
        .order_by(StockMovement.id.desc())
        .limit(20)
    ).all()
    return render(
        request,
        "product_detail.html",
        {"product": product, "movements": movements, "reasons": UI_REASONS},
    )


@router.get("/products/{product_id:int}/edit")
def edit_product_form(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    product = _get_product(db, product_id)
    return _render_form(request, db, _values_from_product(product), [], product)


@router.post("/products/{product_id:int}/edit")
def edit_product(
    request: Request,
    product_id: int,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    product = _get_product(db, product_id)
    values = {f: form.get(f, "") for f in FORM_FIELDS}
    data, errors = validate_product(db, values, creating=False, product_id=product.id)
    if errors:
        return _render_form(request, db, values, errors, product, status_code=400)
    for key, value in data.items():
        setattr(product, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_form(
            request, db, values, [f"A product with SKU '{data['sku']}' already exists."], product, status_code=400
        )
    request.app.state.registry.emit(PRODUCT_UPDATED, product_id=product.id, sku=product.sku)
    flash(request, "Product saved.", "success")
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@router.post("/products/{product_id:int}/stock")
def change_stock(
    request: Request,
    product_id: int,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    product = _get_product(db, product_id)
    target = f"/products/{product.id}"
    action = form.get("action", "")
    reason = form.get("reason", "")
    note = form.get("note", "").strip()
    try:
        if not product.is_active:
            raise StockError("This product is inactive. Reactivate it to change stock.")
        if reason not in UI_REASONS:
            raise StockError("Choose a reason.")
        amount = parse_nonneg_int(form.get("quantity", ""), "Quantity")
        if action == "add":
            change = amount
        elif action == "remove":
            change = -amount
        elif action == "set":
            change = amount - product.quantity
            if change == 0:
                flash(request, "Stock is already at that level.", "info")
                return RedirectResponse(target, status_code=303)
        else:
            raise StockError("Choose whether to add, remove or set stock.")
        adjust_stock(db, request.app.state.registry, product, change, reason, note, user)
    except (StockError, ValueError) as exc:
        flash(request, str(exc).rstrip(".") + ".", "error")
        return RedirectResponse(target, status_code=303)
    flash(request, f"Stock updated: {product.quantity} {product.unit} on hand.", "success")
    return RedirectResponse(target, status_code=303)


def _set_active(request, db, product_id: int, active: bool):
    product = _get_product(db, product_id)
    product.is_active = active
    product.updated_at = utcnow()
    db.commit()
    request.app.state.registry.emit(PRODUCT_UPDATED, product_id=product.id, sku=product.sku)
    flash(request, f"{product.name} {'reactivated' if active else 'deactivated'}.", "success")
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@router.post("/products/{product_id:int}/deactivate")
def deactivate(
    request: Request, product_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):  # fmt: skip
    return _set_active(request, db, product_id, False)


@router.post("/products/{product_id:int}/activate")
def activate(
    request: Request, product_id: int, db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):  # fmt: skip
    return _set_active(request, db, product_id, True)
