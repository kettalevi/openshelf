# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Template rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..models import User
from .deps import csrf_token

# (label, url, admin_only, order)
CORE_MENU = [
    ("Dashboard", "/", False, 10),
    ("Products", "/products", False, 20),
    ("Movements", "/movements", False, 30),
    ("Categories", "/categories", False, 40),
    ("Users", "/users", True, 90),
]


def flash(request: Request, message: str, level: str = "info") -> None:
    # Reassign instead of appending in place: the session middleware only
    # persists top-level changes, so mutating a nested list could be lost.
    pending = request.session.get("_flash", [])
    request.session["_flash"] = [*pending, {"message": message, "level": level}]


def _menu(request: Request, user: User | None) -> list[tuple[str, str]]:
    if user is None:
        return []
    items = list(CORE_MENU)
    items += [
        (m.label, m.url, m.admin_only, m.order)
        for m in request.app.state.registry.menu_items
    ]
    items.sort(key=lambda item: item[3])
    return [(label, url) for label, url, admin_only, _ in items if user.is_admin or not admin_only]


def render(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
):
    state = request.app.state
    user = getattr(request.state, "user", None)

    def page_url(page: int) -> str:
        params = dict(request.query_params)
        params["page"] = str(page)
        return f"{request.url.path}?{urlencode(params)}"

    full = {
        "user": user,
        "csrf_token": csrf_token(request),
        "flashes": request.session.pop("_flash", []),
        "menu": _menu(request, user),
        "edition": state.registry.edition,
        "widgets": state.registry.dashboard_widgets,
        "page_url": page_url,
        **(context or {}),
    }
    return state.templates.TemplateResponse(request, template, full, status_code=status_code)


@dataclass
class Page:
    items: list
    page: int
    pages: int
    total: int

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def paginate(db: Session, stmt: Select, page: int, per_page: int = 25) -> Page:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    pages = max(1, ceil(total / per_page))
    page = min(max(page, 1), pages)
    items = db.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    return Page(list(items), page, pages, total)
