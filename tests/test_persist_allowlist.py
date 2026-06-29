"""Tests for the global persist allowlist + ownership guard (T4b/T5).

Fast layer — no podman. Exercises persist.resolve_global_persist (hard-deny, default-deny,
allowed) and persist.guard_ownership directly.
"""

import os
from pathlib import Path

import pytest

from harnessed import paths, persist
from harnessed.persist import (
    PersistDeniedError,
    PersistNotAllowlistedError,
    PersistOwnershipError,
)


@pytest.fixture
def home(monkeypatch, tmp_path):
    """An isolated $HOME (+ XDG_CONFIG_HOME under it) so Path.home() / the allowlist are sandboxed."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    return h


def _write_allowlist(*lines: str) -> Path:
    af = paths.persist_allowlist_path()
    af.parent.mkdir(parents=True, exist_ok=True)
    af.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return af


def _real(p) -> Path:
    return Path(os.path.realpath(str(p)))


class TestHardDeny:
    """Sensitive dirs are denied REGARDLESS of the allowlist — never opt-in-able."""

    @pytest.mark.parametrize("sub", [".ssh", ".aws", ".gnupg"])
    def test_sensitive_dirs_denied_even_if_allowlisted(self, home, sub):
        target = home / sub
        target.mkdir()
        _write_allowlist(str(target))  # explicitly try to allow it
        with pytest.raises(PersistDeniedError):
            persist.resolve_global_persist(str(target))

    def test_subdir_of_sensitive_denied(self, home):
        (home / ".ssh").mkdir()
        _write_allowlist(str(home / ".ssh"))
        with pytest.raises(PersistDeniedError):
            persist.resolve_global_persist(str(home / ".ssh" / "id_ed25519"))

    def test_config_harnessed_denied(self, home):
        _write_allowlist(str(home / ".config" / "harnessed"))
        with pytest.raises(PersistDeniedError):
            persist.resolve_global_persist("~/.config/harnessed")

    def test_bare_home_denied(self, home):
        _write_allowlist(str(home))
        with pytest.raises(PersistDeniedError):
            persist.resolve_global_persist(str(home))


class TestDefaultDeny:
    """Absent from the allowlist (or no file at all) → refused, naming the fix."""

    def test_missing_allowlist_file_denies(self, home):
        target = home / ".gbrain"
        target.mkdir()
        with pytest.raises(PersistNotAllowlistedError):
            persist.resolve_global_persist(str(target))

    def test_not_listed_denies(self, home):
        (home / ".gbrain").mkdir()
        (home / ".other").mkdir()
        _write_allowlist(str(home / ".other"))
        with pytest.raises(PersistNotAllowlistedError):
            persist.resolve_global_persist(str(home / ".gbrain"))

    def test_comments_and_blanks_ignored(self, home):
        (home / ".gbrain").mkdir()
        _write_allowlist("# a comment", "", "   ", "# ~/.gbrain (commented out)")
        with pytest.raises(PersistNotAllowlistedError):
            persist.resolve_global_persist(str(home / ".gbrain"))

    def test_error_names_file_and_line(self, home):
        target = home / ".gbrain"
        target.mkdir()
        with pytest.raises(PersistNotAllowlistedError) as ei:
            persist.resolve_global_persist(str(target))
        msg = str(ei.value)
        assert str(paths.persist_allowlist_path()) in msg  # names the file to edit
        assert str(_real(target)) in msg                   # names the exact line to add


class TestAllowed:
    """A listed path (or a child of one) passes and returns the canonical host dir."""

    def test_listed_path_passes(self, home):
        target = home / ".gbrain"
        target.mkdir()
        _write_allowlist(str(target))
        assert persist.resolve_global_persist(str(target)) == _real(target)

    def test_subdir_of_listed_passes(self, home):
        parent = home / "data"
        (parent / "tool").mkdir(parents=True)
        _write_allowlist(str(parent))
        assert persist.resolve_global_persist(str(parent / "tool")) == _real(parent / "tool")

    def test_tilde_expanded(self, home):
        (home / ".gbrain").mkdir()
        _write_allowlist("~/.gbrain")
        assert persist.resolve_global_persist("~/.gbrain") == _real(home / ".gbrain")

    def test_env_var_expanded(self, home, monkeypatch):
        (home / ".gbrain").mkdir()
        monkeypatch.setenv("GBRAIN_HOME", str(home / ".gbrain"))
        _write_allowlist(str(home / ".gbrain"))
        assert persist.resolve_global_persist("$GBRAIN_HOME") == _real(home / ".gbrain")


class TestOwnershipGuard:
    """Pre-existing dir owned by a foreign uid → loud, named error (T5)."""

    def test_absent_dir_ok(self, tmp_path):
        persist.guard_ownership(tmp_path / "does-not-exist")  # no raise

    def test_same_uid_ok(self, tmp_path):
        d = tmp_path / "mine"
        d.mkdir()
        persist.guard_ownership(d)  # created by us → no raise

    def test_foreign_uid_raises(self, tmp_path, monkeypatch):
        d = tmp_path / "theirs"
        d.mkdir()
        # Pretend the caller is some other uid than the dir's owner.
        monkeypatch.setattr(os, "getuid", lambda: os.stat(d).st_uid + 1)
        with pytest.raises(PersistOwnershipError) as ei:
            persist.guard_ownership(d)
        assert "keep-id" in str(ei.value)  # names the cause + remediation
