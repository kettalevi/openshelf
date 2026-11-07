# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""User creation and validation."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Role, User
from ..security import hash_password

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("Password is too long")


def create_user(db: Session, username: str, password: str, role: str = Role.STAFF) -> User:
    username = normalize_username(username)
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 3-64 characters: letters, digits, '.', '_' or '-'"
        )
    if role not in Role.ALL:
        raise ValueError("Unknown role")
    validate_password(password)
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError(f"The username '{username}' is already taken") from None
    return user


def has_users(db: Session) -> bool:
    return db.scalar(select(func.count(User.id))) > 0


def active_admin_count(db: Session) -> int:
    return db.scalar(
        select(func.count(User.id)).where(
            User.role == Role.ADMIN, User.is_active.is_(True)
        )
    )
