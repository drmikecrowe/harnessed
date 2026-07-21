#!/usr/bin/env bash
# install.sh — gitleaks binary + guard script, delivered IDENTICALLY by a container build and a
# host launch. One file, two executors, one outcome.
#
# What it does:
#   1. Downloads the pinned gitleaks release tarball for the host arch (linux x64/arm64).
#   2. Extracts the `gitleaks` binary into $HARNESSED_BIN_DIR.
#   3. Copies `gitleaks-guard` (the PreToolUse hook script) into $HARNESSED_BIN_DIR.
#
# The host content cache ($HARNESSED_INSTALL_CACHE) holds the extracted binary so the per-launch
# re-run — mandatory, because the host home is wiped on every launch — skips the download once
# it has been done. `install.cache` in recipe.yaml keys the cache dir; it MUST match
# GITLEAKS_VERSION below (bump both together to upgrade).
#
# Env is the `install.script` contract (emit.install_env) — same keys in both modes:
#   HARNESSED_BIN_DIR       executables land here; it is on PATH first, so the guard is reachable
#   HARNESSED_CONFIG_DIR    the agent config dir (image ~/.claude | host home)
#   HARNESSED_INSTALL_CACHE pinned-ref content cache; empty when no `install.cache` is declared
#   HARNESSED_MODE          host | container
#   HARNESSED_RECIPE_DIR    this recipe's own directory (source for cp)
#   HARNESS                 the harness being built/launched
# Deliberately NOT available: PROJECT_DIR and friends — a build has no project mounted.
set -euo pipefail

# Pinned release. Must match `install.cache` in recipe.yaml (the host cache key).
# Bump both together; mismatched values produce a permanently stale cache silently.
GITLEAKS_VERSION="8.30.1"
GITLEAKS_TAG="v${GITLEAKS_VERSION}"

: "${HARNESSED_BIN_DIR:?install.sh requires HARNESSED_BIN_DIR}"
: "${HARNESSED_RECIPE_DIR:?install.sh requires HARNESSED_RECIPE_DIR}"

# Detect CPU arch. The gitleaks release naming: linux_x64 / linux_arm64.
arch="$(uname -m)"
case "$arch" in
  x86_64)  gl_arch="x64" ;;
  aarch64) gl_arch="arm64" ;;
  *) echo "gitleaks install.sh: unsupported arch '$arch' — cannot download binary" >&2; exit 1 ;;
esac

TARBALL_URL="https://github.com/gitleaks/gitleaks/releases/download/${GITLEAKS_TAG}/gitleaks_${GITLEAKS_VERSION}_linux_${gl_arch}.tar.gz"

# Cache MISS is "the directory does not exist" — harnessed creates only its parent.
# Populate into a temp sibling and rename, so a partial download is never mistaken for a hit.
src="${HARNESSED_INSTALL_CACHE:-}"
if [ -n "$src" ]; then
    if [ ! -d "$src" ]; then
        tmp="${src}.partial.$$"
        rm -rf "$tmp"
        mkdir -p "$tmp"
        curl -fsSL "$TARBALL_URL" | tar -xz -C "$tmp" gitleaks
        chmod +x "$tmp/gitleaks"
        mv "$tmp" "$src"
    fi
    cp "$src/gitleaks" "$HARNESSED_BIN_DIR/gitleaks"
else
    # No cache declared (should not happen with `install.cache` in recipe.yaml, but be safe).
    curl -fsSL "$TARBALL_URL" | tar -xz -C "$HARNESSED_BIN_DIR" gitleaks
fi
chmod +x "$HARNESSED_BIN_DIR/gitleaks"

# The PreToolUse gate script. install.sh puts it on PATH (via $HARNESSED_BIN_DIR) in both modes —
# replacing the old approach of a Dockerfile COPY that only ran at container build time.
cp "$HARNESSED_RECIPE_DIR/gitleaks-guard" "$HARNESSED_BIN_DIR/gitleaks-guard"
chmod +x "$HARNESSED_BIN_DIR/gitleaks-guard"
