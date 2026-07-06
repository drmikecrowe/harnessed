# beads-shared recipe — implementation plan

Goal: run `bd` (beads) against a **single shared `dolt sql-server`** — the `beads-server` service
(bead **main-8by**) — instead of each container/host embedding its own Dolt engine. This removes the
exclusive-file-lock contention behind the 2026-07-05 lock-collision incident: one long-lived server
that everyone connects to, so a host `bd` and every container's `bd` never fight over the same
`.beads/dolt` directory.

Sibling of [`beads`](../beads/PLAN.md) (embedded / per-container Dolt engine). Same `bd` binary, same
in-repo git-tracked `.beads/`; the only difference is **storage wiring** — external shared server vs
embedded. `conflicts: [beads, beads-stealth, agent-carnet]` prevents combining variants in one stack.

Upstream: <https://github.com/gastownhall/beads> (bd 1.1.0) · <https://github.com/dolthub/dolt> (dolt
2.1.10) — the same pinned toolchain the `beads` recipe verifies.

## Shape

- **Service** (`catalog/services/beads-server/`): single-container standalone `dolt sql-server` on
  the existing single-container `ServiceDef` (mirrors `ping`). One image, one port (3307, loopback),
  one **named** volume (`beads-server-data`, mounted at `/data`). Loopback-only, no auth.
- **Recipe** (this dir): bakes `bd` + `dolt` + the `bd-resolve-beads-dir` / `bd-setup-agent` helpers;
  `init.run` points `bd` at the shared server. No MCP, no skill, no `service:` ref.
- **Stack** (`catalog/stacks/claude_beads-shared/`): `recipes: [beads-shared]` +
  `services: [beads-server]`.

## How `bd` connects to the external server (the crux — a first-class bd feature)

`bd init --server --external --server-host host.containers.internal --server-port 3307`:

| flag | effect |
|------|--------|
| `--server` | use an external `dolt sql-server` instead of bd's embedded engine |
| `--external` | server is **externally managed** — bd connects but never starts/stops it |
| `--server-host` / `--server-port` | connection target; persisted to `.beads/metadata.json` |

Evidence this is real (bd 1.1.0 `bd init --help`): *"Pass `--server` to use an external dolt
sql-server instead. In server mode, set connection details with `--server-host`, `--server-port`,
and `--server-user`."* and `--external`: *"Server is externally managed (skip server startup); use
with `--shared-server` or `--server`."* Password (unused here — loopback/no-auth) would be
`BEADS_DOLT_PASSWORD`. `bd dolt set host|port|database [--update-config]` is the equivalent
post-init reconfiguration path.

**Multi-database-per-server:** `bd init` (no `--database`) derives the database name from the
project's issue prefix and creates it on the shared server, so each project gets its own Dolt
database on the one server — the design's "multi-database-per-server" isolation, no per-tenant auth.

## Service auto-start trigger (design open-question #1 — resolved)

A `dolt sql-server` speaks the MySQL wire protocol, not MCP, so it can NOT be an MCP `service:` ref
(those become hatago `/mcp` URL proxies). It is attached at the **stack** level via `services:`.
`launcher._service_refs` was extended to union the stack's own `services:` list with recipe MCP
`service:` refs, so `_ensure_services` starts `beads-server` host-published on launch (idempotent,
outlives the instance). This also activates the same field the (not-yet-shipped) `claude_agentmemory`
stack already depends on.

## MVP scope

**FRESH server (empty DB).** A new project's database is minted on the shared server on first
`bd init`. Verified via: `harnessed svc up beads-server` (or auto-start on `harnessed launch
claude_beads-shared`), then `bd list` / create an issue and confirm it round-trips.

## Deferred follow-ups

1. **One-time migration of an existing repo's Dolt history** (design open-question #2, the riskiest
   step): importing this repo's existing `.beads/dolt/main/.dolt` (issues, dependency edges, `bd
   remember` memories) into the shared server's named volume as this project's database — via `dolt
   remote` push/pull between the old dir and the served DB, or a volume copy. **Not** `bd init
   --reinit-local` (discards history). Must be proven before cutting an existing repo over. This
   recipe **never** runs `--reinit-local`.
2. **sha256 pin for the dolt asset in the service image.** The service Dockerfile installs dolt via
   mise's `github:` backend (attestation-verified, pinned to 2.1.10) — stronger than a hand-rolled
   checksum. A belt-and-suspenders sha256 could not be computed in this offline build environment
   (must not guess a hash); add one if the install method ever moves off mise.
3. **Dolt-remote (refs/dolt/data) git sync fidelity in external mode.** `bd config set
   dolt.auto-commit on` is applied; confirming `bd dolt push`/`pull` sync semantics against an
   external shared server (vs the embedded engine) is a live-run acceptance item.
4. **Startup ordering (design open-question #1 remainder).** Auto-start is via the stack `services:`
   list at `harnessed launch`. Whether `harnessed init` should also pre-warm the service is left as a
   follow-up.

## Verification

- Hermetic: `mise exec -- uv run --extra dev pytest -q` — new service/recipe/stack pass strict-load +
  JSON-schema + `_service_refs` unit tests. `claude_beads-shared` is CLI-only (no MCP/skill/command
  surface), so it is listed in the test's `NO_CAPABILITY_ORACLE` set alongside `claude_beads`.
- Live (manual, `HARNESSED_PODMAN=1`): build the service image, `harnessed launch claude_beads-shared`
  against a scratch repo, confirm `beads-server` container is up on :3307 and `bd init`/`bd list`
  round-trip against it.
