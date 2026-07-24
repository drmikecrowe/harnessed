"""Stack inheritance (`extends:`) and strict stack fields.

`extends:` was written in real stack manifests long before it existed in the loader. Because stack
parsing was tolerant of unknown keys, it silently did NOTHING: the stack inherited no recipes, no
services, and none of the parent's flags, while looking for all the world like it did. These tests
pin both halves of the fix — inheritance actually works, and an unknown stack key is now loud.

Merge semantics:
  * recipes / services / harnesses / ssh_keys — UNION, parent's first, then the child's, de-duped.
  * everything else — the child's declared value overrides; an omitted key is inherited.
  * `name` is never inherited; `extends` never survives into the merged manifest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessed.schema import SchemaError, load_stack


def _stack(root: Path, name: str, body: str) -> Path:
    d = root / "stacks" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "stack.yaml").write_text(f"name: {name}\n{body}")
    return d


class TestExtendsMerge:
    def test_child_unions_recipes_and_services_with_parent(self, tmp_path):
        _stack(tmp_path, "base", "recipes: [ccstatusline, openbrain]\nservices: [gbrain]\n")
        child = _stack(
            tmp_path, "kid", "extends: base\nrecipes: [beads-team, serena]\nservices: [beads-server]\n"
        )
        stk = load_stack(child)
        # Parent's entries first, then the child's additions.
        assert stk.recipes == ["ccstatusline", "openbrain", "beads-team", "serena"]
        assert stk.services == ["gbrain", "beads-server"]

    def test_union_dedupes_without_reordering(self, tmp_path):
        _stack(tmp_path, "base", "recipes: [a, b]\n")
        child = _stack(tmp_path, "kid", "extends: base\nrecipes: [b, c]\n")
        assert load_stack(child).recipes == ["a", "b", "c"]

    def test_scalars_are_inherited_when_the_child_omits_them(self, tmp_path):
        # The bug that started this: a stack said `extends: default` and silently got NONE of these.
        _stack(
            tmp_path,
            "base",
            "permissions: auto\nforward_git_credentials: true\nforward_aws_sso: true\n"
            "instructions: from-parent\n",
        )
        child = _stack(tmp_path, "kid", "extends: base\nrecipes: [x]\n")
        stk = load_stack(child)
        assert stk.permissions == "auto"
        assert stk.forward_git_credentials is True
        assert stk.forward_aws_sso is True
        assert stk.instructions == "from-parent"

    def test_child_scalar_overrides_the_parent(self, tmp_path):
        _stack(tmp_path, "base", "permissions: auto\nforward_aws_sso: true\n")
        child = _stack(tmp_path, "kid", "extends: base\npermissions: prompt\n")
        stk = load_stack(child)
        assert stk.permissions == "prompt"
        assert stk.forward_aws_sso is True  # untouched key still inherited

    def test_name_is_never_inherited(self, tmp_path):
        _stack(tmp_path, "base", "recipes: [a]\n")
        child = _stack(tmp_path, "kid", "extends: base\n")
        assert load_stack(child).name == "kid"

    def test_extends_does_not_survive_into_the_merged_manifest(self, tmp_path):
        _stack(tmp_path, "base", "recipes: [a]\n")
        child = _stack(tmp_path, "kid", "extends: base\n")
        assert "extends" not in load_stack(child).raw

    def test_chains_resolve_transitively(self, tmp_path):
        _stack(tmp_path, "grand", "recipes: [a]\npermissions: auto\n")
        _stack(tmp_path, "parent", "extends: grand\nrecipes: [b]\n")
        child = _stack(tmp_path, "kid", "extends: parent\nrecipes: [c]\n")
        stk = load_stack(child)
        assert stk.recipes == ["a", "b", "c"]
        assert stk.permissions == "auto"


class TestExtendsErrors:
    def test_cycle_is_rejected(self, tmp_path):
        _stack(tmp_path, "a", "extends: b\n")
        b = _stack(tmp_path, "b", "extends: a\n")
        with pytest.raises(SchemaError, match="cycle"):
            load_stack(b)

    def test_self_reference_is_rejected(self, tmp_path):
        me = _stack(tmp_path, "me", "extends: me\n")
        with pytest.raises(SchemaError, match="cycle"):
            load_stack(me)

    def test_missing_parent_names_the_offender(self, tmp_path):
        child = _stack(tmp_path, "kid", "extends: nope\n")
        with pytest.raises(SchemaError, match="nope"):
            load_stack(child)

    def test_non_string_extends_is_rejected(self, tmp_path):
        child = _stack(tmp_path, "kid", "extends: [a, b]\n")
        with pytest.raises(SchemaError, match="extends"):
            load_stack(child)


class TestStrictStackFields:
    def test_unknown_field_is_rejected_with_a_suggestion(self, tmp_path):
        # The whole point: `exteds:`/`harness:` used to be swallowed in silence.
        d = _stack(tmp_path, "s", "exteds: base\n")
        with pytest.raises(SchemaError, match="did you mean 'extends'"):
            load_stack(d)

    def test_singular_harness_is_rejected(self, tmp_path):
        d = _stack(tmp_path, "s", "harness: claude\n")
        with pytest.raises(SchemaError, match="did you mean 'harnesses'"):
            load_stack(d)

    def test_every_known_field_still_loads(self, tmp_path):
        d = _stack(
            tmp_path,
            "s",
            "recipes: [a]\nservices: [b]\nharnesses: [claude]\npermissions: auto\n"
            "instructions: hi\nforward_git_credentials: true\nforward_aws_sso: true\n"
            "ssh_keys: [id_ed25519]\nstate: {k: v}\n",
        )
        stk = load_stack(d)
        assert stk.recipes == ["a"] and stk.services == ["b"] and stk.permissions == "auto"
