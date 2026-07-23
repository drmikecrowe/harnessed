"""bd harnessed-1t4.5 — the merged mise tool layer must be a function of the tool SET.

podman's layer cache key is the literal instruction text, so a `RUN mise use -g …` whose argument
order follows stack.yaml authoring order means two stacks with the same tools share zero layers.
The requirement is stated at the level a stack author sees it: same tools in, same layer out.
"""
from __future__ import annotations

from harnessed.emit import write_derived_dockerfile
from harnessed.schema import Recipe


def _tools_line(tmp_path, recipes, stack="s"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = write_derived_dockerfile(tmp_path, stack, "claude", recipes)
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if "mise use -g" in ln]
    assert len(lines) == 1, f"expected exactly one merged tool layer, got {lines}"
    return lines[0]


def _recipe(tmp_path, name, tools):
    return Recipe(name=name, tools=tools, root=tmp_path / name)


class TestMergedToolLayerIsOrderIndependent:
    def test_same_tool_set_different_recipe_order_is_byte_identical(self, tmp_path):
        a = _recipe(tmp_path, "a", ["pulumi@3.140.0"])
        b = _recipe(tmp_path, "b", ["npm:context-mode@1.0.169"])
        c = _recipe(tmp_path, "c", ["pipx:serena-agent@0.1.4"])
        forward = _tools_line(tmp_path / "f", [a, b, c])
        reverse = _tools_line(tmp_path / "r", [c, b, a])
        assert forward == reverse

    def test_order_within_one_recipe_does_not_matter_either(self, tmp_path):
        one = _recipe(tmp_path, "one", ["pulumi@3.140.0", "npm:ccstatusline@2.2.22"])
        other = _recipe(tmp_path, "one", ["npm:ccstatusline@2.2.22", "pulumi@3.140.0"])
        assert _tools_line(tmp_path / "1", [one]) == _tools_line(tmp_path / "2", [other])

    def test_a_tool_declared_by_two_recipes_is_installed_once(self, tmp_path):
        shared = "npm:context-mode@1.0.169"
        a = _recipe(tmp_path, "a", [shared])
        b = _recipe(tmp_path, "b", [shared, "pulumi@3.140.0"])
        line = _tools_line(tmp_path, [a, b])
        assert line.count(shared) == 1

    def test_the_layer_still_installs_every_declared_tool(self, tmp_path):
        a = _recipe(tmp_path, "a", ["pulumi@3.140.0"])
        b = _recipe(tmp_path, "b", ["pipx:repowise@0.4.0"])
        line = _tools_line(tmp_path, [a, b])
        assert '"pulumi@3.140.0"' in line and '"pipx:repowise@0.4.0"' in line

    def test_two_stacks_with_the_same_tools_produce_the_same_layer(self, tmp_path):
        # Stack NAME differs, tool set does not — the tool layer must still be shareable.
        a = _recipe(tmp_path, "a", ["pulumi@3.140.0"])
        b = _recipe(tmp_path, "b", ["npm:context-mode@1.0.169"])
        left = _tools_line(tmp_path / "l", [a, b], stack="alpha")
        right = _tools_line(tmp_path / "r", [b, a], stack="beta")
        assert left == right
