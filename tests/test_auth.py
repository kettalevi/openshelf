# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
from openshelf.security import hash_password, verify_password
from openshelf.web.routes.auth import safe_next


def test_fresh_install_redirects_to_setup(anon):
    for path in ("/", "/products", "/login"):
        response = anon.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/setup"


def test_setup_creates_admin_once(anon):
    anon.get("/setup")
    response = anon.post(
        "/setup", {"username": "Boss", "password": "longenough1", "confirm": "longenough1"}
    )
    assert response.status_code == 303
    assert anon.get("/").status_code == 200  # logged in immediately

    anon.get("/")
    again = anon.post(
        "/setup", {"username": "x2", "password": "longenough1", "confirm": "longenough1"}
    )
    assert again.status_code == 403
    assert anon.get("/setup").headers["location"] == "/login"


def test_setup_validates_input(anon):
    anon.get("/setup")
    mismatch = anon.post("/setup", {"username": "boss", "password": "longenough1", "confirm": "nope"})
    assert mismatch.status_code == 400 and "do not match" in mismatch.text
    short = anon.post("/setup", {"username": "boss", "password": "short", "confirm": "short"})
    assert short.status_code == 400 and "at least 8" in short.text


def test_login_and_logout(admin, app):
    from conftest import Browser

    other = Browser(app)
    assert other.get("/products").headers["location"].startswith("/login?next=")
    bad = other.login("admin", "wrong password")
    assert bad.status_code == 400 and "Incorrect" in bad.text
    assert other.login("ADMIN", "correct horse").status_code == 303  # case-insensitive
    assert other.get("/products").status_code == 200
    other.post("/logout")
    assert other.get("/products").status_code == 303


def test_login_is_throttled(admin, app):
    from conftest import Browser

    attacker = Browser(app)
    attacker.get("/login")
    for _ in range(5):
        assert attacker.post("/login", {"username": "admin", "password": "bad"}).status_code == 400
    blocked = attacker.post("/login", {"username": "admin", "password": "correct horse"})
    assert blocked.status_code == 429


def test_post_requires_csrf_token(admin):
    response = admin.post("/logout", csrf=False)
    assert response.status_code == 403
    assert admin.get("/").status_code == 200  # still signed in
    forged = admin.post("/logout", {"csrf_token": "forged"}, csrf=False)
    assert forged.status_code == 403


def test_safe_next_blocks_open_redirects():
    assert safe_next("/products?page=2") == "/products?page=2"
    for bad in ("//evil.example", "https://evil.example", "\\evil", "", None):
        assert safe_next(bad) == "/"


def test_staff_cannot_use_admin_pages(staff):
    assert staff.get("/users").status_code == 403
    assert staff.get("/products/import").status_code == 403
    assert staff.post("/categories", {"name": "Food"}).status_code == 403
    # but they can use the everyday pages
    assert staff.get("/products").status_code == 200
    assert staff.get("/categories").status_code == 200


def test_deactivated_user_is_locked_out(admin, staff, app):
    from conftest import Browser

    users_page = admin.get("/users").text
    assert "sam" in users_page
    sam_id = _user_id(app, "sam")
    admin.post(f"/users/{sam_id}/active", {"active": "0"})
    assert staff.get("/products").status_code == 303
    assert Browser(app).login("sam", "staff-pass-1").status_code == 400


def test_cannot_remove_last_admin(admin, app):
    admin_id = _user_id(app, "admin")
    admin.post(f"/users/{admin_id}/active", {"active": "0"})
    assert admin.get("/products").status_code == 200  # still active
    admin.post(f"/users/{admin_id}/role", {"role": "staff"})
    assert admin.get("/users").status_code == 200  # still admin


def test_change_own_password(admin, app):
    from conftest import Browser

    admin.get("/account")
    wrong = admin.post(
        "/account",
        {"current_password": "nope", "new_password": "brand new pw", "confirm": "brand new pw"},
    )
    assert wrong.status_code == 400
    ok = admin.post(
        "/account",
        {"current_password": "correct horse", "new_password": "brand new pw", "confirm": "brand new pw"},
    )
    assert ok.status_code == 303
    assert Browser(app).login("admin", "brand new pw").status_code == 303


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-password")
    assert stored.startswith("scrypt$") and "s3cret" not in stored
    assert verify_password("s3cret-password", stored)
    assert not verify_password("other", stored)
    assert not verify_password("x", "garbage")
    assert hash_password("same") != hash_password("same")  # salted


def _user_id(app, username):
    from sqlalchemy import select

    from openshelf.models import User

    with app.state.session_factory() as db:
        return db.scalar(select(User.id).where(User.username == username))
