"""A channel is not a pin — agent `build_args` values must be immutable (#329 unit 7).

`_parse_agent_build_args` validated that a build_arg HAS a value and never what the value IS, so
`BUN_VERSION: latest` was accepted. Nothing downstream caught it either: `validate_agent_pin` reads
Dockerfile TEXT, where the line is `bun@${BUN_VERSION}` — a shell variable, which reads as pinned
precisely because the pin is supposed to live in the manifest. The channel reached `--build-arg` and
the image became whatever `latest` meant that day.

The rule is stated POSITIVELY, reusing `_IMMUTABLE_REF_RE` — the same allow-list already guarding
`install.refs[].ref`. A deny-list was tried on this codebase once and found insufficient
(bd harnessed-1t4.6: it let `--branch feat/...` through), which is why extending a blocklist is not
the fix here. An unrecognised shape fails CLOSED.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from harnessed.schema import SchemaError, _parse_agent_build_args, load_agent

MANIFEST = Path("/catalog/agents/demo/agent.yaml")
CATALOG_AGENTS = Path(__file__).resolve().parents[1] / "catalog" / "agents"

# Every version this catalog actually ships. A gate that rejects one of these is worse than the
# hole it closes, so they are asserted as a set rather than sampled.
SHIPPED = ("16.4.6", "1.3.14", "0.139.0", "2.1.223", "1.17.9")

# The seven the pre-existing deny-list knew about, plus the six it did NOT — the class intent
# review caught. `stable` is not hypothetical: plan REVISION 15 measured claude's channel
# pointers as `stable` 2.1.221 / `latest` 2.1.228.
DENYLIST_KNEW = ("latest", "main", "master", "head", "trunk", "dev", "edge")
DENYLIST_MISSED = ("nightly", "canary", "stable", "beta", "alpha", "lts", "release", "current")


def _parse(value, key="BUN_VERSION"):
    return _parse_agent_build_args({key: value}, MANIFEST)[0]


# --- Channels are rejected -----------------------------------------------------------------------


@pytest.mark.parametrize("channel", DENYLIST_KNEW)
def test_a_channel_the_old_denylist_knew_is_rejected(channel):
    """S-1, S-2, S-3."""
    with pytest.raises(SchemaError):
        _parse(channel)


@pytest.mark.parametrize("channel", DENYLIST_MISSED)
def test_a_channel_the_old_denylist_missed_is_rejected(channel):
    """S-18. The reason this gate is an allow-list: enumerating channels does not converge. Each of
    these is a real release channel of some tool, and none was in the seven-string blocklist."""
    with pytest.raises(SchemaError):
        _parse(channel)


@pytest.mark.parametrize("decorated", ["@latest", ":latest", "--branch main"])
def test_a_decorated_floating_ref_is_rejected(decorated):
    """S-4, S-5, S-6. `@latest` is the sharpest instance: the Dockerfile lint matches that exact
    token in TEXT and would reject it there — the manifest value was simply never tested."""
    with pytest.raises(SchemaError):
        _parse(decorated)


@pytest.mark.parametrize("branch", ["feat/per-server-tool-filtering", "my-branch", "release/2.1"])
def test_a_feature_branch_is_rejected(branch):
    """S-19. bd harnessed-1t4.6: a feature branch moves exactly as main does, and it is what broke
    the deny-list. Two builds a week apart produce different images from identical inputs."""
    with pytest.raises(SchemaError):
        _parse(branch)


@pytest.mark.parametrize("value", ["LATEST", "Main", "NIGHTLY"])
def test_a_channel_in_any_case_is_rejected(value):
    """S-10. Case is not a bypass."""
    with pytest.raises(SchemaError):
        _parse(value)


@pytest.mark.parametrize("value", ["  latest  ", "\tmain\n"])
def test_surrounding_whitespace_is_not_a_bypass(value):
    """S-11."""
    with pytest.raises(SchemaError):
        _parse(value)


# --- Real versions are accepted ------------------------------------------------------------------


@pytest.mark.parametrize("version", SHIPPED)
def test_every_version_this_catalog_ships_is_accepted(version):
    """S-12. The false-positive half of the contract, and the one that would break every build."""
    assert _parse(version) == {"BUN_VERSION": version}


@pytest.mark.parametrize(
    "version",
    ["v6.0.3", "2.1.223-rc.1", "1.2.3+build.5", "20260814", "0.1.2", "a" * 40, "A" * 40],
)
def test_other_legitimate_pin_shapes_are_accepted(version):
    """S-13, S-20. Version tags with or without `v`, pre-release and build metadata, a date-shaped
    version, and a full 40-hex commit SHA in either case."""
    assert _parse(version) == {"BUN_VERSION": version}


@pytest.mark.parametrize(
    "version", ["1.2.3-rc1+build.5", "2.1.223-rc.1+exp.sha.5114f85", "1.0.0-alpha.1+001"],
)
def test_semver_with_both_prerelease_and_build_metadata_is_accepted(version):
    """S-28. Found by adversarial review: the suffix was ONE optional group, so a version carrying
    a prerelease AND build metadata matched the `-rc1` half, left `+build.5` unconsumed, and failed.
    Valid SemVer, and every build of an agent pinned that way would have failed at manifest load.

    The earlier tests had `-rc.1` and `+build.5` as separate cases and never together — the gap was
    in the test data, not only in the pattern.
    """
    assert _parse(version) == {"BUN_VERSION": version}


def test_a_pinned_value_is_stored_stripped(tmp_path):
    """S-23. The value reaches `--build-arg NAME=value`; leading whitespace there is a different
    string than the one the manifest author meant."""
    assert _parse("  1.3.14  ") == {"BUN_VERSION": "1.3.14"}


# --- Both parse branches, and the two declared exceptions ----------------------------------------


def test_the_scalar_and_mapping_forms_are_gated_alike():
    """S-7. The parser's own docstring: the two branches 'express one rule … an asymmetry between
    them is not a smaller bug, it is the same bug with a quieter failure'."""
    with pytest.raises(SchemaError) as scalar:
        _parse("latest")
    with pytest.raises(SchemaError) as mapping:
        _parse({"value": "latest"})

    assert "latest" in str(scalar.value) and "latest" in str(mapping.value)
    assert "BUN_VERSION" in str(scalar.value) and "BUN_VERSION" in str(mapping.value)


def test_a_hold_does_not_excuse_a_channel():
    """S-8. `validate_agent_pin`'s docstring: a declared exception 'suppresses the ABSENT error and
    NOTHING else — an agent that expresses one WRONGLY is a defect, and laundering the second
    through the first is exactly what hold: was stopped from becoming'. HELD means pinned-and-frozen,
    not unpinned."""
    with pytest.raises(SchemaError):
        _parse({"value": "latest", "hold": "unqueryable: the resolver cannot order these tags"})


def test_a_spec_does_not_excuse_a_channel():
    """S-9. A spec explains where a pin resolves from; it does not create one."""
    with pytest.raises(SchemaError):
        _parse({"value": "nightly", "spec": "github:oven-sh/bun"})


def test_a_held_real_version_is_still_accepted():
    """The complement of S-8, so the gate is not read as 'hold is banned'. omp ships exactly this
    shape and must keep loading."""
    parsed = _parse({"value": "1.3.14", "hold": "unqueryable: mise maps bun to core:bun"})

    assert parsed == {"BUN_VERSION": "1.3.14"}


# --- The message ----------------------------------------------------------------------------------


def test_the_error_names_the_manifest_the_key_and_the_value():
    """S-17. The reader has to know WHICH agent, WHICH arg, and what to replace."""
    with pytest.raises(SchemaError) as exc:
        _parse("latest", key="CLAUDE_VERSION")

    msg = str(exc.value)
    assert str(MANIFEST) in msg
    assert "CLAUDE_VERSION" in msg
    assert "latest" in msg


# --- The pre-existing errors still behave ----------------------------------------------------------


@pytest.mark.parametrize("bad", [None, True, False, "", "   "])
def test_an_absent_value_is_still_rejected_as_absent(bad):
    """N-3. The new gate must not swallow the older, more specific error — 'has no value' and 'is
    not a pinned version' send the reader to different fixes."""
    with pytest.raises(SchemaError) as exc:
        _parse(bad)

    assert "no value" in str(exc.value)


def test_unpinnable_inside_build_args_is_still_its_own_error():
    """N-3."""
    with pytest.raises(SchemaError) as exc:
        _parse({"unpinnable": "no selector exists"})

    assert "unpinnable" in str(exc.value)


def test_a_mapping_without_a_value_is_still_its_own_error():
    """N-3."""
    with pytest.raises(SchemaError) as exc:
        _parse({"hold": "frozen"})

    assert "without a 'value'" in str(exc.value)


# --- One vocabulary, and the real catalog ----------------------------------------------------------


def test_every_shipped_agent_manifest_still_loads():
    """S-14. The gate is a regression guard, not a migration: no shipped agent may newly fail."""
    agents = sorted(p.parent for p in CATALOG_AGENTS.glob("*/agent.yaml"))
    assert agents, "no agent manifests found — this guard would pass vacuously"

    for agent_dir in agents:
        load_agent(agent_dir.name)  # raises if the new gate rejects a shipped pin


@pytest.mark.parametrize(
    "value", [*SHIPPED, *DENYLIST_KNEW, *DENYLIST_MISSED, "v6.0.3", "a" * 40, "feat/x", "@latest"],
)
def test_the_agent_gate_and_the_refs_gate_agree(value, tmp_path):
    """S-21. ONE vocabulary across the two surfaces that share the instrument — executed, not
    asserted in prose. Both validators are run on the same input and their verdicts compared, so
    this stays true if either moves.
    """
    from harnessed.schema import _parse_install_refs

    def agent_accepts(v):
        try:
            _parse_agent_build_args({"X_VERSION": v}, MANIFEST)
            return True
        except SchemaError:
            return False

    def refs_accepts(v):
        try:
            _parse_install_refs({"k": {"repo": "owner/repo", "ref": v}}, "install")
            return True
        except SchemaError:
            return False

    assert agent_accepts(value) == refs_accepts(value), (
        f"{value!r}: agent gate and install.refs gate disagree — the two surfaces share one "
        "instrument and must not drift"
    )


# --- Hostile input -------------------------------------------------------------------------------


# Written as escapes, not glyphs: ruff RUF001/2/3 reject ambiguous characters in source, and it is
# right to — a homoglyph that reads as "1.2.3" is exactly the confusion under test here.
ARABIC_INDIC = "\u0661.\u0662.\u0663"  # "1.2.3" in U+0660..U+0669
ARABIC_INDIC_MIXED = "1.\u0662"  # one ASCII digit and one Arabic-Indic
ARABIC_INDIC_ZERO = "\u06600"
FULLWIDTH = "\uff11.\uff12.\uff13"  # "1.2.3" in U+FF10..U+FF19


@pytest.mark.parametrize(
    "value", [ARABIC_INDIC, ARABIC_INDIC_ZERO, ARABIC_INDIC_MIXED, FULLWIDTH],
)
def test_non_ascii_digits_are_not_a_version(value):
    """S-24. Python's `\\d` is Unicode-aware, so Arabic-Indic and full-width digits matched the
    allow-list and were accepted as pins. No registry, tag or installer resolves them — accepting
    one is the gate failing open on precisely the unrecognised shape it promises to fail closed on."""
    with pytest.raises(SchemaError):
        _parse(value)


@pytest.mark.parametrize("value", [ARABIC_INDIC, ARABIC_INDIC_MIXED])
def test_non_ascii_digits_are_not_a_ref_either(value):
    """S-25. The same constant guards `install.refs[].ref`, so it had the identical hole. Fixing one
    surface and not the other would rebuild the asymmetry this unit exists to remove."""
    from harnessed.schema import _parse_install_refs

    with pytest.raises(SchemaError):
        _parse_install_refs({"k": {"repo": "owner/repo", "ref": value}}, "install")


def test_an_absurdly_long_value_is_rejected_promptly():
    """S-27. `(?:\\.\\d+)*` and `(?:[-+.][0-9A-Za-z.]+)?` both match dots, so a failing input makes
    the engine try every split — measured quadratic (4002 chars -> 96 ms). A length cap runs BEFORE
    the regex, so the pathological input never reaches it.

    Asserts the outcome and the promptness together: a test that only checked the rejection would
    still pass while taking a minute.
    """
    import time

    value = "1" + ".1" * 3000 + "!"

    start = time.perf_counter()
    with pytest.raises(SchemaError):
        _parse(value)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"took {elapsed:.3f}s — the cap is not running before the regex"


def test_an_absurdly_long_ref_is_rejected_promptly():
    """S-31. Found by adversarial review round 2: the cap was added to the agent surface only, while
    `install.refs[].ref` reached the SAME regex unbounded. A cap on one of two callers of one pattern
    is not a cap — and I had recorded that as a known limit rather than fixing it, which is how a
    documented gap becomes a shipped defect."""
    import time

    from harnessed.schema import _parse_install_refs

    ref = "1" + ".1" * 3000 + "!"

    start = time.perf_counter()
    with pytest.raises(SchemaError):
        _parse_install_refs({"k": {"repo": "owner/repo", "ref": ref}}, "install")
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"took {elapsed:.3f}s — the ref cap is not running before the regex"


def test_every_shipped_recipe_still_loads_after_the_tightening(tmp_path):
    """S-26. The Unicode fix tightens a constant the recipe path shares, so the recipe path is the
    one that has to be proven unharmed."""
    from harnessed.schema import load_recipe

    catalog = Path(__file__).resolve().parents[1] / "catalog" / "recipes"
    recipes = sorted(p.parent for p in catalog.glob("*/recipe.yaml"))
    assert recipes, "no recipes found — this guard would pass vacuously"

    for recipe_dir in recipes:
        load_recipe(recipe_dir, strict=True)


# --- The write path, not only the read path --------------------------------------------------------


def _agent_manifest(tmp_path: Path, value: str = "1.2.3") -> Path:
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        "harness: demo\nimage: demo:latest\nbuild_args:\n"
        f"  BUN_VERSION: {{ value: \"{value}\" }}\n",
        encoding="utf-8",
    )
    return manifest


@pytest.mark.parametrize("channel", ["latest", "nightly", "main"])
def test_the_update_writer_refuses_to_persist_a_channel(tmp_path, channel):
    """S-29. Found by adversarial review: the gate was READ-only. `harnessed update` wrote a
    resolver-produced value straight into agent.yaml, so a resolver that returned a channel left an
    invalid manifest on disk and turned the NEXT build into a schema error.

    A pin invariant enforced only where values are read is not enforced.
    """
    from harnessed.update import _rewrite_agent_build_arg

    manifest = _agent_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")

    assert _rewrite_agent_build_arg(manifest, "BUN_VERSION", channel) is False
    assert manifest.read_text(encoding="utf-8") == before, "a refused write still touched the file"


def test_the_update_writer_still_applies_a_real_version(tmp_path):
    """S-30. The complement: the guard must not break the path it protects."""
    from harnessed.update import _rewrite_agent_build_arg

    manifest = _agent_manifest(tmp_path, "1.2.3")

    assert _rewrite_agent_build_arg(manifest, "BUN_VERSION", "1.3.14") is True
    assert "1.3.14" in manifest.read_text(encoding="utf-8")


# --- Property: the shape is what decides, not an enumeration ---------------------------------------


@settings(max_examples=200)
@given(st.text(min_size=1, max_size=24, alphabet=st.characters(min_codepoint=97, max_codepoint=122)))
def test_no_bare_word_is_ever_accepted_as_a_pin(word):
    """S-22. The whole point of an allow-list: it does not matter whether anyone enumerated this
    channel. A value made only of letters is never a version, so it is never a pin — including the
    channel nobody has invented yet.
    """
    with pytest.raises(SchemaError):
        _parse(word)


@settings(max_examples=200)
@given(
    st.lists(st.integers(min_value=0, max_value=9999), min_size=1, max_size=4),
    st.booleans(),
)
def test_any_dotted_numeric_version_is_accepted(parts, with_v):
    """S-22, the other side. A one-sided property ('channels are rejected') cannot catch a gate that
    rejects everything, so the accepting half is asserted too."""
    version = ("v" if with_v else "") + ".".join(str(p) for p in parts)

    assert _parse(version) == {"BUN_VERSION": version}
