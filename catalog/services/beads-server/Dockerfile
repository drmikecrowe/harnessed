# Service image: beads-server — the ONE `dolt sql-server` for a project; every `bd` in every agent
# container is a client of it (see service.yaml for the why). Built on first use by the launcher, or
# `podman build -t harnessed-beads-server:latest .`. Scanned by the BLD-02 image-scan gate when built
# via the launcher.
#
# This is a SERVICE Dockerfile, so it carries its OWN full lineage (FROM, ENTRYPOINT) — unlike a
# recipe Dockerfile, which omits FROM/ARG HARNESS (see gbrain's service Dockerfile for the same note).
#
# ── dolt AND bd, via mise's `github:` backend (same install path as the beads recipes) ───────────
# mise resolves the release asset for the current arch and verifies GitHub artifact attestations — a
# stronger supply-chain guarantee than a hand-rolled curl + sha256sum, and the method already proven
# in this repo. Every release is pinned EXACTLY (no @latest / :latest — the build rejects them).
#
# `bd` is baked here, not just `dolt`, because the git sync runs INSIDE this container:
# `bd dolt push` (refs/dolt/data) shells out to the dolt CLI, which only ever routes to a server on
# its own loopback — so it cannot run from an agent container (verified: `dial tcp [::1]:3307:
# connect: connection refused`). `harnessed svc sync beads-server` execs it here. Versions match the
# beads recipes' pins so client and server share one proven toolchain.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

ARG MISE_VERSION=v2026.7.0
ARG DOLT_VERSION=2.1.10
ARG BEADS_VERSION=1.1.0

# python3 (NOT python3-minimal — it omits the stdlib `json` module, which the entrypoint's
# legacy-metadata migration needs: `ModuleNotFoundError: No module named 'json'`). ubuntu:24.04 ships
# no interpreter at all, and the migration must not depend on what the recipe images happen to have.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git bash openssh-client python3 \
    && rm -rf /var/lib/apt/lists/*

# Same uid-1000 user as harnessed-base (ubuntu:24.04 ships `ubuntu` at 1000), so `--userns=keep-id`
# maps the host user cleanly and every byte this server writes into the bind-mounted data dir stays
# host-owned — a Dolt data dir written by a foreign uid would EACCES for every agent container.
ARG USERNAME=harnessed
RUN usermod -l ${USERNAME} ubuntu \
    && groupmod -n ${USERNAME} ubuntu \
    && usermod -d /home/${USERNAME} ${USERNAME} \
    && mkdir -p /home/${USERNAME} /data \
    && chown -R ${USERNAME}:${USERNAME} /home/${USERNAME} /data

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER ${USERNAME}
ENV PATH="/home/${USERNAME}/.local/bin:/home/${USERNAME}/.local/share/mise/shims:${PATH}"
RUN curl -fsSL https://mise.run | MISE_VERSION="${MISE_VERSION}" sh \
    && mise use -g "github:dolthub/dolt@${DOLT_VERSION}" "github:gastownhall/beads@${BEADS_VERSION}" \
    && mise install \
    && dolt version && bd --version

# Dolt needs a global identity for the commits it writes. bd supplies the per-write actor; this is
# only the fallback so the engine never blocks on a missing identity.
RUN dolt config --global --add user.name "beads-server" \
    && dolt config --global --add user.email "beads-server@harnessed.local"

# /data is a BIND MOUNT of this project's .beads (the launcher wires it from the owning recipe's
# persist entry) — deliberately NOT a VOLUME: a named volume would put the bytes somewhere no agent
# container can see, and the whole point is that agents reach the project's data in this dir.
#
# No EXPOSE, but the port IS reached: the launcher publishes 3307 on a runtime-allocated host port
# bound to 127.0.0.1 (`publish: ephemeral`), so the host side is chosen per launch and EXPOSE — a
# static declaration — could only ever be wrong. See service.yaml for why the socket form was
# reversed.
#
# HEALTHCHECK verifies MySQL-level AUTH, not just a listener. dolt 2.1.10 has no `sql-client`
# subcommand (the previous healthcheck used it, so it could never pass); the global --host/--port/
# --user flags on `dolt sql` are the supported client form, and --no-tls is required.
#
# --password MUST match what the entrypoint actually granted. It was left as '' when the port
# reversal landed, so every rebuilt sidecar authenticated with an empty password against a server
# that now requires one and sat permanently `unhealthy` while serving every client correctly. A
# healthcheck that authenticates differently from real clients is worse than none: it reports
# failure on a healthy server, which is the exact defect the reversal existed to remove.
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=6 \
    CMD dolt --host 127.0.0.1 --port 3307 --user root --password "${HARNESSED_SVC_PASSWORD}" --no-tls sql -q 'SELECT 1' >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
