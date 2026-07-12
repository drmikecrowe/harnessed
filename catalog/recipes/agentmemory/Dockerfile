# Recipe Dockerfile for: agentmemory
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# This bakes ONLY the MCP SHIM (the protocol adapter), not the store (the store lives in the
# service image). The shim is agentmemory's stdio MCP server (packages/mcp/bin.mjs →
# dist/standalone.mjs), a thin proxy that reaches the shared REST store over AGENTMEMORY_URL.
# hatago spawns it as a per-instance child; the agent reaches it through hatago's endpoint.
#
# Contingent on the hatago consolidation: a recipe can only bake a stdio child into the harness
# image once hatago lives in it. Until then this Dockerfile is correct in shape but unbuildable
# in the harness image.
#
# pnpm — never npm/npx. Pin the exact version (no @latest).
USER harnessed
# The stdio MCP shim (proxies to the store over AGENTMEMORY_URL) is `@agentmemory/mcp`, NOT
# `@agentmemory/agentmemory`. Verified against the npm registry at 0.9.27:
#   @agentmemory/mcp         bin: { "agentmemory-mcp": "bin.mjs" }   <- the shim recipe.yaml runs
#   @agentmemory/agentmemory bin: { "agentmemory":     "dist/cli.mjs" }  <- the store CLI/daemon
# Only `@agentmemory/mcp` ships the `agentmemory-mcp` binary. The store CLI belongs in the SERVICE
# image (catalog/services/agentmemory/), not here — this image needs the adapter and nothing else.
ARG AGENTMEMORY_VERSION=0.9.27
RUN pnpm add -g "@agentmemory/mcp@${AGENTMEMORY_VERSION}"
