# beads-stealth-server recipe — implementation plan

Goal: make `bd` (beads) available in the **stealth-server** cell of the beads 2×2 — STEALTH
placement (`.beads/` outside the repo, host-persisted, zero git footprint) on the SHARED
`beads-server` `dolt sql-server` for storage.

This is the server-backed sibling of [`beads-stealth`](../beads-stealth/PLAN.md) and the
stealth-placement sibling of [`beads-team-server`](../beads-team-server/PLAN.md). It reuses the
`beads-server` service unchanged. All four beads variants are mutually exclusive
(`conflicts:` in each recipe.yaml).

Upstream: <https://github.com/gastownhall/beads> · release binary · MIT license.

## Why this cell

`beads-stealth` uses bd's embedded Dolt engine, which takes an EXCLUSIVE on-disk file lock on its
host-persisted `.beads/dolt`. A host `bd` and a container `bd` therefore can't both hold a live
engine against it — the same lock-collision (2026-07-05 incident) the `beads-server` service was
built to fix for the in-repo variants. Pointing stealth `bd` at the shared external server removes
that contention while keeping the invisible, zero-git-footprint placement.

## Shape

- Dockerfile bakes `bd` (1.1.0) + `dolt` (2.1.10), pinned + attestation-verified via mise `github:`
  — the same proven toolchain as `beads-team-server`.
- `persist:` — `.beads/` `scope: project`, `location: host` (identical to `beads-stealth`).
  `BEADS_DIR` is a static image ENV at the fixed mount path; no `bd-resolve-beads-dir` helper (that
  only matters for the in-repo variants).
- **No auto-init.** A `hooks: SessionStart` notice (self-gated on `bd list`) tells the user to run,
  once, then restart: `bd init --stealth --server --external --server-host host.containers.internal
  --server-port 3307 --quiet --non-interactive --role maintainer && bd config set dolt.auto-commit on`,
  then `bd setup claude --project --stealth`. Baked as `BEADS_INIT_HINT` + `/etc/beads-setup-hint`
  (the setup line branches on `${HARNESS}`). Rationale: `bd setup` writes `.claude/settings.json` +
  `CLAUDE.md` into the project and can't be made reliably idempotent/footprint-free, so it's a
  deliberate user action, not an every-attach auto-run.
- Stack `claude_beads-stealth-server` attaches the `beads-server` sidecar via its `services:` list.

## What lives where

`.beads/` (host-persisted, outside repo) holds only config + `metadata.json` (the server pointer) +
the passive `issues.jsonl` export. The live issue graph — including dependency edges, which are NOT
in `issues.jsonl` — lives in the shared server's named volume (`beads-server-data`).

## Risks / checks

- **CLI-only surface**: no skill/command/mcp/plugin, so the assembler capability oracle is
  structurally empty — this stack is in `NO_CAPABILITY_ORACLE` (tests/test_recipes_integration.py),
  verified via the live podman layer, not the fast sweep.
- **Flag composition verified**: `bd init --stealth --server --external …` parses and reaches the
  server-connect stage on bd 1.1.0 (checked on host). The remaining live check is an end-to-end
  `harnessed build && harnessed test` against a running `beads-server` (HARNESSED_PODMAN=1): confirm
  a fresh project's database is minted on the shared server and `bd create`/`bd dep add`/`bd list`
  round-trip.
- **Migration out of scope (MVP)**: minting a fresh server database only; importing an existing
  embedded `.beads/dolt` history into the shared server is a deferred follow-up. Never runs
  `bd init --reinit-local`.
