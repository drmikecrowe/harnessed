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
import subprocess
from pathlib import Path

import pytest

from harnessed import paths
from harnessed.ctrquery import _runtime

from support import podman

# NOT `Path.home() / ".config"` (#432). `conftest._isolated_home` points HOME at an empty tmp dir
# for the session, so recomputing the guard path from the home would make both tests below skip
# on EVERY machine — the exact "test quietly stops running while the suite stays green" failure
# this file exists to pin. `_REAL_XDG_CONFIG_HOME` is captured at conftest import, before any
# fixture moves either variable, and it also honors a non-default XDG_CONFIG_HOME that
# `Path.home() / ".config"` never did.
from tests.conftest import _REAL_HOME, _REAL_XDG_CONFIG_HOME, _REAL_XDG_DATA_HOME


class TestPodmanConfigIsReachable:
    def test_the_isolated_root_exposes_containers(self):
        """The whole point: podman's config dir resolves from inside the isolated XDG root."""
        real = Path(os.environ["XDG_CONFIG_HOME"]) / "containers"
        if not (_REAL_XDG_CONFIG_HOME / "containers").is_dir():
            pytest.skip("no ~/.config/containers on this machine — nothing to expose")
        assert real.exists(), (
            "containers/ is not reachable from the isolated XDG root, so rootless podman cannot "
            "read storage.conf and will look for images in the wrong graphroot"
        )

    def test_storage_conf_is_readable_through_it(self):
        """`storage.conf` is the specific file that carries `graphroot`. Exposing the directory but
        not reaching the file would leave the bug in place."""
        src = _REAL_XDG_CONFIG_HOME / "containers" / "storage.conf"
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


class TestPodmanStorageSurvivesTheIsolatedHome:
    """The HOME half of the same collision — the one that reddened live.yml on `main`.

    `TestPodmanConfigIsReachable` above pins the graphroot only for a machine that DECLARES one in
    `storage.conf`. A GitHub runner declares none, so podman uses its default — derived from HOME —
    and `conftest._isolated_home` moved it away from the store `harnessed build` had just filled.
    """

    def test_the_isolated_home_exposes_container_storage(self):
        if not (_REAL_XDG_DATA_HOME / "containers").is_dir():
            pytest.skip("no containers data dir on this machine — nothing to expose")
        exposed = Path(os.environ["HOME"]) / ".local" / "share" / "containers"
        assert exposed.is_dir(), (
            "the real containers store is not reachable from the isolated HOME, so rootless "
            "podman resolves an EMPTY default graphroot and tries to pull `localhost/…` images "
            "from a registry named localhost"
        )
        assert exposed.resolve() == (_REAL_XDG_DATA_HOME / "containers").resolve()

    def test_only_the_store_is_linked_back(self):
        """The half that must not regress: exposing the store is not restoring the home.

        Asserted on the SHAPE of the exposure rather than on absent paths. The suite writes into the
        isolated home as it runs — `paths` resolves `$XDG_DATA_HOME` to `$HOME/.local/share` when
        the variable is unset — so "`~/.claude` does not exist" would be an assertion about test
        ORDER, which `pytest-randomly` reshuffles. That the leaf is the only symlink is not.
        """
        assert Path.home() != _REAL_HOME
        assert not (Path.home() / ".local").is_symlink(), (
            "the whole .local tree is linked back, which exposes far more than podman's store"
        )
        assert not (Path.home() / ".local" / "share").is_symlink()


@podman
def test_the_isolated_home_does_not_move_the_graphroot():
    """The property, asserted against the real binary: HOME isolation must not move the store.

    Everything above is reachability of a path. This is what actually failed — podman's OWN answer
    for where its images live, under the isolated HOME, must equal its answer under the real one.
    Machine-independent by construction: it compares podman to itself rather than to a literal, so
    it holds whether or not this machine declares a graphroot.
    """
    fmt = "{{.Store.GraphRoot}}"
    rt = _runtime()
    isolated = subprocess.run(
        [rt, "info", "--format", fmt], capture_output=True, text=True, check=True
    ).stdout.strip()
    real = subprocess.run(
        [rt, "info", "--format", fmt],
        capture_output=True, text=True, check=True,
        env={**os.environ, "HOME": str(_REAL_HOME)},
    ).stdout.strip()
    assert isolated == real, (
        f"the suite's isolated HOME moved podman's graphroot ({isolated}) away from the store "
        f"`harnessed build` populates ({real}); every localhost/… image is invisible to the tests"
    )


class TestTestsThatOptOutStillWin:
    def test_a_test_can_still_override_xdg_config_home(self, monkeypatch, tmp_path):
        """test_ensure_local_catalog_links / test_persist_* set their own XDG_CONFIG_HOME; their
        monkeypatch runs after the autouse fixture and must keep winning."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert paths.user_catalog() == tmp_path / "harnessed" / "catalog"
