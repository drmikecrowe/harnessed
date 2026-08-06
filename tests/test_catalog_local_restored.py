"""bd harnessed-ng5 — the suite must leave `<checkout>/catalog-local/` exactly as it found it.

`harnessed build` maintains those symlinks against whatever `$XDG_CONFIG_HOME` is set at the time,
and every test in this suite runs under a fresh tmp one (`conftest._isolated_user_catalog`). The
live tests shell out to the real binary in the real checkout, so without this the developer's own
overlay links come back pointing into a `/tmp` tree that pytest deletes on the way out — invisible
in `git status`, because `catalog-local/` is gitignored.

The restore is a plain context manager rather than only a fixture so these tests can drive it
directly, without `pytester`. It is imported from `conftest`, not `support`, because
`test_live_gate_accounting` copies the shipped conftest verbatim into a sandbox where `support` is
not importable — so conftest may not import from it.
"""

from __future__ import annotations

import os
import shutil

from pathlib import Path

import pytest

from conftest import catalog_local_restored

_KINDS = ("agents", "recipes", "services", "stacks")


class _Boom(Exception):
    """A type nothing else raises.

    Deliberately not `RuntimeError`: `NotImplementedError` subclasses it, so a `pytest.raises(
    RuntimeError)` here was satisfied by the not-yet-implemented stub and the test passed against
    an empty implementation. Caught in RED.
    """


def _overlay(root: Path, kind: str) -> Path:
    """A dir shaped like a user overlay: `<root>/harnessed/catalog/<kind>`."""
    d = root / "harnessed" / "catalog" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_restores_a_link_the_body_repointed(tmp_path):
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    mine = _overlay(tmp_path / "real-xdg", "agents")
    (links / "agents").symlink_to(mine)

    with catalog_local_restored(repo):
        (links / "agents").unlink()
        (links / "agents").symlink_to(_overlay(tmp_path / "tmp-xdg", "agents"))

    assert Path(os.readlink(links / "agents")) == mine


def test_removes_links_the_body_added_when_catalog_local_was_absent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with catalog_local_restored(repo):
        links = repo / "catalog-local"
        links.mkdir()
        for kind in _KINDS:
            (links / kind).symlink_to(_overlay(tmp_path / "tmp-xdg", kind))

    assert not (repo / "catalog-local").exists(), (
        "a catalog-local/ that did not exist before must not survive the run"
    )


def test_removes_a_link_the_body_added_beside_an_existing_one(tmp_path):
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    kept = _overlay(tmp_path / "real-xdg", "agents")
    (links / "agents").symlink_to(kept)

    with catalog_local_restored(repo):
        (links / "recipes").symlink_to(_overlay(tmp_path / "tmp-xdg", "recipes"))

    assert Path(os.readlink(links / "agents")) == kept
    assert not (links / "recipes").is_symlink(), "the link the body added must be gone"
    assert links.is_dir(), "a catalog-local/ that existed before must be left in place"


def test_never_touches_real_content(tmp_path):
    """A real directory at `catalog-local/<kind>` is the user's — never unlinked, before or after."""
    repo = tmp_path / "repo"
    real = repo / "catalog-local" / "recipes"
    real.mkdir(parents=True)
    (real / "keep.txt").write_text("mine\n")

    with catalog_local_restored(repo):
        (repo / "catalog-local" / "stacks").mkdir()
        (repo / "catalog-local" / "stacks" / "also-keep.txt").write_text("mine too\n")

    assert (real / "keep.txt").read_text() == "mine\n"
    assert (repo / "catalog-local" / "stacks" / "also-keep.txt").read_text() == "mine too\n"


def test_real_content_the_body_created_outranks_restoring_the_link(tmp_path):
    """The two invariants collide here, and NEVER-DELETE wins. Deliberate, and pinned.

    Adversarial review, finding B1: if the body replaces a snapshotted symlink with a real
    directory, restoring the link would mean deleting that directory. It is not this helper's to
    delete — a test that leaves real content behind has done something surprising, and destroying
    it is worse than leaving it. So the content stays and the link is NOT restored.
    """
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    (links / "agents").symlink_to(_overlay(tmp_path / "real-xdg", "agents"))

    with catalog_local_restored(repo):
        (links / "agents").unlink()
        (links / "agents").mkdir()
        (links / "agents" / "surprise.txt").write_text("body wrote this\n")

    assert (links / "agents" / "surprise.txt").read_text() == "body wrote this\n"
    assert not (links / "agents").is_symlink()


def test_real_content_is_never_even_written_over(tmp_path, monkeypatch):
    """The property is "don't TOUCH real content", not "real content happens to survive".

    Adversarial review round 3, findings B2/C1: the assertions above pass with the
    `elif path.exists(): continue` guard DELETED, because `symlink_to` then raises FileExistsError
    and the round-2 `except OSError` swallows it — same end state, no test can tell. That made a
    guard added in round 1 undetectable by a fix added in round 2, which is how a protection quietly
    becomes decoration.

    So assert the thing the swallow cannot fake: no attempt is made at all.
    """
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    (links / "agents").symlink_to(_overlay(tmp_path / "real-xdg", "agents"))

    attempted: list[Path] = []
    real_symlink_to = Path.symlink_to

    def recording_symlink_to(self, target, *a, **kw):
        attempted.append(self)
        return real_symlink_to(self, target, *a, **kw)

    monkeypatch.setattr(Path, "symlink_to", recording_symlink_to)

    with catalog_local_restored(repo):
        (links / "agents").unlink()
        (links / "agents").mkdir()

    monkeypatch.undo()
    assert (links / "agents") not in attempted, (
        "teardown tried to symlink over real content and relied on the error being swallowed"
    )


def test_real_content_destroyed_by_the_body_is_not_recoverable(tmp_path):
    """The snapshot is of LINKS, not of content — so this is a limit, pinned rather than implied.

    Adversarial review round 3, finding B1: a real directory present before the session is recorded
    as `None` (not a symlink). If the body deletes it and puts a symlink there, teardown removes the
    symlink — correctly, it is not ours to keep — and has nothing to put back. The directory is gone,
    destroyed by the BODY, not by this helper, which never copied its contents and could not.

    "Leave it as you found it" therefore means links, not bytes. Nothing in `harnessed build`
    produces this state; a test that does has already done something surprising.
    """
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    real = links / "agents"
    real.mkdir()
    (real / "user-content.txt").write_text("mine\n")

    with catalog_local_restored(repo):
        shutil.rmtree(real)
        real.symlink_to(_overlay(tmp_path / "tmp-xdg", "agents"))

    assert not real.exists(), "the body destroyed it; the helper cannot and does not resurrect it"
    assert not real.is_symlink(), "but the helper does remove the link the body left"


def test_restores_every_kind_even_when_the_body_raises(tmp_path):
    """All four kinds, not just the first.

    Adversarial review round 2, finding 4: snapshotting only `agents` here let a restore that
    skipped every other kind on the exception path pass.
    """
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    mine = {k: _overlay(tmp_path / "real-xdg", k) for k in _KINDS}
    for kind in _KINDS:
        (links / kind).symlink_to(mine[kind])

    with pytest.raises(_Boom):
        with catalog_local_restored(repo):
            # RE-POINT rather than merely delete: if the body left the links untouched, a teardown
            # that did nothing at all would pass this test (review round 3, finding C3).
            for kind in _KINDS:
                (links / kind).unlink()
                (links / kind).symlink_to(_overlay(tmp_path / "tmp-xdg", kind))
            raise _Boom

    for kind in _KINDS:
        assert Path(os.readlink(links / kind)) == mine[kind]


def test_a_failure_restoring_one_kind_neither_masks_the_body_nor_stops_the_rest(tmp_path, monkeypatch):
    """Teardown must never become the error the developer sees.

    Adversarial review round 2, finding 3: the restore loop had no per-item handler, so an OSError
    on the first kind propagated out of the `finally` — replacing the body's real exception with a
    teardown one, and leaving the remaining three kinds unrestored. A test that fails for the wrong
    reason is worse than one that fails.
    """
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    mine = {k: _overlay(tmp_path / "real-xdg", k) for k in _KINDS}
    for kind in _KINDS:
        (links / kind).symlink_to(mine[kind])

    real_unlink = Path.unlink

    def exploding_unlink(self, *a, **kw):
        if self.name == "agents":
            raise PermissionError("simulated: cannot unlink agents")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", exploding_unlink)

    with pytest.raises(_Boom):  # the BODY's exception, not the teardown's
        with catalog_local_restored(repo):
            raise _Boom

    monkeypatch.undo()
    for kind in _KINDS:
        assert Path(os.readlink(links / kind)) == mine[kind], f"{kind} not restored"
