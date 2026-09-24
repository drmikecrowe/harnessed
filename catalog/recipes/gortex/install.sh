#!/usr/bin/env bash
# install.sh — gortex's user-level agent wiring, baked into the stack config dir (both modes).
#
# This runs upstream's own per-machine installer (`gortex install`), not a hand-rolled copy of
# its output: the skill/command/agent bodies are embedded in the binary, so replicating them in
# this repo would fork 40+ files that drift the moment the pin moves. Constrained so every
# write lands in harnessed-owned space (see flags below); measured against v0.64.5.
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_HOME_SHIM
# PROJECT_DIR and friends are absent by design — a build has no project. The daemon and repo
# registration cannot happen here (install is fingerprint-gated, once per stack, and its
# exports die with the subprocess); that is init.run's job at attach time.
set -euo pipefail

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# --- 1. the binary: NOT here -----------------------------------------------------------------------
# `tools: [github:zzet/gortex@…]` owns it (rtk pattern, bd harnessed-1t4.3) — mise's github:
# release install runs in both modes on harnessed's own config/data dirs. This guard fails the
# install if `tools:` delivered nothing runnable, before the wiring below bakes a profile that
# references a binary that does not exist — with a named cause, not bash's bare "command not
# found". `gortex version` is a SUBCOMMAND at this pin — cobra rejects `--version` (caught by a
# real build; the flag form dies with "unknown flag").
if ! command -v gortex >/dev/null 2>&1; then
    echo "install.sh: gortex not on PATH — the tools: (github:zzet/gortex@…) layer delivered nothing runnable" >&2
    exit 1
fi
gortex version

# --- 2. the wiring ----------------------------------------------------------------------------------
# --agents=claude-code   recipes never name harnesses; every harness consumes the same
#                         Claude-canonical profile, and this adapter writes exactly that shape
#                         (skills/commands/agents + settings). It is also what keeps the other
#                         19 adapters' user-level files (~/.codex/, ~/.copilot/, …) unwritten.
# --no-hooks             hooks are declared in recipe.yaml `hooks:`, because the assembler
#                         regenerates settings.json AFTER this script and would silently drop
#                         an installer-written hook (rtk measured that at 0.06% delivery).
#                         Writing them in both places would double-fire.
# --no-claude-md         the identity CLAUDE.md is assembler-rendered per stack; the same
#                         workflow text rides every MCP initialize response and the gortex-*
#                         skills already baked by this run.
# --claude-config-dir    writes INSIDE the given root (verified v0.64.5), i.e. straight into
#                         the profile. The .claude.json MCP stanza it drops there is inert:
#                         Claude Code reads ~/.claude.json at $HOME root, and harnessed's MCP
#                         wiring (hatago / native .mcp.json) owns the real server list anyway.
#
# HOME pinned to the shim so any write the adapter still resolves against $HOME lands in
# harnessed-owned space, never the user's real home (the rtk `rtk init -g` lesson). The pin is
# PER-INVOCATION: only the `gortex install` below runs shimmed — `gortex version` above is
# read-only at this pin and deliberately unshimmed. A future edit adding another gortex call
# here must re-pin HOME on it or the containment contract silently stops holding.
# Idempotent: upstream skips byte-identical files, so the every-launch host re-run is cheap.
HOME="${HARNESSED_HOME_SHIM:?install.sh requires HARNESSED_HOME_SHIM}" gortex install \
    --agents=claude-code \
    --no-hooks \
    --no-claude-md \
    --claude-config-dir "${HARNESSED_CONFIG_DIR}"
