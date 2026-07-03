#!/usr/bin/env bash
set -euo pipefail
# Runs once, in the mounted project dir ($PWD = project root), the first time this project is opened
# (when .carnet/ is absent). Git-free + non-touching: plain `agent-carnet init` creates .carnet/ and
# writes NO .gitignore entry, no git hooks, no repo discovery — the --gitignore flag is intentionally
# omitted (mirrors beads' --stealth posture). Idempotent — and additionally gated by when_missing, so
# re-launches never reach here.
agent-carnet init
