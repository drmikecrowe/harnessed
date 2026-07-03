# Recipe Dockerfile for: caveman
#
# caveman's deliverables are already Claude-canonical skills/ + commands/ + agents/ trees. Clone
# the pinned release tag and copy them into ~/.claude/ — the exact layout `claude plugin install`
# drops, minus the plugin-registry wrapping and the Claude-tool hooks (GAP 2; see PLAN.md
# Phasing).
#
# We deliberately do NOT run bin/install.js: it delegates to per-harness plugin systems
# (claude plugin marketplace add / gemini extensions install / npx skills add) that (a) bypass the
# assembler's harness-independent fan-out, (b) need network + the harness binary at build time,
# and (c) wire settings.json/plugin.json hooks harnessed can't express today (GAP 2). Replicating
# the installer's result deterministically is the faithful move.
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# No Node needed — skills/commands/agents are pure Markdown/TOML. Only the JS hooks (omitted, GAP
# 2) need Node, so there is no apt/pnpm/runtime dep: the lightest possible body.
#
# Entirely as USER harnessed (writes only to ~/.claude/ + /tmp); no system install, so no
# USER root phase is needed (gstack assumes the same writable ~/.claude in the base image).
USER harnessed
# Pin caveman to an exact release tag — the assembler pin gate accepts tags and SHAs, rejects
# main/HEAD/@latest. `--branch v1.9.0` is a real published tag. For maximum reproducibility use
# fetch-by-SHA as gstack does: CAVEMAN_REF=32f37af81a02a4b91c107b768f1365848e5bf005 with
# `git init … && git remote add … && git fetch --depth 1 origin ${CAVEMAN_REF} && git checkout -q
# FETCH_HEAD`. Bump CAVEMAN_REF to update; if switching to a SHA use the full 40-char form.
ARG CAVEMAN_REF=v1.9.0
# `cp -r …/.` (trailing-slash contents form) puts skills/caveman -> ~/.claude/skills/caveman, NOT
# ~/.claude/skills/caveman/skills/caveman — the probe paths in `expect:` resolve against the flat
# layout this produces.
RUN set -eu; \
    git clone --quiet --depth 1 --branch "${CAVEMAN_REF}" \
        https://github.com/JuliusBrussee/caveman.git /tmp/caveman && \
    mkdir -p ~/.claude/skills ~/.claude/commands ~/.claude/agents && \
    cp -r /tmp/caveman/skills/.   ~/.claude/skills/ && \
    cp -r /tmp/caveman/commands/. ~/.claude/commands/ && \
    cp -r /tmp/caveman/agents/.   ~/.claude/agents/ && \
    rm -rf /tmp/caveman
