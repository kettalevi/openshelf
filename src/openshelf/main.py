# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Application factory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import Settings, load_settings
from .db import Base, make_engine, make_session_factory
from .plugins import PluginRegistry, discover_plugins, run_plugin
from .security import LoginThrottle
from .services.parsing import format_money
from .services.users import has_users
from .web.deps import NotAuthenticated
from .web.render import render
from .web.routes import auth, categories, dashboard, movements, products, users

PACKAGE_DIR = Path(__file__).parent

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # No inline scripts or styles: everything is served from this origin.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}


def create_app(
    settings: Settings | None = None,
    plugins: list[Callable[[PluginRegistry], None]] | None = None,
) -> FastAPI:
    """Build the application.

    ``plugins`` overrides entry-point discovery (used by tests).
    """
    settings = settings or load_settings()
    registry = PluginRegistry()
    for plugin in plugins if plugins is not None else discover_plugins():
        run_plugin(plugin, registry)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)  # after plugins, so their tables are included

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.throttle = LoginThrottle()

    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.loader = ChoiceLoader(
        [FileSystemLoader(str(d)) for d in registry.template_dirs]
        + [FileSystemLoader(str(PACKAGE_DIR / "templates"))]
    )
    templates.env.filters["money"] = format_money
    templates.env.filters["utc"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M") if dt else ""
    templates.env.globals.update(
        app_name=settings.app_name,
        currency=settings.currency,
        source_url=settings.source_url,
        version=__version__,
    )
    app.state.templates = templates

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="openshelf_session",
        max_age=14 * 24 * 3600,
        same_site="lax",
        https_only=settings.https_only,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(NotAuthenticated)
    async def not_authenticated(request: Request, exc: NotAuthenticated):
        with request.app.state.session_factory() as db:
            if not has_users(db):
                return RedirectResponse("/setup", status_code=303)
        target = "/login"
        if exc.next_url:
            target += "?" + urlencode({"next": exc.next_url})
        return RedirectResponse(target, status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        return render(
            request,
            "error.html",
            {"status": exc.status_code, "message": exc.detail},
            status_code=exc.status_code,
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "version": __version__}

    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    for module in (auth, dashboard, products, categories, movements, users):
        app.include_router(module.router)
    for router, prefix in registry.routers:
        app.include_router(router, prefix=prefix)
    return app
