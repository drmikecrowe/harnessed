"""Forward the HOST's credential surface into a container, as podman `-v`/`-e`/`--device` args.

Every function here answers one question: given what is present on this host, what arguments make
that credential reachable inside the container WITHOUT copying the secret in? The whole module is
built on referencing a live credential store rather than replicating it (ARCHITECTURE.md
§Constraints) — sockets and public/config files are forwarded, private key material never is.

Pure derivation from host state: each builder inspects the filesystem (and, for the YubiKey and
gpg-agent paths, shells out to read host configuration) and returns a list of arguments. Nothing
here runs a container, and nothing here decides WHETHER to forward — the stack's opt-in gating
lives with the caller in launcher.py.
"""
from __future__ import annotations

import os
import subprocess
import sys

from pathlib import Path

from ruamel.yaml import YAML

from . import paths
from .console import _err
from .paths import CONTAINER_HOME

# The in-container home as a string, for interpolating into `-v src:dst` specs. Derived here rather
# than imported from launcher so the dependency points INTO this module; `paths.CONTAINER_HOME`
# stays the single source of truth for the value itself.
_CONTAINER_HOME_STR = str(CONTAINER_HOME)


def _host_os() -> str:
    """'macos' | 'linux' | 'other'. Drives per-OS agent socket paths + YubiKey passthrough."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):  # pyright: ignore[reportUnreachable]
        return "linux"
    return "other"


def _op_agent_socket(home: Path) -> Path:
    """Host path to the 1Password SSH agent socket, per OS (paths are 1Password-published)."""
    if _host_os() == "macos":
        return home / "Library" / "Group Containers" / "2BUA8C4S2C.com.1password" / "t" / "agent.sock"
    return home / ".1password" / "agent.sock"


def _gpg_ssh_socket() -> Path | None:
    """Host path to the gpg-agent SSH socket (YubiKey-resident keys), cross-platform.

    `gpgconf --list-dirs agent-ssh-socket` is the portable source of truth on Linux AND macOS; fall
    back to the Linux default only when gpgconf isn't on PATH. None when undeterminable.
    """
    try:
        out = subprocess.run(
            ["gpgconf", "--list-dirs", "agent-ssh-socket"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    if _host_os() == "linux":
        return Path(f"/run/user/{os.getuid()}/gnupg/S.gpg-agent.ssh")
    return None


def _macos_op_socket_mount_source(rt: str, host_sock: Path) -> Path | None:
    """macOS only: a path the container runtime can bind-mount for the 1Password agent socket.

    PENDING VERIFICATION (macOS-gated — I could not test this from Linux). On macOS the container
    runtime is a Linux VM (podman machine / Docker Desktop), and a host unix socket does NOT
    traverse the host→VM file share, so a plain `-v <host_sock>:…` usually fails. The working pattern
    is to reverse-forward the socket INTO the VM and bind-mount the in-VM path. This wires the podman
    machine reverse-forward; it is UNVERIFIED on real hardware — see
    docs/todos/2026-06-30-macos-ssh-agent-forwarding.md before trusting it.

    Returns the in-VM socket path on a best-effort success, else None (caller falls back to the raw
    host path + a note). Never raises; never blocks the launch.
    """
    if rt != "podman":
        return None  # Docker Desktop uses a different relay; not wired yet (see the todo).
    vm_sock = Path("/tmp/harnessed-op-agent.sock")
    try:
        # Reverse-forward host_sock → vm_sock inside the running podman machine, backgrounded.
        # StreamLocalBindUnlink=yes clears a stale vm_sock so a second launch's -R bind doesn't fail
        # (the fixed path would otherwise leak a dead socket + a backgrounded ssh forever).
        # ExitOnForwardFailure=yes makes ssh exit non-zero if the forward can't be established, so we
        # DON'T return a path pointing at nothing.
        r = subprocess.run(
            ["podman", "machine", "ssh", "-f", "-N", "-T",
             "-o", "StreamLocalBindUnlink=yes", "-o", "ExitOnForwardFailure=yes",
             "-R", f"{vm_sock}:{host_sock}"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None  # forward failed → caller falls back to the note, not a dead socket path
    return vm_sock


def _ssh_agent_args(home: Path, gpg_ssh_sock: Path | None, *, rt: str = "podman") -> list[str]:
    """Forward the host's SSH signing/auth agent into the container, setting SSH_AUTH_SOCK.

    Two agents, in precedence order (ports container.sh):
    - 1Password SSH agent — primary. op-ssh-sign signs commits through it and `git push` over SSH
      authenticates through it. Private keys never leave 1Password. Path is OS-aware
      (`_op_agent_socket`); on macOS the mountable source may be a podman-machine relay path.
    - gpg-agent SSH socket — the YubiKey path. Mounted when present, but only claims SSH_AUTH_SOCK
      when 1Password's socket is absent, so a machine with both keeps 1Password as the active signer.

    Each is conditioned on the socket existing, so this is a clean no-op when neither agent is running.
    """
    ctr = _CONTAINER_HOME_STR
    args: list[str] = []
    op_agent = _op_agent_socket(home)
    op_present = op_agent.is_socket()
    if op_present:
        source = op_agent
        if _host_os() == "macos":
            relayed = _macos_op_socket_mount_source(rt, op_agent)
            if relayed is not None:
                source = relayed
            else:
                _err.print(
                    "[yellow]note:[/yellow] macOS 1Password agent forwarding is unverified "
                    "(host→VM socket relay) — if push/sign fails, see "
                    "docs/todos/2026-06-30-macos-ssh-agent-forwarding.md"
                )
        ctr_sock = f"{ctr}/.1password/agent.sock"
        args += ["-v", f"{source}:{ctr_sock}", "-e", f"SSH_AUTH_SOCK={ctr_sock}"]
    if gpg_ssh_sock is not None and gpg_ssh_sock.is_socket():
        # A ':' in the socket path would reparse the `-v src:dst` spec. Sockets don't normally
        # contain ':', but gpgconf output is host-derived — skip defensively rather than mis-mount.
        if ":" in str(gpg_ssh_sock):
            _err.print(
                f"[yellow]note:[/yellow] gpg-agent SSH socket path {gpg_ssh_sock} contains ':' "
                "— skipping mount."
            )
        else:
            ctr_gpg = f"{ctr}/.gnupg-sockets/S.gpg-agent.ssh"
            args += ["-v", f"{gpg_ssh_sock}:{ctr_gpg}"]
            if not op_present:  # 1Password wins; gpg only drives SSH_AUTH_SOCK when it's the only agent
                args += ["-e", f"SSH_AUTH_SOCK={ctr_gpg}"]
    return args


def _yubikey_device_args() -> list[str]:
    """`--device` passthrough for a connected YubiKey (Yubico vendor id 1050) so in-container gpg/
    op-ssh can reach the token. LINUX ONLY: macOS runs the container in a Linux VM with no
    `/dev/bus/usb`, so USB passthrough isn't possible there (the YubiKey reaches the container via
    the gpg-agent SSH socket relay instead). Best-effort `lsusb` parse; [] when absent.
    """
    if _host_os() != "linux":
        return []
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    for line in out.stdout.splitlines():
        low = line.lower()
        if "yubico" not in low and "id 1050:" not in low:
            continue
        # "Bus 003 Device 004: ID 1050:0407 Yubico.com ..." → /dev/bus/usb/003/004
        parts = line.split()
        if len(parts) >= 4:
            bus, dev = parts[1], parts[3].rstrip(":")
            device = f"/dev/bus/usb/{bus}/{dev}"
            if Path(device).exists():
                return ["--device", device]
    return []


def _ssh_dir_mounts(home: Path, ssh_keys: list[str]) -> list[str]:
    """Forward the non-secret SSH surface + opt-in private keys, file-by-file (NOT the whole ~/.ssh).

    The repo hard-denies `~/.ssh` to recipes for a reason (persist.py); blanket-mounting it would
    drop every private key into the container. Instead:
    - Always (when present, ro): `config`, `known_hosts`, and every `*.pub` — host verification +
      ssh config + public identities, none of which are secret.
    - Private keys ONLY when the stack's `ssh_keys:` opts them in by basename — for hosts without an
      agent (1Password/gpg). The name is schema-validated to a single component, so it can't escape
      ~/.ssh; we still re-check the resolved path stays under ~/.ssh as defense-in-depth.
    """
    ctr = _CONTAINER_HOME_STR
    ssh_dir = (home / ".ssh").resolve()
    if not ssh_dir.is_dir():
        return []
    args: list[str] = []

    def _mount_named(name: str) -> None:
        # Resolve the entry and require it be a regular file living DIRECTLY under ~/.ssh.
        # Symlinks are followed, so a config / known_hosts / *.pub whose target escapes ~/.ssh
        # (e.g. ~/.ssh/config -> ~/.aws/credentials) is rejected — the same defense-in-depth the
        # opt-in ssh_keys path uses — rather than mounting the secret target read-only. `:` is the
        # podman `-v src:dst:opts` separator: a name containing one would reparse the spec (no shell
        # injection — list args), so skip it.
        if ":" in name:
            _err.print(f"[yellow]note:[/yellow] skipping ~/.ssh/{name} (':' in name).")
            return
        target = (ssh_dir / name).resolve()
        if target.parent != ssh_dir or not target.is_file():
            return
        args.extend(["-v", f"{target}:{ctr}/.ssh/{name}:ro"])

    for name in ("config", "known_hosts"):
        _mount_named(name)
    for pub in sorted(ssh_dir.glob("*.pub")):
        _mount_named(pub.name)
    for name in ssh_keys:
        target = (ssh_dir / name).resolve()
        if target.parent != ssh_dir or not target.is_file():
            _err.print(
                f"[yellow]note:[/yellow] ssh_keys: '{name}' not found in ~/.ssh (or not a regular "
                f"file) — skipping."
            )
            continue
        args += ["-v", f"{target}:{ctr}/.ssh/{name}:ro"]
    return args


def _gnupg_mounts(home: Path) -> list[str]:
    """Forward only the NON-SECRET GPG files — NEVER the private keyring.

    The bash launcher mounted all of ~/.gnupg, which drags in `private-keys-v1.d/*.key` — the actual
    secret key material for SOFTWARE openpgp keys (only YubiKey-resident keys are stubs there). `ro`
    doesn't help: read-only still means fully readable → exfiltratable by an autonomous agent (or a
    compromised dep) in the container. That also overrides persist.py's hard-deny of ~/.gnupg. So we
    forward ONLY the public/config surface, file-by-file, and never `private-keys-v1.d/`.

    This means SSH-format signing (op-ssh-sign / gpg-agent SSH socket, see `_ssh_agent_args`) is the
    supported in-container path; full openpgp GPG *signing* in-container (which needs the gpg-agent
    socket + selectively-forwarded YubiKey stubs, without the software secrets) is a scoped follow-up
    — see docs/todos/2026-06-30-macos-ssh-agent-forwarding.md.
    """
    ctr = _CONTAINER_HOME_STR
    gnupg = home / ".gnupg"
    if not gnupg.is_dir():
        return []
    args: list[str] = []
    for name in ("pubring.kbx", "trustdb.gpg", "gpg.conf", "gpg-agent.conf", "sshcontrol"):
        f = gnupg / name
        if f.is_file():
            args += ["-v", f"{f}:{ctr}/.gnupg/{name}:ro"]
    return args


def _trusted_ssh_keys(stk_ssh_keys: list[str], from_overlay: bool, stack: str) -> list[str]:
    """Private-key (`ssh_keys`) mounts are honored ONLY from the user's own overlay catalog.

    A stack.yaml can come from a SHARED repo catalog (per CLAUDE.md). Mounting a real private key is
    the KEY OWNER's decision, not a third-party stack author's — so `ssh_keys` from anywhere but the
    user overlay (`~/.config/harnessed/catalog`) is dropped with a warning. (Public keys / config /
    known_hosts, which are not secret, are unaffected — this only gates private-key files.)
    """
    if stk_ssh_keys and not from_overlay:
        _err.print(
            f"[yellow]note:[/yellow] ignoring ssh_keys from shared-catalog stack '{stack}' — declare "
            f"private keys only in your user overlay (~/.config/harnessed/catalog)."
        )
        return []
    return stk_ssh_keys


def _stack_from_overlay(stack: str) -> bool:
    """True when this stack resolves to the user's own overlay catalog — the gate _trusted_ssh_keys
    applies before mounting any private key. False if the stack can't be resolved at all (fail
    closed: an unresolvable stack is not "yours")."""
    try:
        stack_dir = paths.find_in_catalog("stacks", stack)
    except Exception:
        return False
    return stack_dir.resolve().is_relative_to(paths.user_catalog().resolve())


def _gh_hosts_missing_plaintext_token(gh_hosts: Path) -> bool:
    """True when hosts.yml has host/user entries but no plaintext `oauth_token` anywhere.

    Modern `gh` defaults to storing the OAuth token in the OS credential store (macOS Keychain,
    Secret Service, Credential Manager) instead of this file, falling back to plain text only when
    no store is available or `--insecure-storage` is passed. The container only gets this file
    bind-mounted in (read-only, see below) — it has no access to the host's keychain — so a
    hosts.yml with real entries but no `oauth_token` field anywhere means `gh` inside the container
    has no usable token, even though `gh auth status` succeeds on the host. Confirmed on macOS: a
    keychain-backed entry looks like `users: {<name>: {}}` — the token is entirely absent, not
    present-but-empty.
    """
    try:
        data = YAML(typ="safe", pure=True).load(gh_hosts.read_text())
    except Exception:
        return False  # can't parse — don't warn on a guess

    def has_token(node: object) -> bool:
        if isinstance(node, dict):
            if "oauth_token" in node:
                return True
            return any(has_token(v) for v in node.values())
        return False

    return bool(data) and not has_token(data)


def _git_identity_config_mount(home: Path) -> list[str]:
    """Mount the host's git identity config (`~/.config/git` dir, else legacy `~/.gitconfig`) ro.

    Carries user.signingkey, gpg.format=ssh, gpg.ssh.program=op-ssh-sign, commit.gpgsign — the
    settings op-ssh-sign needs to actually sign commits. It's a public-key reference, not a secret.
    """
    ctr = _CONTAINER_HOME_STR
    xdg_git = home / ".config" / "git"
    legacy_git = home / ".gitconfig"
    if xdg_git.is_dir():
        return ["-v", f"{xdg_git}:{ctr}/.config/git:ro"]
    if legacy_git.is_file():
        return ["-v", f"{legacy_git}:{ctr}/.gitconfig:ro"]
    return []


def _ssh_agent_auto_forward_args(home: Path | None = None, rt: str = "podman") -> list[str]:
    """Auto-forward the host SSH signing/auth agent (1Password primary, gpg-agent fallback) plus the
    ro git identity config WHENEVER the agent socket is live on the host — independent of the stack's
    `forward_git_credentials` opt-in.

    Rationale (why this is safe to make the default, unlike the full credential bundle): the agent
    socket exposes no key material and gates every sign/auth behind a host-side 1Password approval or
    YubiKey touch, and the git config it needs to drive op-ssh-sign is a public signing-key reference,
    not a secret. So "1Password available → wired up" holds. The genuinely-secret surface — the gh
    oauth token in hosts.yml and opt-in private SSH keys — stays behind `forward_git_credentials` in
    `_credential_forward_args`. No-op when no agent socket is present.
    """
    home = home or Path.home()
    args = _ssh_agent_args(home, _gpg_ssh_socket(), rt=rt)
    if not args:
        return []
    args += _git_identity_config_mount(home)
    return args
