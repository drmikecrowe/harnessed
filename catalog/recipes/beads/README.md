# `beads` — recipe family

`bd` ([beads](https://github.com/gastownhall/beads)) is a CLI graph issue tracker for coding agents:
dependency-aware tasks, auto-ready detection, hash-based IDs, and persistent project memory
(`bd remember` / `bd prime`). It is **not** an MCP server — it is a binary the agent shells out to.
Storage is [Dolt](https://github.com/dolthub/dolt), a versioned SQL database.

This directory is a recipe **family**: one tool, four wirings. Each subdirectory is a complete,
self-contained recipe (its own `recipe.yaml` + `Dockerfile`) and is referenced from a stack with a
variety ref — its path under `catalog/recipes/`:

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes: [beads/team]      # NOT `beads` — the family itself is not a usable recipe
```

Sibling varieties are **implicitly mutually exclusive**: a stack that lists two of them fails at
assemble time (`schema._check_recipe_conflicts`). No `conflicts:` entry pairs them — the family is
the source of truth.

## Choosing a variety

The four varieties are a 2×2 over **placement** (where `.beads/` lives) × **storage** (which Dolt
engine holds the live data). They are siblings, not a hierarchy.

|                            | Embedded engine (per-container)                | Shared `beads-server` service              |
| -------------------------- | ---------------------------------------------- | ------------------------------------------ |
| **In-repo** (git-tracked)  | [`beads/team`](team/README.md)                 | [`beads/team-server`](team-server/README.md)         |
| **Stealth** (outside repo) | [`beads/stealth`](stealth/README.md)           | [`beads/stealth-server`](stealth-server/README.md)   |

Pick along two independent questions:

1. **Do teammates need the issue graph?**
   *Yes* → a `team` variety: `.beads/` is committed, `bd init` installs git hooks, and the git
   `origin` is auto-wired as a Dolt remote so `bd dolt push` / `bd dolt pull` sync issue data (under
   `refs/dolt/data` — never a git branch, so protected-branch workflows are untouched).
   *No — the repo must stay clean* → a `stealth` variety: `.beads/` lives on the host, outside the
   repo entirely, and `--stealth` is passed throughout. Use this when dogfooding a tool against a
   repo whose collaborators must not see beads at all.

2. **Will more than one `bd` hold the database at once?**
   An embedded Dolt engine takes an **exclusive on-disk file lock**. A host `bd` and a container
   `bd` (or two containers) can never both hold a live engine against the same store — this is the
   2026-07-05 lock collision. If that applies to you, take a `-server` variety: it points `bd` at the
   shared [`beads-server`](../../services/beads-server/) service (one externally-managed
   `dolt sql-server`, one Dolt **database per project**) and the contention disappears.
   Otherwise the embedded engine is simpler — no sidecar, no port.

The `-server` varieties require the `beads-server` service to be attached at the **stack** level
(`services: [beads-server]`), not via an MCP `service:` ref — a `dolt sql-server` speaks the MySQL
wire protocol, not MCP.

## Setup — the same shape for all four

Nothing is auto-initialized. Every variety declares `setup: {summary, reference, condition}` in its
`recipe.yaml`; the assembler turns `condition` (`! bd list >/dev/null 2>&1`) into a self-gating
Claude `SessionStart` hook that prints the variety's summary until the workspace is initialized, then
stays silent. Harnesses with no live per-session check (codex/opencode/omp/antigravity) get the same
summary as a static note in their identity file.

**Why manual:** `bd setup <tool>` writes `.claude/settings.json` + `CLAUDE.md` into the project on bd
1.1.0. That is a real footprint and cannot be made reliably idempotent across every git layout, so
first-time init is a deliberate user action inside a running instance — not an every-attach auto-run.

The sequence is always the same three steps; only step 1 differs per variety (see each variety's
README):

```sh
# 1. Initialize the store — flags are VARIETY-SPECIFIC.
bd init ...

# 2. Wire bd into the harness. --project targets the writable project root; the container's
#    ~/.claude is harnessed's read-only profile mount, so a global setup cannot write hooks there.
#    Add --stealth on the stealth varieties. `bd setup --list` shows supported harnesses.
bd setup <harness> --project [--stealth]

# 3. Restart the agent so the newly written hook/settings are loaded.
```

Both commands are idempotent: `bd init` no-ops on an existing `.beads/`, and `bd setup` updates its
marked section rather than duplicating it.

### Verify

```sh
bd where --json    # which database is active, and how bd found it
bd doctor          # full health check — the primary diagnostic
bd list            # the setup hook's own gate: once this succeeds, the notice goes silent
```

## Shared reference

### Configuration precedence (highest wins)

1. CLI flags
2. Environment variables
3. `.beads/config.local.yaml` (machine-local)
4. `.beads/config.yaml` (project config, git-tracked in the `team` varieties)
5. `~/.config/bd/config.yaml` (global user config)
6. Database config table (inside Dolt)
7. Hardcoded defaults

Config files are **YAML, not TOML** — a `config.toml` is silently ignored.

### `.beads/metadata.json`

Controls how `bd` discovers and connects to the database — `dolt_mode`, `dolt_server_host`,
`dolt_database`, `project_id`. If this file is wrong, nothing works. On the `-server` varieties this
is the file that points at the shared server, and `dolt_database` **must be unique per project**
(mismatches surface as phantom issues from another project's database).

### Environment variables

| Variable             | What it does                                                     |
| -------------------- | ---------------------------------------------------------------- |
| `BEADS_DIR`          | Override the `.beads/` location. **Baked as a static `ENV` by the stealth varieties** (see below). |
| `BD_ACTOR`           | Actor name for audit trails                                       |
| `BD_BRANCH`          | Branch-per-agent write isolation                                  |
| `BD_DEBUG_RPC=1`     | Show Dolt server communication — the first thing to set on a connection failure |
| `BD_DEBUG_SYNC=1`    | Show sync internals                                               |
| `BD_DEBUG_ROUTING=1` | Show issue routing decisions                                      |

Recipe `init:` exports flow straight into the agent process, so a variety can set `BEADS_DIR` without
a profile.d shim — but only the stealth varieties need to: their bind-mount target is a **fixed**
container path (`/home/harnessed/.beads`), so a Dockerfile `ENV` is safe and never varies per
project. The `team` varieties keep `.beads/` inside whatever path the project is mounted at, where a
static `ENV` would be wrong the moment the mount moved — bd's own discovery (walk up from cwd) is
used instead.

### Troubleshooting

| Symptom | Check |
| --- | --- |
| `bd` connects to nothing / "can't find database" | `bd where --json`; then `.beads/metadata.json` — is `dolt_mode` what the variety expects? |
| Stale LOCK file | `flock -n .beads/dolt/.dolt/lock echo "Lock is free"` — if it prints, the lock file is stale and safe to remove |
| Issues from the wrong project appear | `dolt_database` in `metadata.json` doesn't match the real database name. `bd doctor --server` |
| `.beads/` present after `git clone` but no database (team varieties) | the Dolt data dir is gitignored; re-run `bd init` — it rebuilds from config |
| Git ignores `.beads/` changes | leftover skip-worktree bits: `git ls-files -v \| rg '^S'`, then `git update-index --no-skip-worktree <file>` |

`bd doctor --fix` auto-repairs outdated git hooks, a missing `project_id`, and a stale
`.beads/.gitignore`. It is generally safe but has had destructive bugs in past versions — read what
it proposes before confirming.

## Shared design decisions

- **Install: mise `github:` backend, pinned.** All four bake `bd` (and, except `beads/stealth`, the
  standalone `dolt` CLI) via `mise use -g "github:gastownhall/beads@1.1.0"`. mise resolves the
  release asset for the current arch and verifies GitHub artifact attestations — a stronger
  supply-chain guarantee than a hand-rolled curl + sha256. Versions are pinned exactly: the
  assembler's pin gate rejects `@latest` / `:latest` / `--branch main`.
- **`dolt` is baked alongside `bd`** everywhere except `beads/stealth`. bd's bundled Dolt is an
  embedded *library*, not a spawnable server: `bd init --server` / `bd dolt start` / `bd dolt push`
  shell out to a real `dolt` binary on PATH. All varieties that need it pin the same 2.1.10, so the
  family shares one proven toolchain.
- **No MCP, no skill.** beads is a CLI. Agent discovery is the `SessionStart` hook + the `CLAUDE.md`
  section that `bd setup claude` installs — not a skill, not an `AGENTS.md` mutation. No `mcp:`
  block, no hatago entry.
- **Persistence differs per variety** and is the whole point of the 2×2 — see each variety's README.

## Relationship to the host machine guide

If you also run `bd` **on the host**, `~/.agents/docs/beads/setup.md` covers that (shared
`dolt sql-server` under a systemd user unit, Gastown integration, Manjaro install). Two things do not
carry over into harnessed:

- **No systemd.** The shared server here is the `beads-server` **container service**, started by the
  launcher and reachable from the pod at `host.containers.internal:3307` (bd's own external-server
  default port). `bd` is told the server is `--external`: it connects but never starts or stops it.
- **Version drift.** That guide was written against beads 0.60.0 from `steveyegge/beads`; these
  recipes pin **1.1.0 from `gastownhall/beads`**. Cross-check flags with `bd help init` before
  copying a command out of it.

The general parts — the mental model, config precedence, `metadata.json`, `bd doctor`, the error
table — are reproduced above in their harnessed-applicable form.

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Host-machine setup guide (shared Dolt server, systemd, Gastown): `~/.agents/docs/beads/setup.md`
- Recipe authoring (`persist`, `setup`, `init` fields): `docs/guides/recipe-authoring.md`
- The `beads-server` service: `catalog/services/beads-server/`
