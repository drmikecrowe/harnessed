#!/usr/bin/env bash
set -e

DATA_DIR=/data          # bind mount of this project's .beads (in_repo or host-persisted)
DOLT_DIR="${DATA_DIR}/dolt"
SOCK_DIR="${DATA_DIR}/run"

mkdir -p "${DOLT_DIR}" "${SOCK_DIR}"

# A stale socket from an unclean shutdown makes dolt refuse to bind. Removing it is safe: this is the
# only container that ever serves this data dir, and it holds the exclusive Dolt lock below.
rm -f "${SOCK_DIR}/mysql.sock"

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
