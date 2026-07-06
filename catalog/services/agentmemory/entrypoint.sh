#!/usr/bin/env bash
# Service entrypoint: agentmemory — the shared REST memory store (plan agentmemory / design §9).
#
# Long-lived foreground store (REST :3111 + viewer :3113). Runs as `harnessed` (USER in the
# Dockerfile); the self-managed iii-engine inherits this UID — no distroless 65532 dance.
# AGENTMEMORY_SECRET is intentionally unset (localhost-open, like `ping`). For a multi-tenant
# host set it (via varlock) and pass the same secret to the recipe shim env + a hatago
# Authorization header — flagged, not blocking.
set -euo pipefail
exec agentmemory
