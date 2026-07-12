# `beads` — recipe family

`bd` ([beads](https://github.com/gastownhall/beads)) is a CLI graph issue tracker for coding agents:
dependency-aware tasks, auto-ready detection, hash-based IDs, and persistent project memory
(`bd remember` / `bd prime`). It is **not** an MCP server — it is a binary the agent shells out to.
Storage is [Dolt](https://github.com/dolthub/dolt), a versioned SQL database.

This directory is a recipe **family**: one tool, two wirings. Each subdirectory is a complete,
self-contained recipe (its own `recipe.yaml` + `Dockerfile`) and is referenced from a stack with a
variety ref — its path under `catalog/recipes/`:

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes:  [beads/team]      # NOT `beads` — the family itself is not a usable recipe
services: [beads-server]    # required: this project's dolt sql-server
```

Sibling varieties are **implicitly mutually exclusive**: a stack that lists both fails at assemble
time (`schema._check_recipe_conflicts`).

## Choosing a variety — one question

**Should the issue graph live in the repo, where teammates get it on clone?**

| | recipe | `.beads/` lives | git sees |
|---|---|---|---|
| **Yes** | [`beads/team`](team/README.md) | in the repo, git-tracked | `.beads/` config + `issues.jsonl`; Dolt history on `refs/dolt/data` |
| **No** | [`beads/stealth`](stealth/README.md) | host-persisted, outside the repo | nothing |

That is the whole decision. **Storage is not a choice**: both recipes run the same engine — the
[`beads-server`](../../services/beads-server/service.yaml) service, one `dolt sql-server` per project
— and the service *follows* whichever placement the recipe declared (`data.persist: .beads`).

The service is attached at the **stack** level (`services: [beads-server]`), not via an MCP `service:`
ref — a `dolt sql-server` speaks the MySQL wire protocol, not MCP, so it is not hatago-proxied.

## Why there is no embedded mode, and no per-container server

Both used to exist: `beads/team-server` and `beads/stealth-server` were the "shared server" half of a
2×2 whose other half was the embedded engine. That 2×2 is gone. The reason is a real incident,
root-caused 2026-07-12.

Dolt takes an **exclusive flock** on its data dir. `bd init --server` spawned a `dolt sql-server`
**per container**, and every container in a bare+worktree checkout resolves to the **same** `.beads`
(bd keys it off the git common dir — verify with `bd where`). The first container to start won the
lock; every other one retried forever:

```
database "dolt" is locked by another dolt process; either clone the database to run a second
server, or stop the dolt process which currently holds an exclusive write lock on the database
```

Embedded mode is not an escape: same Dolt engine, same flock, merely held for one command instead of
continuously — which converts a loud permanent failure into an intermittent race. The only shape that
removes the contention *by construction* is **one server per project, N clients**. That is now the
only shape shipped.

Two consequences worth knowing:

- **Agents reach the server over a unix socket**, not a port. The socket lives inside the
  bind-mounted `.beads/`, so it is a filesystem object every container already sees. TCP could never
  have worked across containers: `127.0.0.1` means something different in each network namespace, so
  a client cannot reach another container's server, whatever port bd records. The launcher exports
  the path as `$HARNESSED_BEADS_SERVER_SOCKET`.
- **Git sync runs on the host, not in the agent.** `bd dolt push` shells out to the `dolt` CLI, which
  only routes to a server on *its own* loopback — so it can only run inside the server container:

  ```sh
  harnessed svc sync beads-server --stack <stack>   # execs `bd dolt push` in the server container
  ```

  `beads/team` only (stealth has no remote to push to), and explicit by design: it writes to your git
  remote.

## Setup — the same shape for both

Nothing is auto-initialized. Each recipe declares `setup: {summary, reference, condition}` in its
`recipe.yaml`; the assembler turns `condition` (`! bd list >/dev/null 2>&1`) into a self-gating Claude
`SessionStart` hook that prints the summary until the workspace is initialized, then stays silent.
Harnesses with no live per-session check (codex/opencode/omp/antigravity) get the same summary as a
static note in their identity file.

**Why manual:** `bd setup <tool>` writes `.claude/settings.json` + `CLAUDE.md` into the project on bd
1.1.0. That is a real footprint and cannot be made reliably idempotent across every git layout, so
first-time init is a deliberate user action inside a running instance — not an every-attach auto-run.

Three steps; only step 1 differs between the two recipes (see each recipe's README):

```sh
# 1. Initialize the store as a CLIENT of this project's beads-server. (beads/team shown;
#    beads/stealth adds --stealth.)
bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET"

# 2. Wire bd into the harness (writes .claude/settings.json + CLAUDE.md).
bd setup <harness> --project

# 3. Restart the agent so the hook/instructions load.
```
