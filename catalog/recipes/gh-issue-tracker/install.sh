#!/usr/bin/env bash
# install.sh — post-vendor fixups for the gh-issue-tracker skill.
#
# This recipe fetches NOTHING. Everything it ships is vendored under skills/ and everything it
# needs from the outside is a pinned `tools:` entry. So there is no cache key and no `hold`: there
# is no upstream ref here for `harnessed update` to bump.
#
# Two jobs, both of which the `skills:` copy cannot do on its own:
#
#   1. RESTORE THE EXECUTABLE BIT. The skill's scripts are vendored mode 0600 and arrive in the
#      assembled profile mode 0600 — verified 2026-08-08, where `ready.sh --limit 8` failed with
#      "permission denied" against a real profile. prime.sh is worse than ready.sh here: it is
#      invoked by a SessionStart hook, so a non-executable copy fails on EVERY session open rather
#      than at the moment someone runs the command by hand. Also fixed at the source (the vendored
#      files are 0755 now), but this stays: it is one chmod, it is idempotent, and it makes the
#      recipe correct regardless of what any future copy step does to the mode.
#
#   2. ENFORCE THE gh FLOOR. gh >= 2.94.0 is where --parent/--blocked-by/--blocking and the
#      blockedBy/parent/subIssues JSON fields landed. Below it the skill does not error — it
#      degrades into writing relationship PROSE into issue bodies, which reads fine and is
#      unqueryable. That is the failure worth catching at build time rather than three weeks into a
#      backlog. Checked, not assumed: `tools:` pins gh, but a host launch resolves whatever gh the
#      user's PATH offers.
set -euo pipefail
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

skill="$HARNESSED_CONFIG_DIR/skills/gh-issue-tracker"

# 1. Executable bit. Guarded rather than assumed: on a host launch the skill dir is materialized by
#    the same run, but ordering is the assembler's business, not this script's.
if [ -d "$skill/scripts" ]; then
    chmod +x "$skill"/scripts/*.sh
    # Fail loudly rather than ship a skill whose entry points do not run.
    test -x "$skill/scripts/ready.sh"
    test -x "$skill/scripts/prime.sh"
    test -x "$skill/scripts/claim.sh"
fi

# 2. gh version floor. A missing gh is NOT fatal here — the container build installs it from the
#    pinned `tools:` layer, which may not be on PATH at the moment this runs, and prime.sh already
#    no-ops silently when gh is absent at runtime. An OLD gh is fatal, because that is the silent
#    one.
if command -v gh >/dev/null 2>&1; then
    have="$(gh --version 2>/dev/null | head -1 | sed -E 's/.*gh version ([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
    need=2.94.0
    # Pure-sort version compare: the lower of {have, need} sorted first must be `need`.
    if [ "$(printf '%s\n%s\n' "$have" "$need" | sort -V | head -1)" != "$need" ]; then
        echo "gh-issue-tracker: gh $have is below the required $need." >&2
        echo "  Below $need, 'gh issue create --parent/--blocked-by' does not exist and the skill" >&2
        echo "  silently falls back to unqueryable prose in the issue body. Upgrade gh." >&2
        exit 1
    fi
fi
