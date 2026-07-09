# beads recipe — design choices

This recipe makes `bd` ([beads](https://github.com/gastownhall/beads)) available in a stack in
beads' own **default operational mode**: `.beads/` lives in the project (git-tracked), sync happens
via Dolt-native push/pull over the git origin. This file records the decisions and *why*; the
recipe.yaml + Dockerfile are the implementation.

See the sibling [`beads-stealth`](../beads-stealth/README.md) recipe for the fully-invisible
variant (`.beads/` outside the repo entirely, zero git footprint — used e.g. by
`claude_review-harness`, which dogfoods against harnessed's own repo and must not leave a trace).
The four beads variants (beads-team, beads-team-server, beads-stealth, beads-stealth-server) are
siblings, not a hierarchy: each `conflicts:` with the other three to prevent combining any two in
one stack.

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

### In-repo, git-tracked — upstream's actual default

This recipe intentionally does NOT replicate the invisible/host-persisted design of
`beads-stealth`. Per beads' own `docs/GIT_INTEGRATION.md` and `docs/SETUP.md`, the *default*
(non-`--stealth`) mode is:

- `.beads/` lives inside the project directory (this recipe: `persist: location: in_repo, vcs:
  tracked` — harnessed takes no `.gitignore` action; the dir is meant to be committed).
- `bd init` installs git hooks (pre-commit/post-merge — agent-identity commit trailers,
  chained-hook support) unless `--skip-hooks`/`--stealth` is passed.
- `bd init` auto-wires the git `origin` as a **Dolt remote** when one exists, so `bd dolt push` /
  `bd dolt pull` sync issue data across clones/teammates. Beads data is stored under
  `refs/dolt/data`, NOT a git branch or git commit — so this never touches protected `main`
  workflows, and is orthogonal to whatever the repo's actual git history looks like.
- `AGENTS.md`/`CLAUDE.md`-equivalent guidance is generated via `bd setup <tool>` (see "Harness
  setup" below) unless `--skip-agents`/`--stealth` is passed.

The welcome notice prints `bd init --server --quiet --non-interactive --role maintainer`:
`--non-interactive` is required because bd's `--team`/`--contributor` flags are interactive-only
wizards and are explicitly *rejected* without a TTY, so they can't be scripted. `--role maintainer`
is the sensible default for a project's home repo; the OSS fork-based *contributor* role is a
manual `bd init --role contributor` override some users may want — this recipe doesn't assume it.

### No static `BEADS_DIR`

Unlike `beads-stealth` (whose `.beads/` lives at a fixed container path unrelated to the project
mount), this recipe's `.beads/` lives INSIDE a work tree, at whatever path the project happens to
be mounted. A static `ENV BEADS_DIR=...` would be wrong the moment the mount path changed, so the
Dockerfile sets none — for a normal repo bd's own discovery (walk up from cwd to find `.beads/`)
just works.

### Bare + linked-worktree layouts

A bare repo (`.bare/`) with sibling *linked* worktrees breaks default-mode beads. bd anchors its
shared `.beads` to the git "main repository" = the **common dir**, which in a bare setup is the bare
repo — a directory with **no work tree**. The result: `.beads` (and its tracked `issues.jsonl` /
`config.yaml`) lands where nothing can `git add` it, and auto-export fails with "this operation must
be run in a work tree." The DB works, but it's stranded outside every work tree.

**Known limitation:** the recipe no longer ships a `bd-resolve-beads-dir` helper. On a bare +
linked-worktree layout, export `BEADS_DIR` manually in the shell to point at the primary worktree
before running `bd init`:

```sh
export BEADS_DIR=/path/to/main-worktree/.beads
bd init --server --quiet --non-interactive --role maintainer
```

`beads-stealth` sidesteps all of this by keeping `.beads` on the host outside the repo.

### Harness setup: `bd setup <tool>` (one-time, manual)

`bd init` does not install the SessionStart hook or the minimal `CLAUDE.md` section that lets the
agent discover `bd prime`/`bd ready` on its own — that's a separate step. Without it, the recipe
bakes a working `bd` binary the agent never learns to use unprompted.

`bd setup claude --project` writes `.claude/settings.json` + `CLAUDE.md` into the bind-mounted
project root (both persisted on the host, git-tracked along with the rest of `.beads/`) — not the
global default, because `~/.claude/settings.json` inside the container is harnessed's own
read-only profile mount (baked at `harnessed build` time) and `bd setup` can't write hooks there.
Without `--stealth`, the hook runs `bd prime --hook-json` (the full JSON-wrapped workflow context).

The exact command is per-harness, but recipe.yaml's `setup:` note is deliberately harness-agnostic
— it points the user at beads' own docs (`bd setup --list`) rather than baking one command per
harness into the Dockerfile.

### First-time init

`bd init` must run at runtime against the mounted project (the project isn't mounted at build time).
Rather than auto-running it on every attach (which is not reliably idempotent across git layouts),
recipe.yaml declares `setup: {summary, reference, condition: '! bd list >/dev/null 2>&1'}`. The
assembler turns `condition` into a self-gating Claude SessionStart hook (`emit._recipe_hooks_settings`)
that `cat`s the baked notice file (`emit.write_setup_hint_files`) only when `bd list` still fails —
silent once the workspace is initialized. Other harnesses (codex/opencode/omp/antigravity), which
have no live per-session check, get the same summary as a permanent static note in their identity
file instead.

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
  `bd init` is idempotent (no-ops if `.beads/` already exists); `bd setup claude` is idempotent too
  (updates its marked section rather than duplicating it).
- **Real git footprint, by design:** this recipe installs git hooks and commits `.beads/` to the
  project — unlike `beads-stealth`, which keeps `.beads/` outside the repo. Pick the variant that
  matches the project's collaboration model.
- **No `--team`/`--contributor` wizard:** those flags require an interactive TTY and are rejected
  in bd's non-interactive mode. If a project genuinely needs the OSS fork-based contributor
  workflow, run `bd init --role contributor` manually inside the instance.

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Storage modes (embedded vs server): README "Storage Modes"
- Git integration (hooks, Dolt-native sync, worktrees): `docs/GIT_INTEGRATION.md`
- Recipe authoring (persist + init fields): `docs/guides/recipe-authoring.md`
