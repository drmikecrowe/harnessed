# Recipe Dockerfile for: beads-stealth
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
# Bake a harness-aware `bd setup` wrapper. `bd init --stealth` (run once per project, see recipe.yaml)
# only configures git-exclude — per beads' own docs/SETUP.md, wiring the SessionStart hook + minimal
# CLAUDE.md/AGENTS.md section is a SEPARATE step: `bd setup <tool> --stealth`. recipe.yaml's
# `init.run` is one fixed string shared by every harness a stack might use, so it can't branch on
# $HARNESS at runtime — this is the one place that may (per the harness-independent-recipes
# convention): ${HARNESS} is a build-time ARG, resolved once here into a tiny wrapper on PATH.
#
# --project (not global): ~/.claude/settings.json inside the container is harnessed's own read-only
# profile mount (see launcher.py's settings.json bind-mount) — bd can't write hooks there. `--project`
# writes .claude/settings.local.json into the bind-mounted project root instead, which is writable
# and persists on the host like any other project file.
RUN case "${HARNESS}" in \
      claude) printf '#!/bin/sh\nexec bd setup claude --project --stealth\n' > /usr/local/bin/bd-setup-agent ;; \
      *) printf '#!/bin/sh\n# no bd setup recipe for harness "%s" yet (see beads docs/SETUP.md)\n' "${HARNESS}" > /usr/local/bin/bd-setup-agent ;; \
    esac; \
    chmod +x /usr/local/bin/bd-setup-agent
USER harnessed
# BEADS_DIR is now a static ENV pointing at the host-persisted project-scoped bind-mount
# ($HOME/.beads → $XDG_DATA_HOME/harnessed/persist/beads/<git-common-dir-hash>/.beads/).
# Because the mount target is a fixed container path (not $PWD-relative), the ENV is safe
# to bake here — it won't vary across projects. The bd binary writes its embedded Dolt DB
# to this path; `bd init --quiet --stealth` (run once via `harnessed init`) creates it.
ENV BEADS_DIR=/home/harnessed/.beads
