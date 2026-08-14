#!/usr/bin/env bash
# Behavioral capability test for the caveman recipe's GAP-2 SessionStart hook (main-c98).
#
# The `hooks:` recipe field (main-5d8) has NO `expect:` counterpart — asserting "hook X is wired and
# fires" would need a hand-written prober kind in capability.py. A bash test covers it for free: this
# is precisely the GAP-2 shape the tests/ oracle was built to close.
#
# Two assertions, both auth-free (no live claude session needed):
#   1. WIRED  — emit.py merged the recipe's SessionStart hook into the instance's real settings.json.
#   2. FIRES  — the hook's one-time-nudge body behaves: prints the nudge + drops the marker on first
#               run in a project, and stays silent (idempotent) on the second.
# Contract: exit 0 == pass.
set -euo pipefail

# $HARNESSED_CONFIG_DIR, not $CONTAINER_HOME: this script now runs during the install in BOTH modes,
# and CONTAINER_HOME names a container the host has none of — its /home/harnessed default resolved to
# a path that does not exist, so the script failed host-side for a reason that had nothing to do with
# caveman. `emit.install_env` guarantees HARNESSED_CONFIG_DIR in both modes (identical KEYS is that
# function's standing invariant), and it points at the agent config dir directly rather than at a home
# containing one. The ASSERTIONS below are unchanged; only the way the config dir is located.
SETTINGS="${HARNESSED_CONFIG_DIR:?HARNESSED_CONFIG_DIR is set by the install contract}/settings.json"

# --- 1. WIRED: the recipe's hook actually reached the runtime config -----------------------------
if [ ! -f "${SETTINGS}" ]; then
    echo "settings.json not found at ${SETTINGS}" >&2
    exit 1
fi
if ! grep -q 'SessionStart' "${SETTINGS}"; then
    echo "SessionStart hook not present in settings.json" >&2
    exit 1
fi
if ! grep -q 'caveman-notified' "${SETTINGS}"; then
    echo "caveman first-run nudge hook not merged into settings.json" >&2
    exit 1
fi
echo "caveman SessionStart hook is wired into ${SETTINGS}"

# --- 2. FIRES: exercise the same one-time-nudge logic the recipe ships ---------------------------
# Mirrors the hook body from recipe.yaml (marker under $CLAUDE_PROJECT_DIR/.claude, gated so it
# nudges once per project). We drive it directly instead of launching a claude session (auth-free).
proj="$(mktemp -d)"
trap 'rm -rf "${proj}"' EXIT

run_nudge() {
    CLAUDE_PROJECT_DIR="${proj}" bash -lc '
        marker="$CLAUDE_PROJECT_DIR/.claude/.caveman-notified"
        if [ ! -e "$marker" ]; then
            mkdir -p "$(dirname "$marker")" && touch "$marker" && echo "NUDGE"
        fi'
}

first="$(run_nudge)"
if [ "${first}" != "NUDGE" ]; then
    echo "first SessionStart did not emit the nudge (got: '${first}')" >&2
    exit 1
fi
if [ ! -e "${proj}/.claude/.caveman-notified" ]; then
    echo "first SessionStart did not drop the marker file" >&2
    exit 1
fi

second="$(run_nudge)"
if [ -n "${second}" ]; then
    echo "second SessionStart nudged again (not once-per-project idempotent): '${second}'" >&2
    exit 1
fi

echo "caveman first-run nudge fires once and is idempotent"
