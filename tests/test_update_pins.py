"""`harnessed update` — find flagged/outdated pins and offer to bump them (bd harnessed-tfm).

Every download in the catalog is pinned on purpose: `tools:` rejects a floating `@latest`, and
recipe Dockerfiles must pin their downloads. The maintenance cost of that correctness is that pins
rot silently, and until now the only way to notice was a human reading a Dockerfile.

Three rules shape this command, and each has a class below:

  * RESOLVABLE vs OPAQUE — `tools:` is the first-class surface: a mise spec names its backend, so
    the latest version is a registry lookup. install.sh and Dockerfile pins are best-effort text,
    and the hard rule is that an unresolvable pin is REPORTED, never silently skipped. A pin the
    tool quietly drops is worse than no tool: it reads as "everything is current".
  * HELD — bd harnessed-c5t's marker. A held pin is listed informationally, never offered for
    bumping, and never fails `--check`. Skill content is the motivating case (see that bead).
  * --check WRITES NOTHING — it is the CI mode. It exits non-zero on a stale pin and must leave the
    catalog byte-identical, or a CI run would mutate the tree it is validating.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harnessed import update


def _recipe_dir(tmp_path, name, body, *, install_sh=None, dockerfile=None):
    d = tmp_path / "catalog" / "recipes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    if install_sh is not None:
        (d / "install.sh").write_text(install_sh)
    if dockerfile is not None:
        (d / "Dockerfile").write_text(dockerfile)
    return d


def _fake_resolver(table, *, fail=(), age_days=365):
    """A resolver stub. `table` maps (backend, name) -> latest; `fail` names keys that raise.

    Dates default to a year old so the release-age cooldown (bd harnessed-7zb) never interferes —
    these tests are about classification and rewriting, not freshness. The cooldown has its own
    file, where the age is the variable under test.
    """
    published = datetime.now(timezone.utc) - timedelta(days=age_days)

    def resolve(backend, name):
        if (backend, name) in fail:
            raise update.ResolveError(f"registry said no: {name}")
        version = table.get((backend, name))
        return [] if version is None else [update.Release(version=version, published=published)]
    return resolve


class TestPinDiscovery:
    """`tools:` is the resolvable surface — the spec names its own backend."""

    @pytest.mark.parametrize("spec,backend,name,current", [
        ("npm:context-mode@1.0.169", "npm", "context-mode", "1.0.169"),
        ("npm:@agentmemory/mcp@0.9.27", "npm", "@agentmemory/mcp", "0.9.27"),
        ("pipx:serena-agent@1.5.3", "pipx", "serena-agent", "1.5.3"),
        ("github:rtk-ai/rtk@0.43.0", "github", "rtk-ai/rtk", "0.43.0"),
        ("pulumi@3.251.0", "mise", "pulumi", "3.251.0"),
    ])
    def test_every_tools_backend_is_parsed(self, tmp_path, spec, backend, name, current):
        """A scoped npm package (`@agentmemory/mcp@0.9.27`) is the parse that a naive rsplit on '@'
        gets wrong — the version is after the LAST '@', not the first."""
        d = _recipe_dir(tmp_path, "r", f"name: r\ntools:\n  - {spec}\n")
        pins = update.discover_pins(d)
        assert len(pins) == 1
        p = pins[0]
        assert (p.backend, p.name, p.current) == (backend, name, current)
        assert p.spec == spec
        assert p.recipe == "r"
        assert p.file == d / "recipe.yaml"
        assert p.hold is None

    def test_a_held_tools_pin_carries_its_reason(self, tmp_path):
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ntools:\n  - spec: npm:x@1.0.0\n    hold: 'upstream 2.x drops our API'\n",
        )
        assert update.discover_pins(d)[0].hold == "upstream 2.x drops our API"

    def test_a_recipe_with_no_pins_yields_none(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\n")
        assert update.discover_pins(d) == []


class TestOpaquePinsAreReportedNotSkipped:
    """The bead's hard requirement: best-effort surfaces are REPORTED as unresolved."""

    def test_install_cache_is_reported_as_opaque(self, tmp_path):
        """`install.cache` is a synthetic content-cache key ('oak0283bed3-hum1b485648'), not a
        version any registry knows. It is still a PIN, so it must surface."""
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ninstall:\n  script: install.sh\n  cache: 'oak0283bed3'\n",
            install_sh="true\n",
        )
        pins = update.discover_pins(d)
        cache = [p for p in pins if p.backend == "opaque" and "cache" in p.note]
        assert cache, "install.cache must be reported, not silently skipped"
        assert cache[0].current == "oak0283bed3"

    def test_literal_pins_in_install_sh_are_reported(self, tmp_path):
        """The real shape from mikes-universal-setup: a SHA assigned to a shell var, consumed by a
        pinned archive fetch. Not machine-resolvable — but it must not vanish."""
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ninstall:\n  script: install.sh\n",
            install_sh=(
                "set -euo pipefail\n"
                "OAKOSS_SHA=0283bed313563d5677a0838f4bf921b03296cf6c\n"
                "TOOL_REF=\"v6.0.3\"\n"
            ),
        )
        found = {p.current for p in update.discover_pins(d) if p.backend == "opaque"}
        assert "0283bed313563d5677a0838f4bf921b03296cf6c" in found
        assert "v6.0.3" in found

    def test_literal_pins_in_a_dockerfile_are_reported(self, tmp_path):
        d = _recipe_dir(
            tmp_path, "r", "name: r\n",
            dockerfile="FROM base\nARG FOO_REF=v1.2.3\nRUN echo $FOO_REF\n",
        )
        assert any(p.current == "v1.2.3" for p in update.discover_pins(d))

    def test_opaque_pins_never_resolve(self, tmp_path):
        """An opaque pin has no backend to ask, so it lands in `unresolved` with a reason — it is
        never reported as up-to-date, which would be a lie."""
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ninstall:\n  script: install.sh\n  cache: 'abc123'\n",
            install_sh="true\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({}))
        assert report.unresolved
        assert not report.stale and not report.current
        assert all(f.error for f in report.unresolved)


class TestStaleness:
    def test_a_newer_upstream_is_stale(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"}))
        assert len(report.stale) == 1
        f = report.stale[0]
        assert (f.pin.current, f.latest) == ("1.0.0", "1.2.0")

    def test_an_equal_version_is_current(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.2.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"}))
        assert not report.stale and len(report.current) == 1

    def test_a_locally_newer_pin_is_not_stale(self, tmp_path):
        """A pin AHEAD of what the registry reports (a yanked release, a prerelease we chose) must
        not be offered as a 'bump' that silently downgrades."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@2.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.9.0"}))
        assert not report.stale

    @pytest.mark.parametrize("a,b", [
        ("1.9.0", "1.10.0"),    # numeric, not lexicographic — the classic ordering bug
        ("v1.2.3", "v1.2.4"),   # a leading v must not change the ordering
        ("1.2.3", "1.2.3.1"),
        ("1.0.0-rc.1", "1.0.0"),  # a release outranks its own prerelease
    ])
    def test_version_ordering(self, a, b):
        assert update.version_key(a) < update.version_key(b), f"{a} should sort below {b}"

    def test_a_resolver_failure_is_unresolved_not_current(self, tmp_path):
        """A registry timeout must never read as 'up to date'."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report(
            [d], resolve=_fake_resolver({}, fail=[("npm", "x")]),
        )
        assert not report.current and not report.stale
        assert len(report.unresolved) == 1 and "registry said no" in report.unresolved[0].error

    def test_an_unknown_latest_is_unresolved(self, tmp_path):
        """A resolver returning None (package absent) is a reportable gap, not silence."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({}))
        assert len(report.unresolved) == 1


class TestHeldPinsAreInformationalOnly:
    """bd harnessed-c5t's marker, honoured. This is the whole reason the marker exists."""

    def test_a_stale_held_tools_pin_is_listed_but_not_offered(self, tmp_path):
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ntools:\n  - spec: npm:x@1.0.0\n    hold: 'pinned deliberately'\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "9.9.9"}))
        assert not report.stale, "a held pin must never enter the bump set"
        assert len(report.held) == 1
        f = report.held[0]
        assert f.latest == "9.9.9", "the newer ref is still LISTED — informational, not hidden"
        assert f.pin.hold == "pinned deliberately"

    def test_install_hold_holds_the_pins_behind_that_script(self, tmp_path):
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ninstall:\n  script: install.sh\n  cache: 'oak0283bed3'\n"
            "  hold: 'skill content: no scanner vets it'\n",
            install_sh="OAKOSS_SHA=0283bed313563d5677a0838f4bf921b03296cf6c\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({}))
        assert report.held, "install.hold must mark the script's pins held"
        assert all(f.pin.hold for f in report.held)
        assert not report.unresolved, (
            "a HELD opaque pin is held, not unresolved — nobody is being asked to resolve it"
        )

    def test_check_ignores_held_pins(self, tmp_path):
        """CI must stay green on a deliberately-frozen pin, or the hold is worthless."""
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ntools:\n  - spec: npm:x@1.0.0\n    hold: 'frozen'\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "9.9.9"}))
        assert report.check_exit_code() == 0


class TestCheckMode:
    def test_check_exits_non_zero_on_a_stale_pin(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "2.0.0"}))
        assert report.check_exit_code() != 0

    def test_check_exits_zero_when_everything_is_current(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.0.0"}))
        assert report.check_exit_code() == 0

    def test_unresolved_alone_does_not_fail_check(self, tmp_path):
        """Every recipe with a Dockerfile pin has an unresolvable pin. Failing on those would make
        CI permanently red and teach everyone to ignore it — they are reported, not fatal."""
        d = _recipe_dir(
            tmp_path, "r", "name: r\n",
            dockerfile="FROM base\nARG REF=v1.2.3\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({}))
        assert report.unresolved and report.check_exit_code() == 0


class TestRewrite:
    """On accept, the pin is rewritten so a subsequent build picks up the new version."""

    def test_accept_rewrites_the_pin_in_place(self, tmp_path):
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"}))
        update.apply(report.stale)
        assert "npm:x@1.2.0" in (d / "recipe.yaml").read_text()
        assert "npm:x@1.0.0" not in (d / "recipe.yaml").read_text()

    def test_the_rewritten_recipe_still_loads_and_reports_the_new_pin(self, tmp_path):
        """The acceptance criterion is 'a subsequent build picks up the new version' — so the file
        must still parse, and re-reading it must show the bump."""
        d = _recipe_dir(tmp_path, "r", "name: r\ntools:\n  - npm:x@1.0.0\n")
        update.apply(update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"})).stale)
        assert update.discover_pins(d)[0].current == "1.2.0"

    def test_comments_and_surrounding_fields_survive_the_rewrite(self, tmp_path):
        """Catalog recipes are heavily commented — the comments carry the WHY. A rewrite that
        strips them destroys more than it fixes, so the round-trip loader is mandatory."""
        body = (
            "# leading file comment\n"
            "name: r\n"
            "description: \"a recipe\"\n"
            "\n"
            "# why this tool is here\n"
            "tools:\n"
            "  - npm:x@1.0.0   # trailing note\n"
            "\n"
            "egress:\n"
            "  - example.com\n"
        )
        d = _recipe_dir(tmp_path, "r", body)
        update.apply(update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"})).stale)
        after = (d / "recipe.yaml").read_text()
        assert "# leading file comment" in after
        assert "# why this tool is here" in after
        assert "# trailing note" in after
        assert "example.com" in after
        assert "npm:x@1.2.0" in after

    def test_the_rewrite_touches_only_the_pin_line(self, tmp_path):
        """Caught by running the real command: ruamel re-wraps long scalars at its default 80-col
        width, so bumping one pin also reflowed every long `description:` in the file. A pin bump
        must produce a ONE-LINE diff — anything else buries the change under noise and makes the
        rewrite untrustworthy for a reviewer."""
        long_desc = (
            "Serena — LSP-backed semantic code intelligence (symbol retrieval, editing, "
            "refactoring, references) over the project via a stdio MCP server."
        )
        body = (
            f"name: r\ndescription: {long_desc}\n"
            "tools:\n  - npm:x@1.0.0\n"
        )
        d = _recipe_dir(tmp_path, "r", body)
        update.apply(update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"})).stale)
        before_lines = body.splitlines()
        after_lines = (d / "recipe.yaml").read_text().splitlines()
        changed = [
            (a, b) for a, b in zip(before_lines, after_lines) if a != b
        ]
        assert len(before_lines) == len(after_lines), (
            f"line count changed — the file was reflowed:\n{after_lines}"
        )
        assert len(changed) == 1 and "1.2.0" in changed[0][1], f"unexpected edits: {changed}"

    def test_the_mapping_form_is_rewritten_in_place_keeping_its_hold(self, tmp_path):
        """A held pin is never auto-bumped, but `apply` is also reachable from an explicit
        single-pin bump — rewriting the mapping form must not flatten it back to a string and
        silently drop the hold."""
        d = _recipe_dir(
            tmp_path, "r",
            "name: r\ntools:\n  - spec: npm:x@1.0.0\n    hold: 'frozen'\n",
        )
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "1.2.0"}))
        update.apply(report.held)
        after = (d / "recipe.yaml").read_text()
        assert "npm:x@1.2.0" in after and "frozen" in after
        assert update.discover_pins(d)[0].hold == "frozen"

    def test_apply_never_touches_an_opaque_pin(self, tmp_path):
        """A best-effort text pin has no safe automated rewrite — refusing is the correct answer."""
        before = "name: r\ninstall:\n  script: install.sh\n  cache: 'abc123'\n"
        d = _recipe_dir(tmp_path, "r", before, install_sh="true\n")
        report = update.build_report([d], resolve=_fake_resolver({}))
        update.apply(report.unresolved)
        assert (d / "recipe.yaml").read_text() == before

    def test_check_mode_writes_nothing(self, tmp_path):
        """The explicit acceptance criterion. Building a report must be side-effect free — only an
        explicit `apply` writes."""
        body = "name: r\ntools:\n  - npm:x@1.0.0\n"
        d = _recipe_dir(tmp_path, "r", body)
        before = (d / "recipe.yaml").read_bytes()
        report = update.build_report([d], resolve=_fake_resolver({("npm", "x"): "2.0.0"}))
        assert report.check_exit_code() != 0
        assert (d / "recipe.yaml").read_bytes() == before


class TestResolvers:
    """URL/command construction per backend, with the network stubbed."""

    # Per-backend URL and payload handling now lives in test_update_cooldown.py, because each
    # resolver must return a publish DATE and the date is what those tests pin down. Kept here:
    # the two assertions that are about resolution itself rather than about freshness.

    def test_a_scoped_npm_package_keeps_its_slash_unescaped(self):
        """`@scope/name` is one path segment pair in the registry API — percent-encoding the slash
        404s."""
        seen = {}

        def fetch(url):
            seen["url"] = url
            return json.dumps({
                "dist-tags": {"latest": "0.9.28"},
                "time": {"0.9.28": "2026-01-01T00:00:00Z"},
            })

        update.resolve_releases("npm", "@agentmemory/mcp", fetch=fetch)
        assert seen["url"] == "https://registry.npmjs.org/@agentmemory/mcp"

    def test_a_malformed_payload_raises_resolve_error(self):
        """A registry returning something unexpected must surface as unresolved, not crash the
        whole run or be read as 'no newer version'."""
        with pytest.raises(update.ResolveError):
            update.resolve_releases("npm", "x", fetch=lambda url: "not json")


class TestCatalogSweep:
    """The command runs over the real catalog — discovery must survive every recipe we ship."""

    def test_every_catalog_recipe_discovers_without_error(self):
        from harnessed import paths
        roots = [r / "recipes" for r in paths.catalog_roots()]
        seen = 0
        for root in roots:
            if not root.is_dir():
                continue
            for manifest in root.rglob("recipe.yaml"):
                update.discover_pins(manifest.parent)
                seen += 1
        assert seen > 0, "the catalog sweep found no recipes — discovery is not being exercised"

    def test_the_skill_hold_recipe_reports_held_not_stale(self):
        """End-to-end against the real marker: mikes-universal-setup's install.hold must keep its
        SHA pins out of the bump set."""
        from harnessed import paths
        d = paths.find_in_catalog("recipes", "mikes-universal-setup")
        report = update.build_report([d], resolve=_fake_resolver({}))
        assert report.held, "mikes-universal-setup declares install.hold — its pins must be held"
        assert not any(f.pin.hold is None for f in report.held)
        assert report.check_exit_code() == 0
