# Recipe Dockerfile for: beads-team-server
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads), configured by this recipe's init to talk
# to the SHARED `beads-server` service (an external, externally-managed `dolt sql-server`) rather
# than a per-container Dolt engine (bead main-8by). Installed via mise's `github:` backend — the same
# attestation-verified, pinned install the `beads-team` recipe uses. `dolt` is baked alongside `bd`: bd's
# external-server mode connects to the remote server as a client, and `bd dolt push`/`pull`
# (refs/dolt/data git sync) shell out to a `dolt` binary on PATH. Pinned to the SAME versions the
# `beads-team` recipe verifies (bd 1.1.0 + dolt 2.1.10) so both variants share one proven toolchain.
USER harnessed
ARG BEADS_VERSION=1.1.0
ARG DOLT_VERSION=2.1.10
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" "github:dolthub/dolt@${DOLT_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
RUN bd --version && dolt version
USER root
# Welcome-message init (NO auto-init) — same rationale as `beads-team`. recipe.yaml's SessionStart
# hook prints a one-time notice (gated on `bd list`) with the exact first-init commands + restart.
# /etc/beads-setup-hint = the `bd setup <tool> …` line, branched on the build-time ${HARNESS} ARG so
# recipe.yaml stays harness-independent. `--project` targets the writable project root (~/.claude is
# a read-only profile mount); on bd 1.1.0 that lands `.claude/settings.json` + `CLAUDE.md`.
RUN case "${HARNESS}" in \
      claude) printf 'bd setup claude --project\n' > /etc/beads-setup-hint ;; \
      *) printf 'bd setup <your-agent>   # see: bd setup --list\n' > /etc/beads-setup-hint ;; \
    esac
USER harnessed
# The `bd init …` line for the TEAM-SERVER cell (in-repo, git-tracked, SHARED beads-server service).
ENV BEADS_INIT_HINT="bd init --server --external --server-host host.containers.internal --server-port 3307 --quiet --non-interactive --role maintainer && bd config set dolt.auto-commit on"
# No static BEADS_DIR ENV: `.beads/` lives inside the work tree (persist: location: in_repo); bd's
# own discovery finds it for a normal repo. In a bare + linked-worktree layout, run `bd` from the
# default-branch work tree (or set BEADS_DIR to that work tree's `.beads`).
