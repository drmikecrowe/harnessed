# `beads/stealth-server` — outside the repo, zero git footprint, on the shared `beads-server`

> Read [the family README](../README.md) first — it covers what beads is, how to choose a variety,
> the shared three-step setup, config/`metadata.json` reference, and troubleshooting. This file
> covers only what is **specific to this variety**.

## When to use it

The zero-git-footprint placement of [`beads/stealth`](../stealth/README.md), but with the live Dolt
data on the **shared server** instead of a per-container embedded engine. Take this variety when:

- The repo must stay clean (nothing in the project, no hooks, no tracked `.beads/`), **and**
- More than one `bd` will be live against the store: a host `bd` **and** a container `bd`, or two
  containers.

That second condition is why this cell exists. `beads/stealth`'s embedded engine takes an
**exclusive on-disk Dolt file lock** on its host-persisted `.beads/dolt`, so a host `bd` and a
container `bd` can never both hold a live engine against it — the same 2026-07-05 lock collision the
`beads-server` service was built to fix, but for the invisible/host-persisted placement rather than
the in-repo one. Pointing stealth `bd` at the shared server removes the contention while keeping the
zero-footprint placement.

If only one `bd` is ever live, [`beads/stealth`](../stealth/README.md) is simpler — no sidecar, no
port. If teammates need the issue graph, take [`beads/team-server`](../team-server/README.md).

## How it differs

Same placement as `beads/stealth`, same storage as `beads/team-server`:

| | |
| --- | --- |
| **Placement** | Outside the repo. `persist: {name: .beads, scope: project, location: host}` — host-persisted, bind-mounted at the same fixed container path as `beads/stealth`. Here `.beads/` holds only config + `metadata.json` (the pointer at the server); the issue graph lives on the shared server's named volume. |
| **Storage** | The **shared** [`beads-server`](../../../services/beads-server/) service — one standalone, externally-managed `dolt sql-server`, one Dolt **database per project**. |
| **Git** | None. `--stealth` throughout: git-exclude only, no repo hook install, no `AGENTS.md` mutation. |
| **`BEADS_DIR`** | Baked as a static `ENV BEADS_DIR=/home/harnessed/.beads` — the mount target is a fixed container path, so no per-project path arithmetic and no `bd-resolve-beads-dir` helper (that only matters for the in-repo `beads/team*` varieties). |
| **Baked** | `bd` 1.1.0 + `dolt` 2.1.10 — the same versions the other server variety pins, so the family shares one proven toolchain. |

### Attaching the service

The sidecar is attached at the **stack** level, not via an MCP `service:` ref — a `dolt sql-server`
speaks MySQL, not MCP:

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes: [beads/stealth-server]
services: [beads-server]
```

The pod's host-gateway reaches the loopback-published service at `host.containers.internal:3307`
(3307 is bd's own external-server default port). Loopback-only, no auth, so no password is set.

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-all-four).

```sh
bd init --stealth --server --external --server-host <host> --server-port <port>
bd setup <harness> --project --stealth
# restart the agent
```

- `--stealth` → invisible mode: git-exclude only, no repo hook install, no `AGENTS.md` mutation.
- `--server` → use an external `dolt sql-server` instead of bd's embedded engine.
- `--external` → the server is externally managed; bd connects but **never** starts or stops it —
  that is the `beads-server` container's job.

Per-project isolation is multi-database-per-server: `bd init` (no `--database`) derives the database
name from the project's issue prefix and creates it on the shared server.

## Caveats

- **⚠️ "Stealth" is not fully footprint-free on bd 1.1.0** — same as `beads/stealth`: `bd setup
  <tool> --project --stealth` still writes an untracked `.claude/settings.json` + `CLAUDE.md` into
  the project. They are not in bd's stealth git-exclude list.
- **The service must be in the stack.** Without `services: [beads-server]`, `bd` has nothing to
  connect to.
- **Fresh database only (MVP).** A *new* project's database is minted on the shared server.
  Migrating an existing embedded `.beads/dolt` into the shared server is a deferred follow-up; the
  setup summary never includes `bd init --reinit-local`.
