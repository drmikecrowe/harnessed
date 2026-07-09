# beads-team recipe — implementation plan

Goal: make `bd` (beads) available in a stack in beads' own **default operational mode**: `.beads/`
lives inside the project (git-tracked), `bd init` installs git hooks and auto-wires the git origin
as a Dolt remote for `bd dolt push`/`bd dolt pull` sync.

This is a SIBLING of the [`beads-stealth`](../beads-stealth/PLAN.md) recipe, not a superset:
`beads-stealth` trades away all of this for total invisibility (`.beads/` outside the repo, zero
git footprint). `conflicts: [beads-stealth]` in both recipe.yaml files prevents combining them in
one stack.

Upstream: <https://github.com/gastownhall/beads> · release binary (goreleaser style) · MIT license.

See `README.md` (this dir) for *why* each choice was made. This file is the *how*.

## Recipe shape

Dockerfile recipe (bake the `bd` CLI) + a `persist:` entry (`.beads/` in-repo, git-tracked) + an
`init:` block (`bd init --quiet --non-interactive --role maintainer` run once per project via
`harnessed init`). **No MCP, no service.**

```
catalog/recipes/beads-team/
  recipe.yaml        # persist + init declarations
  Dockerfile         # bake the pinned bd binary + the bd-setup-agent wrapper
  PLAN.md  README.md
```

### recipe.yaml

```yaml
name: beads-team
description: "bd (beads) — graph issue tracker / persistent task memory for agents (default mode: in-repo, git-tracked, Dolt-native sync)."

conflicts: [agent-carnet, beads-stealth, beads-stealth-server, beads-team-server]

persist:
  - name: .beads
    scope: workspace
    location: in_repo
    vcs: tracked

init:
  marker:
    scope: workspace
    location: in_repo
    name: .beads
  run: bd init --quiet --non-interactive --role maintainer && bd-setup-agent
```

`location: in_repo` — `.beads/` is already inside the project's own bind-mount; no separate
persist mount. `vcs: tracked` — harnessed takes no `.gitignore` action; the item is meant to be
committed (beads manages its own finer-grained exclusions internally, e.g. `.beads/dolt/`).

The `init:` block is executed by `_run_init_for_stack()` in the launcher (auto-run on every
`harnessed launch`, also runnable explicitly via `harnessed init <stack>`). Because the marker is
the `.beads/` dir itself, and `bd init` creates that dir on success, the check is self-sealing:
after the first successful init, all subsequent launches skip it instantly.

### Dockerfile (bake `bd`)

Primary install: pinned release binary, verified against the release `checksums.txt`. Goreleaser
asset naming: `beads_<ver>_<os>_<arch>.tar.gz`. **No static `ENV BEADS_DIR`** here (unlike
`beads-stealth`): `.beads/` lives inside a work tree, at whatever path the project is mounted.

Also bakes two things for **bare + linked-worktree** support (see README "Bare + linked-worktree
layouts"):

- `/usr/local/bin/bd-resolve-beads-dir` — prints the default-branch work tree's `.beads` when the
  git common dir is a bare repo (else nothing); exits non-zero for a bare repo with no work tree on
  its default branch (the `init.run` gate turns that into a hard abort).
- `/etc/profile.d/beads-dir.sh` — exports `BEADS_DIR` from that helper for every login shell (the
  agent's `bash -l -c` attach and the init container's `bash -lc`).

Both are baked with Docker `COPY <<'SH'` heredocs (validated to build under podman). The host side
mirrors the same resolution in `paths.primary_worktree`, used by `_resolve_marker_host_path` so the
init marker points at the same `.beads` the container writes.

Also bakes `/usr/local/bin/bd-setup-agent`, a harness-aware wrapper resolved at build time from the
`${HARNESS}` ARG (recipe.yaml's `init.run` is one fixed string shared by every harness, so it can't
branch on `$HARNESS` at runtime). For `claude`: `bd setup claude --project`. This is needed because
`bd init` does NOT wire the SessionStart hook or CLAUDE.md section on its own — see "Init via
`harnessed init`" below.

```dockerfile
USER root
ARG BEADS_VERSION=1.0.4
RUN set -eu; \
    case "$(uname -m)" in \
      x86_64)  asset="beads_${BEADS_VERSION}_linux_amd64.tar.gz" ;; \
      aarch64) asset="beads_${BEADS_VERSION}_linux_arm64.tar.gz" ;; \
      *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    # … curl + sha256sum verify + install to /usr/local/bin …
RUN bd --version
USER harnessed
```

## Build / init / test lifecycle

```bash
harnessed build claude_beads-team   # assemble + build derived image (pin gate)
harnessed init  claude_beads-team   # one-time per project: bd init --quiet --non-interactive --role maintainer && bd-setup-agent
harnessed claude_beads-team         # launch; init is auto-checked and skipped (marker already exists)
harnessed test  claude_beads-team   # capability report: ✓ bd (CLI) available
```

Manual verification:
- After `harnessed init`, the project root has a git-tracked `.beads/` directory (issues.jsonl,
  config.yaml) and a `.git/hooks/pre-commit`/`post-merge` installed by `bd init`.
- If the project has a git `origin`, `bd init` auto-wires it as the Dolt remote (`bd dolt push` /
  `bd dolt pull` sync data under `refs/dolt/data` — NOT a git branch, so protected `main` is
  unaffected).
- After `harnessed init`, the project root has `.claude/settings.local.json` (SessionStart hook
  running `bd prime --hook-json`) and a managed beads section in `CLAUDE.md`.
- Re-running `harnessed init` prints "already initialized".
- `bd ready --json` / `bd create …` work inside the instance.
- `bd setup claude --check` reports the hook + `CLAUDE.md` section as current.

## Risks / checks

- **Single-writer (embedded mode):** embedded Dolt locks the file; one instance per project dir
  (two worktrees = two containers = two processes writing the same `.beads/` dir — potential
  contention). Multi-writer needs beads' `--server` mode (external `dolt sql-server`), which this
  recipe does not set up — evaluated and rejected as unnecessary complexity for now; revisit if
  concurrent-writer contention actually shows up in practice.
- **Idempotency:** `bd init` is a no-op if `.beads/` already exists; `harnessed init` skips
  entirely if the marker dir exists before the command. `bd setup claude` is itself idempotent
  (updates its marked section rather than duplicating it), so re-running `bd-setup-agent` is safe
  even outside the marker check.
- **Real git footprint, by design:** unlike `beads-stealth`, this recipe installs git hooks and
  commits `.beads/` to the project. That's the point (upstream's own default, and what makes
  cross-clone/cross-teammate sharing work via `bd dolt push`/`pull`) — but it means `harnessed init`
  on this recipe mutates the user's actual repo (hooks + tracked files), which `beads-stealth` never
  does. Choose the recipe deliberately.
- **`--role maintainer` is a default, not a mandate:** the OSS fork-based contributor pattern
  (`bd init --role contributor`, private task tracking on a public repo you don't maintain) isn't
  wired into this recipe's init command — it's a manual override if you need it (see
  docs/GIT_INTEGRATION.md "Multi-Workspace Sync"). `--team`/`--contributor` themselves are
  interactive wizards and are rejected in bd's non-interactive mode, so they can't be scripted into
  `init.run` at all.
- **Only `claude` wired so far:** `bd-setup-agent` no-ops for any other `${HARNESS}` (e.g. `omp`,
  which has no built-in `bd setup` recipe upstream). Add a case as new harnesses gain bd support.
- **Bare + linked-worktree layouts are handled, but abort on a degenerate one:** in a `.bare` +
  sibling-worktree repo, `bd-resolve-beads-dir` re-anchors `.beads` to the default-branch work tree
  (see the Dockerfile section + README). If the repo is bare with **no** work tree on its default
  branch, `init.run` aborts — there is nowhere committable to put `.beads`; the user must add a work
  tree (or use `beads-stealth`). Verified against a real bare+worktree repo and a synthetic
  no-default-worktree repo.
