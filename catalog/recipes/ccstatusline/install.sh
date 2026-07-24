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

# --- 1. the binary: NOT here ----------------------------------------------------------------------
# `tools: [npm:ccstatusline@…]` owns it in BOTH modes (bd harnessed-1t4.3), which is also what
# collapses the two branches this section used to carry: a container `mise use -g` and a host
# `pnpm add` into the install cache, each yielding a DIFFERENT absolute path. mise's shims dir is
# on PATH in both modes and outlives the per-launch config-dir wipe, so the path statusLine records
# is simply where the tool resolves. Keep CCSTATUSLINE_VERSION in lockstep with that pin.
bin="$(command -v ccstatusline)"
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
