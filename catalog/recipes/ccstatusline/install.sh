#!/usr/bin/env bash
# install.sh — the ccstatusline CLI + the matching `statusLine` block, moved out of the recipe
# Dockerfile (bd harnessed-8px.5). Replaces both former RUN layers.
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE
# PROJECT_DIR and friends are absent by design — a build has no project mounted.
#
# The old Dockerfile hard-coded `/home/harnessed/.local/share/mise/shims/ccstatusline` into
# settings.json. That literal is exactly why this recipe delivered nothing usable on a host launch:
# a container-absolute path that no host can resolve. Here the path is COMPUTED per mode and written
# into the settings.json of whichever config dir this run is installing into.
set -euo pipefail

CCSTATUSLINE_VERSION="2.2.22"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# --- 1. the binary -------------------------------------------------------------------------------
if [ "${HARNESSED_MODE:-}" = "container" ]; then
    # Unchanged from the Dockerfile: mise's `npm:` backend. harnessed-base ships mise + shims on PATH
    # and sets `npm.package_manager pnpm`, so this routes through the managed pnpm supply-chain
    # config — no raw npm/npx — and lands a shim at ~/.local/share/mise/shims/ccstatusline.
    mise use -g "npm:ccstatusline@${CCSTATUSLINE_VERSION}"
    mise install
    bin="$HOME/.local/share/mise/shims/ccstatusline"
else
    # Host: install into $HARNESSED_INSTALL_CACHE, which is the ONLY place a host install may leave
    # something durable. It has to be durable: statusLine is an absolute path in settings.json that
    # the agent execs for the whole session, and $HARNESSED_CONFIG_DIR is rmtree'd and rebuilt on
    # EVERY launch (_materialize_host_home) — so the tree cannot live there, only the pointer to it.
    # `mise use -g` is not an option host-side: it writes the user's own global mise config.
    if ! command -v pnpm >/dev/null 2>&1; then
        echo "error: install (ccstatusline) needs 'pnpm' on PATH to install ccstatusline" \
             "${CCSTATUSLINE_VERSION} host-native." >&2
        exit 1
    fi
    cache="${HARNESSED_INSTALL_CACHE:?host install requires HARNESSED_INSTALL_CACHE}"
    # Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate a
    # temp sibling and rename, so an interrupted install can never be mistaken for a populated cache.
    if [ ! -d "$cache" ]; then
        tmp="${cache}.partial.$$"
        rm -rf "$tmp"
        mkdir -p "$tmp"
        printf '{"name":"harnessed-ccstatusline","private":true}\n' > "$tmp/package.json"
        (cd "$tmp" && pnpm add "ccstatusline@${CCSTATUSLINE_VERSION}")
        mv "$tmp" "$cache"
    fi
    bin="$cache/node_modules/.bin/ccstatusline"
fi
test -x "$bin"

# --- 2. the statusLine block ---------------------------------------------------------------------
# statusLine is a Claude Code concept, so this half is gated on the harness exactly as the
# Dockerfile's `${HARNESS} = claude` branch was. Other harnesses still get the binary above.
if [ "${HARNESS:-}" != "claude" ]; then
    echo "ccstatusline: statusLine is Claude-only; skipped for HARNESS=${HARNESS:-}"
    exit 0
fi

# Read-modify-write rather than overwrite: settings.json may already carry another recipe's baked
# keys (and host-side it is the copy _materialize_host_home just laid down from the profile).
# Container-side the launcher's emit.merge_settings then carries this key through verbatim while
# re-applying harnessed's own required settings.
python3 - "$HARNESSED_CONFIG_DIR/settings.json" "$bin" <<'PY'
import json, pathlib, sys

path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
raw = path.read_text() if path.exists() else ""
data = json.loads(raw) if raw.strip() else {}
data["statusLine"] = {
    "type": "command",
    "command": sys.argv[2],
    "padding": 0,
    "refreshInterval": 10,
}
path.write_text(json.dumps(data, indent=2) + "\n")
PY
