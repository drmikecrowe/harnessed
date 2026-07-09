# Recipe Dockerfile for: gsd-core
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Upstream install docs (docs.opengsd.net/core/installation) say `npx @opengsd/gsd-core@latest`,
# an interactive installer that writes runtime-specific commands/agents/workflows/hooks into the
# target config dir. We replicate that exactly, substituting pnpm dlx for npx (no raw npm/npx) and
# passing the documented non-interactive flags (`--claude --global`) instead of relying on the
# interactive prompts, since there is no TTY during `podman build`. `--global` writes to
# os.homedir()/.claude — i.e. ~/.claude for the harnessed user — which is exactly the profile
# directory the assembler bakes, so the installed commands/agents land where Claude Code expects
# them with no extra wiring.
USER harnessed
# Pin to the latest published stable release (upstream ships no `stable` dist-tag beyond `latest`
# itself; `1.6.1` is an exact version pin, not a floating `@latest`). Bump GSD_CORE_VERSION to update.
ARG GSD_CORE_VERSION=1.6.1
RUN pnpm dlx "@opengsd/gsd-core@${GSD_CORE_VERSION}" --claude --global
