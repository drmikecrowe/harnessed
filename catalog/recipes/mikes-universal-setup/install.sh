#!/usr/bin/env bash
# install.sh — fetch the five byte-identical oakoss skills at a PINNED COMMIT SHA and install them
# into HARNESSED_CONFIG_DIR/skills/ (BOTH modes: container build and host launch). bd harnessed-s8l.
#
# WHY fetch instead of vendor: these five were exact copies of github.com/oakoss/agent-skills
# (verified byte-identical, SKILL.md + every references/ file). Hand-copying them meant silent drift
# and redistributing third-party content in the wheel with no licence notice. Fetching at build time
# from an immutable SHA removes both problems — the bytes are never copied by hand and never shipped.
#
# HOLD — MANUAL UPGRADE ONLY. OAKOSS_SHA below is a SECURITY BOUNDARY, not a maintenance pin. A skill
# is agent INSTRUCTIONS run with the agent's full tool permissions, so upgrading it pulls new
# instructions that no scanner can vet (a compromised skill is prompt-injection, not a CVE — see the
# gsd-build incident). Bumping it therefore requires a human to read the diff of the new SHA and
# re-approve. harnessed-tfm (the pin auto-updater) MUST NOT auto-bump this. See bd memory
# `skill-pins-are-manual-upgrade-only` and beads harnessed-s8l / harnessed-tfm.
#
# Env is the `install.script` contract (emit.install_env), same keys in both modes:
#   HARNESSED_CONFIG_DIR    the agent config dir to install INTO (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when the recipe declares no `install.cache`
#   HARNESSED_MODE          host | container
set -euo pipefail

# Must equal `install.cache` in recipe.yaml — bump BOTH together (and only after a human diff review),
# which also yields a fresh cache dir. A commit SHA, never a tag: a tag is a movable pointer an
# attacker with push access can repoint, which is exactly how a repo compromise reaches pinned
# consumers (gsd-build). A 40-hex commit cannot be moved.
OAKOSS_SHA="0283bed313563d5677a0838f4bf921b03296cf6c"
OAKOSS_TARBALL="https://github.com/oakoss/agent-skills/archive/${OAKOSS_SHA}.tar.gz"

# The five skills to install. Anything MODIFIED locally (map-codebase, tdd, defuddle) is NOT here and
# stays vendored under skills/ — a fetch would discard the local edits.
SKILLS="application-security mermaid-diagrams mise python-uv skill-management"

: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

fetch_pkg() {  # $1 = destination dir; leaves the archive's `agent-skills-<sha>/` root inside it
    mkdir -p "$1"
    curl -fsSL "$OAKOSS_TARBALL" -o "$1/oakoss.tgz"
    tar -xzf "$1/oakoss.tgz" -C "$1"
    rm -f "$1/oakoss.tgz"
}

# Cache MISS is "the directory does not exist" — harnessed creates only its parent. Populate a temp
# sibling and rename, so an interrupted download can never be mistaken for a populated cache.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        fetch_pkg "$tmp"
        mv "$tmp" "$src"
    fi
else
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    fetch_pkg "$src"
fi

# GitHub archive tarballs root at `<repo>-<sha>/`; the skills ship at <root>/skills/<name>/.
root="$src/agent-skills-${OAKOSS_SHA}"
mkdir -p "$HARNESSED_CONFIG_DIR/skills"
for skill in $SKILLS; do
    rm -rf "$HARNESSED_CONFIG_DIR/skills/$skill"
    cp -rL "$root/skills/$skill" "$HARNESSED_CONFIG_DIR/skills/$skill"
    # Fail loudly rather than ship an empty skill dir — the exact failure mode bd harnessed-8px.1 was.
    test -f "$HARNESSED_CONFIG_DIR/skills/$skill/SKILL.md"
done
