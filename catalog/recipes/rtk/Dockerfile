# Recipe Dockerfile for: rtk
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the pinned rtk ("Rust Token Killer") release binary. rtk is a CLI the agent shells out to
# (`rtk git status`, `rtk read file.rs`, …) — NOT an MCP server, NOT a service, NOT a skill — so
# this layer installs the binary, then runs `rtk init -g` to additionally bake `RTK.md` + the
# PreToolUse hook so the agent doesn't have to discover the surface from `rtk --help` alone.
#
# Pin = the release binary (musl-static = zero runtime deps, runs on any base regardless of glibc).
# The version in the URL is the reproducibility anchor: no @latest / :latest / floating ref would
# pass the assembler pin gate. `cargo install rtk` is deliberately NOT used — another "rtk" ("Rust
# Type Kit") on crates.io would fetch the wrong package.
#
# Installed via mise's `github:` backend (harnessed-base already ships mise + shims on PATH — same
# pattern as the beads recipe): mise resolves the arch-matched asset (musl-static on x86_64, gnu on
# aarch64 — no aarch64-musl is published) and verifies GitHub artifact attestations + SLSA
# provenance, a stronger guarantee than this recipe's prior version-pin-only verification.
USER harnessed
ARG RTK_VERSION=0.43.0
RUN mise use -g "github:rtk-ai/rtk@${RTK_VERSION}" && mise install && rtk --version
RUN rtk init -g --auto-patch
