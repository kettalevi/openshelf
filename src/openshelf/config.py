# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SOURCE_URL = "https://github.com/kettalevi/openshelf"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    secret_key: str
    https_only: bool = False
    currency: str = "$"
    app_name: str = "OpenShelf"
    # AGPL section 13: users interacting with the app over a network must be
    # able to get its source. If you modify OpenShelf, point this at your fork.
    source_url: str = DEFAULT_SOURCE_URL


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _persistent_secret(data_dir: Path) -> str:
    """Generate a session-signing key once and keep it in the data directory."""
    path = data_dir / "secret.key"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    with os.fdopen(fd, "w") as handle:
        handle.write(key)
    return key


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    data_dir = Path(env.get("OPENSHELF_DATA_DIR", "data")).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        database_url=env.get("OPENSHELF_DATABASE_URL")
        or f"sqlite:///{data_dir / 'openshelf.db'}",
        secret_key=env.get("OPENSHELF_SECRET_KEY") or _persistent_secret(data_dir),
        https_only=truthy(env.get("OPENSHELF_HTTPS_ONLY")),
        currency=env.get("OPENSHELF_CURRENCY", "$"),
        app_name=env.get("OPENSHELF_APP_NAME", "OpenShelf"),
        source_url=env.get("OPENSHELF_SOURCE_URL", DEFAULT_SOURCE_URL),
    )
