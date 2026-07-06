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
# The stdio MCP shim (proxies to the store over AGENTMEMORY_URL). CONFIRM AT BUILD whether the
# `agentmemory-mcp` bin ships from `@agentmemory/agentmemory` or a separate `@agentmemory/mcp`
# package, and pin the exact source — the shim is the single integration risk (plan §Risks).
# If the bin lives in a separate package, switch the spec below to that package name verbatim.
ARG AGENTMEMORY_VERSION=0.9.27
RUN pnpm add -g "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}"
