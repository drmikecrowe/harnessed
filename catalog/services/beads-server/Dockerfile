# Service image: beads-server — a standalone `dolt sql-server` that every project's `bd` points at
# (bead main-8by). Built by `harnessed svc up beads-server` on first use (or
# `podman build -t harnessed-beads-server:latest`). Scanned by the BLD-02 image-scan gate when built
# via the launcher.
#
# This is a SERVICE Dockerfile, so it carries its OWN full lineage (FROM, CMD) — unlike a recipe
# Dockerfile, which omits FROM/ARG HARNESS (see gbrain's service Dockerfile for the same note).
#
# ── dolt via mise `github:` backend (same as the beads recipe) ────────────────────────────────
# The `beads` recipe installs dolt with `mise use -g github:dolthub/dolt@2.1.10`; mise resolves the
# release asset for the current arch and verifies GitHub artifact attestations — a stronger
# supply-chain guarantee than a hand-rolled curl + sha256sum, and the method already proven in this
# repo. Pin the EXACT dolt release (no @latest / :latest) — 2.1.10, the version the beads recipe
# pins and verifies working with bd 1.1.0's server engine. mise itself is pinned via MISE_VERSION.
FROM debian:bookworm-slim

ARG MISE_VERSION=v2026.7.0
ARG DOLT_VERSION=2.1.10

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git bash \
    && rm -rf /var/lib/apt/lists/*

# Pinned mise install (the run script honors MISE_VERSION), then the pinned dolt release via the
# github: backend. Copy the resolved binary to /usr/local/bin so the CMD needs no shim/PATH setup.
ENV PATH="/root/.local/bin:${PATH}"
RUN curl -fsSL https://mise.run | MISE_VERSION="${MISE_VERSION}" sh \
    && mise use -g "github:dolthub/dolt@${DOLT_VERSION}" \
    && mise install \
    && cp "$(mise which dolt)" /usr/local/bin/dolt \
    && dolt version

# The named service volume (`beads-server-data`) is mounted at /data by `_ensure_service`; dolt
# serves and creates databases under its --data-dir there. dolt needs a global identity for the
# commits it writes; bd supplies the per-write actor, but set a service-level default so the engine
# never blocks on a missing identity.
RUN mkdir -p /data \
    && dolt config --global --add user.name "beads-server" \
    && dolt config --global --add user.email "beads-server@harnessed.local"
VOLUME /data

# `--host 0.0.0.0` is mandatory: dolt sql-server defaults to 127.0.0.1 (in-container loopback) and
# would be unreachable on the published port / via host.containers.internal otherwise. The port is
# then published ONLY to the host loopback by the launcher (loopback-only, no auth — design). Default
# Dolt root user, no password.
EXPOSE 3307
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD bash -c 'exec 3<>/dev/tcp/127.0.0.1/3307' || exit 1

CMD ["dolt", "sql-server", "--host", "0.0.0.0", "--port", "3307", "--data-dir", "/data"]
