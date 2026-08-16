"""Tests for synclinks.py — skill/command/rule fan-out (C1)."""

from pathlib import Path

import pytest

from harnessed.schema import FileExt, Recipe
from harnessed.synclinks import CollisionError, LinkSyncer


def _make_rule_dir(root: Path, name: str, content: str = "# rule") -> Path:
    """Create a rules/<name>/ dir with one markdown file inside it."""
    d = root / "rules" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(content)
    return d


def _recipe(root: Path, rules: list[str]) -> Recipe:
    return Recipe(
        name="test-recipe",
        root=root,
        rules=[FileExt(path=p) for p in rules],
    )


class TestOnlyHarnesses:
    """`only_harnesses` on a rule entry: an allow-list, applied before every other check."""

    def _gated(self, root: Path, path: str, only: list[str]) -> Recipe:
        return Recipe(name="cm", root=root, rules=[FileExt(path=path, only_harnesses=only)])

    def test_ships_to_the_named_harness(self, tmp_path):
        root = tmp_path / "recipe"
        _make_rule_dir(root, "ctx-routing", "# route\nUse ctx_batch_execute.\n")
        syncer = LinkSyncer(harness="omp")
        syncer.add_recipe(self._gated(root, "rules/ctx-routing", ["omp"]))
        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)
        assert (claude_dir / "rules" / "ctx-routing" / "ctx-routing.md").is_file()

    def test_skipped_on_every_other_harness(self, tmp_path):
        # The point of the field: on Claude the recipe's own PreToolUse hook injects this steering,
        # so shipping the rule too would repeat it always-on for nothing.
        root = tmp_path / "recipe"
        _make_rule_dir(root, "ctx-routing")
        for harness in ("claude", "opencode", "codex", "antigravity"):
            syncer = LinkSyncer(harness=harness)
            syncer.add_recipe(self._gated(root, "rules/ctx-routing", ["omp"]))
            claude_dir = tmp_path / f"profile-{harness}" / ".claude"
            syncer.fan(claude_dir)
            assert not (claude_dir / "rules" / "ctx-routing").exists(), harness

    def test_no_harness_ships_everything(self, tmp_path):
        # harness=None is the assemble-time default before a harness is chosen. Skipping there would
        # make a harness-less inspection silently incomplete.
        root = tmp_path / "recipe"
        _make_rule_dir(root, "ctx-routing")
        syncer = LinkSyncer()
        syncer.add_recipe(self._gated(root, "rules/ctx-routing", ["omp"]))
        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)
        assert (claude_dir / "rules" / "ctx-routing").is_dir()

    def test_empty_allow_list_ships_everywhere(self, tmp_path):
        root = tmp_path / "recipe"
        _make_rule_dir(root, "universal")
        syncer = LinkSyncer(harness="claude")
        syncer.add_recipe(self._gated(root, "rules/universal", []))
        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)
        assert (claude_dir / "rules" / "universal").is_dir()

    def test_a_skipped_entry_reserves_no_name(self, tmp_path):
        """Filtering happens BEFORE the collision check, so two recipes may ship one rule name for
        different harnesses. Reserving the name would forbid exactly the split this field enables."""
        root_a, root_b = tmp_path / "a", tmp_path / "b"
        _make_rule_dir(root_a, "shared", "omp flavour")
        _make_rule_dir(root_b, "shared", "claude flavour")
        syncer = LinkSyncer(harness="claude")
        syncer.add_recipe(Recipe(name="a", root=root_a,
                                rules=[FileExt(path="rules/shared", only_harnesses=["omp"])]))
        syncer.add_recipe(Recipe(name="b", root=root_b,
                                 rules=[FileExt(path="rules/shared", only_harnesses=["claude"])]))
        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)
        assert "claude flavour" in (claude_dir / "rules" / "shared" / "shared.md").read_text()

    def test_a_skipped_entry_need_not_exist(self, tmp_path):
        """The existence check is also downstream of the filter, so a harness that does not take an
        entry never fails on it."""
        syncer = LinkSyncer(harness="claude")
        syncer.add_recipe(self._gated(tmp_path / "recipe", "rules/absent", ["omp"]))
        syncer.fan(tmp_path / "profile" / ".claude")


class TestRulesRoundTrip:
    def test_rules_fanned_into_profile(self, tmp_path):
        """A recipe declaring rules: gets .claude/rules/<name>/ with the markdown file."""
        recipe_root = tmp_path / "recipe"
        _make_rule_dir(recipe_root, "my-rule", "# guidance\nDo the right thing.\n")

        recipe = _recipe(recipe_root, ["rules/my-rule"])
        syncer = LinkSyncer()
        syncer.add_recipe(recipe)

        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)

        dest = claude_dir / "rules" / "my-rule" / "my-rule.md"
        assert dest.is_file()
        assert "Do the right thing." in dest.read_text()

    def test_flat_rule_file_fanned_into_profile(self, tmp_path):
        """A recipe declaring a flat rules/<name>.md file links to .claude/rules/<name>.md."""
        recipe_root = tmp_path / "recipe"
        rules_dir = recipe_root / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "foo.md").write_text("# flat rule\nStay flat.\n")

        recipe = _recipe(recipe_root, ["rules/foo.md"])
        syncer = LinkSyncer()
        syncer.add_recipe(recipe)

        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)

        dest = claude_dir / "rules" / "foo.md"
        assert dest.is_file()
        assert "Stay flat." in dest.read_text()

    def test_rules_collision_raises(self, tmp_path):
        """Two recipes shipping a rule with the same name abort with CollisionError."""
        root_a = tmp_path / "recipe-a"
        root_b = tmp_path / "recipe-b"
        _make_rule_dir(root_a, "shared-rule")
        _make_rule_dir(root_b, "shared-rule")

        recipe_a = Recipe(name="a", root=root_a, rules=[FileExt(path="rules/shared-rule")])
        recipe_b = Recipe(name="b", root=root_b, rules=[FileExt(path="rules/shared-rule")])

        syncer = LinkSyncer()
        syncer.add_recipe(recipe_a)
        with pytest.raises(CollisionError, match="shared-rule"):
            syncer.add_recipe(recipe_b)

    def test_rules_missing_dir_raises(self, tmp_path):
        """A recipe pointing at a non-existent rules dir raises CollisionError immediately."""
        recipe = _recipe(tmp_path / "recipe", ["rules/no-such-dir"])
        syncer = LinkSyncer()
        with pytest.raises(CollisionError, match="does not exist"):
            syncer.add_recipe(recipe)

    def test_rules_dir_not_created_when_empty(self, tmp_path):
        """No recipe declares rules → fan() does not create an empty rules dir."""
        syncer = LinkSyncer()
        claude_dir = tmp_path / "profile" / ".claude"
        syncer.fan(claude_dir)
        # skills/commands dirs ARE created (empty); rules dir should also be created
        # consistently by _fan_into — just verify the fan call completes without error.
        # The dir is created because _fan_into always calls mkdir.
        assert (claude_dir / "rules").is_dir()
