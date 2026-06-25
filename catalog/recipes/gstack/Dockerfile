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
# gstack drives a headless Chromium via Playwright. Its ./setup runs `playwright install chromium`
# (the browser binary) but NOT `playwright install-deps` (the OS shared libraries Chromium needs to
# launch), so on the Ubuntu base the browser downloads yet chromium.launch() fails with
# "Playwright Chromium could not be launched". Install the system deps first — bun is in the base
# image and install-deps shells out to apt, hence USER root.
RUN bunx playwright install-deps chromium
RUN git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup
RUN cd ~/.claude/skills/gstack && ./bin/gstack-config set redact_prepush_hook true — /ship
USER harnessed
