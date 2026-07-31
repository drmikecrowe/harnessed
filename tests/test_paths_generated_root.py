"""The generated-stack root (harnessed-7rx.2).

Machine-minted stacks live under XDG DATA, NOT in the user's authoring overlay, so `harnessed list`
can distinguish them and a regenerated manifest can never clobber a hand-written one. It must be
enumerable, because volume-gc/host-gc define an orphan as "its stack no longer resolves".
"""
from __future__ import annotations

from harnessed import paths


def test_generated_root_is_under_xdg_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.generated_catalog_root() == tmp_path / "harnessed" / "generated"


def test_generated_root_is_a_catalog_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "harnessed" / "generated").mkdir(parents=True)
    assert paths.generated_catalog_root() in paths.catalog_roots()


def test_generated_root_loses_to_the_user_overlay(tmp_path, monkeypatch):
    """An authored stack must win over a generated one of the same name."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "data" / "harnessed" / "generated").mkdir(parents=True)
    (tmp_path / "config" / "harnessed" / "catalog").mkdir(parents=True)
    roots = paths.catalog_roots()
    assert roots.index(paths.user_catalog()) < roots.index(paths.generated_catalog_root())


def test_absent_generated_root_is_omitted(tmp_path, monkeypatch):
    """Never hand podman or the resolver a path that does not exist."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.generated_catalog_root() not in paths.catalog_roots()


def test_generated_stacks_are_enumerated(tmp_path, monkeypatch):
    """volume-gc/host-gc orphan detection depends on this.

    Note the shape: the ROOT contains `stacks/`, exactly like the other two catalog roots, because
    `list_catalog` iterates `root / kind`.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = tmp_path / "harnessed" / "generated" / "stacks" / "gen-stack"
    d.mkdir(parents=True)
    (d / "stack.yaml").write_text("name: gen-stack\nrecipes: []\nservices: []\n")
    assert "gen-stack" in paths.list_catalog_stacks()
