"""`setup.run` is removed, and its absence is enforced rather than assumed (bd harnessed-0tk.9).

`run` executed only on the host: `_host_run_setups` ran it and the container path never selected it
(`_pending_setup_scripts` matches on `setup.script`), so one recipe behaved differently depending on
the backend it launched under — the asymmetry the backend seam exists to remove.

Deleting the field alone would not have been enough. Recipes tolerate unknown keys by design (the
D-14 forward-field policy), so a `run:` recipe would have parsed clean and then done nothing at all
— failing more quietly than before. Hence the explicit rejection these tests pin.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from harnessed.schema import SetupSpec, SchemaError, load_recipe

_BASE = "name: r\nsetup:\n  summary: s\n  reference: http://x\n"


def _recipe(tmp_path, body: str):
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    (d / "setup.sh").write_text("#!/usr/bin/env bash\n")
    return d


class TestTheFieldIsGone:
    def test_setupspec_has_no_run_field(self):
        assert "run" not in {f.name for f in fields(SetupSpec)}

    def test_setupspec_still_has_script(self):
        """The replacement must still be there — a passing removal test means nothing if the
        mechanism it points people at vanished too."""
        assert "script" in {f.name for f in fields(SetupSpec)}


class TestDeclaringItIsAnError:
    def test_run_alone_is_rejected(self, tmp_path):
        d = _recipe(tmp_path, _BASE + "  run: bd init --shared-server\n")
        with pytest.raises(SchemaError, match=r"'setup\.run' has been removed"):
            load_recipe(d, strict=True)

    def test_the_error_names_the_replacement(self, tmp_path):
        """A removal message that does not say what to use instead just relocates the confusion."""
        d = _recipe(tmp_path, _BASE + "  run: echo hi\n")
        with pytest.raises(SchemaError, match=r"setup\.script"):
            load_recipe(d, strict=True)

    def test_run_is_rejected_when_empty_string(self, tmp_path):
        d = _recipe(tmp_path, _BASE + "  run: ''\n")
        with pytest.raises(SchemaError, match="has been removed"):
            load_recipe(d, strict=True)

    def test_bare_run_key_is_rejected(self, tmp_path):
        """`run:` with NO value parses to None in YAML. Keying the guard on truthiness would wave it
        through as 'not declared', silently ignoring a key whose author believed it did something —
        the precise failure this removal exists to prevent, reintroduced by the guard itself."""
        d = _recipe(tmp_path, _BASE + "  run:\n")
        with pytest.raises(SchemaError, match="has been removed"):
            load_recipe(d, strict=True)

    def test_the_valid_fields_list_no_longer_advertises_run(self, tmp_path):
        """The unknown-field error is a DIFFERENT message from the removal error, and it enumerates
        the valid fields. Leaving `run` in that list tells an author who mistyped some other field
        that `run` is available — sending them to write the one thing that is rejected."""
        d = _recipe(tmp_path, _BASE + "  script_path: setup.sh\n")
        with pytest.raises(SchemaError) as exc:
            load_recipe(d, strict=True)
        assert "unknown field" in str(exc.value)
        valid = str(exc.value).split("valid fields:")[1]
        assert "run" not in valid, f"the valid-fields list still offers 'run': {valid}"
        assert "script" in valid

    def test_a_script_only_recipe_still_loads(self, tmp_path):
        """The guard must reject `run`, not executable setup in general."""
        d = _recipe(tmp_path, _BASE + "  script: setup.sh\n")
        r = load_recipe(d, strict=True)
        assert r.setup is not None and r.setup.script == "setup.sh"


class TestConfirmNowGatesScriptAlone:
    def test_confirm_without_script_is_rejected(self, tmp_path):
        d = _recipe(tmp_path, _BASE + "  confirm: are you sure?\n")
        with pytest.raises(SchemaError, match="confirm"):
            load_recipe(d, strict=True)

    def test_confirm_with_script_is_accepted(self, tmp_path):
        d = _recipe(tmp_path, _BASE + "  script: setup.sh\n  confirm: are you sure?\n")
        r = load_recipe(d, strict=True)
        assert r.setup is not None and r.setup.confirm == "are you sure?"


class TestNoCatalogRecipeDeclaresIt:
    def test_every_shipped_recipe_loads(self):
        """The catalog is parsed with the new rule — a shipped recipe still carrying `run:` would
        now be a hard load failure for every user, so prove none does."""
        from harnessed import paths

        catalog = paths.harnessed_home() / "catalog" / "recipes"
        loaded = 0
        for recipe_yaml in sorted(catalog.rglob("recipe.yaml")):
            load_recipe(recipe_yaml.parent, strict=True)
            loaded += 1
        assert loaded, "found no recipes to check — the catalog path is wrong"
