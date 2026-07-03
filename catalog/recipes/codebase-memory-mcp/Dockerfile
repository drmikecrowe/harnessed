# Recipe Dockerfile for: codebase-memory-mcp (cbm)
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# cbm is a static C binary with zero runtime deps (158 tree-sitter grammars + Hybrid LSP compiled
# in, embedded SQLite) — it needs nothing from the base image's node/pnpm/python/uv. This replicates
# ONLY the binary-extract step of upstream's "Manual install"; do NOT run cbm's own installer
# (scripts/setup.sh / the `install` command), which auto-configures 11 agents (writes .mcp.json,
# skills, hooks, AGENTS.md) — harnessed owns all of that.
USER root
# Pin to the exact release (v0.8.1). Download the architecture-matched tarball + checksums.txt,
# verify against the SHA in checksums.txt, and install the binary. Pin the STANDARD asset name
# `codebase-memory-mcp-linux-<arch>.tar.gz` (there is a `-portable` tarball sibling — leave it).
ARG CBM_VERSION=0.8.1
RUN set -eu; \
    arch="$(uname -m)"; \
    case "$arch" in x86_64|amd64) arch="amd64";; aarch64|arm64) arch="arm64";; *) echo "unsupported $arch" >&2; exit 1;; esac; \
    asset="codebase-memory-mcp-linux-${arch}.tar.gz"; \
    base="https://github.com/DeusData/codebase-memory-mcp/releases/download/v${CBM_VERSION}"; \
    cd /tmp; \
    curl -fsSL "${base}/${asset}" -o "${asset}"; \
    curl -fsSL "${base}/checksums.txt" -o checksums.txt; \
    grep " ${asset}\$" checksums.txt > expected.sha256; \
    sha256sum -c expected.sha256; \
    tar xzf "${asset}"; \
    install -m 0755 codebase-memory-mcp /usr/local/bin/codebase-memory-mcp; \
    rm -rf /tmp/*
USER harnessed
