"""A7 — agent manifests own their pins, and `harnessed update` can see them.

The spec is `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §Phase A/A7 (D7 for `unpinnable:`).

These tests exist because A7 introduces the first place in the catalog where a pin can be declared
in three different shapes — a bare scalar, a `{value, spec?, hold?}` mapping, and a top-level
`unpinnable:` entry that is deliberately NOT a pin at all. Each shape has a different obligation at
the build boundary, and two of the three are new. What is being defended:

  * a mapping-form pin must reach `podman build` as its VALUE, never as its dict (the old reader
    stringified whatever it was given, so a dict would have shipped as `--build-arg NAME={'value':
    '1.2.3'}` on a green build rather than failing);
  * an `unpinnable:` entry must reach the build as NOTHING — it names an ARG that does not exist;
  * `--check` must not go red over an agent that is unpinnable by nature, or it is red forever.
"""

import re
from pathlib import Path

import pytest

from harnessed.schema import SchemaError, load_agent
from harnessed.launcher import _agent_build_arg_flags
from harnessed import update as pinupdate


def _write(tmp_path, name, body):
    d = tmp_path / "agents" / name
    d.mkdir(parents=True)
    (d / "agent.yaml").write_text(body)
    return d


_HEAD = "harness: omp\nimage: harnessed-omp\n"


class TestBuildArgShapes:
    def test_scalar_pin_still_loads(self, tmp_path):
        """NC-10: the shape every agent.yaml uses today must survive untouched."""
        _write(tmp_path, "omp", _HEAD + 'build_args:\n  OMP_VERSION: "16.4.6"\n')
        assert load_agent("omp", root=tmp_path).build_args == {"OMP_VERSION": "16.4.6"}

    @pytest.mark.parametrize("scalar", ["", " null", ' ""', " '   '", " true"])
    def test_a_scalar_with_no_version_is_an_error(self, tmp_path, scalar):
        """The scalar branch is held to the mapping branch's standard, because they are one rule.

        Missed on the first pass and caught in review of PR #334: bare `OMP_VERSION:` is YAML null,
        `str(None)` is `"None"`, and it reached the argv as `--build-arg OMP_VERSION=None`. Nothing
        downstream catches that any more — the Dockerfile ARGs no longer carry defaults, which is
        the whole point of A1.
        """
        _write(tmp_path, "omp", _HEAD + f"build_args:\n  OMP_VERSION:{scalar}\n")
        with pytest.raises(SchemaError, match="OMP_VERSION"):
            load_agent("omp", root=tmp_path)

    def test_mapping_pin_exposes_value_not_the_mapping(self, tmp_path):
        _write(tmp_path, "omp", _HEAD + (
            "build_args:\n"
            '  OMP_VERSION: { value: "17.2.11", spec: "github:can1357/oh-my-pi" }\n'
        ))
        agent = load_agent("omp", root=tmp_path)
        assert agent.build_args == {"OMP_VERSION": "17.2.11"}
        assert agent.build_arg_specs == {"OMP_VERSION": "github:can1357/oh-my-pi"}

    def test_mapping_pin_without_value_is_an_error(self, tmp_path):
        _write(tmp_path, "omp", _HEAD + 'build_args:\n  OMP_VERSION: { spec: "github:a/b" }\n')
        with pytest.raises(SchemaError, match="value"):
            load_agent("omp", root=tmp_path)

    def test_hold_carries_its_reason(self, tmp_path):
        _write(tmp_path, "omp", _HEAD + (
            'build_args:\n  OMP_VERSION: { value: "16.4.6", hold: "unqueryable: names no upstream" }\n'
        ))
        agent = load_agent("omp", root=tmp_path)
        assert agent.build_arg_holds["OMP_VERSION"].startswith("unqueryable")

    @pytest.mark.parametrize("hold", ['hold: ""', "hold: null"])
    def test_empty_hold_reason_is_an_error(self, tmp_path, hold):
        """A hold with no reason is the shape that turns `hold:` into an unaudited escape hatch."""
        _write(tmp_path, "omp", _HEAD + f'build_args:\n  OMP_VERSION: {{ value: "16.4.6", {hold} }}\n')
        with pytest.raises(SchemaError, match="hold"):
            load_agent("omp", root=tmp_path)

    def test_hold_does_not_license_a_missing_value(self, tmp_path):
        """Mirrors the `tools:` rule (schema.py) — a hold freezes a pin, it does not replace one."""
        _write(tmp_path, "omp", _HEAD + 'build_args:\n  OMP_VERSION: { hold: "because" }\n')
        with pytest.raises(SchemaError, match="value"):
            load_agent("omp", root=tmp_path)

    def test_unpinnable_inside_build_args_is_rejected(self, tmp_path):
        """D7 moved it to the top level; accepting both spellings would give one concept two homes."""
        _write(tmp_path, "omp", _HEAD + 'build_args:\n  X_VERSION: { unpinnable: "no selector" }\n')
        with pytest.raises(SchemaError, match="unpinnable"):
            load_agent("omp", root=tmp_path)


class TestUnpinnableField:
    def test_reason_is_exposed(self, tmp_path):
        _write(tmp_path, "antigravity", _HEAD + 'unpinnable:\n  AGY_VERSION: "no version selector"\n')
        agent = load_agent("antigravity", root=tmp_path)
        assert agent.unpinnable == {"AGY_VERSION": "no version selector"}

    def test_it_is_not_a_build_arg(self, tmp_path):
        _write(tmp_path, "antigravity", _HEAD + 'unpinnable:\n  AGY_VERSION: "no version selector"\n')
        assert load_agent("antigravity", root=tmp_path).build_args == {}

    @pytest.mark.parametrize("reason", ['""', "null"])
    def test_empty_reason_is_an_error(self, tmp_path, reason):
        _write(tmp_path, "antigravity", _HEAD + f"unpinnable:\n  AGY_VERSION: {reason}\n")
        with pytest.raises(SchemaError, match="unpinnable"):
            load_agent("antigravity", root=tmp_path)

    @pytest.mark.parametrize("key", ["agy", "Agy_Version", "AGY-VERSION", "1AGY"])
    def test_key_must_use_the_build_arg_namespace(self, tmp_path, key):
        """D7 §namespace: one namespace, so 'declared in both' is a reachable rule, not a vacuous one."""
        _write(tmp_path, "antigravity", _HEAD + f'unpinnable:\n  {key}: "reason"\n')
        with pytest.raises(SchemaError, match="unpinnable"):
            load_agent("antigravity", root=tmp_path)

    def test_same_key_in_build_args_and_unpinnable_is_an_error(self, tmp_path):
        _write(tmp_path, "omp", _HEAD + (
            'build_args:\n  OMP_VERSION: "16.4.6"\n'
            'unpinnable:\n  OMP_VERSION: "no selector"\n'
        ))
        with pytest.raises(SchemaError, match="OMP_VERSION"):
            load_agent("omp", root=tmp_path)

    def test_the_same_key_in_two_agents_is_fine(self, tmp_path):
        """Keys are agent-scoped — nothing merges across manifests, so this is not a collision."""
        _write(tmp_path, "a1", _HEAD + 'unpinnable:\n  CLI_VERSION: "reason one"\n')
        _write(tmp_path, "a2", _HEAD + 'unpinnable:\n  CLI_VERSION: "reason two"\n')
        assert load_agent("a1", root=tmp_path).unpinnable["CLI_VERSION"] == "reason one"
        assert load_agent("a2", root=tmp_path).unpinnable["CLI_VERSION"] == "reason two"


class TestBuildArgvBoundary:
    """What actually reaches `podman build`. The schema is not the boundary — this is."""

    def test_mapping_form_reaches_the_argv_as_its_value(self, tmp_path):
        _write(tmp_path, "omp", _HEAD + (
            'build_args:\n  OMP_VERSION: { value: "17.2.11", spec: "github:can1357/oh-my-pi" }\n'
        ))
        flags = _agent_build_arg_flags(load_agent("omp", root=tmp_path))
        assert flags == ["--build-arg", "OMP_VERSION=17.2.11"]

    def test_no_dict_ever_leaks_into_the_argv(self, tmp_path):
        """The old reader stringified anything; a dict would have shipped silently on a green build."""
        _write(tmp_path, "omp", _HEAD + 'build_args:\n  OMP_VERSION: { value: "17.2.11" }\n')
        flags = _agent_build_arg_flags(load_agent("omp", root=tmp_path))
        assert not any("{" in f or "'value'" in f for f in flags)

    def test_an_unpinnable_entry_contributes_no_flag_at_all(self, tmp_path):
        """The absence IS the assertion: AGY_VERSION names no ARG, so passing it would fail the build."""
        _write(tmp_path, "antigravity", _HEAD + (
            'unpinnable:\n  AGY_VERSION: "installer offers no version selector"\n'
        ))
        assert _agent_build_arg_flags(load_agent("antigravity", root=tmp_path)) == []


class TestUpdateSeesAgents:
    def _resolve(self, _backend, _name):
        return [pinupdate.Release(version="17.2.11", published=None)]

    def test_a_spec_bearing_pin_is_discovered_and_offered(self, tmp_path):
        d = _write(tmp_path, "omp", _HEAD + (
            'build_args:\n  OMP_VERSION: { value: "16.4.6", spec: "github:can1357/oh-my-pi" }\n'
        ))
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        assert [f.pin.current for f in report.stale] == ["16.4.6"]
        assert report.stale[0].latest == "17.2.11"

    def test_a_held_pin_is_listed_but_never_offered(self, tmp_path):
        d = _write(tmp_path, "omp", _HEAD + (
            "build_args:\n"
            '  OMP_VERSION: { value: "16.4.6", spec: "github:can1357/oh-my-pi", hold: "pinned to v16 by choice" }\n'
        ))
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        assert not report.stale
        assert [f.pin.current for f in report.held] == ["16.4.6"]

    def test_a_pin_with_no_spec_is_unresolved_not_invented(self, tmp_path):
        """No `spec:` means no upstream to query. It must be reported, not silently dropped."""
        d = _write(tmp_path, "claude", _HEAD + 'build_args:\n  CLAUDE_VERSION: "2.1.88"\n')
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        assert [f.pin.current for f in report.unresolved] == ["2.1.88"]

    def test_an_unpinnable_agent_reports_under_its_own_status(self, tmp_path):
        d = _write(tmp_path, "antigravity", _HEAD + (
            'unpinnable:\n  AGY_VERSION: "installer offers no version selector"\n'
        ))
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        assert [f.pin.key for f in report.unpinnable] == ["AGY_VERSION"]
        assert not report.unresolved and not report.stale and not report.held

    def test_the_report_identifies_agent_and_key(self, tmp_path):
        d = _write(tmp_path, "antigravity", _HEAD + 'unpinnable:\n  AGY_VERSION: "no selector"\n')
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        pin = report.unpinnable[0].pin
        assert (pin.recipe, pin.key) == ("antigravity", "AGY_VERSION")

    def test_check_stays_green_when_the_only_finding_is_unpinnable(self, tmp_path):
        """An UNPINNABLE agent is permanently unpinnable — failing --check would be red forever,
        which is the argument check_exit_code's own docstring already makes for unresolved pins."""
        d = _write(tmp_path, "antigravity", _HEAD + 'unpinnable:\n  AGY_VERSION: "no selector"\n')
        report = pinupdate.build_report(
            [], agent_dirs=[d], resolve=self._resolve, minimum_release_age_minutes=0,
        )
        assert report.check_exit_code() == 0


class TestApplyWritesAgentPins:
    """The round trip, not just the report.

    Missed on the first pass and caught in review of PR #334. Every A7 acceptance criterion
    described a STATE ("the pin lives in agent.yaml", "update resolves agent pins"), and none
    described the round trip report -> apply -> file changed. So `update` grew the ability to OFFER
    an agent bump it had no ability to WRITE, and every state-shaped test passed.
    """

    def _findings(self, agent_dir, latest="17.2.11"):
        return pinupdate.build_report(
            [], agent_dirs=[agent_dir],
            resolve=lambda _b, _n: [pinupdate.Release(version=latest, published=None)],
            minimum_release_age_minutes=0,
        ).stale

    def test_a_mapping_form_pin_is_actually_rewritten(self, tmp_path):
        d = _write(tmp_path, "omp", _HEAD + (
            'build_args:\n'
            '  OMP_VERSION: { value: "16.4.6", spec: "github:can1357/oh-my-pi" }\n'
        ))
        applied = pinupdate.apply(self._findings(d))
        assert len(applied) == 1
        assert '17.2.11' in (d / "agent.yaml").read_text()
        assert load_agent("omp", root=tmp_path).build_args == {"OMP_VERSION": "17.2.11"}

    def test_the_rewrite_keeps_the_spec_and_its_comments(self, tmp_path):
        """A bump must be a one-line diff, or a reviewer cannot see what changed."""
        d = _write(tmp_path, "omp", _HEAD + (
            "# why this pin exists\n"
            'build_args:\n'
            '  OMP_VERSION: { value: "16.4.6", spec: "github:can1357/oh-my-pi" }\n'
        ))
        pinupdate.apply(self._findings(d))
        text = (d / "agent.yaml").read_text()
        assert "# why this pin exists" in text
        assert "github:can1357/oh-my-pi" in text

    def test_an_explicit_bump_of_a_held_pin_keeps_its_hold(self, tmp_path):
        """`hold` blocks the OFFER, not the WRITE — `apply` is also reachable from an explicit
        single-pin bump, so a held pin handed to it is rewritten deliberately. The obligation is
        that the rewrite must not flatten the mapping and drop the hold on the way through. This
        mirrors `test_update_pins.py::test_the_mapping_form_is_rewritten_in_place_keeping_its_hold`
        for recipes; the agent rewriter is a different function and inherits none of its guarantees.
        """
        d = _write(tmp_path, "omp", _HEAD + (
            "build_args:\n"
            '  OMP_VERSION: { value: "16.4.6", spec: "github:can1357/oh-my-pi", hold: "v16 by choice" }\n'
        ))
        report = pinupdate.build_report(
            [], agent_dirs=[d],
            resolve=lambda _b, _n: [pinupdate.Release(version="17.2.11", published=None)],
            minimum_release_age_minutes=0,
        )
        assert not report.stale, "a held pin must never be OFFERED"
        pinupdate.apply(report.held)
        agent = load_agent("omp", root=tmp_path)
        assert agent.build_args == {"OMP_VERSION": "17.2.11"}
        assert agent.build_arg_holds["OMP_VERSION"] == "v16 by choice"
        assert agent.build_arg_specs["OMP_VERSION"] == "github:can1357/oh-my-pi"


class TestShippedManifestsStillLoad:
    def test_every_catalog_agent_validates(self):
        """NC-10, against THIS REPOSITORY's catalog rather than a fixture.

        The root is resolved from this file, not from `paths.catalog_roots()`. Going through the
        roots would put the developer's `~/.config/harnessed/catalog` overlay first — so on a
        machine with a populated overlay, a broken shipped manifest could sail through while the
        test validated somebody's local copy instead. That is the exact inverse of the job.
        """
        repo_catalog = Path(__file__).resolve().parent.parent / "catalog"
        agents_dir = repo_catalog / "agents"
        names = sorted(p.name for p in agents_dir.iterdir() if (p / "agent.yaml").is_file())
        assert names, f"no agents found under {agents_dir} — the test is not exercising anything"
        for name in names:
            load_agent(name, root=repo_catalog)


_REPO_CATALOG = Path(__file__).resolve().parent.parent / "catalog"
# A three-part version and nothing else. `stable`/`latest` are CHANNEL POINTERS: the installer
# accepts them and they MOVE — both were measured advancing within a single day (2026-08-12).
# Pinning one would be a floating acquisition behind a manifest that reads as pinned, which is the
# defect this epic exists to remove (plan REVISION 15). The pinned version itself is owned by
# catalog/agents/claude/agent.yaml and deliberately not repeated here.
_THREE_PART_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-\S+)?$")


class TestA3ClaudeCarriesItsPin:
    """A3 — the claude harness CLI is acquired at a declared version, not at whatever ships today.

    Reads THIS repository's catalog, not `paths.catalog_roots()`, for the reason
    `TestShippedManifestsStillLoad` gives: the roots would put a developer's personal overlay first
    and validate somebody's local copy instead of the shipped one.
    """

    @property
    def _agent(self):
        return load_agent("claude", root=_REPO_CATALOG)

    def test_the_version_reaches_the_build_as_a_build_arg(self):
        """Scenario 1: the pin is DATA in the manifest, and it becomes `--build-arg`.

        The invariant is the WIRING — whatever the manifest declares is what the build receives —
        so the declared value is read, never hardcoded. Adversarial review of 03d7a65 raised this:
        pinning the literal here meant a routine `harnessed update` bump failed the test for the
        wrong reason, reporting a broken pipeline when only the version had changed.
        """
        agent = self._agent
        declared = agent.build_args["CLAUDE_VERSION"]
        assert set(agent.build_args) == {"CLAUDE_VERSION"}
        assert _agent_build_arg_flags(agent) == ["--build-arg", f"CLAUDE_VERSION={declared}"]

    def test_the_pinned_value_is_a_version_and_never_a_channel_pointer(self):
        """Scenario 8: the constraint REVISION 15 added — resolve a channel ONCE, pin the literal.

        Asserted rather than merely intended: `stable` would satisfy the installer and silently
        reintroduce the floating install.
        """
        value = self._agent.build_args["CLAUDE_VERSION"]
        assert value not in ("stable", "latest")
        assert _THREE_PART_VERSION.match(value), f"not a pinned version: {value!r}"

    def test_the_pin_is_held_and_carries_no_resolver_spec(self):
        """Scenario 2: pinnable but not resolvable, so `update` holds it instead of querying."""
        assert "CLAUDE_VERSION" in self._agent.build_arg_holds
        assert self._agent.build_arg_holds["CLAUDE_VERSION"].strip()
        assert "CLAUDE_VERSION" not in self._agent.build_arg_specs

    def test_the_hold_reason_gives_the_true_reason_not_the_disproven_one(self):
        """Scenario 2a: REVISION 15's whole lesson — the OLD reason was present, well-formed, false.

        So presence is not the property under test; content is. The disproven claim was that
        `downloads.claude.ai` publishes only `latest`. It publishes `stable` too, and the real
        reason the pin is unresolvable is that no resolver BACKEND can query a vendor download host.

        Limit, stated where the claim is made: this catches a reason that reproduces the specific
        falsehood REVISION 15 corrected. It cannot decide truth in general.
        """
        reason = self._agent.build_arg_holds["CLAUDE_VERSION"].lower()
        assert "only `latest`" not in reason and "only latest" not in reason
        assert "backend" in reason or "resolver" in reason

    def test_a_held_pin_is_not_an_unpinnable_one(self):
        """Scenario 3: D7 keeps these two states distinct. claude is held; antigravity is conceded.

        Collapsing them would let a pinnable tool hide in the conceded-exception list forever.
        """
        assert "CLAUDE_VERSION" not in self._agent.unpinnable

    def test_update_reports_the_pin_as_opaque_rather_than_guessing(self):
        """Scenario 4: `harnessed update` SEES it, and says it cannot query it — never invents one."""
        pins = pinupdate.discover_agent_pins(_REPO_CATALOG / "agents" / "claude")
        pin = next(p for p in pins if p.key == "CLAUDE_VERSION")
        assert pin.current == self._agent.build_args["CLAUDE_VERSION"]
        assert pin.backend == "opaque"
        assert not pin.resolvable
