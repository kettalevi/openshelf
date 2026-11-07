# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 kettalevi
"""Plugin system.

OpenShelf discovers plugins through the ``openshelf.plugins`` entry-point
group. Each entry point must resolve to a callable taking a
:class:`PluginRegistry`::

    # my_plugin/__init__.py
    def register(registry):
        registry.add_router(router)
        registry.add_menu_item("Reports", "/reports", admin_only=True)
        registry.on("stock.low", notify_owner)

    # pyproject.toml of the plugin
    [project.entry-points."openshelf.plugins"]
    my_plugin = "my_plugin:register"

See docs/plugins.md for the full guide.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from fastapi import APIRouter

from .config import truthy

log = logging.getLogger("openshelf.plugins")

ENTRY_POINT_GROUP = "openshelf.plugins"

# Hook names emitted by the core. Handlers receive keyword arguments only.
STOCK_CHANGED = "stock.changed"  # product_id, sku, change, quantity_after, reason, movement_id
STOCK_LOW = "stock.low"  # product_id, sku, name, quantity, reorder_level
PRODUCT_CREATED = "product.created"  # product_id, sku
PRODUCT_UPDATED = "product.updated"  # product_id, sku


@dataclass(frozen=True)
class MenuItem:
    label: str
    url: str
    admin_only: bool = False
    order: int = 100


class PluginRegistry:
    """Everything a plugin may contribute to the application."""

    def __init__(self) -> None:
        self.edition = "community"
        self.routers: list[tuple[APIRouter, str]] = []
        self.menu_items: list[MenuItem] = []
        self.template_dirs: list[Path] = []
        self.dashboard_widgets: list[str] = []
        self.plugin_names: list[str] = []
        self._hooks: dict[str, list[Callable[..., None]]] = defaultdict(list)

    # -- contributions -------------------------------------------------
    def set_edition(self, name: str) -> None:
        """Label shown in the footer, e.g. ``"commercial"``."""
        self.edition = name

    def add_router(self, router: APIRouter, prefix: str = "") -> None:
        self.routers.append((router, prefix))

    def add_menu_item(
        self, label: str, url: str, *, admin_only: bool = False, order: int = 100
    ) -> None:
        self.menu_items.append(MenuItem(label, url, admin_only, order))

    def add_template_dir(self, path: str | Path) -> None:
        """Templates here take precedence over the core ones with the same name."""
        self.template_dirs.append(Path(path))

    def add_dashboard_widget(self, template_name: str) -> None:
        """Include ``template_name`` on the dashboard (it gets the page context)."""
        self.dashboard_widgets.append(template_name)

    # -- hooks ---------------------------------------------------------
    def on(self, event: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """Decorator form of :meth:`subscribe`."""

        def decorator(fn: Callable[..., None]) -> Callable[..., None]:
            self.subscribe(event, fn)
            return fn

        return decorator

    def subscribe(self, event: str, fn: Callable[..., None]) -> None:
        self._hooks[event].append(fn)

    def emit(self, event: str, **payload) -> None:
        """Call every handler. A failing handler is logged, never propagated."""
        for fn in list(self._hooks.get(event, ())):
            try:
                fn(**payload)
            except Exception:
                log.exception("Plugin hook %r failed for event %r", fn, event)


def discover_plugins() -> list[Callable[[PluginRegistry], None]]:
    """Load plugin entry points. Disabled with OPENSHELF_DISABLE_PLUGINS=1."""
    if truthy(os.environ.get("OPENSHELF_DISABLE_PLUGINS")):
        return []
    return [ep.load() for ep in entry_points(group=ENTRY_POINT_GROUP)]


def run_plugin(fn: Callable[[PluginRegistry], None], registry: PluginRegistry) -> None:
    """Run one plugin's ``register``. Errors are fatal unless explicitly ignored."""
    name = f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__name__', repr(fn))}"
    try:
        fn(registry)
    except Exception:
        if truthy(os.environ.get("OPENSHELF_IGNORE_PLUGIN_ERRORS")):
            log.exception("Plugin %s failed to load; continuing without it", name)
            return
        raise
    registry.plugin_names.append(name)
