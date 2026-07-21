# Recipe Dockerfile for: solidspec
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `solidspec` Rust CLI from source. The base image already ships `rust@1.87` via mise
# (catalog/base/Dockerfile.harnessed-base:81); solidspec's edition 2024 needs Rust >= 1.85, so
# the toolchain is sufficient — no rustup step. Upstream's only documented install is
# build-from-source (no release binaries; crates.io publish unconfirmed), so the pin-safe
# equivalent that needs no crates.io publish is `cargo install --git … --tag`.
USER root
# git2 (libgit2-sys) builds libgit2 from source at install time and needs cmake + pkg-config;
# the base image has libssl-dev + zlib1g-dev but NOT cmake/pkg-config. Without this, the
# cargo build fails resolving the git2 dependency.
RUN apt-get update && apt-get install -y --no-install-recommends cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*
USER harnessed
# Drop to harnessed before `cargo install` so the cargo home + binary live under the
# unprivileged user; `cargo install` places the binary in ~/.cargo/bin (already on PATH via
# mise's rust shim). Pin to the exact published tag v0.3.0 — the assembler rejects floating
# refs (--branch main / :latest / @latest). `solidspec --version` proves the bake + cmake step.
ARG SOLIDSPEC_REF=v0.3.0
RUN cargo install --git https://github.com/jyjeanne/solidspec --tag ${SOLIDSPEC_REF} \
    && solidspec --version
