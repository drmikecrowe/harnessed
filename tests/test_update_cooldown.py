"""Minimum release age, and telling the user what to actually run (bd harnessed-7zb, harnessed-czo).

COOLDOWN (7zb)
    A release that is hours old has not been vetted by anyone. A compromised or simply broken
    publish is usually yanked within days, so refusing to offer anything younger than a week costs
    nothing and closes that window. Renovate calls this `minimumReleaseAge`.

    This is not hypothetical. Measured against the live catalog on 2026-07-25, two of the five
    bumps `harnessed update` offered would have been withheld: `pulumi 3.254.0` was 2 days old, and
    `ccstatusline 2.2.26` was published the same day it was offered.

    A cooled-off update is NOT a failure. It goes in its own bucket and must not fail `--check` —
    you cannot act on a release you are deliberately waiting for, and a CI job that fails on one
    would be red for a week at a time through no fault of the repo.

AFFECTED STACKS (czo)
    The old post-bump message said "run the capability tests for the affected stacks", naming
    neither the stacks nor the command. Both are computable: a stack lists its recipes flatly, and
    the capability test is `harnessed test <stack> <harness>`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from harnessed import update

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _recipe_dir(tmp_path, name, body):
    d = tmp_path / "catalog" / "recipes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    return d


def _resolver(version, published):
    return lambda backend, name: update.Release(version=version, published=published)


class TestCooldownWithholdsFreshReleases:
    def test_a_release_younger_than_the_window_is_not_offered(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(2)), now=NOW, cooldown_days=7,
        )
        assert not report.stale, "a 2-day-old release must not be in the bump set"
        assert len(report.cooling) == 1

    def test_a_release_older_than_the_window_is_offered(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(30)), now=NOW, cooldown_days=7,
        )
        assert len(report.stale) == 1 and not report.cooling

    @pytest.mark.parametrize("age,expected_bucket", [
        (6.9, "cooling"),
        (7.1, "stale"),
    ])
    def test_the_boundary_is_the_configured_window(self, tmp_path, age, expected_bucket):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(age)), now=NOW, cooldown_days=7,
        )
        assert len(getattr(report, expected_bucket)) == 1

    def test_the_window_is_configurable(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(10)), now=NOW, cooldown_days=30,
        )
        assert report.cooling and not report.stale

    def test_zero_disables_the_cooldown(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(0.1)), now=NOW, cooldown_days=0,
        )
        assert report.stale and not report.cooling

    def test_a_cooling_finding_reports_its_age(self, tmp_path):
        """The user has to decide whether to wait, so the report must say HOW fresh it is."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(2)), now=NOW, cooldown_days=7,
        )
        f = report.cooling[0]
        assert f.latest == "2.0.0"
        assert f.age_days is not None and 1.9 < f.age_days < 2.1

    def test_cooling_never_fails_check(self, tmp_path):
        """You cannot act on a release you are waiting for — failing CI on it would be red for a
        week through no fault of the repo."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(1)), now=NOW, cooldown_days=7,
        )
        assert report.check_exit_code() == 0

    def test_apply_refuses_a_cooling_finding(self, tmp_path):
        """Belt and braces: even handed the cooling bucket directly, nothing is written."""
        body = "name: r\ntools:\n  - npm:x@1.0.0\n"
        d = _recipe_dir(tmp_path, "r", body)
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(1)), now=NOW, cooldown_days=7,
        )
        update.apply(report.cooling)
        assert (d / "recipe.yaml").read_text() == body

    def test_an_undated_release_is_withheld_not_offered(self, tmp_path):
        """If a backend cannot tell us the age, the 7-day guarantee cannot be honoured. Withhold
        and say so rather than offering an unaged bump under a rule that promises otherwise."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", None), now=NOW, cooldown_days=7,
        )
        assert not report.stale
        assert report.unresolved and "age" in report.unresolved[0].error.lower()

    def test_an_undated_release_is_offered_when_the_cooldown_is_off(self, tmp_path):
        """With no cooldown there is no promise to break, so a missing date is not disqualifying."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", None), now=NOW, cooldown_days=0,
        )
        assert len(report.stale) == 1

    def test_a_held_pin_stays_held_regardless_of_age(self, tmp_path):
        """The hold outranks the cooldown — a held pin is never offered whatever its age."""
        d = _recipe_dir(
            tmp_path, "r", "name: r\ntools:\n  - spec: npm:x@1.0.0\n    hold: 'frozen'\n",
        )
        report = update.build_report(
            [d], resolve=_resolver("2.0.0", _ago(90)), now=NOW, cooldown_days=7,
        )
        assert report.held and not report.stale and not report.cooling


class TestPublishDates:
    """Every backend must supply a real date, or the cooldown is unenforceable."""

    def test_npm_reads_the_packument_time_for_the_resolved_version(self):
        import json
        payload = json.dumps({
            "dist-tags": {"latest": "2.2.26"},
            "time": {"2.2.22": "2026-06-16T06:02:08.122Z", "2.2.26": "2026-07-25T07:13:18.627Z"},
        })
        rel = update.resolve_latest("npm", "ccstatusline", fetch=lambda url: payload)
        assert rel.version == "2.2.26"
        assert rel.published == datetime(2026, 7, 25, 7, 13, 18, 627000, tzinfo=timezone.utc)

    def test_npm_asks_for_the_packument_not_the_latest_endpoint(self):
        """`/latest` carries the version but no date — the full packument is the only source of
        `time`, so the URL must not keep the old `/latest` suffix."""
        import json
        seen = {}

        def fetch(url):
            seen["url"] = url
            return json.dumps({"dist-tags": {"latest": "1.0.0"}, "time": {"1.0.0": "2026-01-01T00:00:00Z"}})

        update.resolve_latest("npm", "ccstatusline", fetch=fetch)
        assert seen["url"] == "https://registry.npmjs.org/ccstatusline"

    def test_pypi_reads_the_upload_time(self):
        import json
        payload = json.dumps({
            "info": {"version": "1.6.1"},
            "urls": [{"upload_time_iso_8601": "2026-06-20T10:00:00.000000Z"}],
        })
        rel = update.resolve_latest("pipx", "serena-agent", fetch=lambda url: payload)
        assert rel.version == "1.6.1"
        assert rel.published == datetime(2026, 6, 20, 10, 0, 0, tzinfo=timezone.utc)

    def test_github_reads_published_at(self):
        import json
        payload = json.dumps({"tag_name": "v3.254.0", "published_at": "2026-07-23T15:10:53Z"})
        rel = update.resolve_latest("github", "pulumi/pulumi", fetch=lambda url: payload)
        assert rel.version == "v3.254.0"
        assert rel.published == datetime(2026, 7, 23, 15, 10, 53, tzinfo=timezone.utc)


class TestMiseGetsADateViaItsOwnRegistry:
    """`mise latest` returns a bare version with no date. `mise registry` maps a tool to its
    backend, and the aqua/ubi/github backend IS an owner/repo — so mise itself supplies the GitHub
    repo whose releases carry `published_at`. No hand-maintained tool->repo map."""

    REGISTRY = (
        "esc                           aqua:pulumi/esc asdf:fxsalazar/asdf-esc\n"
        "pulumi                        aqua:pulumi/pulumi asdf:canha/asdf-pulumi\n"
        "kubespy                       aqua:pulumi/kubespy asdf:jfreeland/asdf-kubespy\n"
    )

    def test_the_repo_is_derived_from_the_aqua_backend(self):
        assert update.mise_repo("pulumi", run=lambda cmd: self.REGISTRY) == "pulumi/pulumi"

    def test_the_asdf_plugin_repo_is_never_used(self):
        """`asdf:canha/asdf-pulumi` is the PLUGIN's repo, not pulumi's — its releases would be the
        plugin's, so a version read from it would be nonsense."""
        assert update.mise_repo("pulumi", run=lambda cmd: self.REGISTRY) != "canha/asdf-pulumi"

    def test_an_exact_name_match_is_required(self):
        """`pulumi` must not match the `esc` or `kubespy` rows, which also mention pulumi/."""
        assert update.mise_repo("esc", run=lambda cmd: self.REGISTRY) == "pulumi/esc"

    def test_a_tool_with_no_usable_backend_yields_none(self):
        registry = "weirdtool                     asdf:someone/asdf-weirdtool\n"
        assert update.mise_repo("weirdtool", run=lambda cmd: registry) is None

    def test_a_mise_tool_resolves_version_and_date_through_github(self):
        import json

        def run(cmd):
            return self.REGISTRY

        def fetch(url):
            assert url == "https://api.github.com/repos/pulumi/pulumi/releases/latest"
            return json.dumps({"tag_name": "v3.254.0", "published_at": "2026-07-23T15:10:53Z"})

        rel = update.resolve_latest("mise", "pulumi", fetch=fetch, run=run)
        assert rel.version == "v3.254.0"
        assert rel.published == datetime(2026, 7, 23, 15, 10, 53, tzinfo=timezone.utc)

    def test_an_underivable_tool_surfaces_rather_than_guessing(self):
        """No aqua/ubi/github backend means no date source. Raise so it lands in `unresolved`
        instead of silently falling back to an undated `mise latest`."""
        registry = "weirdtool                     asdf:someone/asdf-weirdtool\n"
        with pytest.raises(update.ResolveError):
            update.resolve_latest("mise", "weirdtool", fetch=lambda url: "{}",
                                  run=lambda cmd: registry)


class TestTagPrefixIsNormalisedToThePinsOwnConvention:
    """Caught by running --check on the live catalog: `pulumi@3.251.0` resolved to `v3.254.0`,
    because routing mise through GitHub returns the TAG and tags carry a `v`. Writing that back
    yields `pulumi@v3.254.0` — a shape the file never used and mise may reject. The bump must keep
    whatever convention the pin already had."""

    def _bump(self, tmp_path, current_spec, latest):
        d = _recipe_dir(tmp_path, "r", f"name: r\ntools:\n  - {current_spec}\n")
        report = update.build_report(
            [d], resolve=_resolver(latest, _ago(30)), now=NOW, cooldown_days=7,
        )
        update.apply(report.stale)
        return (d / "recipe.yaml").read_text()

    def test_a_v_tag_is_stripped_for_an_unprefixed_pin(self, tmp_path):
        assert "pulumi@3.254.0" in self._bump(tmp_path, "pulumi@3.251.0", "v3.254.0")

    def test_the_v_is_not_left_behind(self, tmp_path):
        assert "@v3.254.0" not in self._bump(tmp_path, "pulumi@3.251.0", "v3.254.0")

    def test_a_v_prefixed_pin_keeps_its_v(self, tmp_path):
        """The reverse: a recipe that pins `v6.0.3` should stay v-prefixed."""
        assert "tool@v6.1.0" in self._bump(tmp_path, "tool@v6.0.3", "v6.1.0")

    def test_a_v_is_added_when_the_pin_uses_one_but_the_release_does_not(self, tmp_path):
        assert "tool@v6.1.0" in self._bump(tmp_path, "tool@v6.0.3", "6.1.0")

    def test_the_reported_version_is_the_one_that_will_be_written(self, tmp_path):
        """The report said `3.251.0 -> v3.254.0` while `apply` wrote `3.254.0`. Showing a target
        different from the one that lands makes the preview untrustworthy, so normalise once at
        classification and let the report and the write agree."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - pulumi@3.251.0\n")
        report = update.build_report(
            [d], resolve=_resolver("v3.254.0", _ago(30)), now=NOW, cooldown_days=7,
        )
        assert report.stale[0].latest == "3.254.0"

    def test_a_cooling_finding_is_normalised_too(self, tmp_path):
        """The cooling bucket is a preview of a future bump — same rule applies."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - pulumi@3.251.0\n")
        report = update.build_report(
            [d], resolve=_resolver("v3.254.0", _ago(2)), now=NOW, cooldown_days=7,
        )
        assert report.cooling[0].latest == "3.254.0"

    def test_a_scoped_npm_spec_is_unaffected(self, tmp_path):
        """Normalisation must key off the VERSION, not stray `v`s elsewhere in the spec."""
        out = self._bump(tmp_path, "npm:@vendor/vtool@1.0.0", "1.2.0")
        assert "npm:@vendor/vtool@1.2.0" in out


class TestAffectedStacks:
    """bd harnessed-czo — name the stacks and print the commands."""

    @pytest.fixture
    def catalog(self, tmp_path, monkeypatch):
        stacks = tmp_path / "catalog" / "stacks"
        (stacks / "alpha").mkdir(parents=True)
        (stacks / "alpha" / "stack.yaml").write_text(
            "name: alpha\nrecipes: [serena, pulumi]\nharnesses: [claude]\n"
        )
        (stacks / "beta").mkdir(parents=True)
        (stacks / "beta" / "stack.yaml").write_text(
            "name: beta\nrecipes: [pulumi]\nharnesses: [claude, omp]\n"
        )
        (stacks / "gamma").mkdir(parents=True)
        (stacks / "gamma" / "stack.yaml").write_text("name: gamma\nrecipes: [other]\n")
        monkeypatch.setattr(update.paths, "catalog_roots", lambda: [tmp_path / "catalog"])
        return stacks

    def test_a_bumped_recipe_maps_to_the_stacks_containing_it(self, catalog):
        assert update.affected_stacks(["serena"]) == {"alpha": ["claude"]}

    def test_a_recipe_in_several_stacks_lists_them_all(self, catalog):
        assert sorted(update.affected_stacks(["pulumi"])) == ["alpha", "beta"]

    def test_each_stack_carries_its_declared_harnesses(self, catalog):
        assert update.affected_stacks(["pulumi"])["beta"] == ["claude", "omp"]

    def test_a_stack_with_no_declared_harness_is_still_listed(self, catalog):
        """`harnesses:` is optional. Dropping such a stack would hide a real dependency; the caller
        renders a placeholder instead."""
        assert update.affected_stacks(["other"]) == {"gamma": []}

    def test_a_recipe_in_no_stack_yields_nothing(self, catalog):
        assert update.affected_stacks(["orphan"]) == {}

    def test_verify_commands_are_runnable_text(self, catalog):
        lines = update.verify_commands({"beta": ["claude", "omp"]})
        assert "harnessed build beta claude && harnessed test beta claude" in lines
        assert "harnessed build beta omp && harnessed test beta omp" in lines

    def test_a_stack_without_harnesses_renders_a_placeholder(self, catalog):
        lines = update.verify_commands({"gamma": []})
        assert len(lines) == 1 and "<harness>" in lines[0]
