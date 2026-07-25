#!/usr/bin/env bash
set -e

DATA_DIR=/data          # bind mount of this project's .beads (in_repo or host-persisted)
DOLT_DIR="${DATA_DIR}/dolt"
SOCK_DIR="${DATA_DIR}/run"

mkdir -p "${DOLT_DIR}" "${SOCK_DIR}"

# A stale socket from an unclean shutdown makes dolt refuse to bind. Removing it is safe: this is the
# only container that ever serves this data dir, and it holds the exclusive Dolt lock below.
rm -f "${SOCK_DIR}/mysql.sock"

# ── NO metadata.json rewriting — deliberately ───────────────────────────────────────────────────
# This used to stamp `dolt_server_socket` into the workspace's metadata.json on every startup, so bd
# would find the socket. That was wrong for a reason that only shows up on someone else's machine:
# metadata.json is part of bd's TRACKED surface (`bd init` commits it), and the socket path is an
# absolute host path. Committed, it hands every teammate a path that does not exist for them — and
# because socket mode disables auto-start, they do not degrade gracefully, they are hard-blocked.
# That breaks the one rule beads/team exists to keep: sharing the tracker must not require harnessed.
#
# The socket does not need to be persisted at all. `BEADS_DOLT_SERVER_SOCKET` puts bd in socket mode
# on its own — verified against a workspace whose metadata.json says `dolt_mode: server` and carries
# no socket key: with the variable set, bd refuses with "Auto-start is not supported in socket mode"
# and spawns nothing; without it the same workspace auto-starts as bd normally would. So the recipes
# export it (`env: BEADS_DOLT_SERVER_SOCKET: {persist:.beads}/run/mysql.sock`, resolved per mode) and
# nothing machine-local is ever written to disk. A teammate without harnessed simply lacks the
# variable and gets bd's ordinary behaviour.
#
# See BEADS.md §4. Do not reintroduce a metadata writer here without reading it.

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
