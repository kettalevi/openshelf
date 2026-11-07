# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
import re

import pytest
from fastapi.testclient import TestClient

from openshelf.config import Settings
from openshelf.main import create_app

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class Browser:
    """A cookie-keeping client that handles CSRF tokens like a real browser."""

    def __init__(self, app):
        self.client = TestClient(app, follow_redirects=False)
        self.csrf = None

    def _remember(self, response):
        match = CSRF_RE.search(response.text) if "text/html" in response.headers.get("content-type", "") else None
        if match:
            self.csrf = match.group(1)
        return response

    def get(self, path, **kw):
        return self._remember(self.client.get(path, **kw))

    def post(self, path, data=None, *, csrf=True, **kw):
        data = dict(data or {})
        if csrf:
            if self.csrf is None:
                self.get("/login")
            data["csrf_token"] = self.csrf
        return self._remember(self.client.post(path, data=data, **kw))

    def login(self, username, password):
        self.get("/login")
        response = self.post("/login", {"username": username, "password": password})
        self.get("/")  # pick up the new session's CSRF token
        return response


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret-key",
    )


@pytest.fixture
def app(settings):
    return create_app(settings, plugins=[])


@pytest.fixture
def anon(app):
    return Browser(app)


@pytest.fixture
def admin(app):
    browser = Browser(app)
    browser.get("/setup")
    response = browser.post(
        "/setup",
        {"username": "admin", "password": "correct horse", "confirm": "correct horse"},
    )
    assert response.status_code == 303
    browser.get("/")
    return browser


@pytest.fixture
def staff(app, admin):
    response = admin.post(
        "/users", {"username": "sam", "password": "staff-pass-1", "role": "staff"}
    )
    assert response.status_code == 303
    browser = Browser(app)
    assert browser.login("sam", "staff-pass-1").status_code == 303
    return browser


def add_product(browser, **fields):
    data = {"sku": "SKU-1", "name": "Widget", "price": "9.99", "cost": "4.00",
            "quantity": "10", "reorder_level": "3", "unit": "pcs"}
    data.update(fields)
    response = browser.post("/products", data)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    browser.get(location)  # follow the redirect like a browser, consuming the flash
    return int(location.rsplit("/", 1)[1])
