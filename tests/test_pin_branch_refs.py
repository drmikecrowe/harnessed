"""bd harnessed-1t4.6 — a clone ref must be IMMUTABLE, not merely "not main".

The pre-existing gate rejected `--branch main|master|HEAD`, `:latest` and `@latest`, which let a
real build clone `--branch "feat/per-server-tool-filtering"`. A feature branch moves exactly like
`main` does: two builds a week apart produce different images from identical inputs.

These tests state the REQUIREMENT (which refs may reach a build), not the implementation: they go
through the two public gates authors actually hit — `validate_pin` for Dockerfile bodies and
`validate_install_script` / `validate_setup_script` for the .sh bodies those Dockerfiles moved into.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harnessed.schema import (
    InstallSpec,
    PinValidationError,
    Recipe,
    SetupSpec,
    validate_install_script,
    validate_pin,
    validate_setup_script,
)

SHA = "11de390be1be6849eb9a15f91ff4922dd16c589a"


def _script_recipe(tmp_path: Path, body: str, *, field: str = "install") -> Recipe:
    root = tmp_path / "r"
    root.mkdir(exist_ok=True)
    (root / "s.sh").write_text(body, encoding="utf-8")
    r = Recipe(name="r", root=root)
    if field == "install":
        r.install = InstallSpec(script="s.sh")
    else:
        r.setup = SetupSpec(summary="s", reference="r", script="s.sh")
    return r


class TestImmutableCloneRefs:
    """A ref that a maintainer can move must not pass the gate."""

    @pytest.mark.parametrize("ref", ["v1.2.3", "1.2.3", "v6.0.3", "0.1.2", "v2.0.0-rc.1", SHA])
    def test_tag_or_sha_ref_passes(self, ref):
        validate_pin("r", f'RUN git clone --depth 1 --branch "{ref}" https://example.com/x.git /o')

    @pytest.mark.parametrize(
        "ref",
        ["feat/per-server-tool-filtering", "develop", "release-branch", "my-fork", "next"],
    )
    def test_moving_branch_ref_is_rejected_and_named(self, ref):
        with pytest.raises(PinValidationError) as exc:
            validate_pin("r", f'RUN git clone --branch "{ref}" https://example.com/x.git /o')
        assert ref in str(exc.value)

    def test_unquoted_branch_ref_is_rejected(self):
        with pytest.raises(PinValidationError, match="dev"):
            validate_pin("r", "RUN git clone --branch dev https://example.com/x.git /o")

    def test_main_is_still_rejected(self):
        # The pre-existing behaviour must survive the widening.
        with pytest.raises(PinValidationError, match="main"):
            validate_pin("r", "RUN git clone --branch main https://example.com/repo")

    def test_comment_explaining_a_branch_does_not_trigger(self):
        validate_pin("r", '# never do: git clone --branch develop\nRUN git clone --branch "v1.0.0" x')


class TestShellVariableRefs:
    """Catalog scripts pin via `FOO_REF="v6.0.3"` then clone `--branch "$FOO_REF"`.

    The gate must follow that one hop, or every real recipe becomes invisible to it.
    """

    def test_variable_resolving_to_a_tag_passes(self, tmp_path):
        body = 'set -e\nX_REF="v6.0.3"\ngit clone --depth 1 --branch "$X_REF" https://e.com/x.git /o\n'
        validate_install_script(_script_recipe(tmp_path, body))

    def test_variable_resolving_to_a_sha_passes(self, tmp_path):
        body = f'X_REF="{SHA}"\ngit clone --branch "${{X_REF}}" https://e.com/x.git /o\n'
        validate_install_script(_script_recipe(tmp_path, body))

    def test_variable_resolving_to_a_branch_is_rejected_and_names_the_ref(self, tmp_path):
        body = 'X_REF="feat/wip"\ngit clone --depth 1 --branch "$X_REF" https://e.com/x.git /o\n'
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(_script_recipe(tmp_path, body))
        assert "feat/wip" in str(exc.value)

    def test_unresolvable_variable_is_rejected_fail_closed(self, tmp_path):
        # No assignment in the body: the gate cannot prove the ref is immutable, so it must refuse
        # rather than wave it through (the same fail-closed stance as the rest of the pin gates).
        body = 'git clone --depth 1 --branch "$MYSTERY_REF" https://e.com/x.git /o\n'
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(_script_recipe(tmp_path, body))
        assert "MYSTERY_REF" in str(exc.value)

    def test_setup_script_is_gated_the_same_way(self, tmp_path):
        body = 'git clone --branch "topic/x" https://e.com/x.git /o\n'
        with pytest.raises(PinValidationError, match="topic/x"):
            validate_setup_script(_script_recipe(tmp_path, body, field="setup"))


class TestShippedCatalogSatisfiesTheGate:
    """The rule only counts if the catalog we ship actually obeys it."""

    def test_every_catalog_install_and_setup_script_passes(self):
        from harnessed import paths

        catalog = paths.harnessed_home() / "catalog" / "recipes"
        scripts = sorted(catalog.rglob("*.sh"))
        assert scripts, f"no recipe scripts found under {catalog}"
        for script in scripts:
            recipe = Recipe(name=script.parent.name, root=script.parent)
            recipe.install = InstallSpec(script=script.name)
            validate_install_script(recipe)
