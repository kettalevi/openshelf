# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Request dependencies: database session, authentication, CSRF protection.

Plugins can reuse ``get_db``, ``require_user``, ``require_admin`` and
``csrf_protect`` in their own routers.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from ..models import Role, User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class NotAuthenticated(Exception):
    def __init__(self, next_url: str | None = None):
        self.next_url = next_url


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("uid")
    user = db.get(User, user_id) if user_id else None
    if user is not None and not user.is_active:
        user = None
    request.state.user = user
    return user


def require_user(request: Request, user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise NotAuthenticated(
            request.url.path if request.method in SAFE_METHODS else None
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(403, "Administrator access is required for this action.")
    return user


# -- CSRF -----------------------------------------------------------------


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


async def csrf_protect(request: Request) -> None:
    """Reject state-changing requests without the session's CSRF token.

    The token is accepted from the ``csrf_token`` form field or the
    ``X-CSRF-Token`` header.
    """
    if request.method in SAFE_METHODS:
        return
    sent = request.headers.get("x-csrf-token")
    if not sent:
        form = await request.form()
        sent = form.get("csrf_token")
    expected = request.session.get("csrf")
    if (
        not expected
        or not isinstance(sent, str)
        or not hmac.compare_digest(sent.encode(), expected.encode())
    ):
        raise HTTPException(
            403, "Your session expired or the form was invalid. Reload and try again."
        )


async def get_form(request: Request) -> FormData:
    return await request.form()
