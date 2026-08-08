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
from hypothesis import given, strategies as st

from harnessed import update as pinupdate
from harnessed.schema import PinValidationError, parse_extra_tools

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


class TestParseExtraToolsProperties:
    """Invariants over inputs nobody enumerated by hand."""

    _names = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"),
        min_size=1, max_size=12,
    ).filter(lambda s: not s.startswith("#"))

    @given(name=_names, ver=st.from_regex(r"\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z"))
    def test_any_pinned_entry_round_trips(self, name, ver):
        assert parse_extra_tools(f"{name}@{ver}\n") == [f"{name}@{ver}"]

    @given(name=_names)
    def test_any_bare_name_is_rejected(self, name):
        """The general form of the bug: no '@' anywhere is always unpinned."""
        with pytest.raises(PinValidationError):
            parse_extra_tools(f"{name}\n")

    @given(name=_names, ver=st.from_regex(r"\A[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z"))
    def test_a_trailing_comment_never_changes_the_parsed_spec(self, name, ver):
        """Comment text must never leak into the spec handed to mise."""
        assert parse_extra_tools(f"{name}@{ver}  # note\n") == parse_extra_tools(f"{name}@{ver}\n")


class TestShippedDefaultIsPinned:
    """S6 — the permanent regression gate on the real template."""

    def test_the_shipped_default_passes_its_own_validator(self):
        entries = parse_extra_tools(DEFAULT_LIST.read_text())
        assert entries, "the template must still list tools"
        assert all("@" in e for e in entries)

    def test_dua_is_pinned_to_a_version_whose_asset_exists(self):
        """The pin that broke the build. 2.41.1 verified installing from a cold registry cache."""
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

    def test_apply_does_not_match_a_different_tool_with_a_shared_prefix(self, tmp_path):
        """`dua` must not rewrite `dua-cli`; a substring swap here corrupts a neighbour."""
        f = tmp_path / "extra-tools.default.txt"
        f.write_text("dua-cli@1.0.0\ndua@2.41.1\n")
        pinupdate.apply([self._stale(f)])
        assert f.read_text() == "dua-cli@1.0.0\ndua@2.42.0\n"
