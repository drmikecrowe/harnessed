"""tokensave on `tools:` — Phase 2's first migration, and NC-7's proof.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` Phase 2 and NC-7 ("tokensave's supply-chain
posture must not regress. It verifies a sha256 per arch today").

The deleted Dockerfile downloaded a release asset and verified a hand-written sha256 per arch under
`USER root`. That root requirement was never about the download — it was about the DESTINATION,
`/usr/local/bin`. mise installs into the stack's own tool tree, already on PATH in both modes, so
the privilege disappears and with it the audible host skip.

These tests replace the three parametrized cases tokensave lost when it left `ROOT_ONLY`. The one
that matters is `test_the_lockfile_checksums_are_the_ones_the_dockerfile_verified`: NC-7 is a claim
about CONTINUITY, and the only way to hold it is to compare against what the old file actually said.
"""

import tomllib

import pytest

from harnessed import paths
from harnessed.schema import load_recipe
from harnessed.toollock import recipe_lock_path

# Verbatim from the deleted Dockerfile's `case "$(uname -m)"` block, which verified them with
# `sha256sum -c` after the download. Hard-coded on purpose: a test that derived these from the
# lockfile would compare the lockfile to itself and prove nothing about continuity.
DOCKERFILE_SHA = {
    "linux-x64": "sha256:d35519fe698a24d2e2bb5622e94b3bdb4794dc1e36acffc980260b50afb40460",
    "linux-arm64": "sha256:69c88d0617036d44f2620f5779cd8578fad77664c2373d64de632b8e346ad334",
}
SPEC = "github:aovestdipaperino/tokensave@7.0.2"


@pytest.fixture
def recipe():
    return load_recipe(paths.harnessed_home() / "catalog" / "recipes" / "tokensave")


class TestTheMigration:
    def test_the_binary_now_comes_from_tools(self, recipe):
        assert SPEC in recipe.tools

    def test_the_dockerfile_is_gone(self, recipe):
        assert not (recipe.root / "Dockerfile").exists()

    def test_it_no_longer_declares_a_root_only_install(self, recipe):
        """The whole point: `install.system` existed to make a host skip AUDIBLE. With `tools:`
        there is no skip, because nothing needs privilege any more."""
        assert recipe.install is None or recipe.install.system is None

    def test_it_still_expects_its_mcp_server(self, recipe):
        """The migration moves WHERE the binary comes from and nothing else."""
        assert "tokensave" in (recipe.raw.get("expect", {}).get("mcp") or [])


class TestNC7SupplyChainContinuity:
    """The constraint that gated this migration for the whole epic."""

    def test_the_recipe_ships_a_lockfile(self, recipe):
        assert recipe_lock_path(recipe.root) is not None

    def test_the_lockfile_covers_the_pinned_spec(self, recipe):
        path = recipe_lock_path(recipe.root)
        assert path is not None
        locked = tomllib.loads(path.read_text(encoding="utf-8"))["tools"]
        assert "github:aovestdipaperino/tokensave" in locked

    @pytest.mark.parametrize("platform", sorted(DOCKERFILE_SHA))
    def test_the_lockfile_checksums_are_the_ones_the_dockerfile_verified(self, recipe, platform):
        """NC-7 is a continuity claim, so it is tested against the OLD file's literals.

        Same bytes, verified by a different mechanism: `sha256sum -c` in a RUN layer became a
        lockfile mise refuses to install past. Equal-or-better is the bar the constraint sets, and
        `github:` additionally verifies artifact attestations and SLSA provenance — which the
        hand-rolled check never did.
        """
        path = recipe_lock_path(recipe.root)
        assert path is not None
        entry = tomllib.loads(path.read_text(encoding="utf-8"))["tools"][
            "github:aovestdipaperino/tokensave"][0]
        assert entry[f"platforms.{platform}"]["checksum"] == DOCKERFILE_SHA[platform]

    def test_the_locked_version_matches_the_pin(self, recipe):
        """A lockfile for a different version verifies the wrong artifact perfectly."""
        path = recipe_lock_path(recipe.root)
        assert path is not None
        entry = tomllib.loads(path.read_text(encoding="utf-8"))["tools"][
            "github:aovestdipaperino/tokensave"][0]
        assert entry["version"] == SPEC.rpartition("@")[2]

    def test_both_linux_arches_are_covered(self, recipe):
        """The deleted Dockerfile handled x86_64 and aarch64 and hard-failed on anything else.
        Losing an arch here would mean an unverified install on that arch, not a failure."""
        path = recipe_lock_path(recipe.root)
        assert path is not None
        entry = tomllib.loads(path.read_text(encoding="utf-8"))["tools"][
            "github:aovestdipaperino/tokensave"][0]
        assert {"platforms.linux-x64", "platforms.linux-arm64"} <= set(entry)


def test_the_lockfile_is_the_one_the_stack_merge_would_pick_up():
    """Ties the recipe to the machinery: the file is where `stack_lock_body` looks for it."""
    from harnessed.toollock import stack_lock_body

    recipe = load_recipe(paths.harnessed_home() / "catalog" / "recipes" / "tokensave")
    body = stack_lock_body([recipe])
    assert "aovestdipaperino/tokensave" in body
    assert DOCKERFILE_SHA["linux-x64"] in body
