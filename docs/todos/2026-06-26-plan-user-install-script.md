---
created: 2026-06-26T00:00:00.000Z
title: Plan a one-shot user install script
area: general
status: pending
files:
  - README.md
  - src/harnessed/paths.py
---

## Problem

Today installation is manual and multi-step: users must already have podman + uv (or
pipx), then run `uv tool install ./harnessed` (`README.md`). There is no single entry point
a new user can run to go from nothing to a working `harnessed` CLI. (Note: the existing
`harnessed install <stack>` command is unrelated — it writes a per-stack launcher shim, not
a bootstrap installer.)

We want a one-shot install script users can run (e.g. `curl … | sh`-style or a checked-in
`install.sh`) that bootstraps the toolchain and installs the CLI.

## Solution (to plan)

Open questions to resolve before building:
- **Delivery**: hosted `curl … | sh` vs. a checked-in `install.sh` users clone-and-run.
  Weigh the supply-chain posture against the project's own "pin every download" stance —
  the installer shouldn't violate the constraints it ships.
- **Prerequisites**: detect/verify podman; install uv (pinned) if absent; then
  `uv tool install harnessed`. Decide whether to install podman or only check + instruct.
- **Source**: install from PyPI (once published) vs. from the repo. Pin the version.
- **Platforms**: Linux first; document macOS (apple-container support is pending per
  `README.md`).
- **Idempotence + uninstall**: re-runnable, and a clean `uv tool uninstall harnessed` path.
- **Verify**: on a clean machine/container, run the script and confirm `harnessed --help`
  works and a sample stack builds/launches.

Coordinate the README + `web/` install sections with whatever lands here (see
[2026-06-26-overhaul-web-folder-to-match-new-docs]).
