# Recipe Dockerfile for: beads/stealth-server
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads) configured (by this recipe's init) for the
# STEALTH-SERVER cell of the beads 2×2: `.beads/` lives OUTSIDE the repo (host-persisted bind-mount,
# zero git footprint — like `beads/stealth`) BUT the live Dolt data lives on the SHARED `beads-server`
# service instead of a per-container embedded engine (like `beads/team-server`). Host `.beads/` then
# holds only config + metadata.json (the pointer at the server); the issue graph itself is on the
# shared server's named volume, so a host `bd` and every container's `bd` can operate without the
# exclusive-file-lock collision embedded/stealth mode otherwise risks (the 2026-07-05 incident).
#
# Installed via mise's `github:` backend — the same attestation-verified, pinned install the other
# beads recipes use. `dolt` is baked alongside `bd` at the SAME versions the other server variant
# pins (bd 1.1.0 + dolt 2.1.10) so the whole family shares one proven toolchain; bd's external-server
# mode connects to the remote server as a MySQL client.
USER harnessed
# Pin to the exact release tag (no @latest / :latest / --branch — the assembler pin gate rejects
# floating refs).
ARG BEADS_VERSION=1.1.0
ARG DOLT_VERSION=2.1.10
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" "github:dolthub/dolt@${DOLT_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
RUN bd --version && dolt version
USER root
# Welcome-message init (NO auto-init) — same rationale as `beads/stealth`. recipe.yaml's harness-
# agnostic `setup:` note is self-gated on Claude by `setup.condition` (`! bd list`); `bd setup
# --stealth` still writes an untracked `.claude/settings.json` + `CLAUDE.md` on bd 1.1.0, so it
# can't be auto-run footprint-free.
USER harnessed
# BEADS_DIR is a static ENV pointing at the host-persisted project-scoped bind-mount
# ($HOME/.beads → $XDG_DATA_HOME/harnessed/persist/beads/<git-common-dir-hash>/.beads/) — same fixed
# container path as `beads/stealth`, so no per-project path arithmetic and no bd-resolve-beads-dir
# helper is needed (that helper only matters for the in-repo `beads/team*` variants). Here `.beads/`
# holds config + the server pointer; the issue data itself lives on the shared beads-server.
ENV BEADS_DIR=/home/harnessed/.beads
