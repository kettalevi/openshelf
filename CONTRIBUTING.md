# Contributing to OpenShelf

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Reporting bugs

Open an issue and include: what you did, what you expected, what happened, and
your OpenShelf version (`openshelf --version`) and Python version. Please do
not attach real customer data, and never post your `secret.key`.

**Security problems:** please do not open a public issue. Use GitHub's
private vulnerability reporting (the repository's **Security** tab, then
**Report a vulnerability**).

## Development setup

```bash
git clone https://github.com/kettalevi/openshelf.git
cd openshelf
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

Run the app against a throwaway data directory while you work:

```bash
OPENSHELF_DATA_DIR=/tmp/openshelf-dev openshelf run
```

## Pull requests

- Keep each pull request focused on one change.
- Add or update tests; `python -m pytest` must pass.
- OpenShelf is intentionally a **basic, single-store** inventory app. Large
  features such as multi-warehouse stock, purchase orders or integrations are
  out of scope for this repository; the [plugin system](docs/plugins.md) is
  the place for those.
- New Python and CSS/JS files start with the two-line license header used by
  the existing files (`SPDX-License-Identifier: AGPL-3.0-or-later`).
- No inline `<script>` or `style=""` in templates: the Content-Security-Policy
  forbids them. Put scripts and styles in `static/`.

## License of contributions

By submitting a contribution you agree that it is licensed under the same
license as the project, AGPL-3.0-or-later.
