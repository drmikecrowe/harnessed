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
    InstallRef,
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


class TestInstallRefsAreASecondSourceOfProof:
    """Phase 3 of #329: the pin may live in `install.refs:` instead of in the script.

    The fail-closed rule above reads "no literal assignment in this file" as unprovable, which is
    right while a script is self-contained — and wrong the moment the pin moves to the manifest by
    design. These fix WHERE the proof may come from without loosening WHAT counts as proof: the
    manifest value runs through the same immutability check a literal would.
    """

    def _with_refs(self, tmp_path: Path, body: str, refs: dict) -> Recipe:
        r = _script_recipe(tmp_path, body)
        assert r.install is not None
        r.install.refs = refs
        return r

    def test_a_declared_ref_resolves_the_variable(self, tmp_path):
        body = 'git clone --depth 1 --branch "$HARNESSED_REF_CAVEMAN" https://e.com/x.git /o\n'
        recipe = self._with_refs(
            tmp_path, body, {"caveman": InstallRef(repo="JuliusBrussee/caveman", ref="v1.9.0")}
        )
        validate_install_script(recipe)  # must not raise

    def test_a_full_sha_in_the_manifest_also_resolves(self, tmp_path):
        body = 'git clone --branch "$HARNESSED_REF_GSTACK" https://e.com/x.git /o\n'
        recipe = self._with_refs(
            tmp_path, body, {"gstack": InstallRef(repo="garrytan/gstack", ref=SHA)}
        )
        validate_install_script(recipe)

    def test_a_ref_key_that_does_not_match_the_variable_still_fails_closed(self, tmp_path):
        """The typo case, and the reason this is not a blanket exemption for `HARNESSED_REF_*`.

        Declaring `caveman` while the script reads `$HARNESSED_REF_CAVEMEN` means the script gets an
        EMPTY variable at build time and clones the default branch. Resolving by name is what makes
        that a lint failure instead of a silent floating clone.
        """
        body = 'git clone --branch "$HARNESSED_REF_CAVEMEN" https://e.com/x.git /o\n'
        recipe = self._with_refs(
            tmp_path, body, {"caveman": InstallRef(repo="JuliusBrussee/caveman", ref="v1.9.0")}
        )
        with pytest.raises(PinValidationError, match="CAVEMEN"):
            validate_install_script(recipe)

    def test_a_recipe_without_refs_is_unaffected(self, tmp_path):
        """The Dockerfile and agent gates pass no recipe at all, so their behaviour must not move."""
        body = 'git clone --branch "$HARNESSED_REF_ANYTHING" https://e.com/x.git /o\n'
        with pytest.raises(PinValidationError, match="HARNESSED_REF_ANYTHING"):
            validate_install_script(_script_recipe(tmp_path, body))

    def test_a_local_assignment_overrides_the_manifest_and_is_what_gets_checked(self, tmp_path):
        """Precedence must mirror the SHELL's, not the author's intent.

        `HARNESSED_REF_CAVEMAN=main` in the body shadows the exported env for everything after it,
        so the script clones `main` no matter what the manifest says. Resolving manifest-last let
        the lint bless that: it checked the immutable tag while the build took the branch. The hole
        needs no malice — a leftover debugging line is enough.
        """
        body = (
            'HARNESSED_REF_CAVEMAN="main"\n'
            'git clone --branch "$HARNESSED_REF_CAVEMAN" https://e.com/x.git /o\n'
        )
        recipe = self._with_refs(
            tmp_path, body, {"caveman": InstallRef(repo="JuliusBrussee/caveman", ref="v1.9.0")}
        )
        with pytest.raises(PinValidationError, match="main"):
            validate_install_script(recipe)

    def test_the_same_precedence_applies_to_archive_downloads(self, tmp_path):
        """`_mutable_archive_ref` took the identical fix; asserting one and not the other would
        leave half the hole open, and the archive path is the one Family B's tarball fetches use."""
        body = (
            'HARNESSED_REF_OAKOSS="main"\n'
            'curl -sSL "https://codeload.github.com/o/r/tar.gz/$HARNESSED_REF_OAKOSS" -o a.tgz\n'
        )
        recipe = self._with_refs(
            tmp_path, body, {"oakoss": InstallRef(repo="oakoss/agent-skills", ref=SHA)}
        )
        with pytest.raises(PinValidationError, match="main"):
            validate_install_script(recipe)

    def test_a_floating_value_in_the_manifest_is_still_rejected(self, tmp_path):
        """Defence in depth. The schema rejects a floating `ref:` before this runs, so this asserts
        the lint does not simply TRUST the manifest — it checks the value it was handed, exactly as
        it checks a literal. If the schema guard were ever relaxed, this is what still fails."""
        body = 'git clone --branch "$HARNESSED_REF_X" https://e.com/x.git /o\n'
        recipe = self._with_refs(tmp_path, body, {"x": InstallRef(repo="o/r", ref="main")})
        with pytest.raises(PinValidationError, match="main"):
            validate_install_script(recipe)


class TestShippedCatalogSatisfiesTheGate:
    """The rule only counts if the catalog we ship actually obeys it."""

    def test_every_catalog_install_and_setup_script_passes(self):
        """Lint each script against its REAL manifest, not a fabricated one.

        This used to build `Recipe(name=…, root=…)` + `InstallSpec(script=…)` from the file path
        alone. That was equivalent while a script's pinnedness was decidable from its own text — and
        it stopped being equivalent in Phase 3 of #329, when `install.refs:` moved Family B pins into
        recipe.yaml. A synthetic recipe has no refs, so `--branch "$HARNESSED_REF_CAVEMAN"` looks
        unresolvable and the gate rejects a recipe the catalog ships and the real gate accepts.

        Loading the manifest is also the stronger test: it exercises the pairing that actually
        ships, where the fabricated one exercised a combination that exists nowhere.
        """
        from harnessed import paths
        from harnessed.schema import load_recipe

        catalog = paths.harnessed_home() / "catalog" / "recipes"
        scripts = sorted(catalog.rglob("*.sh"))
        assert scripts, f"no recipe scripts found under {catalog}"
        for script in scripts:
            manifest = script.parent / "recipe.yaml"
            if manifest.is_file():
                recipe = load_recipe(script.parent, strict=True)
                if recipe.install is None:
                    recipe.install = InstallSpec(script=script.name)
                else:
                    # Point the SAME InstallSpec at this file rather than building a new one: a
                    # fresh InstallSpec would drop `refs`, which is the whole reason the manifest is
                    # loaded here. Every .sh in the dir gets linted, including one the manifest does
                    # not name — an unreferenced script is exactly where an unpinned clone hides.
                    recipe.install.script = script.name
            else:
                recipe = Recipe(name=script.parent.name, root=script.parent)
                recipe.install = InstallSpec(script=script.name)
            validate_install_script(recipe)
