# Recipe Dockerfile for: hyperpowers
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# hyperpowers' deliverables are a Claude-canonical skills/ + commands/ + agents/ tree (22 skills,
# 10 commands, 5 subagents). Clone the pinned commit and copy them into ~/.claude/ — the exact
# layout `claude plugin install` drops, minus the plugin-registry wrapping and the Claude-tool
# hooks (GAP 2; see PLAN Phasing). We deliberately do NOT run the plugin installer: it bypasses
# the assembler's harness-independent fan-out, needs the claude binary + network at build time,
# and wires settings.json hooks harnessed can't express. No Node/apt needed — deliverables are
# pure Markdown.
USER harnessed
# Upstream publishes NO tags/releases, so pin to the full SHA of main HEAD (fetch-by-SHA). A
# floating `--branch main` clone fails the assembler pin gate.
ARG HYPERPOWERS_REF=7905547b6eb0665d631dd1e4f557e3863cd7a1b4
RUN set -euo pipefail; \
    git init -q /tmp/hp && cd /tmp/hp \
    && git remote add origin https://github.com/withzombies/hyperpowers.git \
    && git fetch --depth 1 origin "${HYPERPOWERS_REF}" && git checkout -q FETCH_HEAD \
    && mkdir -p ~/.claude/skills ~/.claude/commands ~/.claude/agents \
    && cp -r /tmp/hp/skills/.   ~/.claude/skills/ \
    && cp -r /tmp/hp/commands/. ~/.claude/commands/ \
    && cp -r /tmp/hp/agents/.   ~/.claude/agents/ \
    && rm -rf /tmp/hp
# (body ends as USER harnessed — nothing here needs root)
