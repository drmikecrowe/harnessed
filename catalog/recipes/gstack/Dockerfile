# Recipe Dockerfile for: gstack
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# WHAT'S LEFT HERE, AND WHY. gstack's content install (git fetch the pinned commit + run upstream's
# own ./setup) moved to `install.sh`, which runs in BOTH modes — that half was silently missing on a
# `--host` launch (bd harnessed-8px.1). What remains is the one step a host launch structurally
# cannot perform: a root-level apt install. It is declared as `install.system:` in recipe.yaml, so a
# host launch prints the reason and skips it by name instead of failing or pretending.
#
# ORDERING NOTE: this body used to run AFTER install.sh, because the assembler emitted a recipe's
# `install:` block before its Dockerfile body. Since bd harnessed-8px.21.4 that is reversed — every
# Dockerfile body runs at BUILD and every install.sh at container runtime — so these root steps now
# run FIRST. Nothing here depends on install.sh's output, which is what makes the flip safe: the
# chown below hands back ~/.bun after the root `bunx` above touched it, and install-deps only
# supplies the shared libraries Chromium needs to LAUNCH, which nothing in ./setup requires.
USER root
# gstack drives a headless Chromium via Playwright. Its ./setup runs `playwright install chromium`
# (the browser binary) but NOT `playwright install-deps` (the OS shared libraries Chromium needs to
# launch), so on the Ubuntu base the browser downloads yet chromium.launch() fails with
# "Playwright Chromium could not be launched". Install the system deps — bun is in the base image
# and install-deps shells out to apt, hence USER root. THIS is the `install.system:` step.
RUN bunx playwright install-deps chromium
# `bunx` above ran as root with HOME=/home/harnessed, so it can leave root-owned files under ~/.bun
# (bun's cache lives there). Hand bun's home back to the runtime user before the image ships, or a
# later harnessed-user `bun` invocation fails with "unable to write files to tempdir: AccessDenied"
# and the supply-chain scan cannot read the tree.
RUN chown -R harnessed:harnessed /home/harnessed/.bun
# End as the unprivileged runtime user — never leave a recipe layer sitting on root.
USER harnessed
