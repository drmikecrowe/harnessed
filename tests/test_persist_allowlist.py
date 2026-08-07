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

    def test_the_message_names_the_pinned_mapping(self, tmp_path, monkeypatch):
        """bd harnessed-rv2.1. The guard's premise — "the invoking uid maps 1:1 inside" — was only
        true on a host whose uid happened to be 1000, which is why it rubber-stamped the CI failure
        it exists to catch. The pinned `keep-id:uid=1000` mapping is what MAKES that premise true,
        so the remediation text must name the mapping it is actually reasoning about."""
        d = tmp_path / "theirs"
        d.mkdir()
        owner = os.stat(d).st_uid
        monkeypatch.setattr(os, "getuid", lambda: owner + 1)
        with pytest.raises(PersistOwnershipError) as ei:
            persist.guard_ownership(d)
        msg = str(ei.value)
        assert f"keep-id:uid={paths.CONTAINER_UID}" in msg, (
            f"the guard still describes the stale unpinned mapping: {msg}"
        )
        assert f"chown -R {owner + 1}" in msg  # remediation targets the CALLER, who can write


class TestTheGuardFollowsTheMappingInsteadOfAssumingIt:
    """bd harnessed-rv2.1. The guard exists (T5) so that a wrong assumption about the userns mapping
    surfaces as a named PRE-LAUNCH error instead of `mkdir: cannot create directory '/data/dolt':
    Permission denied` twenty layers down — which is exactly how live.yml failed six runs running.

    A guard that derives its answer from `os.getuid()` directly is assuming the mapping is what it
    hopes; it cannot catch the mapping being wrong, which is the one thing it is for. So it asks
    `paths.pod_host_uid()`, which READS `USERNS_ARG`. The two can then never drift apart.
    """

    def test_pod_host_uid_follows_the_pinned_mapping(self):
        """Pinned: the image's uid is mapped onto the invoking user, so the pod writes as us."""
        assert paths.pod_host_uid() == os.getuid()

    def test_pod_host_uid_is_none_for_an_unpinned_mapping(self, monkeypatch):
        """Bare `keep-id` maps the image's uid out of the SUBUID range, so the host uid the pod
        writes as is not computable from the argument. None, not a guess."""
        monkeypatch.setattr(paths, "USERNS_ARG", "--userns=keep-id")
        assert paths.pod_host_uid() is None

    @pytest.mark.parametrize(
        "mapping, expected",
        [
            # RESOLVED — the mapping tells us exactly which host uid the pod writes as.
            ("--userns=keep-id:uid=1000,gid=1000", "caller"),   # the pinned form
            ("--userns=keep-id:gid=1000,uid=1000", "caller"),   # reversed — `\b` matches after `,`
            ("--userns=keep-id:uid=01000,gid=1000", "caller"),  # zero-padded
            ("--userns=host", "image"),                         # no namespace: container 1000 IS host 1000
            # UNRESOLVED — the pod writes as a uid this function cannot compute.
            ("--userns=keep-id", None),                         # the bug: image uid maps to a SUBUID
            ("--userns=keep-id:uid=1001,gid=1001", None),       # mapped onto somebody else
            ("--userns=keep-id:uid=10000,gid=1000", None),      # 1000 is a PREFIX of 10000, not a match
            ("--userns=keep-id:subuid=1000", None),             # `uid=` inside a longer word: no `\b`
            ("--userns=auto", None),                            # private range
            ("--userns=nomap", None),                           # host user excluded entirely
        ],
    )
    def test_the_mapping_is_parsed_not_guessed(self, monkeypatch, mapping, expected):
        """CodeRabbit's finding: returning CONTAINER_UID for an UNRESOLVED mapping is not fail-safe.

        Under bare `keep-id` on a host whose user is 1001, podman maps host 1001 -> container 1001
        and the image's uid 1000 comes from the SUBUID range — so files the pod writes land as
        ~100999 on the host, not as 1000. Answering "1000" would then ACCEPT a persist dir owned by
        host uid 1000 that the pod cannot actually write: fail-open, in exactly the state the
        original bug produces. Unresolved must be None, and the guard must refuse.
        """
        monkeypatch.setattr(paths, "USERNS_ARG", mapping)
        want = {"caller": os.getuid(), "image": paths.CONTAINER_UID, None: None}[expected]
        assert paths.pod_host_uid() == want, f"{mapping} resolved wrong"

    def test_an_unresolved_mapping_refuses_even_a_caller_owned_dir(self, tmp_path, monkeypatch):
        """The fail-OPEN case, driven rather than asserted by name.

        A previous version returned CONTAINER_UID here and called it "fail-safe". It is not: a dir
        owned by uid 1000 would sail through while the pod wrote as a subuid. The guard must refuse
        whenever it cannot say who the pod writes as."""
        d = tmp_path / "beads"
        d.mkdir()
        monkeypatch.setattr(paths, "USERNS_ARG", "--userns=auto")
        with pytest.raises(PersistOwnershipError) as ei:
            persist.guard_ownership(d)
        assert "auto" in str(ei.value)

    def test_an_unresolved_mapping_refuses_before_the_dir_even_exists(self, tmp_path, monkeypatch):
        """An ABSENT dir used to return early, before the mapping was ever consulted — so the
        unresolved case escaped entirely on the common path (harnessed creates the dir itself)."""
        monkeypatch.setattr(paths, "USERNS_ARG", "--userns=keep-id")
        with pytest.raises(PersistOwnershipError):
            persist.guard_ownership(tmp_path / "does-not-exist-yet")

    def test_the_guard_would_have_caught_the_ci_failure(self, tmp_path, monkeypatch):
        """Run 31170180149's situation, which the guard waved through.

        The runner OWNS its own persist dir, so `st_uid == os.getuid()` and the old comparison
        passed. Under the bare mapping the pod still wrote as the image's uid, owned nothing, and
        the beads-server entrypoint died on `mkdir -p /data/dolt`.

        The runner condition is "the host user's uid differs from the image's uid". This dev box is
        uid 1000 and the image is uid 1000, so the condition is unreachable here by holding the host
        fixed — which is the whole reason six CI runs failed while every local run passed. It is
        reachable by moving the image's uid instead: the two-differ relation is what matters, not
        which side moved. `CONTAINER_UID` is patched rather than `os.getuid()` because `tmp_path` is
        really owned by the real uid, and a lie about ownership would test the lie.
        """
        d = tmp_path / "beads"
        d.mkdir()
        assert os.stat(d).st_uid == os.getuid(), "premise: the caller owns its own persist dir"
        monkeypatch.setattr(paths, "CONTAINER_UID", os.getuid() + 1)  # host uid != image uid
        monkeypatch.setattr(paths, "USERNS_ARG", "--userns=keep-id")  # ...and the mapping is bare

        with pytest.raises(PersistOwnershipError) as ei:
            persist.guard_ownership(d)

        msg = str(ei.value)
        # The refusal now comes from the mapping being UNRESOLVED rather than from a uid comparison:
        # under bare keep-id the image's uid is drawn from the subuid range, so there is no host uid
        # to compare against and guessing one was the fail-open bug CodeRabbit found.
        assert "keep-id" in msg and "subuid" in msg

    def test_the_same_dir_is_fine_once_the_mapping_is_pinned(self, tmp_path, monkeypatch):
        """The other half of the pair, and the one that proves the fix UNBLOCKS rather than merely
        relocating the refusal: same dir, same non-1000 host, mapping pinned → launch proceeds."""
        d = tmp_path / "beads"
        d.mkdir()
        monkeypatch.setattr(paths, "CONTAINER_UID", os.getuid() + 1)
        monkeypatch.setattr(paths, "USERNS_ARG", f"--userns=keep-id:uid={os.getuid() + 1},gid=0")
        persist.guard_ownership(d)  # no raise
