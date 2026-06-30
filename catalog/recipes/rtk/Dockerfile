# Recipe Dockerfile for: rtk
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Phase 1 (ship now): bake the pinned rtk ("Rust Token Killer") release binary. rtk is a CLI the
# agent shells out to (`rtk git status`, `rtk read file.rs`, …) — NOT an MCP server, NOT a service,
# NOT a skill — so this layer installs the binary only. The agent learns the surface from
# `rtk --help` (Phase 2's `rtk init -g` would additionally bake `RTK.md` + the PreToolUse hook).
#
# Pin = the release binary (musl-static = zero runtime deps, runs on any base regardless of glibc).
# The version in the URL is the reproducibility anchor: no @latest / :latest / floating ref would
# pass the assembler pin gate. `cargo install rtk` is deliberately NOT used — another "rtk" ("Rust
# Type Kit") on crates.io would fetch the wrong package. Verification = the version pin plus a
# `rtk --version` post-install sanity check (this release publishes no checksums file; see PLAN.md
# "Risks / checks" — checksum verification, if added upstream, is a build-time concern).
USER root
ARG RTK_VERSION=0.43.0
# arch detection: x86_64 gets the musl-static asset (zero runtime deps); aarch64 falls back to the
# gnu asset (no aarch64-musl is published). Any other arch aborts the build loudly.
RUN set -euo pipefail; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)  asset="rtk-x86_64-unknown-linux-musl.tar.gz" ;; \
      aarch64) asset="rtk-aarch64-unknown-linux-gnu.tar.gz" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/rtk.tgz \
      "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/${asset}"; \
    tar xzf /tmp/rtk.tgz -C /tmp; \
    install -m 0755 /tmp/rtk /usr/local/bin/rtk; \
    rm -rf /tmp/rtk*; \
    rtk --version
USER harnessed
