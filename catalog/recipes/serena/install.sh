#!/usr/bin/env bash
# install.sh — the serena CLI plus its GLOBAL language-server config, delivered identically by a
# container build and a host launch.
#
# This replaces two halves that used to live apart and disagree:
#   * the Dockerfile's `RUN uv tool install … && serena init -b LSP` — container-only, so a host
#     launch got neither;
#   * setup.sh's step 1, a `HARNESSED_MODE = host` branch that installed serena and nothing else.
# Both are now this one file, run by both executors. What stays in setup.sh is the ONLY part that
# genuinely needs a project: converging `.serena/project.yml`'s project_name on HARNESSED_CFG_NAME.
# Install has no project (see `install.sh` env contract — no HARNESSED_PROJECT_DIR by design).
#
# Env (emit.install_env), identical keys in both modes:
#   HARNESS  HARNESSED_MODE  HARNESSED_RECIPE_DIR  HARNESSED_CONFIG_DIR  HARNESSED_INSTALL_CACHE
set -euo pipefail

# Exact PyPI pin (upstream's canonical install path). No `install.cache` in recipe.yaml: the cache
# keys a CONTENT clone, and uv already caches wheels itself — there is nothing for harnessed to hold.
SERENA_VERSION="1.5.3"

# The CLI itself is `tools: [pipx:serena-agent@…]` in recipe.yaml (bd harnessed-1t4.3) — the same
# pinned wheel install in both modes, resolved by mise's pipx backend through uv, into the merged
# and cached tool layer. What stays here is the CONFIGURATION half, which mise cannot express.
# Keep SERENA_VERSION in lockstep with that pin.

# `serena init` writes the global config that selects the code-intelligence backend. Without it
# `start-mcp-server` comes up with no LSP backend. `-b LSP` is the current default, stated
# explicitly so a future upstream default flip cannot silently change it.
#
# FOOTPRINT NOTE: this writes $HOME/.serena/serena_config.yml — OUTSIDE HARNESSED_CONFIG_DIR. In a
# build that is the image's own home and disappears with the image; on a host launch it is the
# user's real home. README.md documents the removal command (bd harnessed-8px.6).
if [ ! -f "${HOME}/.serena/serena_config.yml" ]; then
    serena init -b LSP
fi
