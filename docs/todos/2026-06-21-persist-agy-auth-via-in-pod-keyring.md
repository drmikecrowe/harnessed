---
created: 2026-06-21T12:26:12.113Z
title: Persist agy auth via in-pod keyring
area: general
status: pending
files:
  - base/Dockerfile.harnessed-antigravity
  - tools/harnessed/launcher.py
  - tools/harnessed/paths.py
---

> **Migration note (2026-06-24):** the bash launcher referenced below (`lib/harnessed-isolated.sh`,
> `lib/harnessed-isolated-config.sh`, `lib/harnessed-common.sh`) was replaced by the Python CLI
> (`tools/harnessed/launcher.py`, `paths.py`). The auth-mount / state-persistence logic now lives
> there; the problem/solution analysis below still applies.

## Problem

The `antigravity` (`agy`) harness authenticates only via Google OAuth, persisting tokens
into the **OS system keyring** (Secret Service / gnome-keyring). `agy` exposes no API-key
env var and no mountable credential file (its `--help` has no `login`/`auth` subcommand;
the third-party `ANTIGRAVITY_API_KEY` is unverified). In **isolated** mode the clean-room
container has no keyring daemon, so `agy` prints a login URL on **every fresh launch** and
auth never persists across recreates. Current behavior (HRN-04) only emits a warning in the
antigravity branch of the auth-mount logic (was `harnessed_isolated_auth_mounts`).

Decision (this session): build **Option 2** — give `agy` a self-contained, in-pod keyring
whose store persists to the harnessed-owned state dir. **Option 1 (mounting the host
Secret Service / D-Bus session bus) was rejected** on threat-model grounds: it would expose
the user's entire login keyring + desktop session to the sandboxed AI, violating "carries
no host defaults / secrets referenced, never baked" (design §2/§8, README threat model).
Option 2 exposes nothing from the host.

This is scoped as a feature for the next milestone (not done yet — the antigravity harness
currently ships with interactive-OAuth-per-launch documented as a known limitation).

## Solution

- Add `dbus-x11` + `gnome-keyring` (+ `libsecret-1-0`) to the harnessed-antigravity image
  (`base/Dockerfile.harnessed-antigravity`), or the base image if shared.
- On launch (harness-aware, antigravity only), start `dbus-launch` + `gnome-keyring-daemon
  --start --unlock` with an empty/fixed password in the harness member **before** the `agy`
  attach (in the Python launcher's attach path).
- Persist the keyring store dir (`~/.local/share/keyrings`) to
  `$XDG_STATE_HOME/harnessed/<project>/<stack>/` — mirror the existing `.claude`
  state-persistence/copy-on-start pattern (wipe only on first create or `--fresh`), so a
  one-time OAuth survives normal recreates.
- Still requires **one** interactive OAuth (agy prints a URL on first launch); persistence
  holds thereafter.
- Verify: launch the antigravity stack, complete OAuth once, recreate WITHOUT `--fresh`,
  confirm no re-login; `--fresh` should wipe and re-prompt.

Caveats to weigh during implementation:
- `agy` churns ~10 releases/month — its auth/keyring behavior may shift; keep the wiring
  thin and easy to rip out.
- An empty-password keyring stores the token protected by file perms only (at-rest posture
  comparable to the plaintext provider tokens claude/opencode/gemini already use) — fine
  for a harnessed-owned state dir, but document it.
- `agy -p` headless output is gated on `isatty()` (won't matter for interactive auth, but
  relevant if a non-interactive auth-check is ever added).
