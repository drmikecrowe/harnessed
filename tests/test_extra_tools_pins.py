"""Tests for extra-tools pin validation and staleness sweeping (bd harnessed-2o9).

`catalog/base/extra-tools.default.txt` feeds `mise use -g` at base-image build time. It used to
list bare tool names, so every entry resolved `@latest` during the build. On 2026-08-06 that broke
the base image outright: mise resolved `dua` to a version token no release carried and died, taking
all eight container-dependent live tests with it.

The lesson is narrower than "@latest is bad" and worth stating precisely, because it is the same
shape as bd harnessed-2c4: **absence of a version reads as "nothing to validate"**. A bare name
carries no floating MARKER for a regex to find, so it sailed past a check that was looking for
`@latest`. It is not merely floating, it is the most floating thing the file can contain.

`schema._parse_tools` already got this right for recipe `tools:` entries — `"@" not in spec` is
rejected there. These tests hold the extra-tools file to the same rule, and then hold the resulting
pins to a staleness sweep so pinning does not simply trade a broken build for a silently rotting one.
"""

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from harnessed import update as pinupdate
from harnessed.schema import PinValidationError, normalize_extra_tools, parse_extra_tools

# The shipped template, resolved from the repo rather than a fixture: the point of S6 is to hold
# the REAL file to the rule, so a fixture copy would defeat the test.
DEFAULT_LIST = Path(__file__).resolve().parents[1] / "catalog" / "base" / "extra-tools.default.txt"


class TestParseExtraTools:
    """What counts as an entry, and what counts as pinned."""

    def test_bare_tool_name_is_rejected(self):
        """The exact defect: no version means `mise use -g` resolves @latest at build time."""
        with pytest.raises(PinValidationError) as exc:
            parse_extra_tools("dua\n")
        assert "dua" in str(exc.value)

    def test_rejection_says_a_version_is_required(self):
        """A build failure that names nothing cost a day; this message must name the fix."""
        with pytest.raises(PinValidationError) as exc:
            parse_extra_tools("dua\n")
        assert "version" in str(exc.value).lower()

    def test_explicit_latest_is_rejected(self):
        with pytest.raises(PinValidationError):
            parse_extra_tools("dua@latest\n")

    def test_pinned_entry_is_accepted(self):
        assert parse_extra_tools("dua@2.41.1\n") == ["dua@2.41.1"]

    def test_comments_and_blank_lines_are_not_entries(self):
        """Must agree with the Dockerfile's `grep -v '^\\s*#' | grep -v '^\\s*$'`."""
        assert parse_extra_tools("# a comment\n\n   \ndua@2.41.1\n") == ["dua@2.41.1"]

    def test_trailing_comment_is_stripped_like_awk_does(self):
        """The Dockerfile takes `awk '{print $1}'`, so only the first field is the spec."""
        assert parse_extra_tools("dua@2.41.1   # du replacement\n") == ["dua@2.41.1"]

    def test_indented_comment_is_not_an_entry(self):
        assert parse_extra_tools("   # indented\ndua@2.41.1\n") == ["dua@2.41.1"]

    def test_a_backend_prefixed_pin_is_accepted(self):
        """mise accepts backend-prefixed specs; pinning is the rule, not the spelling."""
        assert parse_extra_tools("npm:markdownlint-cli2@0.23.2\n") == ["npm:markdownlint-cli2@0.23.2"]

    def test_one_bad_entry_among_good_ones_still_raises(self):
        with pytest.raises(PinValidationError) as exc:
            parse_extra_tools("bat@0.26.1\ndua\neza@0.23.5\n")
        assert "dua" in str(exc.value)


# mutmut runs the suite across several worker processes, which trips hypothesis'
# `differing_executors` health check and aborts its stats phase — so the mutation layer cannot run
# at all while these properties are collected. Suppressed rather than deleted: the properties are
# worth more than the health check, which is warning about replay determinism we do not rely on.
_MUTMUT_SAFE = settings(suppress_health_check=[HealthCheck.differing_executors])


class TestParseExtraToolsProperties:
    """Invariants over inputs nobody enumerated by hand."""

    # ASCII only, deliberately narrowed when the printable-ASCII rule landed (SPEC amendment 2).
    # The previous generator drew from the whole Ll/Nd Unicode categories, so hypothesis promptly
    # produced names the new rule refuses — correctly. Narrowing the GENERATOR to the spec is the
    # honest fix; widening the RULE to admit unicode would give back the separators (U+2028/U+2029)
    # the rule exists to exclude.
    _names = st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122) | st.sampled_from("0123456789-_"),
        min_size=1, max_size=12,
    ).filter(lambda s: not s.startswith("#"))

    @_MUTMUT_SAFE
    @given(name=_names, ver=st.from_regex(r"\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z"))
    def test_any_pinned_entry_round_trips(self, name, ver):
        assert parse_extra_tools(f"{name}@{ver}\n") == [f"{name}@{ver}"]

    @_MUTMUT_SAFE
    @given(name=_names)
    def test_any_bare_name_is_rejected(self, name):
        """The general form of the bug: no '@' anywhere is always unpinned."""
        with pytest.raises(PinValidationError):
            parse_extra_tools(f"{name}\n")

    @_MUTMUT_SAFE
    @given(name=_names, ver=st.from_regex(r"\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z"))
    def test_a_trailing_comment_never_changes_the_parsed_spec(self, name, ver):
        """Comment text must never leak into the spec handed to mise."""
        assert parse_extra_tools(f"{name}@{ver}  # note\n") == parse_extra_tools(f"{name}@{ver}\n")


class TestGuardAgreesWithTheDockerfile:
    """The invariant the whole guard rests on: it must see what `mise use -g` will see.

    Found by adversarial review. Python hides two byte-level details from the validator that awk
    does not hide from the build, so a file could pass every check and still kill the image — the
    exact failure mode bd harnessed-2o9 is about, reintroduced by its own fix.
    """

    def _dockerfile_pipeline(self, raw: bytes) -> list[bytes]:
        """Byte-for-byte what catalog/base/Dockerfile.harnessed-base pipes into `mise use -g`."""
        import subprocess
        out = subprocess.run(
            ["bash", "-c", r"""grep -v '^\s*#' | grep -v '^\s*$' | awk '{print $1}'"""],
            input=raw, capture_output=True,
        ).stdout
        return [line for line in out.split(b"\n") if line]

    @pytest.mark.parametrize("raw", [
        b"bat@0.26.1\ndua@2.41.1\n",                    # plain LF
        b"bat@0.26.1\r\ndua@2.41.1\r\n",                # CRLF
        "\ufeffbat@0.26.1\ndua@2.41.1\n".encode(),      # UTF-8 BOM
        b"bat@0.26.1   # cat\r\ndua@2.41.1  # du\r\n",  # CRLF with trailing comments
        b"\tbat@0.26.1\ndua@2.41.1",                    # leading tab, no trailing newline
    ], ids=["lf", "crlf", "bom", "crlf-comments", "tab-no-eol"])
    def test_the_parsed_specs_match_what_the_build_pipeline_extracts(self, raw):
        """Whatever the guard blesses must be exactly what mise is handed."""
        parsed = parse_extra_tools(raw.decode("utf-8"))
        staged = normalize_extra_tools(raw.decode("utf-8")).encode("utf-8")
        assert [s.encode("utf-8") for s in parsed] == self._dockerfile_pipeline(staged)

    def test_a_crlf_entry_does_not_reach_mise_with_a_carriage_return(self):
        """awk does not treat \\r as a field separator, so a CRLF file used to yield 'bat@0.26.1\\r'."""
        staged = normalize_extra_tools("bat@0.26.1\r\n")
        assert self._dockerfile_pipeline(staged.encode()) == [b"bat@0.26.1"]

    # Every character `str.splitlines()` breaks on that awk's record separator does not. Enumerated
    # rather than sampled: this is the whole class, and the class already produced three defects.
    PYTHON_ONLY_BREAKS = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85",
                          "\u2028", "\u2029"]
    _SEP_IDS = [f"U+{ord(c):04X}" for c in PYTHON_ONLY_BREAKS]

    @pytest.mark.parametrize("sep", PYTHON_ONLY_BREAKS, ids=_SEP_IDS)
    def test_a_separator_only_python_honours_is_refused(self, sep):
        """These used to parse as two clean specs while awk handed mise the concatenation.

        Refused rather than folded: awk would read `bat@0.26.1<sep>dua@2.41.1` as ONE tool name, so
        there is no reading of the file both sides agree on. Failing closed is the only answer that
        cannot silently install the wrong thing.
        """
        with pytest.raises(PinValidationError):
            parse_extra_tools(f"bat@0.26.1{sep}dua@2.41.1\n")

    @pytest.mark.parametrize("sep", PYTHON_ONLY_BREAKS, ids=_SEP_IDS)
    def test_the_guard_never_disagrees_with_the_build_on_these(self, sep):
        """The invariant restated as a property: agree, or refuse. Never diverge."""
        text = f"bat@0.26.1{sep}dua@2.41.1\n"
        try:
            parsed = parse_extra_tools(text)
        except PinValidationError:
            return  # refused — cannot diverge
        staged = normalize_extra_tools(text).encode("utf-8")
        assert [s.encode("utf-8") for s in parsed] == self._dockerfile_pipeline(staged)

    def test_a_non_ascii_tool_name_is_refused(self):
        """A deliberate restriction, not an oversight — see SPEC amendment 2.

        Admitting unicode would mean admitting U+2028/U+2029, which are exactly the separators this
        rule exists to keep out. No mise tool in the registry needs a non-ASCII name, so the cost of
        the restriction is nil and it makes the guard/build agreement total rather than probable.
        """
        with pytest.raises(PinValidationError):
            parse_extra_tools("café@1.0.0\n")

    def test_a_second_bom_is_refused_rather_than_carried_into_a_tool_name(self):
        """normalize strips ONE leading BOM; a second must not ride along inside the spec."""
        with pytest.raises(PinValidationError):
            parse_extra_tools("\ufeff\ufeffbat@0.26.1\n")

    def test_a_lone_carriage_return_is_a_line_break_too(self):
        """Classic-Mac line endings. Rare, but the fold is one `replace` away and free to get right."""
        assert parse_extra_tools("bat@0.26.1\rdua@2.41.1\r") == ["bat@0.26.1", "dua@2.41.1"]

    def test_a_leading_letter_is_never_mistaken_for_a_bom(self):
        """`lstrip` takes a character SET; a tool starting with the stripped letter would lose it."""
        assert parse_extra_tools("Xvfb@1.0.0\n") == ["Xvfb@1.0.0"]

    def test_a_bom_does_not_ride_on_the_first_spec(self):
        """It carries an '@' and no floating marker, so every check passed it straight through."""
        assert parse_extra_tools("\ufeffbat@0.26.1\n") == ["bat@0.26.1"]


class TestShippedDefaultIsPinned:
    """S6 — the permanent regression gate on the real template."""

    def test_the_shipped_default_passes_its_own_validator(self):
        entries = parse_extra_tools(DEFAULT_LIST.read_text())
        assert entries, "the template must still list tools"
        assert all("@" in e for e in entries)

    def test_dua_is_pinned_to_the_version_that_broke_under_at_latest(self):
        """Asserts the LITERAL pin only — that this version installs is not checkable here.

        Deliberately narrow after adversarial review: the earlier name promised "a version whose
        asset exists", which no assertion in this process can establish. That a cold registry
        cache installs dua@2.41.1 was verified by a real container build; it belongs in the
        evidence report, not in a docstring over a text-membership check.
        """
        entries = parse_extra_tools(DEFAULT_LIST.read_text())
        assert "dua@2.41.1" in entries


class TestStagedBuildContextRejectsUnpinned:
    """S5 — fail on the HOST, naming the file the human must edit."""

    def _home(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        base = home / "catalog" / "base"
        base.mkdir(parents=True)
        (base / "extra-tools.default.txt").write_text("bat@0.26.1\n")
        monkeypatch.setenv("HARNESSED_DIR", str(home))
        return home

    def _user_file(self, monkeypatch, tmp_path, content):
        xdg = tmp_path / "config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        f = xdg / "harnessed" / "extra-tools.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        return f

    def test_unpinned_user_entry_fails_before_podman_runs(self, monkeypatch, tmp_path):
        """Previously this surfaced as `exit status 123` from inside a RUN layer."""
        from harnessed import launcher

        self._home(monkeypatch, tmp_path)
        self._user_file(monkeypatch, tmp_path, "dua\n")
        with pytest.raises(PinValidationError):
            with launcher._staged_build_context():
                pass

    def test_the_error_names_the_user_file_not_the_template(self, monkeypatch, tmp_path):
        """The template is marked 'do not edit for personal use' — pointing there sends them wrong."""
        from harnessed import launcher

        self._home(monkeypatch, tmp_path)
        user_file = self._user_file(monkeypatch, tmp_path, "dua\n")
        with pytest.raises(PinValidationError) as exc:
            with launcher._staged_build_context():
                pass
        assert str(user_file) in str(exc.value)

    def test_the_error_tells_the_user_how_to_recover(self, monkeypatch, tmp_path):
        """This fires on the first build after upgrading, for users who did nothing wrong.

        Their `extra-tools.txt` is a copy of the OLD unpinned template, seeded once and never
        touched since. Naming the remedy is what stops that being a support question.
        """
        from harnessed import launcher

        self._home(monkeypatch, tmp_path)
        self._user_file(monkeypatch, tmp_path, "dua\n")
        with pytest.raises(PinValidationError) as exc:
            with launcher._staged_build_context():
                pass
        assert "delete it and rebuild" in str(exc.value)

    def test_a_pinned_user_file_still_stages(self, monkeypatch, tmp_path):
        """N1/N2 — the guard must not break the staging it guards."""
        from harnessed import launcher

        self._home(monkeypatch, tmp_path)
        self._user_file(monkeypatch, tmp_path, "dua@2.41.1\n")
        with launcher._staged_build_context() as ctx:
            staged = Path(ctx) / "catalog" / "base" / "extra-tools.txt"
            assert staged.read_text() == "dua@2.41.1\n"


class TestExtraToolsDiscovery:
    """S7 — the pins become Pin objects the sweep already knows how to classify."""

    def test_each_pinned_entry_becomes_a_resolvable_pin(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("# c\nbat@0.26.1\ndua@2.41.1  # du\n")
        pins = pinupdate.discover_extra_tools_pins(f)
        assert [(p.name, p.current) for p in pins] == [("bat", "0.26.1"), ("dua", "2.41.1")]
        assert all(p.resolvable for p in pins)

    def test_pins_reuse_the_shared_spec_splitter(self, tmp_path):
        """No second parser: `dua@2.41.1` must resolve through the mise backend like `tools:` does."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        assert pinupdate.discover_extra_tools_pins(f)[0].backend == "mise"

    def test_pins_carry_a_label_saying_where_a_bump_would_land(self, tmp_path):
        """The report prints this next to an offered bump; without it the human cannot tell
        which file `harnessed update` is about to rewrite."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        assert pinupdate.discover_extra_tools_pins(f)[0].recipe == pinupdate.EXTRA_TOOLS_LABEL

    def test_a_non_utf8_file_yields_no_pins_rather_than_raising(self, tmp_path):
        """Same class as bd harnessed-l8p: a decode blowing up in a sweep hides every other pin.

        This is what `errors="replace"` buys, and it is only observable on undecodable bytes.
        """
        f = tmp_path / "extra-tools.default.txt"
        # The undecodable bytes sit in a COMMENT, so the only thing under test is the decode:
        # put them in an entry instead and the parser rejects it for being unpinned, which would
        # pass for the wrong reason.
        f.write_bytes(b"# \xff\xfe comment\ndua@2.41.1\n")
        assert [p.name for p in pinupdate.discover_extra_tools_pins(f)] == ["dua"]

    def test_a_missing_file_yields_no_pins_rather_than_raising(self, tmp_path):
        """N7 — one bad input must never blind the sweep to the recipes."""
        assert pinupdate.discover_extra_tools_pins(tmp_path / "nope.txt") == []

    def test_an_unpinned_file_yields_no_pins_rather_than_raising(self, tmp_path):
        """`update` reports; the BUILD is what refuses. A crash here would hide every recipe pin."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua\n")
        assert pinupdate.discover_extra_tools_pins(f) == []


class TestExtraToolsInReport:
    """S8 — a stale extra-tools pin drives `--check` non-zero."""

    def _releases(self, *versions):
        from harnessed.update import Release
        from datetime import datetime, timezone
        return [
            Release(version=v, published=datetime(2020, 1, 1, tzinfo=timezone.utc))
            for v in versions
        ]

    def test_a_stale_extra_tools_pin_is_reported_stale(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        report = pinupdate.build_report(
            [], extra_tools=f, resolve=lambda b, n: self._releases("2.42.0"),
        )
        assert [x.pin.name for x in report.stale] == ["dua"]

    def test_a_stale_extra_tools_pin_makes_check_exit_non_zero(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        report = pinupdate.build_report(
            [], extra_tools=f, resolve=lambda b, n: self._releases("2.42.0"),
        )
        assert report.check_exit_code() != 0

    def test_an_up_to_date_extra_tools_pin_is_not_stale(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        report = pinupdate.build_report(
            [], extra_tools=f, resolve=lambda b, n: self._releases("2.41.1"),
        )
        assert report.stale == []

    def test_omitting_extra_tools_keeps_the_old_behaviour(self, tmp_path):
        """N8 — every existing caller passes no such argument and must be unaffected."""
        report = pinupdate.build_report([], resolve=lambda b, n: self._releases("9.9.9"))
        assert report.stale == []


class TestExtraToolsRewrite:
    """S9 — bumping a text file must not go through the YAML round-tripper."""

    def _stale(self, path, name="dua"):
        """A stale finding for ONE named tool — selected by name, never by position.

        Indexing `[0]` here silently bumps whichever entry happens to sort first, which is the very
        wrong-neighbour bug these tests exist to catch.
        """
        from harnessed.update import Finding
        pin = next(p for p in pinupdate.discover_extra_tools_pins(path) if p.name == name)
        return Finding(pin=pin, latest="2.42.0")

    def test_apply_bumps_the_version_in_place(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        assert pinupdate.apply([self._stale(f)])
        assert f.read_text() == "dua@2.42.0\n"

    def test_apply_preserves_the_trailing_comment(self, tmp_path):
        """The comments are where the WHY lives — same reason the YAML path round-trips."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1   # du replacement\n")
        pinupdate.apply([self._stale(f)])
        assert "# du replacement" in f.read_text()

    def test_apply_leaves_other_entries_untouched(self, tmp_path):
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("# header\nbat@0.26.1\ndua@2.41.1\neza@0.23.5\n")
        pinupdate.apply([self._stale(f)])
        assert f.read_text() == "# header\nbat@0.26.1\ndua@2.42.0\neza@0.23.5\n"

    def test_apply_handles_the_real_template_shape(self, tmp_path):
        """Blank lines and section comments, exactly as the shipped template is laid out.

        Not decoration: the rewriter indexes `stripped.split()[0]`, which raises IndexError on a
        blank line if the skip above it is ever weakened. The real file is full of blank lines, so
        a bump would crash on the first section break.
        """
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("# Modern CLI replacements\nbat@0.26.1   # cat\n\n# Data\ndua@2.41.1   # du\n")
        assert pinupdate.apply([self._stale(f)])
        assert f.read_text() == (
            "# Modern CLI replacements\nbat@0.26.1   # cat\n\n# Data\ndua@2.42.0   # du\n"
        )

    def test_apply_does_not_rewrite_the_spec_where_it_recurs_in_the_comment(self, tmp_path):
        """Only the ENTRY is a pin; the same text in the comment is prose and must survive."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1   # pinned at dua@2.41.1 after bd harnessed-2o9\n")
        pinupdate.apply([self._stale(f)])
        assert f.read_text() == (
            "dua@2.42.0   # pinned at dua@2.41.1 after bd harnessed-2o9\n"
        )

    @pytest.mark.parametrize("suffix", [".yaml", ".yml"])
    def test_a_yaml_manifest_still_goes_through_the_yaml_rewriter(self, tmp_path, suffix):
        """N6 — dispatch must send YAML to the round-tripper, whichever spelling it uses.

        Asserted via a comment surviving the write: the text rewriter would leave the file's
        structure alone but is not what should be handling a manifest, and the round-tripper is
        the only one of the two that preserves a comment inside a YAML mapping.
        """
        from harnessed.update import Finding, Pin

        manifest = tmp_path / f"recipe{suffix}"
        manifest.write_text("name: demo\ntools:\n  - dua@2.41.1   # du replacement\n")
        pin = Pin(recipe="demo", file=manifest, spec="dua@2.41.1", name="dua",
                  current="2.41.1", backend="mise")
        assert pinupdate.apply([Finding(pin=pin, latest="2.42.0")])
        written = manifest.read_text()
        assert "dua@2.42.0" in written
        assert "# du replacement" in written

    def test_apply_reports_nothing_when_the_entry_is_no_longer_there(self, tmp_path):
        """A bump it could not make must not be reported as made, and must not rewrite the file.

        Reachable for real: the report is built before the prompt, so a concurrent edit (or a second
        `harnessed update`) can remove the entry between classification and the write.
        """
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua@2.41.1\n")
        finding = self._stale(f)
        f.write_text("# someone removed it\n")
        assert pinupdate.apply([finding]) == []
        assert f.read_text() == "# someone removed it\n"

    def test_apply_does_not_match_a_different_tool_with_a_shared_prefix(self, tmp_path):
        """`dua` must not rewrite `dua-cli`; a substring swap here corrupts a neighbour."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua-cli@1.0.0\ndua@2.41.1\n")
        pinupdate.apply([self._stale(f)])
        assert f.read_text() == "dua-cli@1.0.0\ndua@2.42.0\n"
