# beads-stealth recipe — implementation plan

Goal: make `bd` (beads) available in a stack in **fully invisible mode** — `.beads/` host-persisted
under `scope: project` (git-common-dir keyed), outside the repo entirely, zero git side effects.

This is a SIBLING of the plain [`beads`](../beads/PLAN.md) recipe, not a superset: `beads` is
upstream's default operational mode (in-repo, git-tracked, Dolt-native sync via the git origin,
hooks installed); `beads-stealth` trades that away for total invisibility. `conflicts: [beads]` in
both recipe.yaml files prevents combining them in one stack.

Upstream: <https://github.com/gastownhall/beads> · release binary (goreleaser style) · MIT license.

See `README.md` (this dir) for *why* each choice was made. This file is the *how*.

## Recipe shape

Dockerfile recipe (bake the `bd` CLI) + a `persist:` entry (host-persist `.beads/`) + an `init:`
block (`bd init --quiet --stealth` run once per project via `harnessed init`). **No MCP, no service.**

```
catalog/recipes/beads-stealth/
  recipe.yaml        # persist + init declarations
  Dockerfile         # bake the pinned bd binary; ENV BEADS_DIR=/home/harnessed/.beads
  PLAN.md  README.md
```

### recipe.yaml

```yaml
name: beads-stealth
description: bd (beads), fully invisible mode — .beads/ lives outside the repo entirely, zero git footprint.

persist:
  - name: .beads
    scope: project
    location: host

init:
  marker:
    scope: project
    location: host
    name: .beads
  run: bd init --quiet --stealth && bd-setup-agent
```

`scope: project` (git-common-dir keyed) — every worktree of a checkout shares the same `.beads/` DB.
`location: host` — harnessed manages the dir at `$XDG_DATA_HOME/harnessed/persist/beads/<project-hash>/.beads/`
and bind-mounts it at `~/.beads` inside the container (the fixed path `BEADS_DIR` points at).

The `init:` block is executed by `_run_init_for_stack()` in the launcher (auto-run on every
`harnessed launch`, also runnable explicitly via `harnessed init <stack>`). Because the marker is
the `.beads/` dir itself, and `bd init` creates that dir on success, the check is self-sealing:
after the first successful init, all subsequent launches skip it instantly.

### Dockerfile (bake `bd`)

Primary install: pinned release binary, verified against the release `checksums.txt`. Goreleaser
asset naming: `beads_<ver>_<os>_<arch>.tar.gz`. Static `ENV BEADS_DIR=/home/harnessed/.beads`
baked in (safe because the mount target is a FIXED container path, not `$PWD`-relative).

Also bakes `/usr/local/bin/bd-setup-agent`, a harness-aware wrapper resolved at build time from the
`${HARNESS}` ARG (recipe.yaml's `init.run` is one fixed string shared by every harness, so it can't
branch on `$HARNESS` at runtime). For `claude`: `bd setup claude --project --stealth`. This is
needed because `bd init --stealth` does NOT wire the SessionStart hook or CLAUDE.md section on its
own — see "Init via `harnessed init`" below.

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
ENV BEADS_DIR=/home/harnessed/.beads
```

## Build / init / test lifecycle

```bash
harnessed build claude_review-harness   # assemble + build derived image (pin gate + ENV baked in)
harnessed init  claude_review-harness   # one-time per project: bd init --quiet --stealth && bd-setup-agent
harnessed claude_review-harness         # launch; init is auto-checked and skipped (marker already exists)
harnessed test  claude_review-harness   # capability report: ✓ bd (CLI) available
```

Manual verification:
- After `harnessed init`, `$XDG_DATA_HOME/harnessed/persist/beads-stealth/<hash>/.beads/` exists on
  the host and contains `embeddeddolt/`.
- Inside the container, `echo $BEADS_DIR` returns `/home/harnessed/.beads`.
- After `harnessed init`, the project root has `.claude/settings.local.json` (SessionStart hook
  running `bd prime --stealth`) and a managed beads section in `CLAUDE.md`.
- Re-running `harnessed init` prints "already initialized" and does not touch git.
- `bd ready --json` / `bd create …` work inside the instance.
- `bd setup claude --check` reports the hook + `CLAUDE.md` section as current.

## Risks / checks

- **Single-writer:** embedded Dolt locks the file; one instance per project dir (two worktrees =
  two containers = two processes writing the same `.beads/` dir on the host — potential contention,
  as before).
- **Idempotency:** `bd init` is a no-op if `.beads/` already exists; `harnessed init` skips
  entirely if the marker dir exists before the command. `bd setup claude` is itself idempotent
  (updates its marked section rather than duplicating it), so re-running `bd-setup-agent` is safe
  even outside the marker check.
- **Stealth confirmed:** `bd init --stealth` only configures `.git/info/exclude` — it does NOT
  install hooks or touch `CLAUDE.md`/`AGENTS.md`. That's a separate `bd setup <tool> --stealth`
  call, which `bd-setup-agent` now makes (per beads' docs/SETUP.md).
- **Only `claude` wired so far:** `bd-setup-agent` no-ops for any other `${HARNESS}` (e.g. `omp`,
  which has no built-in `bd setup` recipe upstream). Add a case as new harnesses gain bd support.
