# Recipe Dockerfile for: beads
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads): a single native binary that bundles
# embedded Dolt — local-first persistent task memory for agents, run here in beads' DEFAULT
# operational mode (in-repo, git-tracked, Dolt-native sync via the git origin — see recipe.yaml).
# For the fully-invisible variant (`.beads/` outside the repo, zero git footprint), see the sibling
# `beads-stealth` recipe. Installed via mise's `github:` backend — harnessed-base already ships
# mise + shims on PATH (same pattern as catalog/base/Dockerfile.harnessed-omp's `omp` install):
# mise resolves the release asset for the current arch, verifies GitHub artifact attestations, and
# lands `bd` on the mise shim PATH. Replaces a hand-rolled curl + sha256sum + tar install with one
# line and a stronger (attestation-based, not just checksum) supply-chain guarantee.
USER harnessed
# Pin to the exact release tag (no @latest / :latest / --branch — the assembler pin gate rejects
# floating refs). Also bakes the standalone `dolt` CLI (https://github.com/dolthub/dolt) alongside
# `bd` — bd bundles Dolt as an embedded library for its own DB, but the standalone binary is useful
# for ad-hoc inspection/repair of `.beads/`'s Dolt store directly.
ARG BEADS_VERSION=1.1.0
ARG DOLT_VERSION=2.1.10
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" "github:dolthub/dolt@${DOLT_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
# Fails the build loudly instead of at first run.
RUN bd --version && dolt version
USER root
# Bare + linked-worktree support (bd-resolve-beads-dir + profile.d).
#
# Default-mode `bd` anchors its shared `.beads` to the git "main repository" = the common dir. In a
# bare + linked-worktree layout (a `.bare` repo with sibling worktrees) that common dir is the BARE
# repo, which has NO work tree — so `.beads` lands where it can't be committed and auto-export's
# `git add` fails ("must be run in a work tree"). This helper detects that case and points BEADS_DIR
# at the real work tree checked out to the bare repo's default branch instead. A normal repo prints
# nothing (bd's own discovery is correct). A bare repo with no work tree on its default branch exits
# non-zero so `init.run` aborts (see recipe.yaml) rather than silently misplacing the DB.
COPY <<'SH' /usr/local/bin/bd-resolve-beads-dir
#!/bin/sh
set -eu
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
[ "$(git --git-dir="$common" rev-parse --is-bare-repository 2>/dev/null)" = "true" ] || exit 0
head=$(git --git-dir="$common" symbolic-ref --short HEAD 2>/dev/null) || head=
wt=
if [ -n "$head" ]; then
  wt=$(git --git-dir="$common" worktree list --porcelain 2>/dev/null \
    | grep -B2 "^branch refs/heads/$head$" | sed -n 's/^worktree //p' | head -n1)
fi
if [ -z "$wt" ]; then
  echo "bd-resolve-beads-dir: bare repo $common has no work tree on '${head:-detached}'; set BEADS_DIR manually" >&2
  exit 1
fi
printf '%s/.beads\n' "$wt"
SH
RUN chmod +x /usr/local/bin/bd-resolve-beads-dir
# Export BEADS_DIR for every login shell (the agent's `bash -l -c` attach AND the init container's
# `bash -lc`), resolved from the current work tree so it's correct regardless of the mount path.
# Respects an existing BEADS_DIR (user override) and stays silent for normal repos.
COPY <<'SH' /etc/profile.d/beads-dir.sh
if [ -z "${BEADS_DIR:-}" ] && command -v bd-resolve-beads-dir >/dev/null 2>&1; then
  _bd_dir=$(bd-resolve-beads-dir 2>/dev/null) || _bd_dir=
  [ -n "$_bd_dir" ] && export BEADS_DIR="$_bd_dir"
  unset _bd_dir
fi
SH
# Bake a harness-aware `bd setup` wrapper. `bd init` (default mode) already installs git hooks and
# auto-wires the git origin as a Dolt remote — but per beads' own docs/SETUP.md, wiring the
# SessionStart hook + minimal CLAUDE.md/AGENTS.md section is a SEPARATE step: `bd setup <tool>`.
# recipe.yaml's `init.run` is one fixed string shared by every harness a stack might use, so it
# can't branch on $HARNESS at runtime — this is the one place that may (per the
# harness-independent-recipes convention): ${HARNESS} is a build-time ARG, resolved once here into
# a tiny wrapper on PATH.
#
# --project (not global): ~/.claude/settings.json inside the container is harnessed's own read-only
# profile mount (see launcher.py's settings.json bind-mount) — bd can't write hooks there. `--project`
# writes .claude/settings.local.json into the bind-mounted project root instead, which is writable
# and persists on the host (git-tracked, like the rest of `.beads/` in this recipe's default mode).
RUN case "${HARNESS}" in \
      claude) printf '#!/bin/sh\nexec bd setup claude --project\n' > /usr/local/bin/bd-setup-agent ;; \
      *) printf '#!/bin/sh\n# no bd setup recipe for harness "%s" yet (see beads docs/SETUP.md)\n' "${HARNESS}" > /usr/local/bin/bd-setup-agent ;; \
    esac; \
    chmod +x /usr/local/bin/bd-setup-agent
USER harnessed
# No STATIC BEADS_DIR ENV here (unlike beads-stealth, whose mount target is a fixed path): `.beads/`
# lives INSIDE a work tree (persist: location: in_repo — see recipe.yaml). For a normal repo bd's
# own discovery finds it; for a bare + linked-worktree repo the profile.d script above computes
# BEADS_DIR dynamically (→ the default-branch work tree's `.beads`). A static ENV would be wrong the
# moment the project mount path changed, so the value is resolved at shell start, not baked.
