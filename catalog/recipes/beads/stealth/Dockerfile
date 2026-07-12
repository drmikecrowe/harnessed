# Recipe Dockerfile for: beads/stealth
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads): a single native binary that bundles
# embedded Dolt — local-first, git-free persistent task memory for agents. Installed via mise's
# `github:` backend (harnessed-base already ships mise + shims on PATH — same pattern as the
# sibling `beads` recipe and catalog/base/Dockerfile.harnessed-omp's `omp` install): mise resolves
# the release asset for the current arch and verifies GitHub artifact attestations.
USER harnessed
# Pin to the exact release tag (no @latest / :latest / --branch — the assembler pin gate rejects
# floating refs).
ARG BEADS_VERSION=1.1.0
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
# Fails the build loudly instead of at first run.
RUN bd --version
USER root
# Welcome-message init (NO auto-init). This recipe does NOT run `bd init`/`bd setup` automatically —
# `bd setup --stealth` still writes `.claude/settings.json` + `CLAUDE.md` into the project (untracked,
# so NOT actually git-excluded on bd 1.1.0 — it can't be made footprint-free here), so first-init is
# left to the user, via recipe.yaml's harness-agnostic `setup:` note (self-gated on Claude by
# `setup.condition`; `! bd list`).
USER harnessed
# BEADS_DIR is now a static ENV pointing at the host-persisted project-scoped bind-mount
# ($HOME/.beads → $XDG_DATA_HOME/harnessed/persist/beads/<git-common-dir-hash>/.beads/).
# Because the mount target is a fixed container path (not $PWD-relative), the ENV is safe
# to bake here — it won't vary across projects. The bd binary writes its embedded Dolt DB
# to this path; `bd init --quiet --stealth` (run once via `harnessed init`) creates it.
ENV BEADS_DIR=/home/harnessed/.beads
