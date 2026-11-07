# Writing OpenShelf plugins

A plugin is an ordinary Python package that OpenShelf discovers when it starts.
It can add pages, menu entries, dashboard widgets, database tables and react to
events, without any change to OpenShelf itself.

## 1. Register with an entry point

In your plugin's `pyproject.toml`:

```toml
[project]
name = "my-openshelf-plugin"
version = "0.1.0"
dependencies = ["openshelf"]

[project.entry-points."openshelf.plugins"]
my_plugin = "my_plugin:register"
```

Install it into the same environment as OpenShelf (`pip install .`). On the
next start OpenShelf calls `my_plugin.register(registry)`.

If a plugin raises while registering, OpenShelf **refuses to start** so a broken
install is noticed. Set `OPENSHELF_IGNORE_PLUGIN_ERRORS=1` to log the error and
continue without that plugin. Set `OPENSHELF_DISABLE_PLUGINS=1` to load none.

## 2. What `register(registry)` can do

```python
# my_plugin/__init__.py
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from openshelf.web.deps import get_db, require_admin
from openshelf.web.render import render

router = APIRouter()

@router.get("/reports")
def reports(request: Request, db=Depends(get_db), user=Depends(require_admin)):
    return render(request, "reports.html", {"rows": []})

def register(registry):
    registry.add_router(router)                                   # new routes
    registry.add_menu_item("Reports", "/reports", admin_only=True, order=50)
    registry.add_template_dir(Path(__file__).parent / "templates")
    registry.add_dashboard_widget("reports_widget.html")
    registry.set_edition("my edition")                            # footer label

    @registry.on("stock.low")
    def alert(product_id, sku, name, quantity, reorder_level):
        ...  # e.g. send an email
```

| Method | Purpose |
|---|---|
| `add_router(router, prefix="")` | Add a FastAPI `APIRouter`. |
| `add_menu_item(label, url, *, admin_only=False, order=100)` | Add a navigation link. Core items use orders 10 to 40 and 90. |
| `add_template_dir(path)` | Jinja templates here **override** core templates with the same name, and can be rendered with `render(...)`. |
| `add_dashboard_widget(template_name)` | Include a template at the bottom of the dashboard. |
| `set_edition(name)` | Text for the footer ("… edition"). |
| `on(event)` / `subscribe(event, fn)` | React to an event. |

## 3. Reusing core building blocks

Import these in your routes so your pages behave like the rest of the app:

| Import | Use |
|---|---|
| `openshelf.web.deps.get_db` | Database session for the request. |
| `openshelf.web.deps.require_user` / `require_admin` | Require sign-in / administrator. Returns the `User`. |
| `openshelf.web.deps.csrf_protect` | Add `dependencies=[Depends(csrf_protect)]` to a router that handles `POST`. Forms must include `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`. |
| `openshelf.web.render.render(request, template, context)` | Render with the standard layout, menu, flash messages and CSRF token. |
| `openshelf.web.render.flash(request, message, level)` | Queue a message for the next page (`info`, `success`, `error`). |
| `openshelf.services.stock.adjust_stock(...)` | Change stock the right way (atomic, recorded, fires events). Never write `Product.quantity` directly. |

Extend the layout in your templates with `{% extends "base.html" %}`.

Errors from routes under `/api/` are returned as JSON instead of an HTML page,
so a plugin that offers an API should mount it under `/api/`.

The core sets a strict Content-Security-Policy (no inline scripts or styles).
Serve your own scripts and styles as files.

## 4. Events

Handlers receive keyword arguments only. They run **after** the change has been
committed, and an exception in a handler is logged and never breaks the user's
request.

| Event | Arguments |
|---|---|
| `stock.changed` | `product_id, sku, change, quantity_after, reason, movement_id` |
| `stock.low` | `product_id, sku, name, quantity, reorder_level`. Fired when stock *crosses down to* the reorder level, not on every change below it. |
| `product.created` | `product_id, sku` |
| `product.updated` | `product_id, sku` (also fired on activate / deactivate) |

## 5. Database tables

Subclass `openshelf.db.Base`. Tables from every loaded plugin are created at
startup, after all plugins have been registered, so import your models in
`register` (or at module import time):

```python
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from openshelf.db import Base

class SupplierNote(Base):
    __tablename__ = "myplugin_supplier_notes"      # prefix your table names
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    text: Mapped[str] = mapped_column(String(500))
```

Startup only creates **missing tables**; it does not alter existing ones.
Migrations for changes to your own tables are your plugin's responsibility.

## 6. Testing a plugin

Pass your `register` function straight to the app factory instead of relying on
installed entry points:

```python
from openshelf.main import create_app
app = create_app(settings, plugins=[register])
```

See `tests/test_plugins.py` in this repository for a complete example.

## Stability

The plugin API is **0.x and may still change** between minor versions. The
names documented on this page are the supported surface; anything else in
`openshelf` may change without notice.
