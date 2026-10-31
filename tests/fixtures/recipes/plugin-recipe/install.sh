#!/usr/bin/env bash
# GH-649 fixture install: writes a marker into the config dir the install runs against.
set -euo pipefail
mkdir -p "$CLAUDE_CONFIG_DIR/x"
echo marker > "$CLAUDE_CONFIG_DIR/x/marker"
