# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
import threading

import pytest
from sqlalchemy import func, select

from openshelf.models import Product, StockMovement
from openshelf.plugins import PluginRegistry
from openshelf.services.stock import StockError, adjust_stock


def _make_product(app, quantity=10, reorder=3):
    with app.state.session_factory() as db:
        product = Product(sku="S", name="Thing", quantity=quantity, reorder_level=reorder)
        db.add(product)
        db.commit()
        return product.id


def test_concurrent_removals_never_oversell(app):
    pid = _make_product(app, quantity=10)
    outcomes = []

    def worker():
        with app.state.session_factory() as db:
            product = db.get(Product, pid)
            try:
                adjust_stock(db, None, product, -1, "sale")
                outcomes.append("ok")
            except StockError:
                outcomes.append("refused")

    threads = [threading.Thread(target=worker) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 10 and outcomes.count("refused") == 15
    with app.state.session_factory() as db:
        assert db.get(Product, pid).quantity == 0
        assert db.scalar(select(func.count(StockMovement.id))) == 10


def test_events_emitted_after_commit(app):
    pid = _make_product(app, quantity=5, reorder=3)
    registry = PluginRegistry()
    seen = []
    registry.subscribe("stock.changed", lambda **kw: seen.append(("changed", kw["quantity_after"])))
    registry.subscribe("stock.low", lambda **kw: seen.append(("low", kw["quantity"])))
    with app.state.session_factory() as db:
        product = db.get(Product, pid)
        adjust_stock(db, registry, product, -1, "sale")  # 4: still above reorder
        adjust_stock(db, registry, product, -1, "sale")  # 3: crosses the threshold
        adjust_stock(db, registry, product, -1, "sale")  # 2: already low, no new alert
    assert seen == [("changed", 4), ("changed", 3), ("low", 3), ("changed", 2)]


def test_rejects_zero_and_unknown_reason(app):
    pid = _make_product(app)
    with app.state.session_factory() as db:
        product = db.get(Product, pid)
        with pytest.raises(StockError):
            adjust_stock(db, None, product, 0, "sale")
        with pytest.raises(StockError):
            adjust_stock(db, None, product, 1, "made-up")
