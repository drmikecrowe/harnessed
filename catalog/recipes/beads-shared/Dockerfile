# Recipe Dockerfile for: beads-shared
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads), configured by this recipe's init to talk
# to the SHARED `beads-server` service (an external, externally-managed `dolt sql-server`) rather
# than a per-container Dolt engine (bead main-8by). Installed via mise's `github:` backend — the same
# attestation-verified, pinned install the `beads` recipe uses. `dolt` is baked alongside `bd`: bd's
# external-server mode connects to the remote server as a client, and `bd dolt push`/`pull`
# (refs/dolt/data git sync) shell out to a `dolt` binary on PATH. Pinned to the SAME versions the
# `beads` recipe verifies (bd 1.1.0 + dolt 2.1.10) so both variants share one proven toolchain.
USER harnessed
ARG BEADS_VERSION=1.1.0
ARG DOLT_VERSION=2.1.10
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" "github:dolthub/dolt@${DOLT_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
RUN bd --version && dolt version
USER root

# Bare + linked-worktree support (bd-resolve-beads-dir, sourced by init.run — see recipe.yaml).
# Identical to the `beads` recipe: default-mode `bd` anchors `.beads` to the git common dir, which is
# the BARE repo (no work tree) in a bare + linked-worktree layout; this helper points BEADS_DIR at
# the real default-branch work tree instead, or exits non-zero so init.run aborts rather than
# misplacing the DB. A normal repo prints nothing (bd's own discovery is correct).
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

# Harness-aware `bd setup` wrapper (${HARNESS} is a build-time ARG) — same as the `beads` recipe.
# `bd init` installs git hooks + wires the Dolt remote, but wiring the SessionStart hook + minimal
# CLAUDE.md/AGENTS.md section is a SEPARATE `bd setup <tool>` step (beads docs/SETUP.md). `--project`
# writes .claude/settings.local.json into the bind-mounted project root (writable), not the
# read-only ~/.claude profile mount.
RUN case "${HARNESS}" in \
      claude) printf '#!/bin/sh\nexec bd setup claude --project\n' > /usr/local/bin/bd-setup-agent ;; \
      *) printf '#!/bin/sh\n# no bd setup recipe for harness "%s" yet (see beads docs/SETUP.md)\n' "${HARNESS}" > /usr/local/bin/bd-setup-agent ;; \
    esac; \
    chmod +x /usr/local/bin/bd-setup-agent
USER harnessed
# No static BEADS_DIR ENV: `.beads/` lives inside a work tree (persist: location: in_repo). init.run
# resolves BEADS_DIR at attach time for the bare + linked-worktree case; a normal repo relies on bd's
# own discovery.
