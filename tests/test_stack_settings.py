"""`settings:` — top-level Claude settings.json scalars a stack owns.

The case that made the field: claude.ai syncs its uploaded skills into every Claude Code session on
the same account, so a stack that already ships those skills through a recipe loads two copies of
each. `syncClaudeAiSkills: false` is a session-level key no recipe can decide, and the only place to
put it is the settings.json harnessed already produces. Three readers must agree about it:

    schema   accepts scalars, refuses the two blocks harnessed merges by its own rules
    emit     carries it in the assemble-time floor
    merge    writes it OVER a baked or host value (an override, unlike defaultMode's floor)
"""

import json

import pytest

from harnessed.emit import merge_settings, required_settings, write_settings_json
from harnessed.schema import SchemaError, load_stack


def _stack(tmp_path, body: str):
    d = tmp_path / "s"
    d.mkdir()
    (d / "stack.yaml").write_text(f"name: s\n{body}", encoding="utf-8")
    return load_stack(d)


class TestTheDeclarationIsParsedAndValidated:
    def test_scalars_round_trip(self, tmp_path):
        stk = _stack(
            tmp_path, "settings:\n  syncClaudeAiSkills: false\n  model: opus\n  n: 3\n"
        )
        assert stk.settings == {"syncClaudeAiSkills": False, "model": "opus", "n": 3}

    def test_omitted_is_empty(self, tmp_path):
        assert _stack(tmp_path, "").settings == {}

    @pytest.mark.parametrize("key", ["permissions", "hooks"])
    def test_the_blocks_harnessed_merges_are_refused(self, key, tmp_path):
        """An override here would silently drop the hatago grant or a recipe's hooks: the merge
        unions those by its own rules, and two writers with different rules cannot both win."""
        with pytest.raises(SchemaError) as exc:
            _stack(tmp_path, f"settings:\n  {key}: {{}}\n")
        assert key in str(exc.value)

    @pytest.mark.parametrize("value", ["[1, 2]", "{a: 1}", "null"])
    def test_a_non_scalar_value_is_refused(self, value, tmp_path):
        """A list or object would be written into settings.json verbatim and read by Claude, and the
        symptom would be harness misbehaviour with nothing naming the stack field."""
        with pytest.raises(SchemaError) as exc:
            _stack(tmp_path, f"settings:\n  k: {value}\n")
        assert "settings.k" in str(exc.value)

    def test_a_non_mapping_is_refused(self, tmp_path):
        with pytest.raises(SchemaError, match="settings"):
            _stack(tmp_path, "settings: [a]\n")


class TestItReachesTheFile:
    def test_the_floor_carries_it(self, tmp_path):
        out = write_settings_json(
            tmp_path, [], None, None, "claude", {"syncClaudeAiSkills": False}
        )
        assert json.loads(out.read_text())["syncClaudeAiSkills"] is False

    def test_it_never_touches_permissions_or_hooks(self):
        req = required_settings([], settings={"syncClaudeAiSkills": False})
        assert req["permissions"] == {"defaultMode": "acceptEdits"}
        assert "hooks" not in req

    def test_the_merge_overrides_a_baked_value(self):
        """Unlike defaultMode (a floor a recipe's baked mode beats), a stack setting is the author's
        explicit call and wins over whatever the image or the host's live settings carry."""
        required = required_settings([], settings={"syncClaudeAiSkills": False})
        baked = {"syncClaudeAiSkills": True, "permissions": {"defaultMode": "plan"}}
        merged = merge_settings(baked, required)
        assert merged["syncClaudeAiSkills"] is False
        assert merged["permissions"]["defaultMode"] == "plan", (
            "defaultMode stays a floor"
        )

    def test_a_key_the_stack_did_not_set_is_carried_through(self):
        merged = merge_settings({"includeCoAuthoredBy": False}, required_settings([]))
        assert merged["includeCoAuthoredBy"] is False
