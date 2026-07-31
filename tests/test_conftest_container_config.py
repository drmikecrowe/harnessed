"""The isolated XDG root must still let podman find its own config (bd harnessed-vs8).

`conftest._isolated_user_catalog` points XDG_CONFIG_HOME at an empty tmp dir for every test, because
`paths.catalog_roots()` puts `$XDG_CONFIG_HOME/harnessed/catalog` AHEAD of the repo catalog — so
without it the suite silently reads whatever overlay the developer happens to have. That is right and
load-bearing.

The collision: ROOTLESS PODMAN also reads `$XDG_CONFIG_HOME/containers/storage.conf`, and that is
where a custom `graphroot` is declared. Blanked, podman falls back to the DEFAULT graphroot, finds an
empty image store, and tries to PULL a `localhost/…` image from a registry literally named
`localhost`:

    Trying to pull localhost/harnessed-base:latest...
    dial tcp [::1]:443: connect: connection refused

It presents as a network failure and has nothing to do with networking. Every HARNESSED_PODMAN=1
module is affected on a machine whose graphroot is not the default.

The fix is deliberately NOT "restore the real XDG_CONFIG_HOME for podman runs" — that would hand
those tests the developer's catalog overlay back and reintroduce the exact machine-dependence the
isolation exists to remove. Instead the isolated root gets a SYMLINK to the real `containers/` dir:
podman sees its config, `harnessed/catalog` is still absent, and the two concerns stop fighting.

These tests pin both halves, because a fix that quietly traded hermeticity for podman would look
identical from the outside.
"""

import os
from pathlib import Path

import pytest

from harnessed import paths


class TestPodmanConfigIsReachable:
    def test_the_isolated_root_exposes_containers(self):
        """The whole point: podman's config dir resolves from inside the isolated XDG root."""
        real = Path(os.environ["XDG_CONFIG_HOME"]) / "containers"
        if not (Path.home() / ".config" / "containers").is_dir():
            pytest.skip("no ~/.config/containers on this machine — nothing to expose")
        assert real.exists(), (
            "containers/ is not reachable from the isolated XDG root, so rootless podman cannot "
            "read storage.conf and will look for images in the wrong graphroot"
        )

    def test_storage_conf_is_readable_through_it(self):
        """`storage.conf` is the specific file that carries `graphroot`. Exposing the directory but
        not reaching the file would leave the bug in place."""
        src = Path.home() / ".config" / "containers" / "storage.conf"
        if not src.is_file():
            pytest.skip("no storage.conf on this machine (default graphroot — bug cannot bite)")
        via_isolated = Path(os.environ["XDG_CONFIG_HOME"]) / "containers" / "storage.conf"
        assert via_isolated.is_file()
        assert via_isolated.read_text() == src.read_text()


class TestHermeticityIsUnchanged:
    """The half that must NOT regress. If the fix had simply restored the real XDG_CONFIG_HOME,
    every assertion above would pass and the suite would quietly become machine-dependent again."""

    def test_the_user_catalog_overlay_is_still_hidden(self):
        assert not paths.user_catalog().is_dir(), (
            "the developer's catalog overlay is visible again — name resolution is now "
            "machine-dependent, which is what _isolated_user_catalog exists to prevent"
        )

    def test_catalog_roots_is_the_repo_catalog_alone(self, tmp_path, monkeypatch):
        """XDG_DATA_HOME is pinned to an empty dir because the conftest isolates XDG_CONFIG_HOME
        (the user overlay) but NOT XDG_DATA_HOME, where the generated root lives. Without this the
        assertion passes only until the developer's first `harnessed run` creates
        `~/.local/share/harnessed/generated` — after which this hermeticity guard fails on the
        machine, not in the code. Same isolation gap as the one fixed in
        test_harnessed_home.test_catalog_roots_end_at_home."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        roots = paths.catalog_roots()
        assert len(roots) == 1, f"expected only the repo catalog, got {roots}"
        assert roots[0] == paths.harnessed_home() / "catalog"

    def test_the_isolated_root_is_not_the_real_one(self):
        real = os.environ.get("XDG_CONFIG_HOME_REAL") or str(Path.home() / ".config")
        assert os.environ["XDG_CONFIG_HOME"] != real

    def test_nothing_but_containers_is_exposed(self):
        """A blanket copy of ~/.config would drag in far more than podman needs, including the
        overlay. Only `containers` may be present."""
        entries = {p.name for p in Path(os.environ["XDG_CONFIG_HOME"]).iterdir()}
        assert entries <= {"containers"}, f"unexpected entries in the isolated XDG root: {entries}"


class TestTestsThatOptOutStillWin:
    def test_a_test_can_still_override_xdg_config_home(self, monkeypatch, tmp_path):
        """test_ensure_local_catalog_links / test_persist_* set their own XDG_CONFIG_HOME; their
        monkeypatch runs after the autouse fixture and must keep winning."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert paths.user_catalog() == tmp_path / "harnessed" / "catalog"
