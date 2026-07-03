"""Tests for persist directory lifecycle management (GC) — fast, no podman.

Covers:
  - persist_gc.list_entries: empty root, single entry, multiple recipes/projects/names.
  - persist_gc.prune_project: explicit name removal, all-names removal, no-op on missing dir,
    empty parent cleanup.
  - persist_gc._fmt_size: human-readable formatting.
  - CLI integration: persist-list and persist-prune subcommands via main().
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessed import paths
from harnessed.persist_gc import _fmt_size, list_entries, prune_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(tmp_data: Path, recipe: str, project_path: str, name: str, content: str = "x") -> Path:
    """Create a persist dir tree and write a file inside so it has non-zero size."""
    d = paths.persist_project_dir(recipe, project_path, name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.txt").write_text(content, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# list_entries
# ---------------------------------------------------------------------------


class TestListEntries:
    def test_empty_when_persist_root_absent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert list_entries() == []

    def test_empty_when_persist_root_exists_but_has_no_entries(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        paths.persist_root().mkdir(parents=True, exist_ok=True)
        assert list_entries() == []

    def test_single_entry(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        host = _make_entry(tmp_path, "context-mode", "/home/user/proj", ".context-mode")
        entries = list_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.recipe == "context-mode"
        assert e.name == ".context-mode"
        assert e.host_dir == host
        assert e.project_hash == paths.project_hash("/home/user/proj")

    def test_multiple_recipes_projects_names(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "recipe-a", "/proj/1", "cache")
        _make_entry(tmp_path, "recipe-a", "/proj/2", "cache")
        _make_entry(tmp_path, "recipe-b", "/proj/1", "state")
        entries = list_entries()
        assert len(entries) == 3
        recipes = {e.recipe for e in entries}
        assert recipes == {"recipe-a", "recipe-b"}

    def test_size_reflects_file_bytes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj", "data", content="hello")
        (entries := list_entries())
        assert entries[0].size_bytes == 5  # len("hello")


# ---------------------------------------------------------------------------
# prune_project
# ---------------------------------------------------------------------------


class TestPruneProject:
    def test_noop_when_no_matching_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        removed = prune_project("nonexistent", "/proj/x")
        assert removed == []

    def test_removes_specific_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        host = _make_entry(tmp_path, "rcp", "/proj", "cache")
        _make_entry(tmp_path, "rcp", "/proj", "state")  # different name — must survive
        removed = prune_project("rcp", "/proj", name="cache")
        assert removed == [host]
        assert not host.exists()
        # sibling name dir must still exist
        sibling = paths.persist_project_dir("rcp", "/proj", "state")
        assert sibling.is_dir()

    def test_removes_all_names_when_no_name_given(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = _make_entry(tmp_path, "rcp", "/proj", "cache")
        b = _make_entry(tmp_path, "rcp", "/proj", "state")
        removed = prune_project("rcp", "/proj")
        assert set(removed) == {a, b}
        assert not a.exists()
        assert not b.exists()

    def test_cleans_up_empty_hash_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj", "cache")
        prune_project("rcp", "/proj")
        ph = paths.project_hash("/proj")
        hash_dir = paths.persist_root() / "rcp" / ph
        assert not hash_dir.exists(), "empty hash dir should be cleaned up"

    def test_cleans_up_empty_recipe_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj", "cache")
        prune_project("rcp", "/proj")
        recipe_dir = paths.persist_root() / "rcp"
        assert not recipe_dir.exists(), "empty recipe dir should be cleaned up"

    def test_does_not_remove_recipe_dir_when_other_project_remains(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj/a", "cache")
        _make_entry(tmp_path, "rcp", "/proj/b", "cache")
        prune_project("rcp", "/proj/a")
        recipe_dir = paths.persist_root() / "rcp"
        assert recipe_dir.is_dir(), "recipe dir should survive while /proj/b still has data"
        remaining = _make_entry(tmp_path, "rcp", "/proj/b", "cache")  # path still exists
        assert remaining.is_dir()

    def test_noop_on_missing_specific_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj", "state")
        removed = prune_project("rcp", "/proj", name="nonexistent")
        assert removed == []
        # "state" dir should still be there
        assert paths.persist_project_dir("rcp", "/proj", "state").is_dir()


# ---------------------------------------------------------------------------
# _fmt_size
# ---------------------------------------------------------------------------


class TestFmtSize:
    def test_bytes(self):
        assert _fmt_size(512) == "512 B"

    def test_kib(self):
        assert _fmt_size(1024) == "1.0 KiB"

    def test_mib(self):
        assert _fmt_size(2 * 1024 * 1024) == "2.0 MiB"

    def test_gib(self):
        assert _fmt_size(3 * 1024 ** 3) == "3.0 GiB"

    def test_zero(self):
        assert _fmt_size(0) == "0 B"


# ---------------------------------------------------------------------------
# CLI integration — persist-list and persist-prune via main()
# ---------------------------------------------------------------------------


class TestCLIPersistList:
    def test_empty_output_when_no_entries(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        from harnessed.cli import main

        rc = main(["persist-list"])
        assert rc == 0

    def test_lists_entry(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "context-mode", "/home/user/myproj", ".context-mode")
        from harnessed.cli import main

        rc = main(["persist-list"])
        assert rc == 0


class TestCLIPersistPrune:
    def test_refuses_without_yes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_entry(tmp_path, "rcp", "/proj", "cache")
        from harnessed.cli import main

        rc = main(["persist-prune", "--recipe", "rcp", "--project", "/proj"])
        assert rc == 1
        # dir must be untouched
        assert paths.persist_project_dir("rcp", "/proj", "cache").is_dir()

    def test_prunes_with_yes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        host = _make_entry(tmp_path, "rcp", "/proj", "cache")
        from harnessed.cli import main

        rc = main(["persist-prune", "--recipe", "rcp", "--project", "/proj", "--yes"])
        assert rc == 0
        assert not host.exists()

    def test_prune_specific_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        cache = _make_entry(tmp_path, "rcp", "/proj", "cache")
        state = _make_entry(tmp_path, "rcp", "/proj", "state")
        from harnessed.cli import main

        rc = main(["persist-prune", "--recipe", "rcp", "--project", "/proj", "--name", "cache", "--yes"])
        assert rc == 0
        assert not cache.exists()
        assert state.is_dir()

    def test_noop_returns_zero(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        from harnessed.cli import main

        rc = main(["persist-prune", "--recipe", "rcp", "--project", "/proj", "--yes"])
        assert rc == 0
