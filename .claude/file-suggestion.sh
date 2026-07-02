#!/usr/bin/env bash
# Custom @ file-suggestion source. The built-in finder stops at nested .git
# dirs, which excludes contents of the docs/ git submodule. rg --files does
# not stop at submodule boundaries, so it surfaces docs/ paths too.
query=$(cat)
rg --files "${CLAUDE_PROJECT_DIR:-.}" | rg -i "$query"
