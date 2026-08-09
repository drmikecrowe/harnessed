"""Phase 0, unit 1 — `install.refs:` and the derived cache key.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §D1a, "The `install.refs` contract". That
contract's seven rules ARE this test plan — the plan says so explicitly, because implied mechanics
become whatever the first implementation happened to do.

Covered here (rules 1, 4, 6, 7 + ref immutability). Rules 2 and 5 — the `HARNESSED_REF_*` /
`HARNESSED_REPO_*` env emission and `hold:` reporting — land with `emit.py` and `update.py` in the
next unit; `hold` is parsed here so the field exists for them to read.

Why this half is separable: nothing below needs a recipe to be migrated, an env to be emitted, or a
resolver to run. It is the DECLARATION and its derived identity, which everything else builds on.
"""

import hashlib

import pytest

from harnessed.schema import InstallRef, SchemaError, derived_cache_key, load_recipe


def _recipe(tmp_path, body: str, name: str = "r", with_script: bool = True):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "recipe.yaml").write_text(body)
    if with_script:
        (d / "install.sh").write_text("#!/usr/bin/env bash\ntrue\n")
    return d


def _install(tmp_path, body: str, name: str = "r", with_script: bool = True):
    """Load a recipe and hand back its `install:`, narrowed.

    `Recipe.install` is `InstallSpec | None`, so every access below would otherwise be an
    Optional-member-access error. Asserting once here keeps the type checker satisfied without
    scattering asserts through assertions that are about something else.
    """
    spec = load_recipe(_recipe(tmp_path, body, name=name, with_script=with_script)).install
    assert spec is not None
    return spec


_THREE_REFS = """\
name: r
install:
  script: install.sh
  refs:
    oakoss:
      repo: oakoss/agent-skills
      ref: 0283bed313563d5677a0838f4bf921b03296cf6c
    blader:
      repo: blader/humanizer
      ref: 1b48564898e999219882660237fde01bf4843a0f
    aminblg:
      repo: AminBlg/SimpleEnglish
      ref: 379728b51981b6d2ee1de0f201164483a9648972
"""


class TestRule1KeySyntax:
    """`^[a-z][a-z0-9_]*$`, rejected at SCHEMA VALIDATION — not at env-emit time.

    The rule names the phase on purpose: a bad key must fail the build with a message naming the
    key, not produce a silently missing environment variable three steps later.
    """

    @pytest.mark.parametrize("key", ["oakoss", "a", "a1", "some_repo", "x_9_y"])
    def test_a_valid_key_is_accepted(self, tmp_path, key):
        body = f"name: r\ninstall:\n  script: install.sh\n  refs:\n    {key}:\n      repo: o/r\n      ref: v1.0.0\n"
        assert key in _install(tmp_path, body).refs

    @pytest.mark.parametrize("key", ["Oakoss", "OAKOSS", "1oak", "_oak", "oak-oss", "oak.oss", "oak oss", ""])
    def test_an_invalid_key_is_a_schema_error_naming_the_key(self, tmp_path, key):
        body = f"name: r\ninstall:\n  script: install.sh\n  refs:\n    {key!r}:\n      repo: o/r\n      ref: v1.0.0\n"
        with pytest.raises(SchemaError) as exc:
            load_recipe(_recipe(tmp_path, body))
        assert "refs" in str(exc.value)
        if key:
            assert key in str(exc.value), "the error must name the offending key"


    def test_a_duplicate_key_is_a_SchemaError_not_a_yaml_crash(self, tmp_path):
        """Rule 1 says keys are UNIQUE, and the contract says to assert it rather than trust it.

        Found by adversarial review: ruamel raises `DuplicateKeyError` at PARSE time, before any
        of this module's validation runs. Every production caller catches `SchemaError` (or
        `(SchemaError, CollisionError)`), so the ruamel exception escaped all of them and reached
        the user as an unhandled traceback from the launcher — the exact failure mode rule 1 exists
        to prevent, since a YAML editor does not warn on a repeated key.
        """
        body = ("name: r\ninstall:\n  script: install.sh\n  refs:\n"
                "    foo:\n      repo: o/r1\n      ref: v1.0.0\n"
                "    foo:\n      repo: o/r2\n      ref: v2.0.0\n")
        with pytest.raises(SchemaError) as exc:
            load_recipe(_recipe(tmp_path, body))
        assert "foo" in str(exc.value), "the error must name the duplicated key"

    def test_a_duplicate_key_anywhere_in_a_manifest_is_a_SchemaError(self, tmp_path):
        """The fix is in `_load_yaml`, so it covers every manifest, not only `refs:`. Asserted
        here because a narrower fix would leave the same traceback reachable one field over."""
        body = "name: r\ndescription: a\ndescription: b\n"
        with pytest.raises(SchemaError, match="description"):
            load_recipe(_recipe(tmp_path, body))


class TestRule3NamespaceReservation:
    """`HARNESSED_REF_*` / `HARNESSED_REPO_*` belong exclusively to `refs:`.

    The contract commits to this test by name, and adversarial review found it missing — neither
    written nor deferred, falling in the gap between "rules 1/4/6/7 implemented" and "rules 2/5
    deferred". It passes trivially today. Its job is to fail the day someone adds a general-purpose
    launcher variable in that namespace, which would silently shadow a recipe's ref and hand the
    install script an empty value.
    """

    def test_install_env_reserves_no_key_in_the_ref_namespace(self, tmp_path):
        import re as _re

        from harnessed.emit import install_env

        recipe = load_recipe(_recipe(tmp_path, "name: r\ninstall:\n  script: install.sh\n"))
        env = install_env(recipe, mode="container", harness="claude", config_dir="/c",
                          cache_dir="/x", bin_dir="/b", home_shim="/h")
        offenders = [k for k in env if _re.match(r"^HARNESSED_(REF|REPO)_", k)]
        assert not offenders, (
            f"{offenders} collide with the namespace `install.refs:` owns — a recipe ref of that "
            f"name would be silently shadowed"
        )


class TestRefFieldsAreImmutable:
    """D1a: `ref` is a tag or a FULL SHA; floating is rejected exactly as for `tools:`."""

    @pytest.mark.parametrize("ref", ["v1.2.3", "1.2.3", "v2.0.0-rc.1",
                                     "0283bed313563d5677a0838f4bf921b03296cf6c"])
    def test_an_immutable_ref_is_accepted(self, tmp_path, ref):
        body = f"name: r\ninstall:\n  script: install.sh\n  refs:\n    k:\n      repo: o/r\n      ref: {ref}\n"
        assert _install(tmp_path, body).refs["k"].ref == ref

    @pytest.mark.parametrize("ref", ["main", "master", "HEAD", "latest", "feat/some-work", "0283bed"])
    def test_a_moving_or_abbreviated_ref_is_rejected(self, tmp_path, ref):
        """An abbreviated SHA is rejected with the moving ones: it is not a stable identifier,
        and `_IMMUTABLE_REF_RE` already fails closed on anything it does not recognise."""
        body = f"name: r\ninstall:\n  script: install.sh\n  refs:\n    k:\n      repo: o/r\n      ref: {ref}\n"
        with pytest.raises(SchemaError, match="ref"):
            load_recipe(_recipe(tmp_path, body))

    def test_repo_must_be_owner_slash_repo_not_a_url(self, tmp_path):
        """Rule 2: `HARNESSED_REPO_*` carries `owner/repo`, NOT a URL — the script composes the
        URL, so a recipe switching from `git clone` to a tarball needs no manifest change."""
        body = ("name: r\ninstall:\n  script: install.sh\n  refs:\n    k:\n"
                "      repo: https://github.com/o/r.git\n      ref: v1.0.0\n")
        with pytest.raises(SchemaError, match="repo"):
            load_recipe(_recipe(tmp_path, body))

    @pytest.mark.parametrize("script", ["''", "'   '", "123"])
    def test_an_empty_or_non_string_script_is_an_error(self, tmp_path, script):
        """Pre-existing branch, untested until now: this change's line shifts pulled it into the
        changed set, and the honest way to clear that is to test it rather than to explain it."""
        body = f"name: r\ninstall:\n  script: {script}\n"
        with pytest.raises(SchemaError, match=r"install\.script"):
            load_recipe(_recipe(tmp_path, body))

    def test_refs_must_be_a_mapping_not_a_list(self, tmp_path):
        """The shape an author reaches for first, coming from `tools:` — which IS a list."""
        body = "name: r\ninstall:\n  script: install.sh\n  refs:\n    - oakoss\n"
        with pytest.raises(SchemaError, match="mapping"):
            load_recipe(_recipe(tmp_path, body))

    def test_a_ref_entry_must_be_a_mapping_not_a_bare_string(self, tmp_path):
        """`k: v1.0.0` loses the repo, and the repo is the half `update` needs."""
        body = "name: r\ninstall:\n  script: install.sh\n  refs:\n    k: v1.0.0\n"
        with pytest.raises(SchemaError, match="mapping"):
            load_recipe(_recipe(tmp_path, body))

    @pytest.mark.parametrize("missing,body", [
        ("repo", "name: r\ninstall:\n  script: install.sh\n  refs:\n    k:\n      ref: v1.0.0\n"),
        ("ref", "name: r\ninstall:\n  script: install.sh\n  refs:\n    k:\n      repo: o/r\n"),
    ])
    def test_a_missing_repo_or_ref_is_an_error_that_does_not_invent_a_value(self, tmp_path, missing, body):
        """Asserting the MESSAGE, not just the raise.

        Mutation testing: replacing the `or ""` fallback with any other placeholder survived,
        because the substitute still failed the pattern and still raised. What changed was the
        error text — it would report a value the author never wrote. That is the same defect as
        the `install.cache` message this change already fixed: an error must describe the manifest
        in front of the reader.
        """
        with pytest.raises(SchemaError) as exc:
            load_recipe(_recipe(tmp_path, body, name=f"r_{missing}"))
        message = str(exc.value)
        assert missing in message and "'k'" in message
        assert "XX" not in message, "the error must not report a value the manifest does not contain"
        assert "''" in message, "an absent field should be shown as empty, not as a substitute"


class TestRule5HoldIsPerRef:
    """`hold:` scope is the single ref — three refs may hold one and auto-bump two."""

    def test_a_hold_attaches_to_its_own_ref(self, tmp_path):
        body = ("name: r\ninstall:\n  script: install.sh\n  refs:\n"
                "    held:\n      repo: o/r\n      ref: v1.0.0\n      hold: 'structural: no tags'\n"
                "    free:\n      repo: o/s\n      ref: v2.0.0\n")
        refs = _install(tmp_path, body).refs
        assert refs["held"].hold == "structural: no tags"
        assert refs["free"].hold is None

    def test_an_empty_hold_reason_is_an_error(self, tmp_path):
        body = ("name: r\ninstall:\n  script: install.sh\n  refs:\n"
                "    k:\n      repo: o/r\n      ref: v1.0.0\n      hold: ''\n")
        with pytest.raises(SchemaError, match="hold"):
            load_recipe(_recipe(tmp_path, body))

    def test_a_hold_does_not_license_a_floating_ref(self, tmp_path):
        """`tools:` already establishes this; refs must not become the exception."""
        body = ("name: r\ninstall:\n  script: install.sh\n  refs:\n"
                "    k:\n      repo: o/r\n      ref: main\n      hold: 'because'\n")
        with pytest.raises(SchemaError, match="ref"):
            load_recipe(_recipe(tmp_path, body))


class TestRule7RefsAndHandWrittenCacheConflict:
    """NC-5: two sources for one key is a schema error, not a precedence rule."""

    def test_declaring_both_is_an_error(self, tmp_path):
        body = ("name: r\ninstall:\n  script: install.sh\n  cache: v1.0.0\n  refs:\n"
                "    k:\n      repo: o/r\n      ref: v1.0.0\n")
        with pytest.raises(SchemaError, match="cache"):
            load_recipe(_recipe(tmp_path, body))

    def test_cache_alone_still_works(self, tmp_path):
        """NC-5: a recipe with no `refs:` validates unchanged."""
        body = "name: r\ninstall:\n  script: install.sh\n  cache: v1.0.0\n"
        spec = _install(tmp_path, body)
        assert spec.cache == "v1.0.0" and not spec.refs

    def test_refs_alone_derives_the_cache(self, tmp_path):
        spec = _install(tmp_path, _THREE_REFS)
        assert spec.cache == derived_cache_key(spec.refs)

    def test_refs_without_a_script_is_an_error(self, tmp_path):
        """`refs:` declares what a script fetches. Without the script there is nothing to consume
        the env, so the refs would be inert data that `update` still offers to bump.

        The message must name `refs`, not the DERIVED `cache`. Checked because this test passed on
        first run: the derived key was tripping the pre-existing cache-without-script guard, whose
        message points at `install.cache` — a field a refs-only author never wrote.
        """
        body = "name: r\ninstall:\n  system: root-only\n  refs:\n    k:\n      repo: o/r\n      ref: v1.0.0\n"
        with pytest.raises(SchemaError) as exc:
            load_recipe(_recipe(tmp_path, body, with_script=False))
        assert "install.refs" in str(exc.value) and "install.script" in str(exc.value)


class TestTheJsonSchemaAgreesWithThePythonParser:
    """Two validators, one contract. An editor that accepts what the build rejects is worse than
    no editor validation, because the author trusts it."""

    def _install_schema(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        return json.loads((root / "schemas" / "recipe.schema.json").read_text())["properties"]["install"]

    def test_refs_is_declared(self):
        assert "refs" in self._install_schema()["properties"]

    def test_the_key_pattern_matches_rule_1(self):
        assert self._install_schema()["properties"]["refs"]["propertyNames"]["pattern"] == "^[a-z][a-z0-9_]*$"

    def test_refs_requires_a_script_like_cache_does(self):
        assert self._install_schema()["dependentRequired"]["refs"] == ["script"]

    def test_refs_and_cache_together_are_rejected_by_the_json_schema_too(self):
        """Rule 7 is enforced in BOTH validators — the Python parser raises, and the editor must
        not quietly accept the same manifest."""
        assert {"required": ["refs", "cache"]} in self._install_schema().get("not", {}).get("anyOf", [])


class TestRule6DerivedCacheKey:
    """Fully specified so two implementations cannot disagree about which cache entry is which."""

    GOLDEN = "0f4325fc44aef2a1"
    CANONICAL = (
        "aminblg=AminBlg/SimpleEnglish@379728b51981b6d2ee1de0f201164483a9648972\n"
        "blader=blader/humanizer@1b48564898e999219882660237fde01bf4843a0f\n"
        "oakoss=oakoss/agent-skills@0283bed313563d5677a0838f4bf921b03296cf6c"
    )

    def test_the_golden_vector(self, tmp_path):
        """The plan's vector, asserted verbatim. Corrected in REVISION 10 after recomputation —
        the original keyed the third ref `aminglg` and published that string's digest."""
        assert _install(tmp_path, _THREE_REFS).cache == self.GOLDEN

    def test_the_code_builds_the_canonical_input_the_spec_specifies(self):
        """Binds the CODE's canonical construction to the spec's stated string.

        The first version of this test hashed `CANONICAL` and compared it to `GOLDEN` — two
        hardcoded class attributes, never touching `derived_cache_key`. Adversarial review pointed
        out it therefore asserted the spec's self-consistency, not the implementation, while its
        docstring claimed to pin the input. It now runs the real function over the real refs, so a
        wrong delimiter, sort, or trailing newline fails HERE rather than only through the digest.
        """
        refs = {
            "oakoss": InstallRef(repo="oakoss/agent-skills",
                                 ref="0283bed313563d5677a0838f4bf921b03296cf6c"),
            "blader": InstallRef(repo="blader/humanizer",
                                 ref="1b48564898e999219882660237fde01bf4843a0f"),
            "aminblg": InstallRef(repo="AminBlg/SimpleEnglish",
                                  ref="379728b51981b6d2ee1de0f201164483a9648972"),
        }
        assert derived_cache_key(refs) == hashlib.sha256(self.CANONICAL.encode("utf-8")).hexdigest()[:16]
        assert derived_cache_key(refs) == self.GOLDEN

    def test_the_key_is_16_lowercase_hex_characters(self, tmp_path):
        key = _install(tmp_path, _THREE_REFS).cache
        assert key is not None
        assert len(key) == 16 and all(c in "0123456789abcdef" for c in key)

    def test_rule_4_reordering_the_yaml_does_not_change_the_key(self, tmp_path):
        """A cosmetic edit must not force a refetch."""
        reordered = """\
name: r
install:
  script: install.sh
  refs:
    aminblg:
      repo: AminBlg/SimpleEnglish
      ref: 379728b51981b6d2ee1de0f201164483a9648972
    oakoss:
      repo: oakoss/agent-skills
      ref: 0283bed313563d5677a0838f4bf921b03296cf6c
    blader:
      repo: blader/humanizer
      ref: 1b48564898e999219882660237fde01bf4843a0f
"""
        a = _install(tmp_path, _THREE_REFS, name="a").cache
        b = _install(tmp_path, reordered, name="b").cache
        assert a == b == self.GOLDEN

    @pytest.mark.parametrize("field,value", [("ref", "v9.9.9"), ("repo", "other/repo")])
    def test_changing_any_ref_changes_the_key(self, tmp_path, field, value):
        """So a stale cache cannot be served."""
        mutated = _THREE_REFS.replace(
            "repo: blader/humanizer" if field == "repo" else
            "ref: 1b48564898e999219882660237fde01bf4843a0f",
            f"{field}: {value}",
        )
        assert _install(tmp_path, mutated, name="m").cache != self.GOLDEN

    def test_renaming_a_key_changes_the_key(self, tmp_path):
        """The key is part of the identity — it is what the env var is named after."""
        renamed = _THREE_REFS.replace("oakoss:", "oakoss2:")
        assert _install(tmp_path, renamed, name="rn").cache != self.GOLDEN

    def test_a_single_ref_has_no_trailing_newline_in_its_canonical_input(self):
        """The one-ref case is where a trailing-newline bug hides: with N=1 a `join` and a
        `for … + "\\n"` differ, and every multi-ref test still passes."""
        expected = hashlib.sha256(b"k=o/r@v1.0.0").hexdigest()[:16]
        assert derived_cache_key({"k": InstallRef(repo="o/r", ref="v1.0.0")}) == expected

    def test_no_refs_derives_nothing(self):
        assert derived_cache_key({}) is None
