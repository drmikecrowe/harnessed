# Recipe Dockerfile for: agent-carnet
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# WHAT'S LEFT HERE, AND WHY. This recipe's SKILL now installs via `install.sh` (see `install:` in
# recipe.yaml), which runs in BOTH modes — that was the half broken on `--host` (bd harnessed-8px.1).
# What remains below is the CLI itself, and it stays container-only on purpose: a host launch runs
# install.sh against the user's real machine, where `pnpm add -g` would write into their global pnpm
# store, outside every harnessed-owned directory. Putting `agent-carnet` on PATH host-side is
# `provision:`'s job (bd harnessed-zi6.1), not the install script's.
#
# agent-carnet is a pure-JS Node CLI bundled to dist/bin/agent-carnet.mjs — no native binary release,
# so the pnpm global install is the ONLY install path (the published tarball already ships dist/, so
# no build scripts are needed). Pure JS means no apt/system deps, so the whole body runs as the
# unprivileged user — no USER root needed.
USER harnessed
# Pin to the exact published version (no @latest — the assembler pin gate rejects floating refs).
# Keep this in lockstep with AGENT_CARNET_VERSION in install.sh and `install.cache` in recipe.yaml:
# one npm artifact is both the CLI pin and the skill pin. pnpm only; the emit lint rejects raw npm/npx.
ARG AGENT_CARNET_VERSION=0.1.5
RUN pnpm add -g agent-carnet@${AGENT_CARNET_VERSION}
# Verify the global bin resolves on PATH for the harnessed user before the layer is trusted.
RUN agent-carnet --version
