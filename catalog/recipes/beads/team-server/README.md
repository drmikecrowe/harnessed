# `beads/team-server` — in-repo, git-tracked, on the shared `beads-server`

> Read [the family README](../README.md) first — it covers what beads is, how to choose a variety,
> the shared three-step setup, config/`metadata.json` reference, and troubleshooting. This file
> covers only what is **specific to this variety**.

## When to use it

Everything [`beads/team`](../team/README.md) gives you — in-repo, git-tracked, Dolt-native sync —
but with the live Dolt data on **one shared server** instead of a per-container engine. Take this
variety when:

- More than one `bd` will be live against the project at once: a host `bd` **and** a container `bd`,
  or two containers. A per-container engine owns the on-disk store exclusively, and that contention
  is the 2026-07-05 lock collision this variety removes.
- You run several projects and want one Dolt server for all of them (one **database per project**).

If only one `bd` is ever live, [`beads/team`](../team/README.md) is simpler — no sidecar, no port.

## How it differs

Same placement as `beads/team` (in-repo, git-tracked), different storage:

| | |
| --- | --- |
| **Placement** | In-repo. `persist: {name: .beads, scope: workspace, location: in_repo, vcs: tracked}` — identical to `beads/team`. `.beads/` holds config + the JSONL export + the server pointer; the issue graph itself lives on the server. |
| **Storage** | The **shared** [`beads-server`](../../../services/beads-server/) service — a single standalone, externally-managed `dolt sql-server`. One Dolt **database per project** on the one server. |
| **Isolation** | Multi-database-per-server: `bd init` (no `--database`) derives the database name from the project's issue prefix and creates it on the shared server. |
| **Auth** | None. The service is loopback-published only, so no `BEADS_DOLT_PASSWORD` is set. |
| **Baked** | `bd` 1.1.0 + `dolt` 2.1.10 — bd's external-server mode connects as a MySQL client, and `bd dolt push` / `pull` (the `refs/dolt/data` git sync) shell out to a real `dolt` binary. |

### Attaching the service

The sidecar is attached at the **stack** level, not via an MCP `service:` ref — a `dolt sql-server`
speaks the MySQL wire protocol, not MCP, so it is not hatago-proxied:

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes: [beads/team-server]
services: [beads-server]
```

The launcher starts it host-published; the pod's host-gateway reaches it at
`host.containers.internal:3307` (3307 is bd's own external-server default port).

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-all-four).

```sh
bd init --server --external --server-host <host> --server-port <port>
bd setup <harness> --project
# restart the agent
```

The flags are a first-class, documented bd feature — not a workaround:

- `--server` → use an external `dolt sql-server` instead of bd's embedded engine.
- `--external` → the server is **externally managed**: bd connects but never starts or stops it.
  That is the `beads-server` container's job. bd persists host/port to `.beads/metadata.json`.

## Caveats

- **The service must be in the stack.** Without `services: [beads-server]`, `bd` has nothing to
  connect to.
- **Fresh database only (MVP).** A *new* project's database is minted on the shared server.
  Migrating an **existing** repo's `.beads/dolt` history onto the shared server is a deferred
  follow-up — the setup summary deliberately never includes `bd init --reinit-local`, which would
  discard that history.
- **`dolt_database` must be unique per project.** A collision surfaces as another project's issues
  appearing in this one. `bd doctor --server` checks it.
