# Recipe Dockerfile for: codebase-memory-mcp (cbm)
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# cbm is a static C binary with zero runtime deps (158 tree-sitter grammars + Hybrid LSP compiled
# in, embedded SQLite) — it needs nothing from the base image's node/pnpm/python/uv. This replicates
# ONLY the binary-extract step of upstream's "Manual install"; do NOT run cbm's own installer
# (scripts/setup.sh / the `install` command), which auto-configures 11 agents (writes .mcp.json,
# skills, hooks, AGENTS.md) — harnessed owns all of that.
#
# Installed via mise's `github:` backend (harnessed-base already ships mise + shims on PATH — same
# pattern as the beads recipe): mise resolves the standard (non-`-portable`) asset for the current
# arch and verifies GitHub artifact attestations.
USER harnessed
# The release tags carry a `v` prefix (v0.9.0); mise's github: backend resolves the bare version
# against them. Linux amd64/arm64 assets both ship at this tag.
ARG CBM_VERSION=0.9.0
RUN mise use -g "github:DeusData/codebase-memory-mcp@${CBM_VERSION}" && mise install
