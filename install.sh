#!/bin/bash
# harnessed installer
# Usage: curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash
#
# What this script does (nothing hidden):
#   1. Clones the repo to ~/.local/share/code-container (or pulls if already present)
#   2. Symlinks `harnessed` into a directory on your PATH
#      - Prefers ~/.local/bin if it's on your PATH (no sudo needed)
#      - Falls back to /usr/local/bin via sudo

set -euo pipefail

REPO_URL="https://github.com/drmikecrowe/code-container.git"
INSTALL_DIR="$HOME/.local/share/code-container"
BINARIES=("harnessed")

# --- Helpers ---

info()  { echo -e "\033[0;34m==>\033[0m $1"; }
ok()    { echo -e "\033[0;32m==>\033[0m $1"; }
warn()  { echo -e "\033[1;33m==>\033[0m $1"; }
err()   { echo -e "\033[0;31m==>\033[0m $1" >&2; }

# --- Pre-flight checks ---

if ! command -v git >/dev/null 2>&1; then
    err "git is required but not found. Please install git first."
    exit 1
fi

if ! command -v podman >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
    warn "Neither podman nor docker found. You'll need one before running harnessed."
fi

# --- Step 1: Clone or update the repo ---

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only origin main
    ok "Updated to latest"
else
    info "Cloning $REPO_URL -> $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned successfully"
fi

chmod +x "$INSTALL_DIR/harnessed"
chmod +x "$INSTALL_DIR"/lib/*.sh 2>/dev/null || true

# --- Step 2: Symlink into PATH ---

# Choose a PATH dir: prefer ~/.local/bin (no sudo), else /usr/local/bin (sudo).
if echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    LINK_DIR="$HOME/.local/bin"
    SUDO=""
    mkdir -p "$LINK_DIR"
else
    LINK_DIR="/usr/local/bin"
    SUDO="sudo"
    warn "~/.local/bin is not on your PATH; falling back to $LINK_DIR (requires sudo)"
fi

for bin in "${BINARIES[@]}"; do
    SOURCE="$INSTALL_DIR/$bin"
    LINK_TARGET="$LINK_DIR/$bin"
    if [ -L "$LINK_TARGET" ] || [ -e "$LINK_TARGET" ]; then
        info "Removing existing $LINK_TARGET"
        $SUDO rm "$LINK_TARGET"
    fi
    info "Symlinking $SOURCE -> $LINK_TARGET"
    $SUDO ln -s "$SOURCE" "$LINK_TARGET"
    ok "Installed $bin -> $LINK_TARGET"
done

# --- Step 3: Verify ---

if command -v harnessed >/dev/null 2>&1; then
    ok "Done! Run 'harnessed build' to build the images, then build and run a stack: 'harnessed build tracer-time && harnessed tracer-time'."
else
    warn "Installed, but 'harnessed' isn't found on PATH. You may need to restart your shell."
fi
