"""Content-derived naming + minting for `harnessed run` (harnessed-7rx.3).

The name is MACHINE-FACING — it is never typed, only read back out of `harnessed list`,
`volume-gc` and `podman images`. So it is optimised for recognisability, not brevity, and falls
back to a hash only when the readable form would be ambiguous or over-long.
"""
from __future__ import annotations

import re

from pathlib import Path

import pytest

from harnessed import dynstack


class TestNormalize:
    def test_sorts_and_dedupes(self):
        assert dynstack.normalize(["serena", "superpowers", "serena"], None) == (
            None, ("serena", "superpowers"),
        )

    def test_keeps_the_base_separate(self):
        assert dynstack.normalize(["serena"], "default") == ("default", ("serena",))


class TestDeriveName:
    def test_order_does_not_matter(self):
        a = dynstack.derive_name(["superpowers", "serena"], "default")
        b = dynstack.derive_name(["serena", "superpowers"], "default")
        assert a == b

    def test_readable_join_for_a_simple_set(self):
        assert dynstack.derive_name(["superpowers", "serena"], "default") == (
            "default.serena.superpowers"
        )

    def test_no_base_omits_the_prefix(self):
        assert dynstack.derive_name(["serena"], None) == "serena"

    def test_differing_bases_differ(self):
        assert dynstack.derive_name(["serena"], "default") != dynstack.derive_name(["serena"], None)

    def test_slashed_ref_is_sanitised_and_hashed(self):
        """`beads/team` -> `beads-team` is lossy, so the hash disambiguates it from a real
        recipe literally named `beads-team`."""
        slashed = dynstack.derive_name(["beads/team"], None)
        flat = dynstack.derive_name(["beads-team"], None)
        assert slashed.startswith("beads-team-")
        assert slashed != flat

    def test_long_set_is_truncated_with_a_hash(self):
        name = dynstack.derive_name([f"recipe-number-{i}" for i in range(20)], "default")
        assert len(name) <= dynstack.NAME_MAX
        assert name != dynstack.derive_name([f"recipe-number-{i}" for i in range(19)], "default")

    def test_name_is_a_legal_single_path_component(self):
        name = dynstack.derive_name(["beads/team", "superpowers"], "default")
        assert "/" not in name and name not in (".", "..")

    def test_empty_recipe_set_is_rejected(self):
        with pytest.raises(ValueError, match="at least one recipe"):
            dynstack.derive_name([], None)

    def test_case_fold_collision_is_hashed(self):
        """`_sanitize` lowercases, so `Foo` and `foo` produce the same readable join. Without a
        digest they would share one generated manifest, image and pair of volumes."""
        assert dynstack.derive_name(["Foo"], None) != dynstack.derive_name(["foo"], None)

    def test_space_fold_collision_is_hashed(self):
        assert dynstack.derive_name(["foo bar"], None) != dynstack.derive_name(["foo-bar"], None)

    def test_different_services_yield_different_names(self):
        """`run --service` writes into the manifest, so identical recipes with different services
        are different stacks. Sharing a name would let them overwrite each other's manifest and
        share one image and volume pair."""
        a = dynstack.derive_name(["serena"], "default", services=["beads-server"])
        b = dynstack.derive_name(["serena"], "default", services=["other-svc"])
        assert a != b

    def test_service_order_and_duplicates_do_not_matter(self):
        a = dynstack.derive_name(["serena"], "default", services=["x", "y"])
        b = dynstack.derive_name(["serena"], "default", services=["y", "x", "y"])
        assert a == b

    def test_no_services_keeps_the_plain_readable_name(self):
        """Regression guard: adding services to the identity must not put a digest on the common
        case, which is every invocation that does not use the --service escape hatch."""
        assert dynstack.derive_name(["superpowers", "serena"], "default", services=[]) == (
            "default.serena.superpowers"
        )

    def test_services_are_not_confused_with_recipes(self):
        """The digest separates the groups, so a service named `b` must not collide with a recipe
        named `b`."""
        a = dynstack.derive_name(["a", "b"], None)
        b = dynstack.derive_name(["a"], None, services=["b"])
        assert a != b

    @pytest.mark.parametrize("ref", [".", "..", "***"])
    def test_refs_yielding_reserved_components_are_rejected(self, ref):
        """`.` and `..` survive sanitization and `***` sanitizes to empty, so mint would write to
        the stacks dir itself or to its parent."""
        with pytest.raises(ValueError, match="usable stack-name component"):
            dynstack.derive_name([ref], None)


class TestImageReferenceSafety:
    """The name is interpolated into a podman tag by `launcher._derived_image`
    (`harnessed-<harness>-<stack>:latest`). A character that is legal in a directory name but not in
    an OCI reference fails the BUILD, not the test suite — the suite runs no podman — so the grammar
    has to be asserted here or nothing catches it.

    OCI/docker name-component grammar: alphanumerics, separated by `.`, `_`, `__` or runs of `-`,
    with no leading or trailing separator.
    """

    COMPONENT = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*$")

    def _assert_taggable(self, name: str) -> None:
        assert self.COMPONENT.match(name), f"{name!r} is not a legal image-reference component"
        assert self.COMPONENT.match(f"harnessed-claude-{name}"), f"{name!r} breaks the tag"

    def test_the_real_world_set_is_taggable(self):
        """The set that actually failed: `podman build -t harnessed-claude-default+beads-team+...`
        died with 'invalid reference format' because `+` is not in the OCI alphabet."""
        self._assert_taggable(dynstack.derive_name(["superpowers", "beads/team"], "default"))

    @pytest.mark.parametrize("recipes,base,services", [
        (["serena"], None, None),
        (["superpowers", "serena"], "default", None),
        (["beads/team"], None, None),
        (["Foo Bar"], None, None),
        (["a_b"], "c.d", None),
        (["serena"], "default", ["beads-server"]),
        ([f"recipe-number-{i}" for i in range(20)], "default", None),
    ])
    def test_every_derived_name_is_taggable(self, recipes, base, services):
        self._assert_taggable(dynstack.derive_name(recipes, base, services=services))

    def test_separator_cannot_be_produced_by_sanitizing_a_ref(self):
        """The join separator must be OUTSIDE the sanitizer's output alphabet. If a sanitized ref
        could contain it, `["a<sep>b", "c"]` and `["a", "b<sep>c"]` would both join to `a<sep>b<sep>c`
        with neither detected as lossy — a silent collision onto one manifest, image and volume pair.
        """
        assert dynstack.derive_name(["a.b", "c"], None) != dynstack.derive_name(["a", "b.c"], None)
        assert dynstack.derive_name(["a_b", "c"], None) != dynstack.derive_name(["a", "b_c"], None)
        assert dynstack.derive_name(["a-b", "c"], None) != dynstack.derive_name(["a", "b-c"], None)


class TestMint:
    def test_writes_a_manifest_that_names_itself(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        name, d = dynstack.mint(["serena"], "default")
        text = (d / "stack.yaml").read_text()
        assert f"name: {name}" in text
        assert "extends: default" in text
        assert "- serena" in text

    def test_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        n1, d1 = dynstack.mint(["serena"], "default")
        first = (d1 / "stack.yaml").read_text()
        n2, d2 = dynstack.mint(["serena"], "default")
        assert (n1, d1) == (n2, d2)
        assert (d2 / "stack.yaml").read_text() == first

    def test_carries_explicit_services(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["beads/team"], "default", services=["beads-server"])
        assert "- beads-server" in (d / "stack.yaml").read_text()

    def test_different_service_selections_do_not_overwrite_each_other(self, tmp_path, monkeypatch):
        """Two mints differing ONLY in services must land in two directories. Before services
        entered the identity they derived one name, so the second silently rewrote the first."""
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        n1, d1 = dynstack.mint(["serena"], "default", services=["svc-a"])
        n2, d2 = dynstack.mint(["serena"], "default", services=["svc-b"])
        assert n1 != n2 and d1 != d2
        assert "- svc-a" in (d1 / "stack.yaml").read_text()
        assert "- svc-b" in (d2 / "stack.yaml").read_text()

    def test_no_base_emits_no_extends_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["serena"], None)
        assert "extends:" not in (d / "stack.yaml").read_text()

    def test_authored_stack_of_the_same_name_is_refused(self, tmp_path, monkeypatch):
        """The generated root is LAST in precedence, so an authored stack of the same derived name
        wins resolution and would be built and launched instead of this one. Refuse, don't shadow."""
        authored = tmp_path / "authored"
        (authored / "stacks" / "serena").mkdir(parents=True)
        (authored / "stacks" / "serena" / "stack.yaml").write_text("name: serena\nrecipes: []\n")
        gen = tmp_path / "gen"
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: gen)
        monkeypatch.setattr(dynstack.paths, "catalog_roots", lambda: [authored, gen])

        with pytest.raises(ValueError, match="collides with an authored stack"):
            dynstack.mint(["serena"], None)

    def test_manifest_is_marked_generated_in_a_comment_not_a_field(self, tmp_path, monkeypatch):
        """Stack manifests REJECT unknown fields, so the marker must be a comment."""
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["serena"], "default")
        text = (d / "stack.yaml").read_text()
        assert text.lstrip().startswith("#")
        assert "generated:" not in text


class TestModuleBoundary:
    """`dynstack` is the exemplar for the launcher.py split (bd harnessed-4l8).

    launcher.py is 7016 lines — 53% of the codebase — with 20 commands and 179 private helpers.
    The extraction pattern it needs is a DIRECTION rule: pure, derivable logic lives in a focused
    module; launcher.py keeps only the Typer surface and podman orchestration; dependencies point
    INTO the modules and never back out.

    This test is the enforcement. The moment `dynstack` reaches back into `launcher`, the direction
    reverses and every later extraction inherits an import cycle — which is precisely why the `run`
    COMMAND stays in launcher.py: it needs `_build_stack`, `_runtime`, `launch` and `_err`, so a
    module holding it could only work through a cycle or an indirection. Commands are the most
    coupled thing in that file and are the wrong place to start; pure logic is the right place.
    """

    def test_dynstack_does_not_import_launcher(self):
        src = (Path(__file__).parent.parent / "src" / "harnessed" / "dynstack.py").read_text()
        assert "launcher" not in src, (
            "dynstack must not depend on launcher — the dependency points INTO modules, never "
            "back out (bd harnessed-4l8)"
        )


class TestTheDefaultBaselineShips:
    """`--extends` defaults to a stack NAME, so the repo has to ship that stack.

    Until it did, the default was live only for users who had authored a `default` stack in their
    own overlay: a fresh install running `harnessed container-run claude --recipe foo` minted a
    manifest saying `extends: default` and then died on `no such stack`. The failure is in the
    inherited default, not in anything the user typed, so it reads as harnessed being broken.
    """

    def _repo(self) -> Path:
        return Path(__file__).parent.parent

    def test_the_extends_default_names_a_stack_the_repo_ships(self):
        from harnessed import launcher

        name = launcher._EXTENDS_OPT.default
        assert (self._repo() / "catalog" / "stacks" / name / "stack.yaml").is_file(), (
            f"--extends defaults to {name!r}; the repo catalog must ship that stack or every "
            f"default `--recipe` launch fails on a fresh install"
        )

    def test_the_default_stack_composes_the_default_recipe(self):
        from ruamel.yaml import YAML

        raw = YAML(typ="safe").load(
            self._repo() / "catalog" / "stacks" / "default" / "stack.yaml"
        )
        assert raw["recipes"] == ["default"]

    def test_the_default_recipe_ships_the_authoring_skill(self):
        """The skill dir is the ONE copy; .agents/skills/ links to it. A move that breaks the link
        or the recipe path leaves the shipped baseline delivering nothing."""
        repo = self._repo()
        skill = repo / "catalog" / "recipes" / "default" / "skills" / "harnessed-catalog"
        assert (skill / "SKILL.md").is_file()
        link = repo / ".agents" / "skills" / "harnessed-catalog"
        assert link.is_symlink() and link.resolve() == skill.resolve()
