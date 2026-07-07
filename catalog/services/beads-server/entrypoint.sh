#!/usr/bin/env bash
set -e

DATA_DIR=/data

# For an existing data directory (named volume reuse): reset the root password via direct SQL.
# `dolt --data-dir sql` bypasses the MySQL auth layer entirely — no password required. This means
# a stale volume where root had any password (from a prior container rebuild or config change) gets
# silently corrected before the server starts. Fresh data directories have no .dolt dir yet, so
# dolt sql-server initializes them with root/no-password on its own.
if [ -d "${DATA_DIR}/.dolt" ]; then
    dolt --data-dir "${DATA_DIR}" sql \
        -q "ALTER USER 'root'@'%' IDENTIFIED BY ''; FLUSH PRIVILEGES;" \
        2>/dev/null || true
fi

exec dolt sql-server --host 0.0.0.0 --port 3307 --data-dir "${DATA_DIR}"
