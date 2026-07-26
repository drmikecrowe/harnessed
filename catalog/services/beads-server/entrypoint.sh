#!/usr/bin/env bash
set -e

DATA_DIR=/data          # bind mount of this project's .beads (in_repo or host-persisted)
DOLT_DIR="${DATA_DIR}/dolt"
SOCK_DIR="${DATA_DIR}/run"

mkdir -p "${DOLT_DIR}"

# The server is reached over a PUBLISHED TCP PORT, not a unix socket (see service.yaml for why the
# socket form was reversed). Two consequences here:
#
#   1. No socket is served, and the leftover `run/` dir from the socket era is removed. It sat at
#      <repo>/.beads/run/mysql.sock in team placement — a non-file inside the user's source tree
#      that every file-walking tool in the stack tripped over. Only remove it when it holds nothing
#      but the socket we put there.
#   2. A TCP port has no filesystem permissions to hide behind, so root MUST have a password. The
#      launcher provisions one per project and passes it in; refuse to start without it rather than
#      silently serving a project's issue database to every local process.
rm -f "${SOCK_DIR}/mysql.sock"
rmdir "${SOCK_DIR}" 2>/dev/null || true

: "${HARNESSED_SVC_PASSWORD:?beads-server requires a password from the launcher (_svc_password)}"

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

# Dolt initializes a FRESH data dir with a PASSWORDLESS root@'localhost' ONLY, so a client from any
# other address is rejected: `Error 1045 (28000): Access denied for user 'root'` (verified). Grant
# root@'%' once the server is listening — but WITH the launcher's password, because the port is
# published and `root@'%'` with no password would accept every local process on the machine.
#
# The bootstrap connection is the passwordless root@'localhost' dolt just created; it works only
# from inside this container and only until the ALTER below lands. Ordering matters: create/grant
# root@'%' first, then set root@'localhost''s password last, or this script locks itself out
# mid-way through on a restart.
(
    for _ in $(seq 30); do
        if dolt --host 127.0.0.1 --port 3307 --user root --password "" --no-tls \
                sql -q "SELECT 1" >/dev/null 2>&1; then
            dolt --host 127.0.0.1 --port 3307 --user root --password "" --no-tls sql -q \
                "CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY '${HARNESSED_SVC_PASSWORD}';
                 ALTER USER 'root'@'%' IDENTIFIED BY '${HARNESSED_SVC_PASSWORD}';
                 GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
                 ALTER USER 'root'@'localhost' IDENTIFIED BY '${HARNESSED_SVC_PASSWORD}';" \
                >/dev/null 2>&1 && echo "[beads-server] granted root@'%' (password-protected)"
            exit 0
        fi
        # On a RESTART the password is already set, so the passwordless bootstrap above can never
        # succeed. Probe with the password too and exit quietly when it works — otherwise every
        # restart burns 30s and then warns about a server that is perfectly healthy.
        if dolt --host 127.0.0.1 --port 3307 --user root --password "${HARNESSED_SVC_PASSWORD}" \
                --no-tls sql -q "SELECT 1" >/dev/null 2>&1; then
            exit 0
        fi
        sleep 1
    done
    echo "[beads-server] WARNING: server never became reachable; root@'%' not granted" >&2
) &

# --host 0.0.0.0 binds every interface INSIDE the container, which is what makes the port
# publishable at all. That is not a host-side exposure: the launcher publishes with
# `-p 127.0.0.1::3307`, so the only address the host offers is loopback, and the password granted
# above is what guards it. No --socket — nothing serves one now (service.yaml explains why).
exec dolt sql-server \
    --host 0.0.0.0 --port 3307 \
    --data-dir "${DOLT_DIR}"
