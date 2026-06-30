# beads recipe — implementation plan

Goal: make `bd` (beads) available in a stack as **local-first, git-free** persistent task memory,
with `.beads/` living in the user's project folder and zero git side effects.

Upstream: <https://github.com/gastownhall/beads> · npm `@beads/bd` (latest 1.0.5, MIT, native
binary bundling embedded Dolt).

See `README.md` (this dir) for *why* each choice was made. This file is the *how*.

## Recipe shape

Dockerfile recipe (bake the `bd` CLI) + a `new-session` hook that inits the DB. **No MCP, no
service** — beads is a CLI, not an MCP server.
**No skill is shipped:** upstream `bd` offers no standalone Claude skill (it mutates `AGENTS.md`,
which `--stealth` suppresses), so the recipe authors none — the agent runs `bd` directly; a user
may add a skill later.

```
catalog/recipes/beads/
  recipe.yaml
  Dockerfile            # bake the pinned bd binary
  hooks/
    new-session.sh      # bd init --quiet --stealth (runs once, when .beads/ is absent)
  PLAN.md  README.md
```

### recipe.yaml

```yaml
name: beads
description: bd (beads) — local-first, git-free graph issue tracker / persistent task memory for agents.
hooks:
  new_session:
    script: hooks/new-session.sh
    when_missing: .beads     # fire only when the project has no .beads/ yet
```

> `hooks.new_session` depends on the **startup-hooks** feature
> (`docs/todos/2026-06-29-startup-hooks.md`). If that feature is not yet built, the agent has the
> `bd` CLI available and runs `bd init` itself on first use (see "Phasing").

### Dockerfile (bake `bd`)

Primary decision — see README "Install & pinning". Two viable paths; **recommended: pinned release
binary + checksum verify** (deterministic, matches beads' own security guidance, avoids pnpm
postinstall fragility). npm path documented as the alternative.

Sketch (binary path — fill in the pinned version, arch detection, and checksum verify against the
release `checksums.txt`):

```dockerfile
USER root
ARG BEADS_VERSION=1.0.5
# Download the pinned release tarball for the target arch, VERIFY against checksums.txt, install bd
# to /usr/local/bin. Pin to the exact tag (no :latest / @latest / --branch — assembler rejects them).
RUN set -euo pipefail; \
    arch="$(uname -m)"; \
    # … map arch → release asset name, curl -fsSL the vN.N.N asset + checksums.txt, \
    # sha256sum -c, install bd to /usr/local/bin, chmod +x …
USER harnessed
```

Alternative (npm path): `RUN pnpm add -g @beads/bd@${BEADS_VERSION}` as `USER harnessed`.
**Verify** the native binary actually lands — pnpm may skip the package's postinstall
(binary-fetch) step; allow build scripts for `@beads/bd` if so, and confirm `pnpm` global bin is on
`PATH` for the `harnessed` user. (`emit` lint rejects raw `npm`/`npx` — use `pnpm`.)

### hooks/new-session.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
# Runs once, in the mounted project dir ($PWD = project root), the first time this project is opened
# (when .beads/ is absent). Git-free + stealth: .beads/ lives in the project folder, no git hooks,
# no commits, no repo discovery. Idempotent — bd init is a no-op if .beads/ already exists.
export BEADS_DIR="$PWD/.beads"
bd init --quiet --stealth
```

## Test stack

```yaml
# catalog/stacks/claude_beads/stack.yaml
name: claude_beads
harness: claude
recipes: [beads]
```

## Build / test lifecycle

```bash
harnessed build claude_beads   # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_beads         # launch; new-session hook runs `bd init --stealth` in the project
harnessed test  claude_beads   # capability report: ✓ bd (CLI) available
```

Manual verification (no skill is asserted — verify the *behavior* directly):

- After launch against a fresh project dir, `.beads/` exists in that dir on the **host** (persists
  via the project bind-mount), and contains `embeddeddolt/`.
- Re-launching the same project does NOT re-init (sentinel present) and does not touch git
  (`git status` clean; no hooks installed; the user's `AGENTS.md` untouched — `--stealth` skips it).
- `bd ready --json` / `bd create … ` work inside the instance with zero git calls.

## Phasing

1. **If startup-hooks is built:** ship recipe.yaml + Dockerfile + `hooks/new-session.sh`.
   Init is automatic and deterministic.
2. **If not yet:** ship recipe.yaml (no `hooks:`) + Dockerfile only; the agent has the `bd` CLI
   available and runs `bd init --quiet --stealth` (with `BEADS_DIR="$PWD/.beads"`) itself on first
   use, or the user adds workflow guidance later. Add the hook once the feature lands.

## Risks / checks

- **Install determinism:** confirm the chosen install path produces a runnable `bd` and passes the
  assembler pin gate (no floating refs). This is the main build risk — resolve at `harnessed build`.
- **Concurrency:** embedded mode is single-writer (file lock). Fine for one instance per project;
  two instances on the same project dir will contend.
- **Stealth correctness:** verify `--stealth` truly suppresses git hook installation and AGENTS.md
  mutation in a project that *is* a git repo (the mounted project usually has `.git`).
