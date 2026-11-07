# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""First-run setup, login and logout."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Role, User
from ...security import DUMMY_HASH, verify_password
from ...services.users import create_user, has_users, normalize_username
from ..deps import csrf_protect, current_user, get_db, get_form
from ..render import flash, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


def safe_next(value: str | None) -> str:
    """Only allow same-site relative redirects after login."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _log_in(request: Request, user: User) -> None:
    request.session.clear()  # new session on login: prevents session fixation
    request.session["uid"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)


@router.get("/setup")
def setup_form(request: Request, db: Session = Depends(get_db)):
    if has_users(db):
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", {"values": {}, "error": None})


@router.post("/setup")
def setup(request: Request, form=Depends(get_form), db: Session = Depends(get_db)):
    if has_users(db):
        raise HTTPException(403, "Setup has already been completed.")
    values = {"username": form.get("username", "")}
    password = form.get("password", "")
    try:
        if password != form.get("confirm", ""):
            raise ValueError("The passwords do not match")
        user = create_user(db, values["username"], password, Role.ADMIN)
    except ValueError as exc:
        return render(
            request, "setup.html", {"values": values, "error": str(exc)}, status_code=400
        )
    _log_in(request, user)
    flash(request, "Welcome to OpenShelf! Start by adding your first product.", "success")
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_form(
    request: Request,
    next: str = "/",
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if not has_users(db):
        return RedirectResponse("/setup", status_code=303)
    if user is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "login.html", {"next": safe_next(next), "error": None, "username": ""})


@router.post("/login")
def login(request: Request, form=Depends(get_form), db: Session = Depends(get_db)):
    username = normalize_username(form.get("username", ""))
    password = form.get("password", "")
    next_url = safe_next(form.get("next"))
    throttle = request.app.state.throttle
    client = request.client.host if request.client else "-"
    key = f"{client}|{username}"

    def fail(message: str, status: int):
        return render(
            request,
            "login.html",
            {"next": next_url, "error": message, "username": username},
            status_code=status,
        )

    if throttle.blocked(key):
        return fail("Too many failed attempts. Please wait a few minutes.", 429)

    user = db.scalar(select(User).where(User.username == username))
    # Always run a password check so timing does not reveal valid usernames.
    valid = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not (user and user.is_active and valid):
        throttle.fail(key)
        return fail("Incorrect username or password.", 400)

    throttle.reset(key)
    _log_in(request, user)
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
