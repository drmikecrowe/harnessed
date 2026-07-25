#!/usr/bin/env bash
# install.sh — BRIDGE (bd harnessed-197). Fetch UNMODIFIED third-party skills at PINNED COMMIT SHAs
# and install them into $HARNESSED_CONFIG_DIR/skills (both container build and host launch). This is
# deliberately temporary: the end state is consuming the vercel `skills` CLI + skills-lock.json, but
# that CLI cannot pin to a SHA and does NOT verify content on restore (proven 2026-07-24:
# experimental_install installs despite a wrong computedHash; `add repo#<sha>` fails because it
# clones a branch, not a commit). Until vercel-labs/skills #1439 (SHA pin) + #463/#549 (verify /
# real install) land, harnessed provides the pin+verify the ecosystem lacks. DELETE this when they do.
#
# Only unmodified third-party skills live here — the NIH rule: don't vendor what you can reference by
# pin. Skills modified locally (defuddle, tdd, map-codebase) or authored here (varlock, wrangler)
# stay vendored under skills/, because there is nothing upstream to point at.
#
# HOLD / manual-upgrade only: a skill is agent instructions no scanner vets. Bump a SHA below only
# after a human reads the upstream diff, and keep `install.cache` in recipe.yaml in sync so the fetch
# cache invalidates. harnessed-tfm must not auto-bump these (bd memory skill-pins-are-manual-upgrade-only).
set -euo pipefail
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# Pinned sources — commit SHAs, never tags (a tag moves; gsd-build is why).
OAKOSS_SHA=0283bed313563d5677a0838f4bf921b03296cf6c   # oakoss/agent-skills — 5 dir-skills
BLADER_SHA=1b48564898e999219882660237fde01bf4843a0f   # blader/humanizer   — 1 single-file skill

fetch() {  # $1=owner/repo  $2=sha  $3=dest → leaves the archive's <repo>-<sha>/ root inside $3
    mkdir -p "$3"
    curl -fsSL "https://github.com/$1/archive/$2.tar.gz" -o "$3/src.tgz"
    tar -xzf "$3/src.tgz" -C "$3"
    rm -f "$3/src.tgz"
}

# Populate the pinned-content cache atomically (temp+rename), so an interrupted download can never be
# mistaken for a populated cache. Falls back to a throwaway tmp when no cache is declared.
cache="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$cache" ]; then
    if [ ! -d "$cache" ]; then
        tmp="${cache}.partial.$$"; rm -rf "$tmp"; mkdir -p "$tmp"
        fetch oakoss/agent-skills "$OAKOSS_SHA" "$tmp/oakoss"
        fetch blader/humanizer    "$BLADER_SHA" "$tmp/blader"
        mv "$tmp" "$cache"
    fi
else
    cache="$(mktemp -d)"; trap 'rm -rf "$cache"' EXIT
    fetch oakoss/agent-skills "$OAKOSS_SHA" "$cache/oakoss"
    fetch blader/humanizer    "$BLADER_SHA" "$cache/blader"
fi

mkdir -p "$HARNESSED_CONFIG_DIR/skills"

# oakoss: directory-skills at skills/<name>/.
oak="$cache/oakoss/agent-skills-${OAKOSS_SHA}/skills"
for s in application-security mermaid-diagrams mise python-uv skill-management; do
    rm -rf "$HARNESSED_CONFIG_DIR/skills/$s"
    cp -rL "$oak/$s" "$HARNESSED_CONFIG_DIR/skills/$s"
    # Fail loudly rather than ship an empty skill dir — the failure mode bd harnessed-8px.1 was.
    test -f "$HARNESSED_CONFIG_DIR/skills/$s/SKILL.md"
done

# blader/humanizer: a single SKILL.md at the repo root → wrap it into skills/humanizer/.
hum="$cache/blader/humanizer-${BLADER_SHA}"
rm -rf "$HARNESSED_CONFIG_DIR/skills/humanizer"
mkdir -p "$HARNESSED_CONFIG_DIR/skills/humanizer"
cp -L "$hum/SKILL.md" "$HARNESSED_CONFIG_DIR/skills/humanizer/SKILL.md"
test -f "$HARNESSED_CONFIG_DIR/skills/humanizer/SKILL.md"
