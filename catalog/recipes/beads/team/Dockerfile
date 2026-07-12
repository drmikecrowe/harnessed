# Recipe Dockerfile for: beads/team
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake ONLY the `bd` CLI (https://github.com/gastownhall/beads). Deliberately NOT `dolt`: bd runs
# here as a pure CLIENT of the project's `beads-server` service, over a unix socket. It never starts
# an engine, so it never needs a `dolt` binary on PATH — and not shipping one makes that structural.
# The dolt binary lives in the beads-server image, which is also where the git sync runs
# (`harnessed svc sync beads-server`), because `bd dolt push` shells out to a dolt CLI that only ever
# routes to a server on its OWN loopback.
#
# Installed via mise's `github:` backend — harnessed-base already ships mise + shims on PATH. mise
# resolves the release asset for the current arch and verifies GitHub artifact attestations: a
# stronger supply-chain guarantee than a hand-rolled curl + sha256sum. Pin the exact release (no
# @latest / :latest / --branch — the assembler pin gate rejects floating refs).
USER harnessed
ARG BEADS_VERSION=1.1.0
RUN mise use -g "github:gastownhall/beads@${BEADS_VERSION}" && mise install
# Smoke test: a runnable binary also catches an arch mismatch mise's attestation check wouldn't.
RUN bd --version
USER root
# Welcome-message init (NO auto-init). This recipe deliberately does NOT run `bd init`/`bd setup`
# automatically — bd's setup writes into the project (`.claude/settings.json` + `CLAUDE.md` on bd
# 1.1.0) and can't be made reliably idempotent/footprint-free across every git layout, so first-time
# initialization stays a deliberate user action via recipe.yaml's `setup:` note (self-gated on Claude
# by `setup.condition`; `! bd list`).
USER harnessed
# No static BEADS_DIR ENV: `.beads/` lives inside the work tree (persist: location: in_repo) and bd's
# own discovery finds it — including in a bare + linked-worktree layout, where bd resolves it off the
# git common dir (verified with `bd where`). The launcher's beads-server bind-mounts that SAME
# resolved dir (paths.persist_in_repo_dir), so client and server agree by construction.
