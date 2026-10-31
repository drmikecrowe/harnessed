#!/usr/bin/env bash
# GH-649 fixture install: writes a marker into the config dir the install runs against.
set -euo pipefail
# A test sets GH649_FAIL_INSTALL to make this install fail.
if [ -n "${GH649_FAIL_INSTALL:-}" ]; then exit 1; fi
mkdir -p "$CLAUDE_CONFIG_DIR/x"
echo marker > "$CLAUDE_CONFIG_DIR/x/marker"
