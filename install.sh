#!/usr/bin/env sh
# harnessed installer — checked-in, reviewable, POSIX sh.
#
#   ./install.sh               show the plan, ask y/n, install the newest release
#   ./install.sh --force       same, without the y/n prompt
#   ./install.sh --uninstall   remove the CLI; leaves your data untouched
#   ./install.sh --help        usage
#
# The package manager is the one that already manages harnessed, else the
# first found of: mise, uv, pip (into a private venv). Every install also
# writes ~/.local/bin/harnessed-self-update, which reruns the same install
# command for the newest release tag, without the prompt.
#
# This is the honest, auditable form of the manual steps in README §Install.
# The `curl -fsSL <raw-tag-url>/install.sh | sh` one-liner is a documented
# convenience alias for THIS file at a pinned tag — never the primary path,
# and never pointed at a moving branch. Read it before you run it.
#
# Posture: every install names one exact release tag, never a bare clone of
# `main`. By default that tag is the newest stable one the repository
# publishes, looked up at run time, so the installer and self-update trust
# the repository's tags; set HARNESSED_VERSION=<tag> to choose one yourself.
# It refuses to run anything privileged (no sudo, no package-manager writes,
# no podman/docker auto-install) on your behalf.
set -eu

# ── configuration ─────────────────────────────────────────────────────────
# Empty VERSION means: resolve the newest release tag at run time.
# Pin one with HARNESSED_VERSION=<tag> ./install.sh
VERSION="${HARNESSED_VERSION:-}"

REPO="https://github.com/drmikecrowe/harnessed.git"
GH_SLUG="drmikecrowe/harnessed"
PODMAN_MIN_MAJOR=4          # advisory floor; the reference runtime is podman >= 4.0
BIN_DIR="$HOME/.local/bin"
SELF_UPDATE="$BIN_DIR/harnessed-self-update"
PIP_VENV="${XDG_DATA_HOME:-$HOME/.local/share}/harnessed-venv"
MISE_SHIMS="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}/shims"
# The stack launchers run ~/.local/bin/harnessed by absolute path
# (launchscript._harnessed_argv), so mise and pip installs link both here.
COMMANDS="harnessed harnessed-tools"

# ── flags ──────────────────────────────────────────────────────────────────
FORCE=0
ACTION="install"

usage() {
  cat <<'EOF'
usage: install.sh [--force] [--uninstall] [--help]

  (no args)     show what will happen, ask y/n, then install the newest
                harnessed release onto your PATH
  --force       do not ask; install (or reinstall) straight away
  --uninstall   remove the `harnessed` CLI and harnessed-self-update; preserves
                ~/.config/harnessed and $XDG_DATA_HOME/harnessed, and leaves
                podman/docker in place
  --help, -h    show this message

Every install also writes ~/.local/bin/harnessed-self-update. Run it to
reinstall from the newest release tag; it never asks.

Requirements the installer DETECTS but never installs for you:
  * podman (rootless, the reference runtime) or docker
  * one package manager: mise, uv, or python3 >= 3.12 with venv + pip
    (it uses the one that already manages harnessed, else the first found
    in that order)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --uninstall)  ACTION="uninstall" ;;
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

# Newest stable release tag; pre-releases (v1.0.0-rc1) are skipped. Kept as
# text so the self-update helper embeds this exact function.
# shellcheck disable=SC2016  # $1 expands when the function runs
LATEST_TAG_FN='latest_tag() { git ls-remote --tags --refs --sort=-v:refname "$1" "v*" | sed "s#.*refs/tags/##" | grep -v -- - | head -n1; }'
eval "$LATEST_TAG_FN"

# pip path needs a python3 that can build a venv with pip in it.
pip_ok() {
  have python3 && python3 -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 12))' 2>/dev/null
}

# Which package manager owns harnessed today (empty when none does).
manager_in_use() {
  if have mise && mise ls --global 2>/dev/null | grep -q "^pypi:${GH_SLUG} "; then echo mise
  elif have uv && uv tool list 2>/dev/null | grep -q '^harnessed '; then echo uv
  elif [ -x "$PIP_VENV/bin/harnessed" ]; then echo pip
  fi
}

# pipx is not an install manager here, but a pipx copy must not be shadowed.
pipx_has_harnessed() {
  have pipx && pipx list 2>/dev/null | grep -q 'package harnessed '
}

# y/n gate; --force skips it. Reads the terminal, so `curl | sh` still asks.
confirm() {
  [ "$FORCE" = 1 ] && return 0
  printf '%s [y/N] ' "$1"
  reply=""
  read -r reply </dev/tty 2>/dev/null || die "no terminal to ask on. Download install.sh, read it, and run it from a terminal (or pass --force)."
  case "$reply" in
    [Yy]|[Yy][Ee][Ss]) : ;;
    *) say "aborted; nothing changed."; exit 1 ;;
  esac
}

# Remove our links from BIN_DIR, only where they point into $1.
unlink_commands() {
  for c in $COMMANDS; do
    case "$(readlink "$BIN_DIR/$c" 2>/dev/null)" in
      "$1"/*) rm -f "$BIN_DIR/$c"; say "removed: $BIN_DIR/$c" ;;
    esac
  done
}

# ── platform guard ─────────────────────────────────────────────────────────
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

# ── uninstall path ─────────────────────────────────────────────────────────
if [ "$ACTION" = "uninstall" ]; then
  in_use="$(manager_in_use)"
  if [ -z "$in_use" ] && pipx_has_harnessed; then
    in_use="pipx"
  fi
  say "harnessed uninstaller"
  say ""
  say "This will:"
  case "$in_use" in
    mise) info "remove harnessed with:  mise unuse -g pypi:${GH_SLUG}"
          info "remove the links in ${BIN_DIR} that point into ${MISE_SHIMS}" ;;
    uv)   info "remove harnessed with:  uv tool uninstall harnessed" ;;
    pip)  info "delete the venv ${PIP_VENV}"
          info "remove the links in ${BIN_DIR} that point into it" ;;
    pipx) info "remove harnessed with:  pipx uninstall harnessed" ;;
    *)    info "find no harnessed install via mise, uv, pip or pipx (nothing to remove)" ;;
  esac
  [ -f "$SELF_UPDATE" ] && info "delete ${SELF_UPDATE}"
  say "Left in place on purpose:"
  info "podman/docker — the installer never installed them, so it never removes them"
  data_dirs
  say ""
  confirm "Uninstall?"

  case "$in_use" in
    mise) mise unuse -g "pypi:${GH_SLUG}"; unlink_commands "$MISE_SHIMS" ;;
    uv)   uv tool uninstall harnessed ;;
    pip)  unlink_commands "$PIP_VENV"; rm -rf "$PIP_VENV"; say "removed: $PIP_VENV" ;;
    pipx) pipx uninstall harnessed ;;
  esac
  if [ -f "$SELF_UPDATE" ]; then
    rm -f "$SELF_UPDATE"
    say "removed: ${SELF_UPDATE}"
  fi
  exit 0
fi

# ── detect: container runtime (required, never installed for you) ─────────
if have podman; then
  runtime="podman ($(command -v podman))"
  # advisory podman version floor — warn only, never block on a parse quirk
  pv="$(podman --version 2>/dev/null | awk '{print $3}')"
  pv_major="${pv%%.*}"
  case "$pv_major" in
    ''|*[!0-9]*) : ;;   # unparseable — skip the check rather than guess
    *) [ "$pv_major" -lt "$PODMAN_MIN_MAJOR" ] && \
         say "warning: podman ${pv} is below the tested floor ${PODMAN_MIN_MAJOR}.0 — continuing anyway." ;;
  esac
elif have docker; then
  runtime="docker ($(command -v docker))"
else
  say "no container runtime found. Install podman (rootless, the reference runtime)"
  say "or docker with your distro package manager, then re-run this script:"
  podman_install_hint
  die "podman (>= ${PODMAN_MIN_MAJOR}.0) or docker is required. The installer will not install either for you."
fi

# ── detect: package manager (in use first, then mise, uv, pip) ───────────
pipx_has_harnessed && \
  die "harnessed is installed with pipx, which this installer does not manage. Run 'install.sh --uninstall' first, then re-run."

MANAGER="$(manager_in_use)"
if [ -n "$MANAGER" ]; then
  manager_why="already manages harnessed"
elif have mise; then MANAGER=mise; manager_why="found on PATH"
elif have uv;   then MANAGER=uv;   manager_why="found on PATH"
elif pip_ok;    then MANAGER=pip;  manager_why="python3 with venv + pip found"
else
  say "no supported package manager found. Install one of these, then re-run:"
  info "mise: https://mise.jdx.dev/getting-started.html"
  info "uv:   https://docs.astral.sh/uv/getting-started/installation/"
  info "pip:  python3 >= 3.12 with the venv module (e.g. sudo apt install python3-venv)"
  die "mise, uv, or python3 >= 3.12 with venv + pip is required."
fi

# mise and pip link into BIN_DIR; uv places its own links. Anything already
# there must point into the chosen manager's tree; a file or a link from
# another install is never replaced.
case "$MANAGER" in
  mise) link_src="$MISE_SHIMS";   owned="$MISE_SHIMS" ;;
  pip)  link_src="$PIP_VENV/bin"; owned="$PIP_VENV/bin" ;;
  uv)   link_src="";              owned="$(uv tool dir)" ;;
esac
for c in $COMMANDS; do
  [ -e "$BIN_DIR/$c" ] || [ -L "$BIN_DIR/$c" ] || continue
  case "$(readlink "$BIN_DIR/$c" 2>/dev/null)" in
    "$owned"/*) : ;;
    *) die "$BIN_DIR/$c belongs to another install; remove it (or run install.sh --uninstall) and re-run." ;;
  esac
done

# ── resolve the newest release tag unless HARNESSED_VERSION pinned one ─────
if [ -z "$VERSION" ]; then
  have git || die "git is required to find the latest release (or set HARNESSED_VERSION=<tag>)."
  VERSION="$(latest_tag "$REPO")"
  [ -n "$VERSION" ] || die "no release tag found at ${REPO} (set HARNESSED_VERSION=<tag> to pick one)."
  version_why="newest release"
else
  version_why="pinned by HARNESSED_VERSION"
fi

# One install command per manager; the plan shows it, the run and the
# self-update helper execute it. TAG is substituted per use.
install_cmd() {
  case "$MANAGER" in
    mise) printf '%s' "mise use -g pypi:${GH_SLUG}@$1" ;;
    uv)   printf '%s' "uv tool install --force git+${REPO}@$1" ;;
    pip)  printf '%s' "'${PIP_VENV}/bin/pip' install --upgrade git+${REPO}@$1" ;;
  esac
}

# ── plan: say exactly what this run will do BEFORE doing it ────────────────
current="not installed"
if [ -x "$BIN_DIR/harnessed" ]; then current="$BIN_DIR/harnessed"
elif have harnessed; then current="$(command -v harnessed)"
fi

say "harnessed installer"
say ""
say "Found:"
info "runtime : ${runtime}"
info "manager : ${MANAGER} (${manager_why})"
info "current : ${current}"
say ""
say "This will:"
n=1
if [ "$MANAGER" = pip ] && [ ! -x "$PIP_VENV/bin/pip" ]; then
  info "${n}. create a venv:        python3 -m venv ${PIP_VENV}"; n=$((n + 1))
fi
install_step="$n"
info "${n}. install harnessed ${VERSION} (${version_why}):"
info "     $(install_cmd "$VERSION")"; n=$((n + 1))
if [ -n "$link_src" ]; then
  info "${n}. link ${BIN_DIR}/{harnessed,harnessed-tools} -> ${link_src}/"; n=$((n + 1))
fi
info "${n}. write ${SELF_UPDATE}"
info "     (reruns step ${install_step}'s command for the newest release, without asking)"
say ""
say "It will not touch:"
info "podman/docker, or anything needing sudo"
data_dirs
say ""
confirm "Proceed?"

# ── install ────────────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"
if [ "$MANAGER" = pip ] && [ ! -x "$PIP_VENV/bin/pip" ]; then
  say "→ python3 -m venv ${PIP_VENV}"
  python3 -m venv "$PIP_VENV"
fi
say "→ $(install_cmd "$VERSION")"
case "$MANAGER" in
  mise) mise use -g "pypi:${GH_SLUG}@${VERSION}"
        [ -x "$MISE_SHIMS/harnessed" ] || mise reshim ;;
  uv)   uv tool install --force "git+${REPO}@${VERSION}" ;;
  pip)  "$PIP_VENV/bin/pip" install --upgrade "git+${REPO}@${VERSION}" ;;
esac
if [ -n "$link_src" ]; then
  for c in $COMMANDS; do
    ln -sfn "$link_src/$c" "$BIN_DIR/$c"
    say "→ linked $BIN_DIR/$c -> $link_src/$c"
  done
fi

# ── self-update helper: the same install command, newest tag at run time ──
# The pip helper rebuilds its venv if it has gone missing.
helper_pre=""
[ "$MANAGER" = pip ] && helper_pre="[ -x '${PIP_VENV}/bin/pip' ] || python3 -m venv '${PIP_VENV}'"
# shellcheck disable=SC2016  # $tag expands inside the helper, not here
cat >"$SELF_UPDATE" <<EOF
#!/usr/bin/env sh
# Written by harnessed install.sh (manager: ${MANAGER}). Reinstalls the CLI
# from the newest release tag. Never asks: running it is the yes.
set -eu
${LATEST_TAG_FN}
tag="\$(latest_tag '${REPO}')"
[ -n "\$tag" ] || { echo "error: no release tag found at ${REPO}" >&2; exit 1; }
echo "upgrading harnessed to \$tag with ${MANAGER} ..."
${helper_pre}
exec $(install_cmd '"$tag"')
EOF
chmod +x "$SELF_UPDATE"
say "→ wrote ${SELF_UPDATE}"

# ── verify ─────────────────────────────────────────────────────────────────
exe_dir="$BIN_DIR"
[ "$MANAGER" = uv ] && exe_dir="$(uv tool dir --bin)"
[ -x "$exe_dir/harnessed" ] || die "install finished but ${exe_dir}/harnessed is missing."
say ""
say "installed: harnessed ${VERSION} (${exe_dir}/harnessed)."
[ "$exe_dir" = "$BIN_DIR" ] || \
  say "note: uv put harnessed in ${exe_dir}; the stack launchers look for it in ${BIN_DIR}."
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *) say "note: ${BIN_DIR} is not on your PATH; add it to your shell profile." ;;
esac
say "next steps:"
info "harnessed build claude_time     # assemble + build a stack"
info "harnessed claude_time           # run it"
info "harnessed-self-update           # later: upgrade to the newest release"
