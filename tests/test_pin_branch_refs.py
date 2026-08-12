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
    _mutable_fetch_ref,
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


class TestFetchByShaIsGatedLikeAClone:
    """`git fetch <remote> <ref>` acquires an upstream tree exactly as `git clone --branch` does.

    Found in Phase 3 of #329, by migrating a recipe that uses it. Every pin gate keyed off
    `--branch` or an archive URL, so the two Family B recipes that fetch by SHA — the ones that
    CANNOT use `--branch`, because a raw SHA is not a branch name — passed the gate without any of
    their refs ever being read. `git fetch origin main` was accepted.

    That is unit 1's blocker in mirror image: there the gate REJECTED the migrated shape, here it
    accepts anything. Same root cause — a gate built for one spelling of "acquire an upstream ref".

    The recipe that exposed it (hyperpowers) was deleted rather than migrated, which is why these
    fixtures name gstack: it is the OTHER fetch-by-SHA recipe, it still ships, and it is what keeps
    this gate load-bearing rather than hypothetical.

    These assert the requirement (which fetched refs may reach a build) through the public gates,
    and deliberately reuse the clone gate's own guarantees: one-hop variable resolution, `refs:` as
    a second source of proof, resolution BY NAME, and shell precedence on a local assignment. A
    fetch gate that got any of those wrong would be a second, differently-broken copy of a rule the
    repo already has one correct copy of.
    """

    def _fetch(self, ref: str) -> str:
        # The catalog's real shape: init an empty repo, add the remote, fetch one ref, check out
        # FETCH_HEAD. The ref is the LAST argument, which is what makes it invisible to a gate
        # looking for a flag.
        return (
            'git init -q d\n'
            'git -C d remote add origin https://e.com/x.git\n'
            f'git -C d fetch -q --depth 1 origin {ref}\n'
            'git -C d checkout -q FETCH_HEAD\n'
        )

    @pytest.mark.parametrize("ref", [SHA, '"' + SHA + '"', "v1.2.3", '"v2.0.0-rc.1"'])
    def test_an_immutable_fetched_ref_passes(self, tmp_path, ref):
        validate_install_script(_script_recipe(tmp_path, self._fetch(ref)))

    @pytest.mark.parametrize("ref", ["main", '"develop"', "feat/wip", "HEAD"])
    def test_a_moving_fetched_ref_is_rejected_and_named(self, tmp_path, ref):
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(_script_recipe(tmp_path, self._fetch(ref)))
        assert ref.strip('"') in str(exc.value)

    def test_a_variable_with_a_literal_assignment_resolves(self, tmp_path):
        body = f'X_REF="{SHA}"\n' + self._fetch('"$X_REF"')
        validate_install_script(_script_recipe(tmp_path, body))

    def test_an_unresolvable_variable_is_rejected_fail_closed(self, tmp_path):
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(_script_recipe(tmp_path, self._fetch('"$MYSTERY_REF"')))
        assert "MYSTERY_REF" in str(exc.value)

    def test_a_declared_ref_resolves_the_variable(self, tmp_path):
        r = _script_recipe(tmp_path, self._fetch('"$HARNESSED_REF_GSTACK"'))
        assert r.install is not None
        r.install.refs = {"gstack": InstallRef(repo="garrytan/gstack", ref=SHA)}
        validate_install_script(r)  # must not raise

    def test_a_ref_key_that_does_not_match_the_variable_still_fails_closed(self, tmp_path):
        # The typo case. `refs: {gstack}` + `$HARNESSED_REF_GSTAK` hands the script an EMPTY
        # variable, and `git fetch origin ''` is an error rather than a floating fetch — but the
        # gate must not depend on git's behaviour to catch a manifest that names nothing.
        r = _script_recipe(tmp_path, self._fetch('"$HARNESSED_REF_GSTAK"'))
        assert r.install is not None
        r.install.refs = {"gstack": InstallRef(repo="garrytan/gstack", ref=SHA)}
        with pytest.raises(PinValidationError, match="GSTAK"):
            validate_install_script(r)

    def test_a_local_assignment_beats_the_manifest(self, tmp_path):
        # Same precedence rule the clone gate took in PR #352: the shell's, not the author's intent.
        body = 'HARNESSED_REF_GSTACK="main"\n' + self._fetch('"$HARNESSED_REF_GSTACK"')
        r = _script_recipe(tmp_path, body)
        assert r.install is not None
        r.install.refs = {"gstack": InstallRef(repo="garrytan/gstack", ref=SHA)}
        with pytest.raises(PinValidationError, match="main"):
            validate_install_script(r)

    def test_a_dockerfile_run_fetch_is_gated_too(self):
        # A Dockerfile spelling the same acquisition is the identical hole; gating only the .sh half
        # would move the problem rather than close it.
        with pytest.raises(PinValidationError, match="main"):
            validate_pin("r", "RUN git init d && git -C d fetch --depth 1 origin main")

    @pytest.mark.parametrize(
        "line",
        [
            "git fetch",
            "git fetch --all",
            "git -C d fetch origin",
            "git fetch --tags --prune",
        ],
    )
    def test_a_fetch_that_names_no_ref_is_not_an_acquisition(self, tmp_path, line):
        """A refresh is not a version-bearing download, and must not be rejected.

        This is the false-positive half of the gate, and it is the half that decides whether authors
        route around it. `git fetch origin` updates remote-tracking refs; nothing is checked out and
        no pin is expressed, so there is no ref for the gate to have an opinion about. Rejecting it
        would fail on ordinary shell and teach people to hide the acquisition instead.
        """
        validate_install_script(_script_recipe(tmp_path, f"set -e\n{line}\n"))

    def test_a_named_remote_is_not_mistaken_for_the_ref(self, tmp_path):
        """`git fetch upstream v1.2.3` fetches ref `v1.2.3` from remote `upstream`.

        Reading the FIRST argument as the ref would reject every non-`origin` remote by name (a
        remote name is not version-like), which is a false rejection that looks exactly like a
        working gate until someone uses a second remote.
        """
        validate_install_script(
            _script_recipe(tmp_path, "git -C d fetch --depth 1 upstream v1.2.3\n")
        )

    @pytest.mark.parametrize("opt", ["--multiple", "--stdin", "--porcelain", "--some-new-flag"])
    def test_an_option_the_gate_cannot_interpret_fails_closed(self, tmp_path, opt):
        """The gate must not GUESS which token is the ref when an option might have eaten it.

        `git fetch --depth 1 origin main` and `git fetch --multiple origin upstream` have the same
        SHAPE and different meanings: in the first, `1` is a value and `main` is the ref; in the
        second there is no ref at all and both positionals are remotes. Nothing in the text says
        which, so an option in neither the flag set nor the value set makes every later token
        ambiguous — and a gate that guesses reports a confident wrong answer about what is pinned.

        Caught by a mutant: replacing this branch with a pass-through left the whole suite green,
        because every other test here feeds only options the gate already knows. That is the
        "input the parser accepts but the tests never feed it" failure this module keeps hitting.
        """
        with pytest.raises(PinValidationError) as exc:
            validate_install_script(
                _script_recipe(tmp_path, f"git -C d fetch {opt} origin {SHA}\n")
            )
        assert opt in str(exc.value)

    def test_an_option_value_joined_by_equals_consumes_no_positional(self, tmp_path):
        """`--depth=1` is ONE token; `--depth 1` is two. Confusing them shifts every positional.

        Read as if it took a separate value, `--depth=1 origin main` leaves positionals
        `[main]` — one entry, read as the remote — and the floating fetch passes. Read correctly it
        leaves `[origin, main]` and `main` is rejected.
        """
        with pytest.raises(PinValidationError, match="main"):
            validate_install_script(
                _script_recipe(tmp_path, "git -C d fetch --depth=1 origin main\n")
            )

    def test_the_equals_form_still_accepts_a_pinned_ref(self, tmp_path):
        # The other half of the same boundary: reading it correctly must not create a false
        # rejection either. Asserting only the rejection above would pass on a gate that rejects
        # every `--depth=` fetch outright.
        validate_install_script(
            _script_recipe(tmp_path, f"git -C d fetch --depth=1 origin {SHA}\n")
        )

    def test_a_comment_describing_a_floating_fetch_does_not_trigger(self, tmp_path):
        # Comment-stripping is the caller's job everywhere else in this module; assert it holds here
        # too, or the recipes that explain their own pinning strategy fail their own gate.
        #
        # NOTE what this does and does not prove. `_lint_script_file` drops WHOLE-LINE comments
        # before the gate runs, so this asserts that layer, not the gate's own handling. The inline
        # case is a different question and is asserted separately below — a distinction an
        # adversarial review had to point out, because reading this test alone suggests coverage it
        # does not have.
        body = "# never do: git fetch origin main\n" + self._fetch(SHA)
        validate_install_script(_script_recipe(tmp_path, body))


class TestTheFetchWalkSeesWhatGitSees:
    """One invariant, five ways of breaking it: the walk must produce the token stream GIT does.

    Every case here was a FALSE REJECTION — a legitimately pinned fetch that the gate refused —
    found by adversarial review of the first implementation, and every one has the same root cause.
    The walk modelled a token stream git does not actually produce, so tokens that are punctuation,
    an option's value, or a refspec keyword to git were read as refs.

    False rejections are the failure mode that decides whether a gate survives contact with real
    authors. A gate that rejects `git fetch origin <sha> # why this commit` teaches people to delete
    the comment, or to route around the gate entirely; it does not teach them to pin.

    Asserted against `_mutable_fetch_ref` DIRECTLY rather than through `validate_install_script`,
    because several of these interact with the caller's comment-stripping and going through it
    would prove the wrong layer — the mistake the test above documents.
    """

    def test_an_inline_comment_after_a_pinned_ref_is_not_a_ref(self):
        # `_lint_script_file` strips lines that BEGIN with `#`; nothing strips a trailing comment.
        # The arg capture ran to end-of-line, so `#` and every following word were read as refs.
        assert _mutable_fetch_ref(f"git fetch origin {SHA} # bump: fixes CVE-2026-1\n") is None

    def test_an_inline_comment_cannot_hide_a_moving_ref(self):
        # The other half of the boundary. Cutting at `#` must not become a way to smuggle one in.
        assert _mutable_fetch_ref("git fetch origin main # looks innocent\n") == "'main'"

    def test_a_commented_out_ref_is_not_fetched(self):
        # `git fetch origin # main` fetches no ref at all — the shell never passes `main` to git.
        assert _mutable_fetch_ref("git fetch origin # main\n") is None

    def test_the_tag_refspec_keyword_is_not_the_ref(self):
        # `git fetch <remote> tag <name>` is git's own shorthand for fetching one tag. The keyword
        # sat in the ref's position, so the gate checked the word "tag" and never reached the tag.
        assert _mutable_fetch_ref("git fetch origin tag v1.2.3\n") is None

    def test_the_tag_refspec_keyword_does_not_wave_through_what_follows(self):
        assert _mutable_fetch_ref("git fetch origin tag my-moving-tag\n") == "'my-moving-tag'"

    @pytest.mark.parametrize("value", ["yes", "no", "on-demand"])
    def test_recurse_submodules_may_take_a_separate_value(self, value):
        # It is in the FLAG set because `--recurse-submodules` alone is valid — but git also accepts
        # a space-separated value, and then the value landed in the remote's slot and shifted every
        # positional by one, so the REMOTE got checked as the ref.
        assert _mutable_fetch_ref(f"git fetch --recurse-submodules {value} origin {SHA}\n") is None

    def test_recurse_submodules_without_a_value_still_works(self):
        assert _mutable_fetch_ref(f"git fetch --recurse-submodules origin {SHA}\n") is None

    @pytest.mark.parametrize("bundle", ["-qv", "-vq", "-qf"])
    def test_bundled_short_options_are_expanded(self, bundle):
        # `-qv` is `-q -v`. Both are known flags, so this must behave exactly as the unbundled form.
        # It previously hit the unknown-option branch: a rejection, so SAFE, but for a false reason
        # that would send an author hunting a pin problem they do not have.
        assert _mutable_fetch_ref(f"git fetch {bundle} origin {SHA}\n") is None
        assert _mutable_fetch_ref(f"git fetch {bundle} origin main\n") == "'main'"

    def test_a_bundle_containing_an_unknown_short_option_still_fails_closed(self):
        # Expanding must not become a way to launder an option the gate cannot interpret.
        assert "-Z" in (_mutable_fetch_ref(f"git fetch -qZ origin {SHA}\n") or "")

    def test_a_bundle_ending_in_a_value_taking_option_consumes_its_value(self):
        # `-qj 4` is `-q -j 4`; the `4` is a value, not the remote.
        assert _mutable_fetch_ref(f"git fetch -qj 4 origin {SHA}\n") is None

    def test_a_line_continuation_joins_before_the_walk(self):
        # The capture stopped at the newline, so the trailing `\` became the ref. That rejected a
        # pinned fetch — and it is why the moving case below cannot simply be left to the backslash.
        assert _mutable_fetch_ref(f"git fetch origin \\\n    {SHA}\n") is None

    def test_a_line_continuation_cannot_hide_a_moving_ref(self):
        """The reason the fix is JOINING, not ignoring the backslash.

        Before the fix this case was rejected — but by accident, because `\\` is not version-like,
        not because anything read the ref. Dropping the backslash instead of joining would have
        turned an accidental pass into a real FALSE ACCEPT: positionals would be `[origin]` alone,
        which the gate correctly reads as "a remote, no ref" and waves through.
        """
        assert _mutable_fetch_ref("git fetch origin \\\n    main\n") == "'main'"


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
