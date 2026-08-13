"""Choosing WHICH version to offer, pnpm-style (bd harnessed-7zb, round 2).

pnpm's `minimumReleaseAge` does not merely refuse a too-fresh release — it installs the newest
version that IS old enough. Refusing outright would mean a stale pin stays stale for a week even
when a perfectly mature intermediate release exists.

Measured on the live catalog, that distinction decides every pin we have:

    serena  pinned 1.5.3;  1.6.1 published 4 days ago,  1.6.0 published 9 days ago  -> offer 1.6.0
    pulumi  pinned 3.251.0; v3.254.0 2 days ago,        v3.253.0 11 days ago        -> offer 3.253.0

Under refuse-outright, both are unactionable. Under pnpm's rule, both are real bumps.

Where we deliberately DIVERGE from pnpm: an undated release. pnpm's
`minimumReleaseAgeIgnoreMissingTime` defaults to true (install it anyway, because private mirrors
often omit `time`). Here every registry is public and does supply dates, so a missing date means
the age guarantee cannot be kept — we withhold and report instead of quietly installing.

Units follow pnpm: MINUTES. The default is 10080 (7 days) rather than pnpm's 1440 (1 day).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from harnessed import update

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
DAY = 1440  # minutes, pnpm's unit


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _recipe_dir(tmp_path, name, body):
    d = tmp_path / "catalog" / "recipes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    return d


def _releases(*pairs):
    """(version, age_in_days) pairs -> a resolver returning them. None age = undated."""
    rels = [update.Release(version=v, published=None if a is None else _ago(a)) for v, a in pairs]
    return lambda backend, name: rels


def _report(tmp_path, current_spec, resolver, *, minutes=7 * DAY):
    d = _recipe_dir(tmp_path, "r", f"name: r\ntools:\n  - {current_spec}\n")
    return update.build_report(
        [d], resolve=resolver, now=NOW, minimum_release_age_minutes=minutes,
    ), d


class TestNewestSafeVersionWins:
    def test_a_mature_intermediate_is_offered_when_the_newest_is_too_fresh(self, tmp_path):
        """The serena case, exactly."""
        report, _ = _report(
            tmp_path, "pipx:serena-agent@1.5.3",
            _releases(("1.5.3", 60), ("1.6.0", 9), ("1.6.1", 4)),
        )
        assert len(report.stale) == 1
        assert report.stale[0].latest == "1.6.0", "1.6.1 is 4 days old; 1.6.0 at 9 days is safe"

    def test_the_skipped_newer_release_is_named(self, tmp_path):
        """Offering 1.6.0 while 1.6.1 exists is surprising unless the report says why."""
        report, _ = _report(
            tmp_path, "pipx:serena-agent@1.5.3",
            _releases(("1.6.0", 9), ("1.6.1", 4)),
        )
        f = report.stale[0]
        assert f.skipped_newer == "1.6.1"
        assert f.skipped_newer_age_days is not None and 3.9 < f.skipped_newer_age_days < 4.2

    def test_nothing_is_skipped_when_the_newest_is_already_safe(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("1.1.0", 30), ("1.2.0", 20)))
        assert report.stale[0].latest == "1.2.0"
        assert report.stale[0].skipped_newer is None

    def test_all_newer_releases_too_fresh_means_nothing_is_offered(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("1.1.0", 2), ("1.2.0", 1)))
        assert not report.stale
        assert len(report.cooling) == 1
        assert report.cooling[0].latest == "1.2.0", "the cooling report names the NEWEST"

    def test_no_newer_release_at_all_is_current(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.2.0", _releases(("1.1.0", 30), ("1.2.0", 20)))
        assert report.current and not report.stale and not report.cooling

    def test_older_releases_are_never_offered_as_a_downgrade(self, tmp_path):
        """A yanked newest, or a pin deliberately ahead of the registry."""
        report, _ = _report(tmp_path, "npm:x@2.0.0", _releases(("1.9.0", 30), ("1.8.0", 60)))
        assert not report.stale and not report.cooling

    def test_the_chosen_version_is_what_gets_written(self, tmp_path):
        report, d = _report(
            tmp_path, "pipx:serena-agent@1.5.3", _releases(("1.6.0", 9), ("1.6.1", 4)),
        )
        update.apply(report.stale)
        after = (d / "recipe.yaml").read_text()
        assert "pipx:serena-agent@1.6.0" in after
        assert "1.6.1" not in after


class TestUndatedReleases:
    """We diverge from pnpm here on purpose — see the module docstring."""

    def test_an_undated_candidate_is_not_offered(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("2.0.0", None)))
        assert not report.stale
        assert report.unresolved and "date" in report.unresolved[0].error.lower()

    def test_a_dated_safe_release_still_wins_past_an_undated_newer_one(self, tmp_path):
        """One unusable entry must not blind the command to a good bump below it."""
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("1.5.0", 30), ("2.0.0", None)))
        assert report.stale and report.stale[0].latest == "1.5.0"

    def test_undated_releases_are_offered_when_the_gate_is_off(self, tmp_path):
        """With no age requirement there is no promise to break."""
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("2.0.0", None)), minutes=0)
        assert report.stale and report.stale[0].latest == "2.0.0"


class TestMinutesAreTheUnit:
    def test_the_default_is_seven_days(self):
        assert update.DEFAULT_MINIMUM_RELEASE_AGE_MINUTES == 7 * DAY == 10080

    def test_the_window_is_interpreted_in_minutes(self, tmp_path):
        """1440 minutes = 1 day, pnpm's own default. A 2-day-old release passes it."""
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("2.0.0", 2)), minutes=DAY)
        assert report.stale and report.stale[0].latest == "2.0.0"

    def test_the_same_release_fails_the_seven_day_window(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("2.0.0", 2)), minutes=7 * DAY)
        assert report.cooling and not report.stale

    def test_zero_disables_the_gate(self, tmp_path):
        report, _ = _report(tmp_path, "npm:x@1.0.0", _releases(("2.0.0", 0.01)), minutes=0)
        assert report.stale


class TestBackendsListEveryVersion:
    """Payload shapes verified against the live registries on 2026-07-25."""

    def test_npm_reads_versions_crossed_with_the_time_map(self):
        payload = json.dumps({
            "dist-tags": {"latest": "2.2.26"},
            "versions": {"2.2.22": {}, "2.2.25": {}, "2.2.26": {}},
            # `created`/`modified` are the only non-version keys npm puts here — verified live.
            "time": {
                "created": "2026-01-01T00:00:00Z",
                "modified": "2026-07-25T07:13:18.627Z",
                "2.2.22": "2026-06-16T06:02:08.122Z",
                "2.2.25": "2026-07-04T00:00:00.000Z",
                "2.2.26": "2026-07-25T07:13:18.627Z",
            },
        })
        rels = update.resolve_releases("npm", "ccstatusline", fetch=lambda url: payload)
        assert {r.version for r in rels} == {"2.2.22", "2.2.25", "2.2.26"}
        assert all(r.published is not None for r in rels)

    def test_npm_ignores_time_entries_with_no_matching_version(self):
        payload = json.dumps({
            "versions": {"1.0.0": {}},
            "time": {"created": "2026-01-01T00:00:00Z", "1.0.0": "2026-02-01T00:00:00Z",
                     "0.9.0": "2025-01-01T00:00:00Z"},
        })
        rels = update.resolve_releases("npm", "x", fetch=lambda url: payload)
        assert [r.version for r in rels] == ["1.0.0"], "an unpublished/removed version is not real"

    def test_pypi_reads_the_releases_map(self):
        payload = json.dumps({
            "info": {"version": "1.6.1"},
            "releases": {
                "1.5.3": [{"upload_time_iso_8601": "2026-05-26T19:06:28.424565Z"}],
                "1.6.0": [{"upload_time_iso_8601": "2026-07-16T11:58:32.688861Z"}],
                "1.6.1": [{"upload_time_iso_8601": "2026-07-21T15:41:09.268053Z"}],
            },
        })
        rels = update.resolve_releases("pipx", "serena-agent", fetch=lambda url: payload)
        assert {r.version for r in rels} == {"1.5.3", "1.6.0", "1.6.1"}

    def test_pypi_skips_a_release_with_no_files(self):
        """A fully-yanked release keeps its key but loses its files — it has no date and cannot be
        installed, so it is not a candidate."""
        payload = json.dumps({
            "info": {"version": "1.0.0"},
            "releases": {"1.0.0": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}],
                         "1.0.1": []},
        })
        rels = update.resolve_releases("pipx", "x", fetch=lambda url: payload)
        assert [r.version for r in rels] == ["1.0.0"]

    def test_github_reads_the_releases_list(self):
        seen = {}

        def fetch(url):
            seen["url"] = url
            return json.dumps([
                {"tag_name": "v3.254.0", "published_at": "2026-07-23T15:10:53Z",
                 "prerelease": False, "draft": False},
                {"tag_name": "v3.253.0", "published_at": "2026-07-14T11:30:57Z",
                 "prerelease": False, "draft": False},
            ])

        rels = update.resolve_releases("github", "pulumi/pulumi", fetch=fetch)
        assert [r.version for r in rels] == ["v3.254.0", "v3.253.0"]
        assert "/repos/pulumi/pulumi/releases" in seen["url"]
        assert "/releases/latest" not in seen["url"], "the list endpoint, not the single latest"

    @pytest.mark.parametrize("flag", ["prerelease", "draft"])
    def test_github_excludes_prereleases_and_drafts(self, flag):
        """Neither is a shipped version; offering one would bump the catalog onto an unreleased
        build."""
        payload = json.dumps([
            {"tag_name": "v2.0.0-rc1", "published_at": "2026-07-01T00:00:00Z",
             "prerelease": flag == "prerelease", "draft": flag == "draft"},
            {"tag_name": "v1.0.0", "published_at": "2026-06-01T00:00:00Z",
             "prerelease": False, "draft": False},
        ])
        rels = update.resolve_releases("github", "o/r", fetch=lambda url: payload)
        assert [r.version for r in rels] == ["v1.0.0"]

    def test_mise_routes_through_its_registry_to_github(self):
        registry = "pulumi                        aqua:pulumi/pulumi asdf:canha/asdf-pulumi\n"

        def fetch(url):
            assert "/repos/pulumi/pulumi/releases" in url
            return json.dumps([{"tag_name": "v3.253.0", "published_at": "2026-07-14T11:30:57Z",
                                "prerelease": False, "draft": False}])

        rels = update.resolve_releases("mise", "pulumi", fetch=fetch, run=lambda cmd: registry)
        assert [r.version for r in rels] == ["v3.253.0"]


class TestPinConventionSurvivesSelection:
    def test_a_v_tag_is_normalised_to_the_pins_shape(self, tmp_path):
        """pulumi pins bare `3.251.0`; GitHub answers `v3.253.0`."""
        report, d = _report(
            tmp_path, "pulumi@3.251.0", _releases(("v3.254.0", 2), ("v3.253.0", 11)),
        )
        assert report.stale[0].latest == "3.253.0"
        update.apply(report.stale)
        assert "pulumi@3.253.0" in (d / "recipe.yaml").read_text()

    def test_the_skipped_version_is_normalised_too(self, tmp_path):
        report, _ = _report(
            tmp_path, "pulumi@3.251.0", _releases(("v3.254.0", 2), ("v3.253.0", 11)),
        )
        assert report.stale[0].skipped_newer == "3.254.0"


class TestVersionKeyIsATotalOrder:
    """`version_key` must order ANY two version strings, because `_select` SORTS with it.

    Found by pinning `npm:@openai/codex` (A2). `_select` wraps its filter comparison in
    `except TypeError: continue`, so an unorderable version is merely skipped there — but the
    `candidates.sort(...)` two lines later has no such guard, and sorting compares candidates
    against EACH OTHER. Two versions can each compare fine against `current` and still be mutually
    incomparable, which is precisely what crashed `harnessed update --check`:

        TypeError: '<' not supported between instances of 'int' and 'str'

    The real pair, live on the npm registry: `0.146.0-alpha.3.1-linux-x64` and `0.146.0-alpha.3.1`
    key to `('alpha', 3, '1-linux-x64')` and `('alpha', 3, 1)`, which differ in TYPE at index 2.
    """

    # The shapes @openai/codex actually publishes, read from the registry on 2026-08-13.
    REAL_SHAPES = (
        "0.41.0-alpha.1", "0.99.0-alpha.20-darwin-arm64", "0.99.0-darwin-arm64",
        "0.146.0-alpha.3.1-linux-x64", "0.146.0-alpha.3.1", "0.139.0", "0.147.0",
    )

    def test_every_pair_of_real_published_shapes_is_orderable(self):
        """The property, not the one pair: any two keys compare, whatever the mix of shapes."""
        for a in self.REAL_SHAPES:
            for b in self.REAL_SHAPES:
                assert isinstance(update.version_key(a) < update.version_key(b), bool)

    def test_the_exact_pair_that_crashed_the_updater(self):
        """And it orders them the semver way round: `1` is numeric, `1-linux-x64` is not."""
        pair = ["0.146.0-alpha.3.1-linux-x64", "0.146.0-alpha.3.1"]
        assert sorted(pair, key=update.version_key) == [
            "0.146.0-alpha.3.1", "0.146.0-alpha.3.1-linux-x64",
        ]

    def test_a_numeric_identifier_sorts_below_an_alphanumeric_one(self):
        """Semver §11.4.3, and the reason the fix is a tagged tuple rather than `str()` everywhere.

        Coercing both sides to `str` would also stop the crash, and would silently order `10`
        before `9`. That is the classic version-sort bug this module's own docstring warns about.
        """
        assert update.version_key("1.0.0-1") < update.version_key("1.0.0-alpha")

    def test_numeric_prerelease_identifiers_still_compare_numerically(self):
        assert update.version_key("1.0.0-alpha.9") < update.version_key("1.0.0-alpha.10")

    def test_a_prerelease_still_sorts_below_its_own_release(self):
        """The property the original code got right, and the fix must not break."""
        assert update.version_key("1.0.0-alpha.1") < update.version_key("1.0.0")


class TestPrereleasesAreNotOfferedAsBumps:
    """npm listed EVERY version, so an alpha could be offered as an upgrade.

    The github branch already refuses this in so many words — "A prerelease or draft is not a
    shipped version, so offering one would bump the catalog onto an unreleased build" — but the npm
    branch returned the whole `versions` map. Pinning codex made it live: the newest npm version of
    `@openai/codex` is a platform-suffixed alpha, so a bump would have moved the catalog onto
    `0.146.0-alpha.3.1-linux-x64`. Crashing was the loud symptom; THIS was the quiet one.
    """

    def test_npm_omits_prereleases(self):
        payload = json.dumps({
            "versions": {"1.0.0": {}, "1.1.0-alpha.1": {}, "1.1.0": {}},
            "time": {"created": "2026-01-01T00:00:00Z",
                     "1.0.0": "2026-01-02T00:00:00Z",
                     "1.1.0-alpha.1": "2026-01-03T00:00:00Z",
                     "1.1.0": "2026-01-04T00:00:00Z"},
        })
        rels = update.resolve_releases("npm", "x", fetch=lambda url: payload)
        assert [r.version for r in rels] == ["1.0.0", "1.1.0"], "an alpha is not a shipped version"

    def test_a_release_with_build_metadata_is_still_a_release(self):
        """`+build` is NOT a prerelease under semver — only a `-` suffix is. Excluding it would
        quietly drop real shipped versions, which is the opposite failure."""
        # `+build-7` carries a HYPHEN inside the build metadata, so a naive `"-" in version` test
        # would drop it. That naive test is the obvious implementation and it is wrong; this case
        # is here to keep it out.
        payload = json.dumps({
            "versions": {"1.0.0": {}, "1.1.0+build-7": {}},
            "time": {"1.0.0": "2026-01-02T00:00:00Z", "1.1.0+build-7": "2026-01-04T00:00:00Z"},
        })
        rels = update.resolve_releases("npm", "x", fetch=lambda url: payload)
        assert [r.version for r in rels] == ["1.0.0", "1.1.0+build-7"]

    def test_the_codex_shaped_case_end_to_end(self, tmp_path):
        """A pin at a real release is never offered an alpha, however much newer the alpha is."""
        report, _ = _report(
            tmp_path, "npm:@openai/codex@0.139.0",
            _releases(("0.147.0", 30), ("0.146.0-alpha.3.1-linux-x64", 2), ("0.146.0-alpha.3.1", 2)),
        )
        offered = [f.latest for f in report.stale]
        assert offered == ["0.147.0"], f"a prerelease reached the report: {offered}"
