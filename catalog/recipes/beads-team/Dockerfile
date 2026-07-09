# Recipe Dockerfile for: beads-team
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads): a single native binary — local-first
# persistent task memory for agents, run here in-repo + git-tracked (Dolt-native sync via the git
# origin) on bd's SERVER storage engine, a managed per-container dolt sql-server (see recipe.yaml).
# For the fully-invisible variant (`.beads/` outside the repo, zero git footprint), see the sibling
# `beads-stealth` recipe. Installed via mise's `github:` backend — harnessed-base already ships
# mise + shims on PATH (same pattern as catalog/base/Dockerfile.harnessed-omp's `omp` install):
# mise resolves the release asset for the current arch, verifies GitHub artifact attestations, and
# lands `bd` on the mise shim PATH. Replaces a hand-rolled curl + sha256sum + tar install with one
# line and a stronger (attestation-based, not just checksum) supply-chain guarantee.
USER harnessed
# Pin to the exact release tag (no @latest / :latest / --branch — the assembler pin gate rejects
# floating refs). Also bakes the standalone `dolt` CLI (https://github.com/dolthub/dolt) alongside
# `bd` — REQUIRED for this recipe's server mode: `bd init --server` / `bd dolt start` shell out to a
# `dolt` binary on PATH to run the managed per-container `dolt sql-server`; bd's bundled Dolt is an
# embedded library only, not spawnable as a server. Pinned to 2.1.10, verified working with bd 1.1.0's
# server engine (dep add/stats/close survive a server stop/restart with dolt.auto-commit on).
ARG BEADS_VERSION=1.1.0
ARG DOLT_VERSION=2.1.10
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" "github:dolthub/dolt@${DOLT_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
# Fails the build loudly instead of at first run.
RUN bd --version && dolt version
USER root
# Welcome-message init (NO auto-init). This recipe deliberately does NOT run `bd init`/`bd setup`
# automatically — bd's setup writes into the project (`.claude/settings.json` + `CLAUDE.md` on bd
# 1.1.0) and can't be made reliably idempotent/footprint-free across every git layout, so first-time
# initialization is left to the user. recipe.yaml's SessionStart hook prints a one-time notice (gated
# on `bd list`, silent once initialized) with the exact commands to run + restart. The notice reads
# two baked hints:
#   • BEADS_INIT_HINT       — the `bd init …` line for THIS cell (static ENV, below).
#   • /etc/beads-setup-hint — the `bd setup <tool> …` line: the one harness-specific token, branched
#     on the build-time ${HARNESS} ARG so recipe.yaml never names a harness. `--project` targets the
#     writable project root (the ~/.claude profile mount is read-only).
RUN case "${HARNESS}" in \
      claude) printf 'bd setup claude --project\n' > /etc/beads-setup-hint ;; \
      *) printf 'bd setup <your-agent>   # see: bd setup --list\n' > /etc/beads-setup-hint ;; \
    esac
USER harnessed
# The `bd init …` line for the TEAM cell (in-repo, git-tracked, managed per-container dolt server).
# `bd init --server` installs git hooks + auto-wires the git origin as a Dolt remote; auto-commit on
# persists every write (incl. dependency edges, which are NOT in issues.jsonl) to the Dolt store.
ENV BEADS_INIT_HINT="bd init --server --quiet --non-interactive --role maintainer && bd config set dolt.auto-commit on"
# No static BEADS_DIR ENV: `.beads/` lives inside the work tree (persist: location: in_repo); bd's
# own discovery finds it for a normal repo. In a bare + linked-worktree layout, run `bd` from the
# default-branch work tree (or set BEADS_DIR to that work tree's `.beads`).
