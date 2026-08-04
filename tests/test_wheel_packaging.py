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

_MISE_CONFIG = ("mise.toml", "mise.local.toml")
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "build", "*.egg-info", ".venv", "node_modules", *_MISE_CONFIG,
)


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory):
    """Build a wheel from a pristine copy of the checkout that ALSO carries the host-local
    artifacts, and return its member names."""
    src = tmp_path_factory.mktemp("src") / "harnessed"
    shutil.copytree(
        REPO, src, symlinks=True,
        # mise config is EXCLUDED, and not for tidiness. `uv` here is whatever is on PATH, and a
        # harnessed stack whose `tools:` include uv puts a mise SHIM there — the shim IS mise
        # (…/mise/shims/uv -> …/bin/mise), so `uv build` re-enters mise with cwd inside this copy.
        # mise then loads the copied config from a path it has never trusted and refuses; and once
        # trusted it evaluates `mise.toml`'s `{{exec(command="git branch --show-current")}}`, which
        # exits 128 because `.git` is deliberately not copied. Neither failure has anything to do
        # with packaging, and both present as an unexplained "wheel build failed".
        # Excluded rather than worked around: mise config is developer tooling, it is not packaging
        # input, and a build that consults it would not be reproducing what a user's `pip install`
        # does. With no config in the copy mise finds nothing to load and the shim is harmless.
        ignore=_COPY_IGNORE,
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


class TestTheBuildTreeIsHermetic:
    """The build copy must carry no mise config — a guard the wheel assertions cannot provide.

    `uv` in the fixture is whatever is on PATH. A harnessed stack whose `tools:` include uv puts a
    mise SHIM there, and the shim IS mise (`…/mise/shims/uv -> …/bin/mise`), so `uv build` re-enters
    mise with its cwd inside the copy. mise then refuses the never-trusted copied config, and once
    trusted dies evaluating `mise.toml`'s `{{exec(command="git branch --show-current")}}` because
    `.git` is deliberately not copied. Both surface only as "wheel build failed".

    That condition depends on the AMBIENT stack, so the wheel tests above cannot catch a regression
    here: with a stack that ships no uv shim they pass either way. This asserts the property
    directly instead, so removing the exclusion fails a test rather than lying dormant until
    someone launches the wrong stack.
    """

    def test_mise_config_is_excluded_from_the_build_copy(self, tmp_path):
        # Literal filenames, NOT a loop over `_MISE_CONFIG`: iterating the constant means emptying
        # it satisfies this test vacuously, which a mutation run caught doing exactly that.
        src = tmp_path / "src"
        src.mkdir()
        (src / "mise.toml").write_text("")
        (src / "mise.local.toml").write_text("")
        dst = tmp_path / "copy"
        shutil.copytree(src, dst, symlinks=True, ignore=_COPY_IGNORE)
        assert not (dst / "mise.toml").exists(), "mise.toml copied into the build tree"
        assert not (dst / "mise.local.toml").exists(), "mise.local.toml copied into the build tree"

    def test_the_repo_really_has_the_config_being_excluded(self):
        """Otherwise the test above passes vacuously the day mise.toml is renamed or removed."""
        assert (REPO / "mise.toml").is_file(), "mise.toml gone — revisit the exclusion and its test"
