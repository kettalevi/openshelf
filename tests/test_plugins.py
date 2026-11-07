# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""The plugin API is what the commercial edition builds on, so test it well."""

import pytest
from conftest import Browser, add_product
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from openshelf.db import Base
from openshelf.main import create_app
from openshelf.models import User
from openshelf.plugins import PluginRegistry, run_plugin
from openshelf.web.deps import require_admin, require_user

EVENTS = []


class PluginNote(Base):
    __tablename__ = "plugin_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(100))


def sample_plugin(registry: PluginRegistry):
    router = APIRouter()

    @router.get("/reports")
    def reports(user: User = Depends(require_admin)):
        return PlainTextResponse("secret report")

    @router.get("/hello")
    def hello(user: User = Depends(require_user)):
        return PlainTextResponse("hi " + user.username)

    registry.add_router(router)
    registry.add_menu_item("Reports", "/reports", admin_only=True, order=50)
    registry.add_dashboard_widget("plugin_widget.html")
    registry.set_edition("commercial")

    @registry.on("stock.changed")
    def record(**payload):
        EVENTS.append(payload)

    @registry.on("stock.changed")
    def broken(**payload):
        raise RuntimeError("plugin bug")


@pytest.fixture
def plugin_dir(tmp_path):
    d = tmp_path / "plugin_templates"
    d.mkdir()
    (d / "plugin_widget.html").write_text('<section id="widget">Plugin widget for {{ user.username }}</section>')
    (d / "error.html").write_text("Custom error page {{ status }}")
    return d


@pytest.fixture
def plugin_app(settings, plugin_dir):
    def plugin(registry):
        sample_plugin(registry)
        registry.add_template_dir(plugin_dir)

    EVENTS.clear()
    return create_app(settings, plugins=[plugin])


def _admin(app):
    browser = Browser(app)
    browser.get("/setup")
    browser.post("/setup", {"username": "admin", "password": "correct horse", "confirm": "correct horse"})
    browser.get("/")
    return browser


def test_plugin_contributions_appear(plugin_app):
    admin = _admin(plugin_app)
    home = admin.get("/").text
    assert 'href="/reports"' in home  # menu item
    assert "Plugin widget for admin" in home  # dashboard widget
    assert "Commercial edition" in home  # edition label
    assert admin.get("/reports").text == "secret report"
    assert plugin_app.state.registry.plugin_names


def test_plugin_routes_reuse_core_auth(plugin_app):
    anon = Browser(plugin_app)
    admin = _admin(plugin_app)
    admin.post("/users", {"username": "sam", "password": "staff-pass-1", "role": "staff"})
    assert anon.get("/hello").status_code == 303  # not signed in
    staff = Browser(plugin_app)
    staff.login("sam", "staff-pass-1")
    assert staff.get("/hello").text == "hi sam"
    assert staff.get("/reports").status_code == 403
    assert 'href="/reports"' not in staff.get("/").text  # admin-only menu item hidden


def test_plugin_templates_override_core(plugin_app):
    admin = _admin(plugin_app)
    assert "Custom error page 404" in admin.get("/products/9999").text


def test_plugin_tables_are_created(plugin_app):
    with plugin_app.state.session_factory() as db:
        db.add(PluginNote(text="hello"))
        db.commit()
        assert db.scalar(select(PluginNote.text)) == "hello"


def test_hooks_fire_and_failures_are_isolated(plugin_app):
    admin = _admin(plugin_app)
    pid = add_product(admin, quantity="5")  # 'initial' stock movement fires stock.changed
    response = admin.post(f"/products/{pid}/stock", {"action": "remove", "quantity": "2", "reason": "sale"})
    assert response.status_code == 303  # the broken hook did not break the request
    assert [e["change"] for e in EVENTS] == [5, -2]
    assert EVENTS[-1]["quantity_after"] == 3


def test_broken_plugin_fails_loudly_by_default(monkeypatch):
    def bad(registry):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_plugin(bad, PluginRegistry())
    monkeypatch.setenv("OPENSHELF_IGNORE_PLUGIN_ERRORS", "1")
    registry = PluginRegistry()
    run_plugin(bad, registry)  # logged, not raised
    assert registry.plugin_names == []


def test_no_plugins_means_community_edition(admin):
    assert "Community edition" in admin.get("/").text
