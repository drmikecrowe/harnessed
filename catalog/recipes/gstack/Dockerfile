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
# Pin gstack to an exact commit (upstream publishes no release tags). Shallow fetch-by-SHA — GitHub
# allows fetching a reachable commit. Bump GSTACK_REF to update; use the full 40-char SHA.
ARG GSTACK_REF=11de390be1be6849eb9a15f91ff4922dd16c589a
RUN git init -q ~/.claude/skills/gstack \
    && cd ~/.claude/skills/gstack \
    && git remote add origin https://github.com/garrytan/gstack.git \
    && git fetch --depth 1 origin ${GSTACK_REF} \
    && git checkout -q FETCH_HEAD \
    && ./setup
RUN cd ~/.claude/skills/gstack && ./bin/gstack-config set redact_prepush_hook true -- /ship
USER harnessed
