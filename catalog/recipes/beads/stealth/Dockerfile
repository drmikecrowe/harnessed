# Recipe Dockerfile for: beads/stealth
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake ONLY the `bd` CLI (https://github.com/gastownhall/beads) — local-first, git-free persistent
# task memory for agents. Deliberately NOT `dolt`: bd runs here as a pure CLIENT of the project's
# `beads-server` service, over a unix socket. It never starts an engine (bd's bundled Dolt is an
# embedded library, and embedded is exactly what this design removes — see recipe.yaml), so it needs
# no `dolt` binary on PATH, and not shipping one makes that structural.
#
# Installed via mise's `github:` backend (harnessed-base already ships mise + shims on PATH — same
# pattern as catalog/base/Dockerfile.harnessed-omp's `omp` install): mise resolves the release asset
# for the current arch and verifies GitHub artifact attestations.
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
# BEADS_DIR moved to recipe.yaml `env:`. Baked here it was the container mount target spelled out
# literally, which is only half the truth — a host launch has no mount and needs the real persist
# dir. The `{persist:.beads}` template yields both.
