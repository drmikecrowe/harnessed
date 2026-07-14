"""The wheel must ship the catalog — and NOTHING host-local.

`harnessed` ships its catalog inside the wheel (see paths.harnessed_home) so an installed CLI can
`build` with no repo on disk. Two host-local artifacts have historically lived inside `catalog/`,
and setuptools FOLLOWS SYMLINKS, so either could be published:

  * `catalog/<kind>.local` → symlinks into the user's PRIVATE overlay (~/.config/harnessed/catalog).
    These now live in `catalog-local/` (paths.local_links_dir) and `harnessed build` unlinks stale
    ones — but an un-migrated checkout still has them on disk at wheel-build time.
  * `catalog/base/extra-tools.txt` → the user's resolved mise tool list. No longer staged into
    catalog/ (it goes into a temp build context), but old checkouts still carry one.

[tool.setuptools.exclude-package-data] is the backstop for exactly those un-migrated checkouts.
This test builds a REAL wheel with both artifacts planted and asserts they do not appear — a
config-only assertion would not catch a setuptools behavior change.
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or not (REPO / "pyproject.toml").is_file(),
    reason="needs uv and a source checkout to build a wheel",
)

_KINDS = ("agents", "recipes", "services", "stacks")


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory):
    """Build a wheel from a pristine copy of the checkout that ALSO carries the host-local
    artifacts, and return its member names."""
    src = tmp_path_factory.mktemp("src") / "harnessed"
    shutil.copytree(
        REPO, src, symlinks=True,
        ignore=shutil.ignore_patterns(".git", "build", "*.egg-info", ".venv", "node_modules"),
    )

    # A private overlay the `.local` symlinks point at — if packaged, this file is the smoking gun.
    overlay = src.parent / "private_overlay"
    for kind in _KINDS:
        (overlay / kind).mkdir(parents=True)
    (overlay / "recipes" / "my-secret-recipe").mkdir()
    (overlay / "recipes" / "my-secret-recipe" / "recipe.yaml").write_text("name: my-secret-recipe\n")

    for kind in _KINDS:
        link = src / "catalog" / f"{kind}.local"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(overlay / kind)
    (src / "catalog" / "base" / "extra-tools.txt").write_text("my-private-tool\n")

    out = src.parent / "dist"
    proc = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(out)],
        cwd=src, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stderr[-2000:]}"

    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return zipfile.ZipFile(wheels[0]).namelist()


class TestWheelShipsCatalog:
    def test_catalog_is_packaged(self, wheel_names):
        """Without this, an installed harnessed has no catalog and every stack is 'unknown'."""
        catalog = [n for n in wheel_names if "/catalog/" in n]
        assert catalog, "the wheel must contain the catalog"

    def test_base_dockerfiles_are_packaged(self, wheel_names):
        """The base build's -f Dockerfile and its context-relative COPY sources must ship."""
        for needed in (
            "harnessed/catalog/base/Dockerfile.harnessed-base",
            "harnessed/catalog/base/pnpm/config.yaml",
            "harnessed/catalog/base/harnessed-scan",
            "harnessed/catalog/base/harnessed-start",
        ):
            assert needed in wheel_names, f"{needed} missing from wheel"

    def test_stacks_and_recipes_are_packaged(self, wheel_names):
        assert any("/catalog/stacks/" in n for n in wheel_names)
        assert any("/catalog/recipes/" in n for n in wheel_names)
        assert any("/catalog/agents/" in n for n in wheel_names)

    def test_extra_tools_seed_ships(self, wheel_names):
        """The committed seed ships; only the user's resolved file is excluded."""
        assert "harnessed/catalog/base/extra-tools.default.txt" in wheel_names


class TestWheelExcludesHostLocalContent:
    def test_no_local_overlay_symlinks(self, wheel_names):
        leaked = [n for n in wheel_names if ".local" in n]
        assert leaked == [], f"catalog/*.local must not be packaged: {leaked}"

    def test_no_private_user_recipes(self, wheel_names):
        """The overlay the .local symlinks point at must never be followed into the wheel."""
        leaked = [n for n in wheel_names if "my-secret-recipe" in n]
        assert leaked == [], f"user's private overlay leaked into the wheel: {leaked}"

    def test_no_resolved_extra_tools(self, wheel_names):
        leaked = [n for n in wheel_names if n.endswith("catalog/base/extra-tools.txt")]
        assert leaked == [], f"the user's resolved extra-tools.txt must not be packaged: {leaked}"
