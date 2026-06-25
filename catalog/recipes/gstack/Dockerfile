# Recipe Dockerfile for: gstack
#
# No FROM line and no `ARG HARNESS` declaration — the assembler prepends
# `FROM harnessed-${HARNESS}:latest` and re-declares `ARG HARNESS` after FROM, so ${HARNESS} is
# available here without the recipe pinning it to a specific harness. Recipes stay harness-independent.
#
# Installs a skill + a command into the Claude-canonical ~/.claude tree. The launcher extracts these
# baked extensions into the assembled profile after building this image, so they are visible to the
# agent (and the capability test) at runtime exactly like recipe-shipped skills.
USER root
RUN mkdir -p /home/harnessed/.claude/skills/gstack-skill /home/harnessed/.claude/commands && \
    printf '%b' '---\nname: gstack-skill\ndescription: Installed by the gstack Dockerfile recipe.\n---\n# gstack skill\nInstalled into the agent image by the gstack recipe Dockerfile.\n' \
      > /home/harnessed/.claude/skills/gstack-skill/SKILL.md && \
    printf '%b' '---\nname: gstack-cmd\ndescription: gstack command installed via the Dockerfile recipe.\n---\n# /gstack-cmd\nRun the gstack workflow.\n' \
      > /home/harnessed/.claude/commands/gstack-cmd.md && \
    chown -R harnessed:harnessed /home/harnessed/.claude
USER harnessed
