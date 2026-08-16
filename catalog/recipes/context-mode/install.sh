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
# The version is NOT declared in this file (AC-1). `tools:` in recipe.yaml owns it and the one use
# below derives it from mise, so the "keep these in lockstep" comment this replaces is gone, and
# with it the drift it invited — #323 is the same shape in another recipe.
set -euo pipefail

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
    echo "WARNING install (context-mode): 'omp plugin install context-mode@<tools: pin>'" \
         "SKIPPED on a host launch — it writes into your own ~/.omp/plugins, which harnessed does" \
         "not own or mutate. Run this stack in a container to get the native omp extension." >&2
    exit 0
fi

# Derived HERE, at the ONLY point of use — not at the top of the script. Deriving it up front made
# every harness and both modes depend on mise being present, including the two paths that never
# install the plugin at all. The tests caught that immediately.
#
# `mise current <tool>` prints the resolved version alone: no jq (the base image ships none) and no
# column parsing. FAIL CLOSED on empty — for a tool it does not know, mise warns to stderr, prints
# NOTHING and exits 0, so an unguarded read would run `omp plugin install context-mode@` and leave
# omp to interpret that. Silence must not become an empty version.
CONTEXT_MODE_VERSION="$(mise current npm:context-mode 2>/dev/null || true)"
if [ -z "${CONTEXT_MODE_VERSION}" ]; then
    echo "error: install (context-mode): mise reports no installed version for npm:context-mode." \
         "The 'tools:' entry in recipe.yaml is what installs it — the omp plugin cannot be pinned" \
         "without it." >&2
    exit 1
fi

omp plugin install "context-mode@${CONTEXT_MODE_VERSION}"

# --- VERIFY it landed -----------------------------------------------------------------------------
# `omp plugin install` exiting 0 is not proof the extension is present, and a half-installed one is
# INVISIBLE downstream: recipe.yaml's `hooks.skip_harnesses: [omp]` suppresses the bridged Claude
# hooks precisely BECAUSE this extension replaces them, so if it is missing, context-mode runs with
# its MCP server and none of its four native handlers — no routing steering, no session continuity.
#
# Nothing else catches that. `expect:` cannot: `expect.plugins` probes ~/.claude/plugins (Claude
# plugins), not ~/.omp/plugins, and `expect: mcp: [context-mode]` only proves the hub connected,
# which it does either way. Observed live in an omp pod whose `omp plugin list` carried only the
# hooks bridge while `harnessed test` stayed green.
#
# Pure-shell `case` rather than grep/rg: the base image ships neither reliably (same reason the
# version read above avoids jq).
INSTALLED_PLUGINS="$(omp plugin list 2>/dev/null || true)"
case "${INSTALLED_PLUGINS}" in
    *context-mode*) ;;
    *)
        echo "error: install (context-mode): 'omp plugin install" \
             "context-mode@${CONTEXT_MODE_VERSION}' reported success but the plugin is ABSENT from" \
             "'omp plugin list'. Its four omp-native handlers (session_start / tool_call /" \
             "tool_result / session_before_compact) would be silently missing, and the bridged" \
             "Claude hooks are suppressed on omp by design, so the recipe would deliver its MCP" \
             "server with no steering and no session continuity." >&2
        exit 1
        ;;
esac
