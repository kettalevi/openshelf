# OpenShelf

Simple, self-hosted inventory management for small stores.

OpenShelf keeps track of what is on your shelves: products, stock levels, every
stock movement, and what needs reordering. It runs on your own computer or
server, stores everything in a single SQLite file, and needs no external
services.

> **Status: alpha (0.1).** It works and is tested, but expect rough edges. See
> [Known limitations](#known-limitations).

## Features

- **Products** with SKU, barcode, category, selling and cost price, unit and reorder level
- **Stock in / out / stocktake**, each recorded with a reason, a note and who did it
- **Complete movement history**: nothing is ever overwritten
- **Low-stock and out-of-stock alerts** on the dashboard and in product lists
- **Dashboard**: stock value at cost and at retail price, items to restock, recent activity
- **Search and filter** by name, SKU, barcode, category, low stock
- **CSV import and export** (all-or-nothing import with clear row-by-row errors)
- **Users with two roles**: *staff* (day-to-day work) and *administrator* (also manages users, categories, imports)
- **Plugin system** for extending OpenShelf without modifying it ([guide](docs/plugins.md))
- Light and dark mode, works on phones, no JavaScript framework, no build step

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/kettalevi/openshelf.git
cd openshelf
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .
openshelf run
```

Open <http://127.0.0.1:8000>. On first launch you will be asked to create the
administrator account. Data is stored in `./data/` (change it with
`OPENSHELF_DATA_DIR`).

To allow other computers on your network to connect, use
`openshelf run --host 0.0.0.0`, and read [Running it for real](#running-it-for-real) first.

### Docker

```bash
docker compose up -d
```

Then open <http://127.0.0.1:8000>. Data lives in the `openshelf-data` volume.

## Configuration

All settings are environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `OPENSHELF_DATA_DIR` | `./data` | Where the database and the session secret are stored |
| `OPENSHELF_DATABASE_URL` | SQLite file in the data dir | SQLAlchemy URL (SQLite is the supported database) |
| `OPENSHELF_SECRET_KEY` | generated once, saved to `data/secret.key` | Signs login sessions |
| `OPENSHELF_HTTPS_ONLY` | `false` | Set to `true` when served over HTTPS (marks the session cookie `Secure`) |
| `OPENSHELF_CURRENCY` | `$` | Currency symbol shown next to prices |
| `OPENSHELF_APP_NAME` | `OpenShelf` | Name shown in the header and page titles |
| `OPENSHELF_SOURCE_URL` | this repository | "Source code" link in the footer (see [License](#license)) |

Command line:

```bash
openshelf run [--host HOST] [--port PORT] [--proxy-headers]
openshelf create-admin USERNAME      # create an administrator from the terminal
```

## Running it for real

- **Use HTTPS.** Passwords and session cookies travel over the network. Put OpenShelf behind a reverse proxy such as Caddy or nginx that terminates HTTPS, run it with `--proxy-headers`, and set `OPENSHELF_HTTPS_ONLY=true`.
- **Back up the data directory.** Copy `data/openshelf.db` while the app is idle, or use `sqlite3 data/openshelf.db ".backup backup.db"` while it is running. Keep `data/secret.key` with it (if you lose it, everyone just has to sign in again).
- **Do not expose it to the internet casually.** Login attempts are rate-limited, but OpenShelf has had no independent security review.

## Roles

| | Staff | Administrator |
|---|:-:|:-:|
| View products, stock, history, dashboard | ✔ | ✔ |
| Add and edit products, change stock, export CSV | ✔ | ✔ |
| Deactivate / reactivate products | | ✔ |
| Manage categories | | ✔ |
| Import CSV | | ✔ |
| Manage users | | ✔ |

## CSV format

Export your products once to get a file in exactly the right format. Columns:
`sku`, `name` (required), then `barcode`, `category`, `price`, `cost`,
`quantity`, `reorder_level`, `unit`, `description`, `active`.

Import matches rows to products by SKU, creates the new ones, and updates the
rest. Empty cells keep the current value. A changed `quantity` is recorded as a
stock movement. If any row has a problem, nothing is imported.

## Known limitations

- **No automatic database migrations yet.** Tables are created on first start. A future version that changes the schema will need a migration step, which will be documented in the release notes.
- **No JSON API, multi-location stock, purchase orders or point-of-sale integration.** OpenShelf is deliberately basic: one store, one stock count per product.
- Login throttling is kept in memory, so it is per process and resets when the server restarts.
- Times are displayed in UTC.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

OpenShelf is free software, licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).

In short: you may use, study, modify and share it. If you modify OpenShelf and
let other people use it over a network, you must offer them your modified
source code. The footer of every page links to the source for this reason: if
you run a modified version, set `OPENSHELF_SOURCE_URL` to where yours can be
found.
