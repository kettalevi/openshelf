# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""User administration and the signed-in user's own account page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Role, User
from ...security import hash_password, verify_password
from ...services.users import active_admin_count, create_user, validate_password
from ..deps import csrf_protect, get_db, get_form, require_admin, require_user
from ..render import flash, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


def _get_user(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found.")
    return target


@router.get("/users")
def list_users(
    request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    users = db.scalars(select(User).order_by(User.username)).all()
    return render(request, "users.html", {"users": users, "roles": Role.ALL, "values": {}})


@router.post("/users")
def add_user(
    request: Request,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        created = create_user(
            db, form.get("username", ""), form.get("password", ""), form.get("role", Role.STAFF)
        )
        flash(request, f"Created user '{created.username}'.", "success")
    except ValueError as exc:
        flash(request, str(exc) + ".", "error")
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id:int}/active")
def set_active(
    request: Request,
    user_id: int,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = _get_user(db, user_id)
    active = form.get("active") == "1"
    if not active:
        if target.id == user.id:
            flash(request, "You cannot deactivate your own account.", "error")
            return RedirectResponse("/users", status_code=303)
        if target.is_admin and target.is_active and active_admin_count(db) <= 1:
            flash(request, "There must be at least one active administrator.", "error")
            return RedirectResponse("/users", status_code=303)
    target.is_active = active
    db.commit()
    flash(request, f"{target.username} {'activated' if active else 'deactivated'}.", "success")
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id:int}/role")
def set_role(
    request: Request,
    user_id: int,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = _get_user(db, user_id)
    role = form.get("role", "")
    if role not in Role.ALL:
        raise HTTPException(400, "Unknown role.")
    if (
        role != Role.ADMIN
        and target.is_admin
        and target.is_active
        and active_admin_count(db) <= 1
    ):
        flash(request, "There must be at least one active administrator.", "error")
        return RedirectResponse("/users", status_code=303)
    target.role = role
    db.commit()
    flash(request, f"{target.username} is now {role}.", "success")
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id:int}/password")
def reset_password(
    request: Request,
    user_id: int,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = _get_user(db, user_id)
    try:
        password = form.get("password", "")
        validate_password(password)
    except ValueError as exc:
        flash(request, str(exc) + ".", "error")
        return RedirectResponse("/users", status_code=303)
    target.password_hash = hash_password(password)
    db.commit()
    flash(request, f"Password changed for {target.username}.", "success")
    return RedirectResponse("/users", status_code=303)


@router.get("/account")
def account_form(request: Request, user: User = Depends(require_user)):
    return render(request, "account.html", {"error": None})


@router.post("/account")
def change_own_password(
    request: Request,
    form=Depends(get_form),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    new = form.get("new_password", "")
    try:
        if not verify_password(form.get("current_password", ""), user.password_hash):
            raise ValueError("Your current password is incorrect")
        if new != form.get("confirm", ""):
            raise ValueError("The new passwords do not match")
        validate_password(new)
    except ValueError as exc:
        return render(request, "account.html", {"error": str(exc)}, status_code=400)
    user.password_hash = hash_password(new)
    db.commit()
    flash(request, "Password changed.", "success")
    return RedirectResponse("/account", status_code=303)
