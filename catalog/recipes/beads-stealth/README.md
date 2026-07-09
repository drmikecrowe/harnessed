# beads-stealth recipe — design choices

This recipe makes `bd` ([beads](https://github.com/gastownhall/beads)) available in a stack in
**fully invisible mode** — persistent task memory for agents that leaves zero git footprint. This
file records the decisions and *why*; the recipe.yaml + Dockerfile are the implementation.

See the [`beads-team`](../beads-team/README.md) recipe for upstream's actual default operational mode
(in-repo, git-tracked, Dolt-native sync via the git origin). The four beads variants (beads-team,
beads-team-server, beads-stealth, beads-stealth-server) are siblings, not a hierarchy — each
`conflicts:` with the other three to prevent combining any two in one stack.

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

### Harness setup: `bd setup <tool> --stealth` (one-time, manual)

`bd init --stealth` only configures git-exclude — it does not install the SessionStart hook or the
minimal `CLAUDE.md` section that lets the agent discover `bd prime`/`bd ready` on its own. Without
it, the recipe bakes a working `bd` binary the agent never learns to use unprompted.

The exact command (`bd setup <tool> --project --stealth`) is per-harness, but recipe.yaml's
`setup:` note is deliberately harness-agnostic — it points the user at beads' own docs
(`bd setup --list`) rather than baking one command per harness into the Dockerfile.

**⚠️ Footprint caveat (bd 1.1.0):** `bd setup claude --project --stealth` writes `.claude/settings.json`
and `CLAUDE.md` into the project. These files are NOT in bd's stealth git-exclude list, so they
appear as untracked in `git status`. "Stealth" is not fully footprint-free on bd 1.1.0 — the user
opts into that knowingly when choosing this recipe.

### First-time init

`bd init` must run at runtime against the mounted project (the project isn't mounted at build time).
Rather than auto-running it on every attach (which can't be made footprint-free reliably), recipe.yaml
declares `setup: {summary, reference, condition: '! bd list >/dev/null 2>&1'}`. The assembler turns
`condition` into a self-gating Claude SessionStart hook (`emit._recipe_hooks_settings`) that `cat`s
the baked notice file (`emit.write_setup_hint_files`) only when `bd list` still fails — silent once
the workspace is initialized. Other harnesses (codex/opencode/omp/antigravity), which have no live
per-session check, get the same summary as a permanent static note in their identity file instead.

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
- **First-time init is manual:** `bd init` (and `bd setup`) must be run once by the user inside a
  running instance, then the agent restarted. The `SessionStart` notice is silent after that.
  `bd init` is idempotent (no-ops if `.beads/` already exists); `bd setup claude` is idempotent too.
- **Stealth scope (bd 1.1.0):** `--stealth` on `bd init` only touches `.git/info/exclude`; `bd
  setup claude --stealth` changes the hook's runtime behavior (`bd prime --stealth` instead of
  `--hook-json`) — but it still writes `.claude/settings.json` + `CLAUDE.md` into the project, and
  those files are NOT git-excluded by bd's stealth logic. Expect two untracked files after setup.

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Storage modes (embedded vs server): README "Storage Modes"
- Git-free usage (`BEADS_DIR`, `--stealth`): README "Git-Free Usage"
- Recipe authoring (persist + init fields): `docs/guides/recipe-authoring.md`
