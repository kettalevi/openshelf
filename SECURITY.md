# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately with GitHub's vulnerability reporting: open the
repository's **Security** tab, choose **Report a vulnerability**, and describe
the problem. Only the maintainer can see the report.

Helpful details:

- what you found and why it matters (what an attacker could do),
- steps to reproduce, or a proof of concept,
- the OpenShelf version (`openshelf --version`) and how it is deployed.

Please use test data only, and do not access other people's data.

## What to expect

I aim to acknowledge reports within a week, keep you updated while I work on a
fix, and credit you in the release notes if you wish. Please give me a
reasonable time to release a fix before you publish details.

## Supported versions

OpenShelf is in alpha. Security fixes are made for the latest release only.

| Version | Supported |
|---|:-:|
| latest 0.x release | ✔ |
| older releases | ✘ |

## Hardening your installation

See "Running it for real" in the [README](README.md): serve OpenShelf over
HTTPS, set `OPENSHELF_HTTPS_ONLY=true`, and back up the data directory.
