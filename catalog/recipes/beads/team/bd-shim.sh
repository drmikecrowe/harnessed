#!/usr/bin/env bash
# bd — harnessed's workspace-resolving wrapper around the real `bd`.
#
# WHY THIS EXISTS. The recipe exports `BEADS_DIR` (and the launcher exports the beads-server
# connection vars) into the attach shell, resolved ONCE against the project harnessed was launched
# in. `bd` reads them on every invocation, which is exactly what makes it CWD-independent for
# harnesses that start the agent in $HOME (harnessed-b0s). But one harness PROCESS can host sessions
# in several projects — Claude Code's session switcher does precisely this — and every one of them
# inherits the launch project's absolute paths. Observed 2026-07-26: `bd list` in a session opened in
# project B listed project A's issues, silently, because BEADS_DIR still pointed at A.
#
# So the launch values become a FALLBACK rather than the answer: this shim re-resolves the workspace
# from $PWD on every call, and only when $PWD is in a different repository than the one harnessed
# launched in.
#
# THE HONESTY RULE. Retargeting `BEADS_DIR` alone would be worse than the bug: bd would read project
# B's metadata while still connected to project A's dolt server. So a foreign project is only
# retargeted when all three of its pieces are provable — the .beads dir, the sidecar's published
# port, and the sidecar's password. If any is missing this exits non-zero with what to do about it.
# It never falls back to "close enough", because the failure mode of a wrong beads connection is
# writing issues into someone else's database (BEADS.md §10).
set -euo pipefail

shim_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

# The real bd is whatever PATH resolves to once our own dir is out of the way. Resolving it by
# search rather than a baked path keeps the shim correct when mise moves its shims.
filtered=""
saved_ifs=${IFS:-}
IFS=:
for d in $PATH; do
    [ "$d" = "$shim_dir" ] && continue
    filtered="${filtered:+$filtered:}$d"
done
IFS=$saved_ifs
real_bd=$(PATH="$filtered" command -v bd || true)
if [ -z "$real_bd" ]; then
    echo "bd (harnessed shim): no real \`bd\` on PATH behind $shim_dir." >&2
    exit 127
fi

# Escape hatch, for debugging the shim itself or for a session that deliberately wants the launch
# workspace regardless of CWD.
if [ "${HARNESSED_BD_SHIM:-on}" = "off" ]; then
    exec "$real_bd" "$@"
fi

# The repository under $PWD, if any. `bd` itself keys off the git common dir, so this is the same
# question bd would ask — just asked per invocation instead of once per launch.
gcd=$(git rev-parse --git-common-dir 2>/dev/null || true)
if [ -n "$gcd" ]; then
    gcd=$(CDPATH= cd -- "$gcd" 2>/dev/null && pwd -P) || gcd=""
fi

launch_gcd="${HARNESSED_GIT_COMMON_DIR:-}"
if [ -n "$launch_gcd" ] && [ -d "$launch_gcd" ]; then
    launch_gcd=$(CDPATH= cd -- "$launch_gcd" && pwd -P)
fi

# Not in a repo, or in the repo harnessed launched in → the launch env is already correct. This is
# the case that keeps the b0s fix alive: an agent started in $HOME finds no repo and inherits
# BEADS_DIR exactly as before.
if [ -z "$gcd" ] || [ "$gcd" = "$launch_gcd" ]; then
    exec "$real_bd" "$@"
fi

# --- foreign project ---------------------------------------------------------
# Everything below mirrors the launcher's own path arithmetic, and the two are pinned together by
# tests/test_beads_bd_shim.py.

# paths.persist_in_repo_dir: a normal checkout's common dir is <root>/.git, a bare + linked-worktree
# layout's is <...>/.bare and IS the anchor.
if [ "$(basename -- "$gcd")" = ".git" ]; then
    root=$(dirname -- "$gcd")
else
    root=$gcd
fi

# paths.project_hash: sha1 of the normalized common dir, first 8 hex.
if command -v sha1sum >/dev/null 2>&1; then
    key=$(printf '%s' "$gcd" | sha1sum | cut -c1-8)
elif command -v shasum >/dev/null 2>&1; then
    key=$(printf '%s' "$gcd" | shasum | cut -c1-8)
else
    echo "bd (harnessed shim): neither sha1sum nor shasum is available; cannot resolve $root." >&2
    exit 1
fi

# Placement is the foreign project's business, not ours: team keeps .beads in the repo, stealth
# keeps it under harnessed's persist root. Probe for the one that exists.
beads_dir=""
if [ -d "$root/.beads" ]; then
    beads_dir="$root/.beads"
else
    stealth="${XDG_DATA_HOME:-$HOME/.local/share}/harnessed/persist/beads-stealth/$key/.beads"
    [ -d "$stealth" ] && beads_dir="$stealth"
fi
if [ -z "$beads_dir" ]; then
    echo "bd (harnessed shim): $root has no beads workspace." >&2
    echo "  This session's harnessed launch is bound to ${launch_gcd:-<none>}; refusing to run" >&2
    echo "  against it from a different repository. Run \`bd init\` in $root, or cd back." >&2
    exit 1
fi

# launcher._svc_container + _svc_published_port. No podman (i.e. a containerized agent) means no
# discovery is possible at all — say so rather than guessing a port.
#
# `|| true` is load-bearing under `set -o pipefail`: a sidecar that is not running makes `podman
# port` exit non-zero, which would take the whole pipeline — and with `set -e`, the shim — down with
# it, replacing the explanation below with a bare exit code.
port=""
if command -v podman >/dev/null 2>&1; then
    port=$(podman port "harnessed-svc-beads-server-$key" 3307 2>/dev/null |
        sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n1 || true)
fi

# launcher._svc_password.
pw_file="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/svc-secrets/beads-server-$key"

if [ -z "$port" ] || [ ! -f "$pw_file" ]; then
    echo "bd (harnessed shim): $root has a beads workspace, but no reachable beads-server for it." >&2
    echo "  This session's harnessed launch is bound to ${launch_gcd:-<none>} and will not run bd" >&2
    echo "  against another project's database over the wrong server. Launch harnessed in $root" >&2
    echo "  (which starts its beads-server sidecar), or cd back to the launch project." >&2
    exit 1
fi

# `podman port` answered, so we are on the host and the sidecar publishes on loopback — the same
# value launcher.svc_client_env fills in for `{host}` in host mode.
# `env -u` FIRST, and it is load-bearing. Setting the new connection is not enough: bd picks socket
# mode whenever BEADS_DOLT_SERVER_SOCKET is set, so a launch-era socket left in the environment wins
# over every port variable below and bd dials the LAUNCH project's socket while believing it is
# talking to this one (observed 2026-07-27: "Dolt server unreachable at <launch project>/.beads/run/
# mysql.sock" from a session whose BEADS_DIR had been correctly retargeted). Retargeting has to
# REMOVE the old project's connection, not just add the new one.
exec env \
    -u BEADS_DOLT_SERVER_SOCKET \
    -u HARNESSED_BEADS_SERVER_SOCKET \
    -u BEADS_DOLT_SERVER_DATABASE \
    BEADS_DIR="$beads_dir" \
    BEADS_DOLT_SERVER_MODE=server \
    BEADS_DOLT_SERVER_HOST=127.0.0.1 \
    BEADS_DOLT_SERVER_PORT="$port" \
    BEADS_DOLT_SERVER_USER=root \
    BEADS_DOLT_PASSWORD="$(cat "$pw_file")" \
    BEADS_DOLT_AUTO_START=false \
    "$real_bd" "$@"
