"""Global persist allowlist + ownership guard (T4b/T5).

A `global:` persist entry names a REAL host dir to bind-mount rw into the otherwise
sandboxed pod (e.g. `~/.gbrain`, shared with host-native runs). That is a sharp edge:
without a gate a recipe could declare `~/.ssh`. This module IS the gate.

Two independent checks resolve a global entry, both DEFAULT-DENY:
  1. A hard-deny set (sensitive dirs + the bare `$HOME`) rejected REGARDLESS of the
     allowlist — a user can never opt these in by editing a file.
  2. The user-owned allowlist (`paths.persist_allowlist_path()`); a path that is not
     listed (or when the file is absent) is refused with a message naming the exact
     file and the line to add.

Plus an ownership guard (T5): under `--userns=keep-id` harnessed runs as the invoking
user, so a dir it CREATES maps 1:1 into the pod. A PRE-EXISTING dir owned by a different
uid silently EACCESes inside the pod — caught here, before launch, with a remediation.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import paths
from .schema import SchemaError


class PersistDeniedError(SchemaError):
    """A global persist entry resolves to a hard-denied sensitive dir (`~/.ssh` etc.).

    Hard-deny is absolute: it cannot be overridden by the persist allowlist file.
    """


class PersistNotAllowlistedError(SchemaError):
    """A global persist entry is absent from the user-owned persist allowlist (default-deny)."""


class PersistOwnershipError(SchemaError):
    """A persist target dir exists but is owned by a different uid than the caller (T5).

    Under `--userns=keep-id` that uid maps 1:1 into the pod, so the tool would hit EACCES.
    """


def _canonical(p: str | Path) -> Path:
    """Expand `~` and `$VARS`, then realpath-canonicalize (resolve symlinks and `..`)."""
    expanded = os.path.expanduser(os.path.expandvars(str(p)))
    return Path(os.path.realpath(expanded))


def _is_within(child: Path, parent: Path) -> bool:
    """True if `child` == `parent` or is nested under it (both already canonical)."""
    return child == parent or parent in child.parents


def _hard_deny_roots() -> list[Path]:
    """Canonical dirs a global persist entry may NEVER mount, allowlist or not."""
    home = Path.home()
    roots = [
        home / ".ssh",
        home / ".aws",
        home / ".gnupg",
        paths.xdg_config_home() / "harnessed",
    ]
    return [_canonical(r) for r in roots]


def resolve_global_persist(entry: str) -> Path:
    """Canonicalize + authorize a `global:` persist entry; return the host dir to mount.

    Order (both default-deny):
      1. Hard-deny — `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/harnessed`, and `$HOME`
         itself — rejected REGARDLESS of the allowlist (`PersistDeniedError`).
      2. Allowlist — the canonical path must be listed in (or under an entry of)
         `paths.persist_allowlist_path()`; otherwise `PersistNotAllowlistedError`, naming
         the file and the exact line to add.
    """
    real = _canonical(entry)
    home = _canonical(Path.home())

    # 1. Hard-deny — the bare home dir and the sensitive dirs, never overridable.
    if real == home:
        raise PersistDeniedError(
            f"global persist entry {entry!r} resolves to your home dir ({real}) — harnessed "
            "will not mount the bare $HOME into a pod (it would expose every dotfile). Name "
            "the specific subdir the tool needs instead (e.g. ~/.gbrain)."
        )
    for denied in _hard_deny_roots():
        if _is_within(real, denied):
            raise PersistDeniedError(
                f"global persist entry {entry!r} resolves under {denied}, which is permanently "
                "denied (credentials/secrets). This cannot be overridden by the persist allowlist."
            )

    # 2. Default-deny — must appear in (or under an entry of) the user-owned allowlist.
    if not _allowlisted(real):
        af = paths.persist_allowlist_path()
        raise PersistNotAllowlistedError(
            f"global persist entry {entry!r} (resolves to {real}) is not in the persist "
            f"allowlist, so harnessed will not mount it. To permit it, add this exact line to "
            f"{af}:\n"
            f"    {real}\n"
            "Create the file if it does not exist (one path per line, '#' starts a comment)."
        )
    return real


def _allowed_entries() -> list[Path]:
    """Canonical allowlist entries (skipping blanks/comments). Missing file → []."""
    try:
        text = paths.persist_allowlist_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[Path] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(_canonical(line))
    return out


def _allowlisted(real: Path) -> bool:
    return any(_is_within(real, entry) for entry in _allowed_entries())


def guard_ownership(path: Path) -> None:
    """Raise if `path` exists but is owned by a different uid than the caller (T5).

    harnessed runs the pod with `--userns=keep-id`, mapping the invoking uid 1:1 inside, so a
    dir harnessed CREATES is owned correctly by construction. A PRE-EXISTING dir owned by a
    different uid maps to a uid with no write access inside the pod → silent EACCES. Caught
    here, before launch, naming the cause and the remediation. Absent dirs are fine (harnessed
    creates them as the caller).
    """
    try:
        st = path.stat()
    except OSError:
        return  # absent → created later as the caller; nothing to guard
    me = os.getuid()
    if st.st_uid != me:
        raise PersistOwnershipError(
            f"persist dir {path} is owned by uid {st.st_uid}, but harnessed runs as uid {me}. "
            "Under --userns=keep-id that uid maps 1:1 into the pod, so the tool would hit a "
            "silent permission error (EACCES) writing here. Fix the owner "
            f"(e.g. `sudo chown -R {me} {path}`) or remove the stale dir and re-run."
        )
