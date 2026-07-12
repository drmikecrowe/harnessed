#!/usr/bin/env bash
set -e

DATA_DIR=/data          # bind mount of this project's .beads (in_repo or host-persisted)
DOLT_DIR="${DATA_DIR}/dolt"
SOCK_DIR="${DATA_DIR}/run"

mkdir -p "${DOLT_DIR}" "${SOCK_DIR}"

# A stale socket from an unclean shutdown makes dolt refuse to bind. Removing it is safe: this is the
# only container that ever serves this data dir, and it holds the exclusive Dolt lock below.
rm -f "${SOCK_DIR}/mysql.sock"

# ── Migrate a workspace initialized BEFORE this service existed ─────────────────────────────────
# Such a `.beads/metadata.json` still names bd's own managed engine (dolt_mode: server plus a
# dolt_server_host/port, no dolt_server_socket). bd then tries to auto-start a local dolt — and the
# recipe images no longer ship the `dolt` binary, so every command dies with:
#     failed to open database: Dolt server unreachable at 127.0.0.1:0 and auto-start failed:
#     dolt is not installed (not found in PATH)
#
# `bd init` CANNOT fix this: it refuses to touch an initialized workspace ("This workspace is already
# initialized. Aborting."), so re-running init — the migration the docs used to advise — does nothing.
# The only supported repoint is the metadata itself, so the server does it: it is the one component
# that knows both the data dir and the socket path, and it runs before any client connects.
#
# Backed up first, and strictly additive: dolt_database, project_id and the Dolt bytes are untouched,
# so the existing issue history is opened in place. The stale TCP pointers are dropped — 127.0.0.1
# means something different in every container's network namespace, which is why the socket exists.
# HARNESSED_SOCKET_PATH is the CLIENT-visible socket path, passed in by the launcher. It is NOT
# /data/run/mysql.sock: that is where THIS container sees it, while an agent container sees the same
# socket at the project's own path (e.g. <repo>/.beads/run/mysql.sock). metadata.json is read by the
# clients, so it must record their path, never ours.
#
# Never fatal (`|| true`): the server exists to serve the database. A migration that cannot run — a
# hand-edited metadata.json, a read-only mount — must degrade to "bd can't connect yet", not take the
# whole server down with it. `set -e` is on, and an unguarded failure here killed the container.
META="${DATA_DIR}/metadata.json"
if [ -f "${META}" ] && [ -n "${HARNESSED_SOCKET_PATH:-}" ]; then
    SOCKET_PATH="${HARNESSED_SOCKET_PATH}" \
    META="${META}" python3 - <<'PY' || echo "[beads-server] WARNING: metadata migration failed — bd may not connect" >&2
import json, os, shutil, sys

meta_path = os.environ["META"]
socket_path = os.environ["SOCKET_PATH"]
try:
    with open(meta_path) as fh:
        meta = json.load(fh)
except (OSError, ValueError) as exc:
    print(f"[beads-server] metadata.json unreadable ({exc}) — leaving it alone", file=sys.stderr)
    raise SystemExit(0)

if meta.get("dolt_server_socket") == socket_path:
    raise SystemExit(0)  # already pointed at this server

shutil.copy2(meta_path, meta_path + ".pre-socket.bak")
meta["backend"] = meta.get("backend", "dolt")
meta["dolt_mode"] = "server"
meta["dolt_server_socket"] = socket_path
meta.pop("dolt_server_host", None)
meta.pop("dolt_server_port", None)
with open(meta_path, "w") as fh:
    json.dump(meta, fh, indent=2)
print(f"[beads-server] migrated {meta_path} -> socket {socket_path} "
      f"(backup: {os.path.basename(meta_path)}.pre-socket.bak)")
PY
fi

# bd also keeps a port file it calls "the primary source" for the server port. Left behind, it points
# clients at a TCP port that no longer exists in their netns; the socket in metadata.json is the truth.
rm -f "${DATA_DIR}/dolt-server.port" "${DATA_DIR}/dolt-server.lock"

# Dolt initializes a FRESH data dir with root@'localhost' ONLY, so a `bd` in another container
# authenticates from a non-local address and is rejected: `Error 1045 (28000): Access denied for
# user 'root'` (verified). Grant root@'%' once the server is listening. No password: the socket lives
# in the data dir, so it is reachable exactly by whoever can already read the Dolt bytes, and no port
# is published to the host — the single-user local-dev stance.
(
    for _ in $(seq 30); do
        if dolt --host 127.0.0.1 --port 3307 --user root --password "" --no-tls \
                sql -q "SELECT 1" >/dev/null 2>&1; then
            dolt --host 127.0.0.1 --port 3307 --user root --password "" --no-tls sql -q \
                "CREATE USER IF NOT EXISTS 'root'@'%'; GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;" \
                >/dev/null 2>&1 && echo "[beads-server] granted root@'%'"
            exit 0
        fi
        sleep 1
    done
    echo "[beads-server] WARNING: server never became reachable; root@'%' not granted" >&2
) &

# --host 0.0.0.0 keeps a TCP listener up INSIDE the container: the healthcheck uses it, and so does
# the dolt CLI that `bd dolt push` shells out to (it dials its own loopback and nothing else).
# Peers OUTSIDE this container use --socket instead, which lives in the bind-mounted data dir — so
# no port is published to the host at all.
exec dolt sql-server \
    --host 0.0.0.0 --port 3307 \
    --socket "${SOCK_DIR}/mysql.sock" \
    --data-dir "${DOLT_DIR}"
