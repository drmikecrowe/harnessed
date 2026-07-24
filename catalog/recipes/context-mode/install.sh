#!/usr/bin/env bash
# install.sh — context-mode CLI (host) + omp plugin (container+omp only).
#
# Two deliverables, both formerly separate channels:
#   1. context-mode CLI/MCP binary — container: `tools:` (mise npm backend); host: this script.
#   2. omp extension — container+omp only: `omp plugin install` (see omp section below).
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE
#   HARNESSED_BIN_DIR  the stack bin dir (host) or base image ~/.local/bin (container)
# PROJECT_DIR and friends are absent by design — a build has no project mounted.
#
# Keep CONTEXT_MODE_VERSION in lockstep with the `tools:` pin in recipe.yaml and the
# `omp plugin install` version below — all three install the same upstream package.
set -euo pipefail

CONTEXT_MODE_VERSION="1.0.169"

# --- CLI install: NOT here -----------------------------------------------------------------------
# `tools: [npm:context-mode@…]` delivers the CLI in BOTH modes now (bd harnessed-1t4.3). It used to
# cover the container only, so this script carried a host-mode `pnpm add -g` branch; a host launch
# applies the same pinned tool spec, so that branch is gone rather than duplicated.

# --- omp only -------------------------------------------------------------------------------------
# Under omp the bridged Claude hooks are inert (omp-claude-hooks-bridge drops
# hookSpecificOutput.additionalContext, so the PreToolUse routing nudge and the SessionStart context
# re-injection never reach the model, and it maps no omp event to PreCompact at all). recipe.yaml's
# `hooks.skip_harnesses: [omp]` therefore suppresses them, and upstream's own omp extension —
# installed below — takes over, covering session_start / tool_call / tool_result /
# session_before_compact natively. Every other harness uses the hooks and needs nothing here.
if [ "${HARNESS:-}" != "omp" ]; then
    exit 0
fi

# --- container only, and LOUD about it --------------------------------------------------------------
# `omp plugin install` writes into ~/.omp/plugins. Container-side that is an image layer, and it
# SURVIVES launch because the launcher bind-mounts only ~/.omp/agent over it (launcher._omp_agent_mount)
# — the same path Dockerfile.harnessed-omp uses for the hooks bridge itself.
#
# Host-side the same command would write into the USER'S OWN omp installation. That is not harnessed's
# to mutate: ~/.omp is deliberately SHARED host state on a host launch (omp keeps auth, usage, and
# sessions together there, which is why the launcher mounts it read-WRITE rather than isolating it),
# there is no per-stack omp plugin root to redirect the install into, and anything installed would
# persist after the stack is gone — a write outside $HARNESSED_CONFIG_DIR and outside the install
# cache, i.e. exactly the class of side effect a host launch must not have. So: skipped on host, and
# announced. Never silently (bd harnessed-8px.1).
#
# Consequence, stated plainly: `harnessed launch --host` with HARNESS=omp gets context-mode's MCP
# server and CLI (via install.sh above) but NOT the native omp extension, so the four omp-native
# event handlers are absent in that combination. Run the stack in a container to get them.
if [ "${HARNESSED_MODE:-}" != "container" ]; then
    echo "WARNING install (context-mode): 'omp plugin install context-mode@${CONTEXT_MODE_VERSION}'" \
         "SKIPPED on a host launch — it writes into your own ~/.omp/plugins, which harnessed does" \
         "not own or mutate. Run this stack in a container to get the native omp extension." >&2
    exit 0
fi

omp plugin install "context-mode@${CONTEXT_MODE_VERSION}"
