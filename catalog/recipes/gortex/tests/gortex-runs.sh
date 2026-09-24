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
# Capture explicitly: under `set -e` a failing substitution in an assignment aborts the script
# with no message, and the capability report shows only this script's stderr as the one-line
# failure detail — so the reason must be printed here, not left on the cutting room floor.
if ! version_output="$(gortex version 2>&1)"; then
    echo "gortex version failed to run: ${version_output}" >&2
    exit 1
fi
echo "gortex version -> ${version_output}"
# Anchor to "gortex" ADJACENT TO A VERSION, not a bare substring: a bare grep would pass on any
# line mentioning the name, including mise's "ERROR No version is set for shim: gortex" — the
# exact broken-shim failure mode (#449) this check exists to catch.
if ! grep -Eqi 'gortex[^0-9]*[0-9]+\.[0-9]+' <<<"${version_output}"; then
    echo "gortex version did not identify as gortex with a version: ${version_output}" >&2
    exit 1
fi

# The three contexts this runs in hand the script different env: install-time (container +
# host) exports HARNESSED_CONFIG_DIR; the live `harnessed test` exec does not, but the pod
# exports CLAUDE_CONFIG_DIR and $HOME/.claude is the container default — so resolve in that
# order. CONTAINER_HOME is never read (S-15/S-20).
#
# All three names resolve to the SAME tree, by construction rather than by assumption:
# install.sh wrote into $HARNESSED_CONFIG_DIR, which emit.install_env derives from the same
# per-harness config-dir variable the launcher exports as CLAUDE_CONFIG_DIR inside the pod, and
# the container's $HOME/.claude is that same dir (the assembled profile mounts there). If those
# ever diverge, checks 2 and 3 below read the wrong tree and fail loudly — a false PASS would
# need a second settings.json that independently carries a `gortex hook` line.
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
# The grep matches the EMITTED command entry, not a bare substring: the assembler writes this
# file fresh, so a loose grep could pass on the string appearing in some unrelated field while
# the hooks block itself was dropped (the failure mode this check guards). Key-value adjacency
# with spacing-tolerant separators, not a byte-exact literal — that stays true across
# json.dumps separator changes while still refusing a mention anywhere else in the file.
if ! grep -Eq '"command"[[:space:]]*:[[:space:]]*"gortex hook"' "${settings}"; then
    echo "gortex hook command missing from ${settings} — the agent will never be steered at the graph" >&2
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
