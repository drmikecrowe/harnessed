# Recipe Dockerfile for: agent-carnet
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# CLI and skill are both delivered by install.sh (both modes — container build and host launch).
# install.sh runs at container RUNTIME into the stack's volumes (bd harnessed-8px.21.4), not as an
# image layer, so no separate
# RUN is needed here. agent-carnet is pure JS (no native binary, no apt/system deps).
USER harnessed
# Version anchor: must stay in sync with AGENT_CARNET_VERSION in install.sh and `install.cache`
# in recipe.yaml. Verified by test_one_version_literal_binds_the_cli_and_the_skill.
ARG AGENT_CARNET_VERSION=0.1.5
