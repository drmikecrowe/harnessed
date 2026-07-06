# Recipe Dockerfile for: superpowers (upstream: Superpowers)
#
# Superpowers' deliverables are a Claude-canonical skills/<name>/SKILL.md tree (14 skills).
# Clone the pinned release tag and copy them into ~/.claude/skills/ — the layout every harness
# plugin install surfaces, minus the plugin-registry wrapping and the Claude-tool SessionStart
# hook (GAP 2; see PLAN Phasing). We deliberately do NOT run any harness plugin installer: each
# delegates to a per-harness plugin system that bypasses the assembler's harness-independent
# fan-out and wires settings.json hooks harnessed can't express today. No Node needed at build —
# skills are pure Markdown (the per-skill JS scripts are opt-in, run on demand at runtime).
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Entirely USER harnessed: the body writes only to ~/.claude/ and /tmp — nothing needs root.
USER harnessed
# Pin Superpowers to an exact release tag. The pin gate accepts tags and full SHAs and rejects
# main/HEAD/@latest; `--branch v6.0.3` is a real release tag, so it passes. Bump
# SUPERPOWERS_REF to update. For maximum reproducibility the SHA form
# (896224c4b1879920ab573417e68fd51d2ccc9072) may also be used.
ARG SUPERPOWERS_REF=v6.0.3
# Privacy + egress: Superpowers' brainstorming visual companion pings primeradiant.com for a
# versioned logo by default. Disable that non-essential telemetry for the baked image. Drop
# this ENV if a stack wants the visual companion telemetry (the egress firewall governs actual
# outbound either way).
ENV SUPERPOWERS_DISABLE_TELEMETRY=1
# Clone the pinned tag and copy the contents of skills/ (trailing-slash `…/.` form) into
# ~/.claude/skills/, so each skill lands at ~/.claude/skills/<name>/ with its sibling
# references/ and scripts/ subtrees intact. Then drop the clone.
RUN set -eu; \
    git clone --quiet --depth 1 --branch "${SUPERPOWERS_REF}" \
        https://github.com/obra/superpowers.git /tmp/superpowers && \
    mkdir -p ~/.claude/skills && \
    cp -r /tmp/superpowers/skills/. ~/.claude/skills/ && \
    rm -rf /tmp/superpowers
# (body ends as USER harnessed — nothing here needs root)
