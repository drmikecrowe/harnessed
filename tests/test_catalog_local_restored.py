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


def test_restores_even_when_the_body_raises(tmp_path):
    repo = tmp_path / "repo"
    links = repo / "catalog-local"
    links.mkdir(parents=True)
    mine = _overlay(tmp_path / "real-xdg", "agents")
    (links / "agents").symlink_to(mine)

    with pytest.raises(_Boom):
        with catalog_local_restored(repo):
            (links / "agents").unlink()
            raise _Boom

    assert Path(os.readlink(links / "agents")) == mine
