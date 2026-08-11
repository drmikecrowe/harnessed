"""codebase-memory-mcp on `tools:` — Phase 2's second migration.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §1 Family A — *"already uses the mise
`github:` backend, just in shell. Host branch symlinks into `$UV_TOOL_BIN_DIR` — must confirm
`tools:` reproduces that on a host launch"*.

The deleted `install.sh` was a hand-rolled `mise use -g` / `mise install` and nothing else. It
branched on `HARNESSED_MODE` for one reason: a host `mise use -g` would have written the USER's own
`~/.config/mise/config.toml`, putting cbm in every shell they open. That reason is gone — a host
launch redirects `MISE_CONFIG_DIR` and `MISE_DATA_DIR` into the stack's own tree
(`hostrun._apply_host_mise_env`), and the stack's mise shims dir is on the agent's PATH
(`launcher._launch_host` via `_host_tool_shims_dir`), which is what the manual `ln -sf` into
`$UV_TOOL_BIN_DIR` was for. Both properties are asserted for EVERY recipe in
`tests/test_tools_field_parity.py`, so they are deliberately not restated here.

The supply-chain half is a different shape from tokensave's. tokensave had a hand-written sha256 to
preserve, so NC-7 was a continuity claim tested against the old literal. This recipe's shell
verified NO checksum at all, so there is nothing to be continuous with — the lockfile is new
coverage, and the only honest way to test it is against the published assets themselves.
"""

import tomllib

import pytest

from harnessed import paths
from harnessed.schema import load_recipe
from harnessed.toollock import recipe_lock_path

SPEC = "github:DeusData/codebase-memory-mcp@0.9.0"
BACKEND = SPEC.rpartition("@")[0]

# sha256 of the release assets themselves, downloaded from
# https://github.com/DeusData/codebase-memory-mcp/releases/tag/v0.9.0 and hashed with `sha256sum`
# — NOT copied out of `mise.lock`. Deriving them from the lockfile would compare it to itself and
# prove nothing; these are what makes the lockfile's claim checkable at all, given there was no
# previous checksum in the recipe to compare against.
PUBLISHED_SHA = {
    "linux-x64": "sha256:e2832a8d207c26beaa30efa6222ed4a37cb3f526ca4bee060bfbf336ed6fc679",
    "linux-arm64": "sha256:68a345d9a6842f02a3cb07e187b28bc38c4f3a22967f47fadbcd0757ba93a680",
}


@pytest.fixture
def recipe():
    return load_recipe(paths.harnessed_home() / "catalog" / "recipes" / "codebase-memory-mcp")


def _locked(recipe):
    path = recipe_lock_path(recipe.root)
    assert path is not None, "the recipe ships no mise.lock"
    return tomllib.loads(path.read_text(encoding="utf-8"))["tools"][BACKEND][0]


class TestTheMigration:
    def test_the_binary_now_comes_from_tools(self, recipe):
        assert SPEC in recipe.tools

    def test_the_install_script_is_gone_entirely(self, recipe):
        """Not "emptied" — removed. Every line it held was a `mise install` by hand, so a surviving
        script would mean the install happens twice or that a second pin exists to drift."""
        assert recipe.install is None or recipe.install.script is None
        assert not (recipe.root / "install.sh").exists()

    def test_it_has_no_dockerfile_either(self, recipe):
        assert not (recipe.root / "Dockerfile").exists()

    def test_it_still_expects_its_mcp_server(self, recipe):
        """The migration changes WHERE the binary comes from and nothing else. `expect:` is the only
        way the capability test learns the binary should be there, since no script announces it."""
        assert "codebase-memory-mcp" in (recipe.raw.get("expect", {}).get("mcp") or [])

    def test_the_installed_binary_is_the_one_the_mcp_entry_spawns(self, recipe):
        """hatago spawns this command as a stdio child. If `tools:` delivered a differently-named
        binary the server would silently resolve to nothing — the exact failure the original
        Dockerfile-only install had on a host launch."""
        assert recipe.servers[0].command == "codebase-memory-mcp"


class TestTheLockfileIsNewCoverage:
    """NC-7 as it applies here: the shell verified nothing, so this is a gain, not parity."""

    def test_the_recipe_ships_a_lockfile(self, recipe):
        assert recipe_lock_path(recipe.root) is not None

    def test_the_lockfile_covers_the_pinned_spec(self, recipe):
        assert _locked(recipe)

    def test_the_locked_version_matches_the_pin(self, recipe):
        """A lockfile for a different version verifies the wrong artifact perfectly."""
        assert _locked(recipe)["version"] == SPEC.rpartition("@")[2]

    @pytest.mark.parametrize("platform", sorted(PUBLISHED_SHA))
    def test_the_lockfile_checksums_are_the_published_assets(self, recipe, platform):
        """The whole of the guarantee: mise refuses the install on a mismatch. A lockfile nobody
        checked against upstream would enforce whatever bytes happened to be downloaded the day it
        was generated."""
        assert _locked(recipe)[f"platforms.{platform}"]["checksum"] == PUBLISHED_SHA[platform]

    def test_both_linux_arches_are_covered(self, recipe):
        """A missing arch is an UNVERIFIED install on that arch, not a failure — the silent shape."""
        assert {"platforms.linux-x64", "platforms.linux-arm64"} <= set(_locked(recipe))


def test_the_lockfile_is_the_one_the_stack_merge_would_pick_up():
    """Ties the recipe to the machinery: the file is where `stack_lock_body` looks for it."""
    from harnessed.toollock import stack_lock_body

    recipe = load_recipe(paths.harnessed_home() / "catalog" / "recipes" / "codebase-memory-mcp")
    body = stack_lock_body([recipe])
    assert "DeusData/codebase-memory-mcp" in body
    assert PUBLISHED_SHA["linux-x64"] in body
