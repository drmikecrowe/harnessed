#!/usr/bin/env bash
# Behavioral capability test for the gortex recipe.
#
# Runs (a) right after install.sh in the container build, (b) after the host install on every
# host launch, and (c) in the live instance via `harnessed test`. Contract: exit 0 == pass.
# Mode-agnostic by construction: $HARNESSED_CONFIG_DIR is guaranteed in both modes
# (emit.install_env) and CONTAINER_HOME is never read (S-15/S-20).
set -euo pipefail

# 1. The binary must resolve, run, and identify as gortex — guards a wrong-asset or empty
#    install from the `github:` tools: backend before anything else is trusted.
if ! command -v gortex >/dev/null 2>&1; then
    echo "gortex not found on PATH" >&2
    exit 1
fi
version_output="$(gortex version 2>&1)"
echo "gortex version -> ${version_output}"
if ! grep -qi 'gortex' <<<"${version_output}"; then
    echo "gortex version did not identify as gortex: ${version_output}" >&2
    exit 1
fi

# The three contexts this runs in hand the script different env: install-time (container +
# host) exports HARNESSED_CONFIG_DIR; the live `harnessed test` exec does not, but the pod
# exports CLAUDE_CONFIG_DIR and $HOME/.claude is the container default — so resolve in that
# order. CONTAINER_HOME is never read (S-15/S-20).
config="${HARNESSED_CONFIG_DIR:-${CLAUDE_CONFIG_DIR:-${HOME}/.claude}}"

# 2. The wiring must be baked. The hook is the enforcement half of this recipe: without it
#    nothing steers the agent at the graph tools, and the failure is silent (the tools connect
#    and simply go unused — rtk measured that mode at a 0.06% delivery rate). Checked against
#    the ASSEMBLED settings.json, because the assembler regenerates that file after install.sh
#    and is the half that can silently drop the hook.
settings="${config}/settings.json"
if [[ ! -f "${settings}" ]]; then
    echo "settings.json not found at ${settings}" >&2
    exit 1
fi
if ! grep -q 'gortex hook' "${settings}"; then
    echo "gortex hooks missing from ${settings} — the agent will never be steered at the graph" >&2
    exit 1
fi

# 3. A representative slice of `gortex install` output: one skill and one command. (The
#    presence oracle in expect: covers five skills; this re-checks in the install-time contexts
#    where expect: does not run.)
if [[ ! -f "${config}/skills/gortex-guide/SKILL.md" ]]; then
    echo "gortex-guide skill missing from ${config}/skills" >&2
    exit 1
fi
if [[ ! -f "${config}/commands/gortex-guide.md" ]]; then
    echo "gortex-guide command missing from ${config}/commands" >&2
    exit 1
fi

# Deliberately NOT probed here: the daemon. Install time has no project, a host launch reuses
# the user's own daemon, and starting one from a test would race init.run. Daemon health is
# proven transitively by expect: mcp in `harnessed test` (the MCP child exits without one).
echo "gortex binary runs, its hooks are wired, and its skills are baked"
