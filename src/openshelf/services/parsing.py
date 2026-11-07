# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Parsing and formatting of user-entered numbers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_CENTS = 10**11  # 1 billion in major units; a sanity bound, not a business rule
MAX_INT = 10**9


def parse_money(text: str) -> int:
    """Parse ``"12.5"`` / ``"1,234.50"`` into integer cents. Raises ValueError."""
    cleaned = (text or "").strip().replace(",", "")
    if not cleaned:
        return 0
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{text}' is not a valid amount") from None
    if not value.is_finite():
        raise ValueError(f"'{text}' is not a valid amount")
    if value < 0:
        raise ValueError("Amounts cannot be negative")
    # Bound the size first: quantize() raises on huge values such as "1e30".
    if value > Decimal(MAX_CENTS) / 100:
        raise ValueError("Amount is too large")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_money(cents: int | None) -> str:
    cents = cents or 0
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def money_input(cents: int | None) -> str:
    """Plain ``12.50`` form, for pre-filling form fields."""
    cents = cents or 0
    return f"{cents // 100}.{cents % 100:02d}"


def parse_nonneg_int(text: str, label: str = "Value") -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    try:
        value = int(cleaned)
    except ValueError:
        raise ValueError(f"{label} must be a whole number") from None
    if value < 0:
        raise ValueError(f"{label} cannot be negative")
    if value > MAX_INT:
        raise ValueError(f"{label} is too large")
    return value


def to_int(text: str | None, default: int | None = None) -> int | None:
    try:
        return int((text or "").strip())
    except ValueError:
        return default
