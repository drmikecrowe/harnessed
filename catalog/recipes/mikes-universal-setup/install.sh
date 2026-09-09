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
# HOLD / manual-upgrade only: a skill is agent instructions no scanner vets. That is DECLARED, not
# just described — `install.hold` in recipe.yaml, plus a per-ref `hold:` naming each ref's class, is
# what `harnessed update` reads to keep these out of its bump set (bd harnessed-c5t, #329 AC-2).
#
# NO PIN LITERALS HERE (Phase 3 of #329) — not even in a comment, which is why this file names no
# SHA and no owner/repo anywhere. Three `*_SHA=` assignments used to sit below, kept in sync with a
# hand-mashed `install.cache` by a comment asking the reader to bump four things. The pins now live
# in `install.refs:` alone and arrive as env; the cache key is DERIVED from them.
set -euo pipefail

# `:?` rather than a default: an unset ref means the manifest and this script disagree about the key
# name, and a default would paper over that by fetching the default branch. Six variables, six
# guards — each earns its own, so none can be deleted silently. `:?` fires on empty as well as
# unset, which is what a key-name mismatch actually produces.
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"
: "${HARNESSED_REF_OAKOSS:?install.sh requires HARNESSED_REF_OAKOSS (install.refs.oakoss.ref)}"
: "${HARNESSED_REPO_OAKOSS:?install.sh requires HARNESSED_REPO_OAKOSS (install.refs.oakoss.repo)}"
: "${HARNESSED_REF_BLADER:?install.sh requires HARNESSED_REF_BLADER (install.refs.blader.ref)}"
: "${HARNESSED_REPO_BLADER:?install.sh requires HARNESSED_REPO_BLADER (install.refs.blader.repo)}"
: "${HARNESSED_REF_AMINBLG:?install.sh requires HARNESSED_REF_AMINBLG (install.refs.aminblg.ref)}"
: "${HARNESSED_REPO_AMINBLG:?install.sh requires HARNESSED_REPO_AMINBLG (install.refs.aminblg.repo)}"

# The URL is built by the CALLER, not inside fetch(), and that is deliberate. The pin gate
# (`_mutable_archive_ref`) resolves a NAMED variable in an archive URL against `install.refs:`, but
# PASSES THROUGH a positional parameter — the ref is not knowable from `https://…/archive/$2.tar.gz`.
# While this script hid its refs behind `fetch()`'s `$2`, the gate neither rejected nor PROVED these
# pins; it declined to look (bd harnessed-po7, recorded as a residual gap). Naming the variable on
# the URL line turns that pass-through into an actual check, for all three refs.
fetch() {  # $1=archive URL  $2=dest dir → leaves the archive's <repo>-<ref>/ root inside $2
    mkdir -p "$2"
    curl -fsSL "$1" -o "$2/src.tgz"
    tar -xzf "$2/src.tgz" -C "$2"
    rm -f "$2/src.tgz"
}

# GitHub names a source archive's root directory `<repo>-<ref>/`, where <repo> is the bare repo name
# with no owner. Derive it from the same variable the fetch used, so a ref change can never leave
# the copy steps below reading a stale path.
oak_url="https://github.com/${HARNESSED_REPO_OAKOSS}/archive/${HARNESSED_REF_OAKOSS}.tar.gz"
hum_url="https://github.com/${HARNESSED_REPO_BLADER}/archive/${HARNESSED_REF_BLADER}.tar.gz"
ste_url="https://github.com/${HARNESSED_REPO_AMINBLG}/archive/${HARNESSED_REF_AMINBLG}.tar.gz"

# Populate the pinned-content cache atomically (temp+rename), so an interrupted download can never be
# mistaken for a populated cache. Falls back to a throwaway tmp when no cache is declared.
cache="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$cache" ]; then
    if [ ! -d "$cache" ]; then
        tmp="${cache}.partial.$$"; rm -rf "$tmp"; mkdir -p "$tmp"
        fetch "$oak_url" "$tmp/oakoss"
        fetch "$hum_url" "$tmp/blader"
        fetch "$ste_url" "$tmp/aminblg"
        mv "$tmp" "$cache"
    fi
else
    cache="$(mktemp -d)"; trap 'rm -rf "$cache"' EXIT
    fetch "$oak_url" "$cache/oakoss"
    fetch "$hum_url" "$cache/blader"
    fetch "$ste_url" "$cache/aminblg"
fi

mkdir -p "$HARNESSED_CONFIG_DIR/skills"

# oakoss: directory-skills at skills/<name>/.
oak="$cache/oakoss/${HARNESSED_REPO_OAKOSS##*/}-${HARNESSED_REF_OAKOSS}/skills"
for s in application-security mermaid-diagrams mise python-uv skill-management; do
    rm -rf "$HARNESSED_CONFIG_DIR/skills/$s"
    cp -rL "$oak/$s" "$HARNESSED_CONFIG_DIR/skills/$s"
    # Fail loudly rather than ship an empty skill dir — the failure mode bd harnessed-8px.1 was.
    test -f "$HARNESSED_CONFIG_DIR/skills/$s/SKILL.md"
done

# blader (ref key): a single SKILL.md at the repo root → wrap it into skills/humanizer/. The repo is
# named once, in the manifest — a comment copy drifts the same way an assignment does.
hum="$cache/blader/${HARNESSED_REPO_BLADER##*/}-${HARNESSED_REF_BLADER}"
rm -rf "$HARNESSED_CONFIG_DIR/skills/humanizer"
mkdir -p "$HARNESSED_CONFIG_DIR/skills/humanizer"
cp -L "$hum/SKILL.md" "$HARNESSED_CONFIG_DIR/skills/humanizer/SKILL.md"
test -f "$HARNESSED_CONFIG_DIR/skills/humanizer/SKILL.md"

# aminblg (ref key): a directory-skill at skills/simple-english/ (SKILL.md + references/).
ste="$cache/aminblg/${HARNESSED_REPO_AMINBLG##*/}-${HARNESSED_REF_AMINBLG}/skills/simple-english"
rm -rf "$HARNESSED_CONFIG_DIR/skills/simple-english"
cp -rL "$ste" "$HARNESSED_CONFIG_DIR/skills/simple-english"
test -f "$HARNESSED_CONFIG_DIR/skills/simple-english/SKILL.md"
