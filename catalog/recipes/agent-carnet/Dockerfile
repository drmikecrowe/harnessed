# Recipe Dockerfile for: agent-carnet
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# agent-carnet is a pure-JS Node CLI bundled to dist/bin/agent-carnet.mjs — no native binary release,
# so the pnpm global install is the ONLY install path (the published tarball already ships dist/, so
# no build scripts are needed). Pure JS means no apt/system deps, so the whole body runs as the
# unprivileged user — no USER root needed.
USER harnessed
# Pin to the exact published version (no @latest — the assembler pin gate rejects floating refs).
# pnpm only; the emit lint rejects raw npm/npx.
ARG AGENT_CARNET_VERSION=0.1.5
RUN pnpm add -g agent-carnet@${AGENT_CARNET_VERSION}
# Verify the global bin resolves on PATH for the harnessed user before the layer is trusted.
RUN agent-carnet --version
# Install the skill agent-carnet BUNDLES in its npm tarball (skills/agent-carnet/: SKILL.md +
# references/{cookbook,frontmatter}.md). Copy it verbatim from the just-pinned global package into the
# container's ~/.claude/skills/agent-carnet — no second source, no floating ref.
#
# `pnpm root -g` does NOT contain a flat `agent-carnet/` subdir the way a local install would —
# pnpm's global store nests the package under a hashed import-context dir plus its own
# `node_modules/` (verified against a real `pnpm add -g agent-carnet` install:
# `<root>/<hash>/node_modules/agent-carnet/...`, itself a symlink into pnpm's content-addressable
# store). A single global `pnpm add` can register more than one import-context hash for the same
# resolved version, so glob + take the first match rather than assume exactly one; `cp -rL`
# dereferences the symlink into a real copy.
RUN mkdir -p "$HOME/.claude/skills" \
 && skill_src=$(printf '%s\n' "$(pnpm root -g)"/*/node_modules/agent-carnet/skills/agent-carnet | head -1) \
 && cp -rL "$skill_src" "$HOME/.claude/skills/agent-carnet" \
 && test -f "$HOME/.claude/skills/agent-carnet/SKILL.md"
