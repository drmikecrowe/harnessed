# Recipe Dockerfile for: gstack
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Authoring a Dockerfile recipe = run the project's OWN documented install commands. gstack's docs
# say "git clone + ./setup", so that's what we run (the same as on the host); ./setup bakes its
# skills into ~/.claude/skills, and the launcher merges those into the profile so they're live at
# runtime. The only addition is the one OS dependency gstack's ./setup omits (Playwright's libs).
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
