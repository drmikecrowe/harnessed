# Phase 1: Containerized Engine + Transparent Stack - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 1-Containerized Engine + Transparent Stack
**Areas discussed:** `.claude.json` safety, Tools-image build/first-run, Engine selection, In-container home path, `container` continuity
**Mode:** `--auto` — all gray areas auto-selected; each resolved with the recommended default (no interactive prompts).

---

## `.claude.json` safety mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Copy-on-start | Writable per-instance copy; read host state once, write only own copy | ✓ |
| `CLAUDE_CONFIG_DIR` relocation | Point Claude at a per-instance config dir | |
| Keep rw bind-mount | Current `container.sh` behavior | |

**User's choice:** Copy-on-start (auto / recommended).
**Notes:** `CLAUDE_CONFIG_DIR` scope is unverified (may relocate only `.claude/`, not the top-level `.claude.json` — Pitfall 2, #14313/#3833). Kept as a fast-follow contingent on an empirical check. Never rw-bind-mount the whole-file `.claude.json`.

---

## Tools-image build & first-run UX

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-build on first run | Bootstrap builds `harnessed-tools` automatically; `--build` forces rebuild | ✓ |
| Explicit build only | Require `harnessed --build` before first use | |

**User's choice:** Auto-build on first run (auto / recommended).
**Notes:** Matches design §15. First-run latency accepted; prebuilt/published image deferred (v2 IMG-01).

---

## Container engine selection

| Option | Description | Selected |
|--------|-------------|----------|
| podman preferred, docker fallback | Rootless podman via user socket; fall back to docker | ✓ |
| docker only | | |
| podman only | | |

**User's choice:** podman preferred, docker fallback (auto / recommended).
**Notes:** Mirrors existing `container.sh` detection. Document `systemctl --user enable --now podman.socket` + `loginctl enable-linger`.

---

## In-container home / project path

| Option | Description | Selected |
|--------|-------------|----------|
| `/home/harnessed/<relpath>` | Legible, stable Claude session slug | ✓ |
| `/container/$USER` | Keep current `container.sh` path | |

**User's choice:** `/home/harnessed/<relpath>` (auto / recommended).
**Notes:** §14 open item — verify it doesn't break harness installs during planning.

---

## `container` continuity

| Option | Description | Selected |
|--------|-------------|----------|
| Thin alias → `harnessed transparent` | Port logic; `container` delegates | ✓ |
| Remove `container` | | |
| Keep `container.sh` standalone | | |

**User's choice:** Thin alias → `harnessed transparent` (auto / recommended).
**Notes:** Zero behavior change for existing muscle memory (§14 recommendation: keep).

## Claude's Discretion

- Python package layout under `tools/harnessed/`, bootstrap runtime-detection code shape, mount-builder helper factoring (constrained by the host-absolute invariant D-08).
- `harnessed-base` lineage details beyond reusing the existing mise toolchain.

## Deferred Ideas

- Isolated stub generation + headless test → Phase 2
- hatago / recipes / profile assembly → Phase 2
- pnpm supply-chain config + scan gate → Phase 3
- Shared services + full CLI breadth → Phase 4
- varlock/1Password secrets + docs completeness → Phase 5
