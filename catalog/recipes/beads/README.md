# beads recipe — design choices

This recipe makes `bd` ([beads](https://github.com/gastownhall/beads)) available in a stack in
beads' own **default operational mode**: `.beads/` lives in the project (git-tracked), sync happens
via Dolt-native push/pull over the git origin. This file records the decisions and *why*; `PLAN.md`
is the implementation how-to.

See the sibling [`beads-stealth`](../beads-stealth/README.md) recipe for the fully-invisible
variant (`.beads/` outside the repo entirely, zero git footprint — used e.g. by
`claude_review-harness`, which dogfoods against harnessed's own repo and must not leave a trace).
The two recipes are siblings, not a hierarchy: `conflicts: [beads-stealth]` in both prevents
combining them in one stack.

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

We run `bd init --quiet --non-interactive --role maintainer`: `--non-interactive` is required since
`harnessed init` runs this in a headless one-shot container (no TTY) — bd's `--team`/`--contributor`
flags are interactive-only wizards and are explicitly *rejected* in non-interactive mode, so they
can't be scripted here at all. `--role maintainer` is the sensible default for a project's home
repo; the OSS fork-based *contributor* role (private task tracking on a repo you don't maintain) is
a manual `bd init --role contributor` override some users may want — this recipe doesn't assume it.

### No static `BEADS_DIR` (resolved dynamically, bare-aware)

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

Two pieces fix this so the layout behaves like a normal in-repo install:

1. **`bd-resolve-beads-dir`** (baked helper) + **`/etc/profile.d/beads-dir.sh`**: at shell start,
   detect a bare common dir and point `BEADS_DIR` at the work tree checked out to the bare repo's
   **default branch** (the "real main repo worktree") instead. Normal repos → nothing set (bd's own
   discovery is correct). A bare repo with **no** work tree on its default branch → the helper exits
   non-zero, and the recipe's `init.run` gates on it, so init **aborts** loudly rather than silently
   misplacing the DB. Both the agent's login shell and the init container's `bash -lc` source
   profile.d, so `bd init` and every later `bd` call agree on the location.
2. **Host-side marker alignment** (`paths.primary_worktree`): harnessed's init marker
   (`<repo>/.beads/embeddeddolt`) is resolved against the same default-branch work tree, not the raw
   launch path — so launching against `main` *or* a sibling feature worktree both find the one real
   `.beads`, and init isn't needlessly re-run.

Net effect: launch against `main` → `.beads` in `main/` (committable, marker matches). Launch
against a feature worktree → beads still uses `main/.beads` (its shared-DB model), and the marker
follows. `beads-stealth` sidesteps all of this by keeping `.beads` on the host outside the repo.

### Harness setup: `bd setup <tool>`

`bd init` does not install the SessionStart hook or the minimal `CLAUDE.md` section that lets the
agent discover `bd prime`/`bd ready` on its own — that's a separate step. Without it, the recipe
bakes a working `bd` binary the agent never learns to use unprompted.

The Dockerfile bakes `/usr/local/bin/bd-setup-agent`, resolved at build time from the `${HARNESS}`
build ARG (recipe.yaml's `init.run` is one fixed string shared by every harness a stack might use,
so it can't branch on `$HARNESS` at runtime — this is the one place harness-specific behavior may,
per the harness-independent-recipes convention). For `claude` it runs:

```
bd setup claude --project
```

`--project` (not the global default) because `~/.claude/settings.json` inside the container is
harnessed's own read-only profile mount (baked at `harnessed build` time) — `bd setup` can't write
hooks there. `--project` writes `.claude/settings.local.json` into the bind-mounted project root
instead, which is writable and persists on the host — git-tracked, like the rest of `.beads/` in
this recipe's default mode — alongside a managed section in `CLAUDE.md`. Without `--stealth`, the
hook runs `bd prime --hook-json` (the full JSON-wrapped workflow context), not the flush-only
`--stealth` variant.

`bd-setup-agent` no-ops for any `${HARNESS}` beads doesn't have a built-in recipe for yet (e.g.
`omp`) — add a case to the Dockerfile's wrapper as that changes.

### Init via `harnessed init` + auto-run on launch

`bd init` must run **at runtime against the mounted project** (the project isn't mounted at build
time, so a Dockerfile `RUN bd init` is impossible). The `init:` block in recipe.yaml wires this
into the `harnessed init` lifecycle:

```yaml
init:
  marker:
    scope: workspace
    location: in_repo
    name: .beads
  run: bd init --quiet --non-interactive --role maintainer && bd-setup-agent
```

The launcher checks whether `<project>/.beads/` exists on the host before every launch. If it
doesn't, it runs the init command in a transient one-shot container (`podman run --rm`) with the
same project + persist mounts as a normal launch. Once `bd init` succeeds, the `.beads/` dir is
created (in the project itself) and future launches skip the step.

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
- **Real git footprint, by design:** this recipe installs git hooks and commits `.beads/` to the
  project — unlike `beads-stealth`, which never touches git at all. That's the whole point of using
  the plain `beads` recipe instead of `beads-stealth`; pick the one that matches the project.
- **No `--team`/`--contributor` wizard:** those flags require an interactive TTY and are rejected
  in bd's non-interactive mode, so they can't be scripted into `init.run`. If a project genuinely
  needs the OSS fork-based contributor workflow, run `bd init --role contributor` manually inside
  the instance instead of relying on the automated init step.

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Storage modes (embedded vs server): README "Storage Modes"
- Git integration (hooks, Dolt-native sync, worktrees): `docs/GIT_INTEGRATION.md`
- Recipe authoring (persist + init fields): `docs/guides/recipe-authoring.md`
