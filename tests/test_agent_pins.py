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


class TestShippedManifestsStillLoad:
    def test_every_catalog_agent_validates(self):
        """NC-10, against the real catalog rather than a fixture."""
        from harnessed import paths

        agents = sorted(p.name for p in (paths.harnessed_home() / "catalog" / "agents").iterdir()
                        if (p / "agent.yaml").is_file())
        assert agents, "no agents found — the test is not exercising anything"
        for name in agents:
            load_agent(name)
