#!/usr/bin/env bash
set -euo pipefail
# Runs once, in the mounted project dir ($PWD = project root), the first time this project is opened
# (when .beads/ is absent). Git-free + stealth: .beads/ lives in the project folder, no git hooks,
# no commits, no repo discovery. Idempotent — bd init is a no-op if .beads/ already exists.
export BEADS_DIR="$PWD/.beads"
bd init --quiet --stealth
