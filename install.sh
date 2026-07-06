#!/usr/bin/env sh
# harnessed installer — checked-in, reviewable, POSIX sh.
#
#   ./install.sh                 install the `harnessed` CLI (pinned source)
#   ./install.sh --force         reinstall / upgrade in place (idempotent)
#   ./install.sh --install-uv    also install uv (user-space) if it is missing
#   ./install.sh --uninstall     remove the CLI; leaves your data untouched
#   ./install.sh --help          usage
#
# This is the honest, auditable form of the manual steps in README §Install.
# The `curl -fsSL <raw-tag-url>/install.sh | sh` one-liner is a documented
# convenience alias for THIS file at a pinned tag — never the primary path,
# and never pointed at a moving branch. Read it before you run it.
#
# Posture: this project preaches "pin every download" (recipe Dockerfiles
# reject floating refs). The installer follows the same ethos — it installs
# from a pinned git tag, never a bare clone of `main`, and it refuses to run
# anything privileged (no sudo, no package-manager writes, no podman
# auto-install) on your behalf.
set -eu

# ── configuration (single pin point) ──────────────────────────────────────
# VERSION is the git tag the CLI is installed from. It MUST be an existing
# tag, never a branch. As of this writing NO release tag has been cut yet:
# `v0.1.0` is a placeholder that matches pyproject `version = "0.1.0"`.
#   >>> OUTSTANDING RELEASE ACTION: cut and push tag `v0.1.0` before this
#   >>> installer can succeed against the repo source. Until then the
#   >>> `uv tool install git+...@v0.1.0` step will fail to resolve the ref.
# Override for local testing with HARNESSED_VERSION=<tag> ./install.sh
VERSION="${HARNESSED_VERSION:-v0.1.0}"

REPO="https://github.com/drmikecrowe/harnessed.git"

# SOURCE selects where the CLI comes from: `repo` (pinned git tag, the only
# source that exists today) or `pypi` (once published). Flip the default here
# — or export HARNESSED_SOURCE=pypi — after the first PyPI release; nothing
# else in the script changes.
SOURCE="${HARNESSED_SOURCE:-repo}"

PODMAN_MIN_MAJOR=4          # advisory floor; the reference runtime is podman >= 4.0

# ── flags ──────────────────────────────────────────────────────────────────
INSTALL_UV=0
FORCE=0
ACTION="install"

usage() {
  cat <<'EOF'
usage: install.sh [--uninstall] [--install-uv] [--force] [--help]

  (no args)     install the `harnessed` CLI from a pinned source onto your PATH
  --force       reinstall / upgrade even if already installed (idempotent)
  --install-uv  install uv (user-space, single binary) if it is missing;
                without this flag a missing uv is reported, not installed
  --uninstall   remove the `harnessed` CLI; preserves ~/.config/harnessed and
                $XDG_DATA_HOME/harnessed, and leaves podman in place
  --help, -h    show this message

Requirements the installer DETECTS but never installs for you:
  * podman (rootless) — the reference runtime; install with your distro
  * uv                — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
                        or pass --install-uv to have this script do it (user-space only)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --uninstall)  ACTION="uninstall" ;;
    --install-uv) INSTALL_UV=1 ;;
    --force)      FORCE=1 ;;
    -h|--help)    usage; exit 0 ;;
    *) printf 'error: unknown argument: %s\n\n' "$arg" >&2; usage >&2; exit 2 ;;
  esac
done

# ── helpers ────────────────────────────────────────────────────────────────
say()  { printf '%s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

data_dirs() {
  # user data the installer must never touch
  info "config: ${XDG_CONFIG_HOME:-$HOME/.config}/harnessed"
  info "data:   ${XDG_DATA_HOME:-$HOME/.local/share}/harnessed"
}

podman_install_hint() {
  # Print the most relevant distro command first (best-effort), then the rest.
  distro=""
  # shellcheck disable=SC1091
  [ -r /etc/os-release ] && distro="$(. /etc/os-release 2>/dev/null; printf '%s' "${ID:-}")"
  case "$distro" in
    arch|manjaro|endeavouros|cachyos) info "sudo pacman -S podman" ;;
    debian|ubuntu|pop|linuxmint)      info "sudo apt install podman" ;;
    fedora|rhel|centos|rocky|almalinux) info "sudo dnf install podman" ;;
    *)
      info "arch:   sudo pacman -S podman"
      info "debian: sudo apt install podman"
      info "fedora: sudo dnf install podman"
      ;;
  esac
}

# ── (5) platform guard ─────────────────────────────────────────────────────
os="$(uname -s)"
case "$os" in
  Linux) : ;;
  Darwin)
    say "macOS support is pending Apple-container networking (tracked)."
    say "The harnessed CLI is Linux-only today — no runtime is verified on macOS."
    exit 0
    ;;
  *) die "unsupported platform: $os — harnessed is Linux-only." ;;
esac

# ── (4) uninstall path ─────────────────────────────────────────────────────
if [ "$ACTION" = "uninstall" ]; then
  say "Uninstalling the harnessed CLI (your data is preserved):"
  if have uv && uv tool list 2>/dev/null | grep -q '^harnessed'; then
    uv tool uninstall harnessed
    say "removed: harnessed CLI (via uv tool)."
  elif have pipx && pipx list 2>/dev/null | grep -q 'package harnessed'; then
    pipx uninstall harnessed
    say "removed: harnessed CLI (via pipx)."
  else
    say "harnessed CLI not found via uv or pipx — nothing to remove."
  fi
  say ""
  say "left in place on purpose (not removed):"
  info "podman — the installer never installed it, so it never removes it"
  data_dirs
  exit 0
fi

# ── plan: echo what this run will do BEFORE doing it ───────────────────────
case "$SOURCE" in
  repo) src_desc="git+${REPO}@${VERSION}  (pinned tag)" ;;
  pypi) src_desc="harnessed==${VERSION#v}  (PyPI)" ;;
  *)    die "bad SOURCE '$SOURCE' — expected 'repo' or 'pypi'." ;;
esac

action_desc="install"
[ "$FORCE" = 1 ] && action_desc="install (--force / reinstall)"
uv_desc="uv (detected, not installed)"
[ "$INSTALL_UV" = 1 ] && uv_desc="uv (--install-uv: will install if missing)"

say "harnessed installer"
say "  platform : ${os}"
say "  action   : ${action_desc}"
say "  source   : ${src_desc}"
say "  installs : the harnessed CLI into ~/.local/bin"
say "  requires : podman (detected, not installed) + ${uv_desc}"
say "  preserves: your config/data dirs (never touched)"
say ""

# ── (2) detect deps — instruct, do not auto-install (uv is the opt-in exception) ──
if ! have uv; then
  if [ "$INSTALL_UV" = 1 ]; then
    say "uv not found — installing it (user-space, single binary; no sudo):"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv's installer drops an env script that puts ~/.local/bin on PATH.
    # shellcheck disable=SC1091
    [ -r "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env" || true
    have uv || die "uv install ran but 'uv' is still not on PATH — open a new shell and re-run."
  else
    say "uv not found. Install it (user-space, no sudo):"
    info "curl -LsSf https://astral.sh/uv/install.sh | sh"
    info "…or re-run this script with --install-uv"
    die "uv is required to install the harnessed CLI."
  fi
fi

if ! have podman; then
  say "podman (rootless) not found — the reference runtime. Install it with your"
  say "distro package manager, then re-run this script:"
  podman_install_hint
  die "podman is required (reference runtime; >= ${PODMAN_MIN_MAJOR}.0). The installer will not install it for you."
fi

# advisory podman version floor — warn only, never block on a parse quirk
pv="$(podman --version 2>/dev/null | awk '{print $3}')"
pv_major="${pv%%.*}"
case "$pv_major" in
  ''|*[!0-9]*) : ;;   # unparseable — skip the check rather than guess
  *) [ "$pv_major" -lt "$PODMAN_MIN_MAJOR" ] && \
       say "warning: podman ${pv} is below the tested floor ${PODMAN_MIN_MAJOR}.0 — continuing anyway." ;;
esac

# ── (1)+(3) install the CLI from the pinned source; (4) idempotent via --force ──
if have harnessed && [ "$FORCE" != 1 ]; then
  say "harnessed is already installed ($(command -v harnessed))."
  say "re-run with --force to reinstall/upgrade to ${VERSION}."
  exit 0
fi

say "installing the harnessed CLI from ${src_desc} …"
case "$SOURCE" in
  repo) uv tool install --force "git+${REPO}@${VERSION}" ;;
  pypi) uv tool install --force "harnessed==${VERSION#v}" ;;
esac

# ── verify ─────────────────────────────────────────────────────────────────
if ! have harnessed; then
  say "the CLI installed but 'harnessed' is not on your PATH yet."
  say "run this once, then open a new shell:"
  info "uv tool update-shell"
  die "harnessed not on PATH — see the note above."
fi

say ""
say "installed: harnessed ($(command -v harnessed))."
say "next steps:"
info "harnessed build claude_time     # assemble + build a stack"
info "harnessed claude_time           # run it"
