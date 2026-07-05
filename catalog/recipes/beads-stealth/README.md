# beads-stealth recipe — design choices

This recipe makes `bd` ([beads](https://github.com/gastownhall/beads)) available in a stack in
**fully invisible mode** — persistent task memory for agents that leaves zero git footprint. This
file records the decisions and *why*; `PLAN.md` is the implementation how-to.

See the plain [`beads`](../beads/README.md) recipe for upstream's actual default operational mode
(in-repo, git-tracked, Dolt-native sync via the git origin). The two recipes are siblings, not a
hierarchy — `conflicts: [beads]` in both prevents combining them in one stack.

## What beads is

`bd` is a CLI graph issue tracker for coding agents — dependency-aware tasks, auto-ready detection,
hash-based IDs, and persistent project memory (`bd remember` / `bd prime`). It is **not** an MCP
server; it is a binary the agent shells out to. Storage is [Dolt](https://github.com/dolthub/dolt)
(a versioned SQL DB), bundled into the binary.

## Decisions

### Embedded mode, no Dolt server

beads' default and recommended mode runs Dolt **in-process** (data in `.beads/embeddeddolt/`,
single-writer file lock) — no external `dolt sql-server`. This matches harnessed's one-instance-
per-project model. Server mode would force a long-lived `dolt sql-server` sidecar (a harnessed
`service:` with its own port + healthcheck) to buy multi-writer concurrency we do not need.
**Chosen: embedded.** Trade-off: single-writer — two instances on the same project dir contend.

### Git-free + stealth, BEADS_DIR at a fixed container path

The `.beads/` directory is host-persisted at `$XDG_DATA_HOME/harnessed/persist/beads/<project-hash>/.beads/`
and bind-mounted at `$HOME/.beads` (`/home/harnessed/.beads`) inside the container. This is a
**fixed** container path — not `$PWD`-relative — which means `BEADS_DIR` can be baked as a static
`ENV` in the Dockerfile and never varies per project.

Why not `$PWD/.beads` (the old approach): a shell `export BEADS_DIR=…` in a hook script only
affects that script's own process tree and is lost before `bd` ever runs. A Dockerfile `ENV` reaches
every process in the container unconditionally. The fixed mount target makes the static ENV safe.

`scope: project` (git-common-dir keyed) means every worktree of the same checkout shares one
`.beads/` DB — the right behavior for an issue tracker that spans branches.

We run `bd init --quiet --stealth`: `--stealth` configures per-repo git settings for invisible
usage (`.git/info/exclude`), disabling git operations. The user's repo stays clean. Note that
`--stealth` on `bd init` does **not** wire up any AI tool integration by itself — per beads' own
docs/SETUP.md, that's a separate step (see "Harness setup" below).

### Harness setup: `bd setup <tool> --stealth`

`bd init --stealth` only configures git-exclude — it does not install the SessionStart hook or the
minimal `CLAUDE.md` section that lets the agent discover `bd prime`/`bd ready` on its own. Without
this, the recipe bakes a working `bd` binary the agent never learns to use unprompted.

The Dockerfile bakes `/usr/local/bin/bd-setup-agent`, resolved at build time from the `${HARNESS}`
build ARG (recipe.yaml's `init.run` is one fixed string shared by every harness a stack might use,
so it can't branch on `$HARNESS` at runtime — this is the one place harness-specific behavior may,
per the harness-independent-recipes convention). For `claude` it runs:

```
bd setup claude --project --stealth
```

`--project` (not the global default) because `~/.claude/settings.json` inside the container is
harnessed's own read-only profile mount (baked at `harnessed build` time) — `bd setup` can't write
hooks there. `--project` writes `.claude/settings.local.json` into the bind-mounted project root
instead, which is writable and persists on the host like any other project file, alongside a
managed section in `CLAUDE.md`. `--stealth` here means the hook runs `bd prime --stealth` (flush
only, no git operations) rather than `bd prime --hook-json`.

`bd-setup-agent` no-ops for any `${HARNESS}` beads doesn't have a built-in recipe for yet (e.g.
`omp`) — add a case to the Dockerfile's wrapper as that changes.

### Init via `harnessed init` + auto-run on launch

`bd init` must run **at runtime against the mounted project** (the project isn't mounted at build
time, so a Dockerfile `RUN bd init` is impossible). The `init:` block in recipe.yaml wires this
into the `harnessed init` lifecycle:

```yaml
init:
  marker:
    scope: project
    location: host
    name: .beads
  run: bd init --quiet --stealth && bd-setup-agent
```

The launcher checks whether `$XDG_DATA_HOME/harnessed/persist/beads/<project-hash>/.beads/` exists
on the host before every launch. If it doesn't, it runs `bd init --quiet --stealth` in a transient
one-shot container (`podman run --rm`) with the same project + persist mounts as a normal launch.
Once `bd init` succeeds, the `.beads/` dir is created and future launches skip the step.

This mechanism (Option B from the design):
1. `harnessed init <stack>` — explicit, can be run standalone before first use.
2. Auto-checked on every `harnessed launch` — silently skips if already initialized; runs if not.

### No skill shipped

`bd` ships no standalone Claude skill — for Claude, agent-discovery is the SessionStart hook +
minimal `CLAUDE.md` section installed by `bd setup claude` (see "Harness setup" above), not a
skill or `AGENTS.md` mutation (that's the Factory/Codex/Mux path). This recipe authors no skill:
the agent has the `bd` CLI and the hook-injected `bd prime` context. A user may add a workflow
skill later.

### Install: pinned release binary

The upstream `curl install.sh | bash` pulls "latest" — a floating ref the assembler's pin gate
rejects. We download the pinned goreleaser binary (`beads_<ver>_<os>_<arch>.tar.gz`) and verify its
SHA-256 against the release `checksums.txt`. Deterministic and matches beads' own security guidance.

### No MCP, no service

beads is a CLI. The recipe contributes a Dockerfile body (bake `bd`) — no `mcp:` block, no hatago
entry, no `service:` sidecar.

## Caveats

- **Single-writer:** embedded Dolt locks the file; one instance per project dir.
- **Idempotency:** `harnessed init` is idempotent (`bd init` no-ops if `.beads/` exists); `bd setup
  claude` is separately idempotent (updates its marked section instead of duplicating it).
- **Stealth scope confirmed:** `--stealth` on `bd init` only touches `.git/info/exclude` (no git
  ops); `bd setup claude --stealth` only changes the *hook's* behavior (`bd prime --stealth`
  instead of `--hook-json`) — neither one skips installing the hook/CLAUDE.md section, which is
  why `bd-setup-agent` must run as its own explicit step.

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Storage modes (embedded vs server): README "Storage Modes"
- Git-free usage (`BEADS_DIR`, `--stealth`): README "Git-Free Usage"
- Recipe authoring (persist + init fields): `docs/guides/recipe-authoring.md`
