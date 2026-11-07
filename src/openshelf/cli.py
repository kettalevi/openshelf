# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Command line interface: ``openshelf run`` and ``openshelf create-admin``."""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__


def _run(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "openshelf.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips="*" if args.proxy_headers else None,
    )
    return 0


def _create_admin(args: argparse.Namespace) -> int:
    from .config import load_settings
    from .db import Base, make_engine, make_session_factory
    from .models import Role
    from .services.users import create_user

    settings = load_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    password = args.password
    if password is None:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
    with make_session_factory(engine)() as db:
        try:
            user = create_user(db, args.username, password, Role.ADMIN)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    print(f"Created administrator '{user.username}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openshelf", description="Simple inventory management for small stores."
    )
    parser.add_argument("--version", action="version", version=f"openshelf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start the web server")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    run.add_argument(
        "--proxy-headers",
        action="store_true",
        help="trust X-Forwarded-* headers (use only behind a reverse proxy)",
    )
    run.set_defaults(func=_run)

    admin = sub.add_parser("create-admin", help="create an administrator account")
    admin.add_argument("username")
    admin.add_argument("--password", help="omit to be prompted securely")
    admin.set_defaults(func=_create_admin)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
