"""Unit tests for the recipe-authored bash-tests oracle (main-c98).

Covers the PURE, podman-free surface: discovery of `tests/*.sh`, folding an exit code into a
`CapabilityResult(kind=TEST)`, the report-level gating those results feed, and the report rendering.
The live `podman cp` + `podman exec` path (`run_recipe_tests`) is podman-gated and exercised only as
manual acceptance — not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from harnessed import report
from harnessed.capability import (
    TEST,
    CapabilityReport,
    CapabilityResult,
    RecipeTest,
    SecretsSection,
    build_secrets_section,
    discover_recipe_tests,
    fold_test_result,
)
from harnessed.schema import Recipe, load_recipe

CATALOG = Path(__file__).resolve().parents[1] / "catalog" / "recipes"


# --- Discovery (pure) ----------------------------------------------------------------------------


def _recipe_with_tests(tmp_path: Path, name: str, scripts: list[str], others: list[str]) -> Recipe:
    tests_dir = tmp_path / name / "tests"
    tests_dir.mkdir(parents=True)
    for s in scripts + others:
        (tests_dir / s).write_text("#!/usr/bin/env bash\nexit 0\n")
    return Recipe(name=name, root=tmp_path / name)


def test_discover_finds_only_sh_files_sorted(tmp_path):
    recipe = _recipe_with_tests(
        tmp_path, "demo", scripts=["b.sh", "a.sh"], others=["readme.md", "helper.py"]
    )
    found = discover_recipe_tests([recipe])
    assert [t.script for t in found] == ["a.sh", "b.sh"]  # sorted, .sh only
    assert all(t.recipe == "demo" for t in found)
    assert found[0].name == "demo/a.sh"
    assert found[0].tests_dir == tmp_path / "demo" / "tests"


def test_discover_recipe_without_tests_dir_yields_nothing(tmp_path):
    recipe = Recipe(name="bare", root=tmp_path / "bare")
    (tmp_path / "bare").mkdir()
    assert discover_recipe_tests([recipe]) == []


def test_discover_spans_multiple_recipes(tmp_path):
    r1 = _recipe_with_tests(tmp_path, "one", ["x.sh"], [])
    r2 = _recipe_with_tests(tmp_path, "two", ["y.sh"], [])
    names = {t.name for t in discover_recipe_tests([r1, r2])}
    assert names == {"one/x.sh", "two/y.sh"}


def test_discover_finds_shipped_demonstrators():
    """The two proof-adopter recipes actually ship discoverable tests (main-c98 MVP)."""
    rtk = load_recipe(CATALOG / "rtk")
    caveman = load_recipe(CATALOG / "caveman")
    found = {t.name for t in discover_recipe_tests([rtk, caveman])}
    assert "rtk/rtk-runs.sh" in found
    assert "caveman/hook-fires.sh" in found


# --- Folding an exit code into a CapabilityResult (pure) -----------------------------------------

_T = RecipeTest(recipe="demo", tests_dir=Path("/x"), script="t.sh")


def test_fold_pass():
    r = fold_test_result(_T, 0, "all good")
    assert r.kind == TEST
    assert r.name == "demo/t.sh"
    assert r.present is True
    assert r.detail == "exit 0"


def test_fold_failure_carries_exit_and_tail():
    r = fold_test_result(_T, 3, "line one\nassertion failed: rtk missing\n")
    assert r.present is False
    assert r.detail.startswith("exit 3")
    assert "assertion failed: rtk missing" in r.detail


def test_fold_timeout():
    r = fold_test_result(_T, 124, "", timed_out=True)
    assert r.present is False
    assert r.detail == "timeout"


def test_fold_detail_is_truncated():
    r = fold_test_result(_T, 1, "x" * 500)
    assert len(r.detail) <= 120


def test_fold_detail_uses_only_last_line_not_earlier_secrets():
    # Detail must never carry a full transcript — an earlier line (here a fake secret) must not leak.
    output = "TOKEN=sk-supersecret-value\nfinal error line\n"
    r = fold_test_result(_T, 2, output)
    assert "sk-supersecret-value" not in r.detail
    assert "final error line" in r.detail


# --- Gating: TEST results feed the SAME .ok / .exit_code (pure) ----------------------------------


def test_failing_test_turns_report_red():
    rep = CapabilityReport(
        stack="s",
        results=[
            CapabilityResult(name="a", kind="skill", present=True),
            fold_test_result(_T, 0, ""),  # passing test
            fold_test_result(_T, 1, "boom"),  # failing test
        ],
    )
    assert rep.ok is False
    assert rep.exit_code == 1


def test_all_passing_tests_stay_green():
    rep = CapabilityReport(stack="s", results=[fold_test_result(_T, 0, "")])
    assert rep.ok is True
    assert rep.exit_code == 0
    # TEST results serialize with the stable kind string for --json consumers.
    assert rep.to_dict()["results"][0]["kind"] == "test"


# --- Rendering ------------------------------------------------------------------------------------


def test_render_shows_test_pass_and_fail_rows():
    rep = CapabilityReport(
        stack="s",
        results=[fold_test_result(_T, 0, ""), fold_test_result(_T, 1, "boom")],
    )
    md = report.render_markdown(rep)
    assert "| demo/t.sh | test | ✓ passed |" in md
    assert "✗ failed (exit 1: boom)" in md


# --- SecretsSection — pure unit tests ------------------------------------------------------------


class TestSecretsSection:
    """Unit tests for SecretsSection, build_secrets_section, and _render_secrets (no podman)."""

    def test_no_schema_returns_empty_section(self, tmp_path):
        """When proxy_schema_dirs finds nothing, the section says so and items is empty."""
        with patch("harnessed.capability.proxy_schema_dirs", return_value=[]):
            sec = build_secrets_section(tmp_path)
        assert sec.has_schema is False
        assert sec.items == {}
        assert sec.broker_status == "no proxy schema found"
        assert sec.parse_failed is False

    def test_parse_failed_when_modes_returns_none(self, tmp_path):
        """When _varlock_proxy_modes returns None, parse_failed is True and items is None."""
        fake_dir = tmp_path / "schema"
        fake_dir.mkdir()
        with (
            patch("harnessed.capability.proxy_schema_dirs", return_value=[fake_dir]),
            patch("harnessed.capability._varlock_proxy_modes", return_value=None),
            patch("harnessed.capability._varlock_broker_health", return_value="no broker running"),
        ):
            sec = build_secrets_section(tmp_path)
        assert sec.parse_failed is True
        assert sec.items is None
        assert sec.has_schema is True

    def test_items_aggregated_from_modes(self, tmp_path):
        """Items from _varlock_proxy_modes are collected correctly."""
        fake_dir = tmp_path / "schema"
        fake_dir.mkdir()
        modes = {"FOO": "proxied", "BAR": "placeholder"}
        with (
            patch("harnessed.capability.proxy_schema_dirs", return_value=[fake_dir]),
            patch("harnessed.capability._varlock_proxy_modes", return_value=modes),
            patch("harnessed.capability._varlock_broker_health", return_value="no broker running"),
        ):
            sec = build_secrets_section(tmp_path)
        assert sec.items == modes
        assert sec.parse_failed is False

    def test_none_from_modes_stops_aggregation(self, tmp_path):
        """First None from _varlock_proxy_modes marks parse_failed; second dir is never read."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        call_count = 0

        def modes_side_effect(d):
            nonlocal call_count
            call_count += 1
            if d == dir_a:
                return None
            return {"BAR": "proxied"}

        with (
            patch("harnessed.capability.proxy_schema_dirs", return_value=[dir_a, dir_b]),
            patch("harnessed.capability._varlock_proxy_modes", side_effect=modes_side_effect),
            patch("harnessed.capability._varlock_broker_health", return_value="no broker running"),
        ):
            sec = build_secrets_section(tmp_path)
        assert sec.parse_failed is True
        assert call_count == 1  # stopped after first None

    def test_broker_failure_does_not_affect_parse(self, tmp_path):
        """Broker not running is reported in broker_status; the items table is unaffected."""
        fake_dir = tmp_path / "schema"
        fake_dir.mkdir()
        modes = {"KEY": "proxied"}
        with (
            patch("harnessed.capability.proxy_schema_dirs", return_value=[fake_dir]),
            patch("harnessed.capability._varlock_proxy_modes", return_value=modes),
            patch("harnessed.capability._varlock_broker_health", return_value="no broker running"),
        ):
            sec = build_secrets_section(tmp_path)
        assert sec.items == modes
        assert "no broker running" in sec.broker_status

    def test_to_dict_never_contains_values(self, tmp_path):
        """SecretsSection.to_dict only carries names + modes; no secret values."""
        sec = SecretsSection(
            schema_dirs=[tmp_path],
            items={"MY_SECRET": "proxied", "OTHER": "passthrough"},
            broker_status="no broker running",
        )
        d = sec.to_dict()
        assert set(d.keys()) == {"schema_dirs", "items", "broker_status", "parse_failed"}
        # items maps names to modes only
        assert d["items"] == {"MY_SECRET": "proxied", "OTHER": "passthrough"}
        assert d["parse_failed"] is False

    def test_capability_report_to_dict_includes_secrets(self):
        """CapabilityReport.to_dict includes secrets when present."""
        sec = SecretsSection(schema_dirs=[], items={}, broker_status="no proxy schema found")
        rep = CapabilityReport(stack="mystack", results=[], secrets=sec)
        d = rep.to_dict()
        assert "secrets" in d
        assert d["secrets"]["broker_status"] == "no proxy schema found"

    def test_capability_report_to_dict_omits_secrets_when_none(self):
        """CapabilityReport.to_dict omits the secrets key when secrets is None."""
        rep = CapabilityReport(stack="mystack", results=[])
        d = rep.to_dict()
        assert "secrets" not in d

    def test_render_no_schema(self):
        """No proxy schema → section says so, no error."""
        sec = SecretsSection(schema_dirs=[], items={}, broker_status="no proxy schema found")
        rep = CapabilityReport(stack="s", results=[], secrets=sec)
        md = report.render_markdown(rep)
        assert "### Secrets" in md
        assert "no proxy schema found" in md

    def test_render_parse_failed(self, tmp_path):
        """Parse failure → bold warning in the secrets section."""
        sec = SecretsSection(schema_dirs=[tmp_path], items=None, broker_status="no broker running")
        rep = CapabilityReport(stack="s", results=[], secrets=sec)
        md = report.render_markdown(rep)
        assert "### Secrets" in md
        assert "WARNING" in md
        # Must NOT appear as "no items"
        assert "no items" not in md

    def test_render_items_listed(self, tmp_path):
        """Items appear as NAME | mode table rows."""
        sec = SecretsSection(
            schema_dirs=[tmp_path],
            items={"FOO": "proxied", "BAR": "placeholder"},
            broker_status="no broker running",
        )
        rep = CapabilityReport(stack="s", results=[], secrets=sec)
        md = report.render_markdown(rep)
        assert "| FOO | proxied |" in md
        assert "| BAR | placeholder |" in md
        # No secret values
        assert "proxied-value" not in md

    def test_render_no_secrets_section_when_none(self):
        """When secrets is None, no '### Secrets' section is rendered."""
        rep = CapabilityReport(stack="s", results=[])
        md = report.render_markdown(rep)
        assert "### Secrets" not in md

    def test_broker_status_never_exposes_token(self):
        """AC-7: endpointToken, placeholderOverrides, and env values never reach the output.

        Status JSON is shaped like the real `varlock proxy status --format json` row
        (mirrors _status_entry in test_broker_lifecycle.py).
        """
        _TOKEN_SENTINEL = "4f2a9e45-f135-4d47-8284-4f39dcf94551"  # noqa: S105
        _SECRET_SENTINEL = "sk-ant-oat01-THIS-IS-A-RESOLVED-SECRET-VALUE"  # noqa: S105
        _PLACEHOLDER = "vlk_placeholder_PROBE_TOKEN_7db6e07f"
        raw_status = json.dumps([{
            "id": "i0oku",
            "uuid": "8d91df1e-d139-45e4-b751-965f038d0da2",
            "ownerPid": 4242,
            "startedAt": "2026-08-29T10:57:21.059Z",
            "endpointToken": _TOKEN_SENTINEL,
            "schemaFingerprint": "ba1a7bdb",
            "placeholderOverrides": {"PROBE_TOKEN": _PLACEHOLDER},
            "env": {
                "HTTPS_PROXY": "http://127.0.0.1:39443",
                "HTTP_PROXY": "http://127.0.0.1:39443",
                "SSL_CERT_FILE": "/run/harnessed/certs/inst/combined-ca.pem",
                "RESOLVED": _SECRET_SENTINEL,
            },
            "entryPaths": ["/proj"],
        }])
        proc_mock = type("P", (), {"returncode": 0, "stdout": raw_status})()
        # `which` too: without it a runner with no varlock returns "varlock not on PATH" before the
        # status is parsed, and every negative assertion below passes without testing anything.
        with (
            patch("harnessed.launchenv.shutil.which", return_value="/usr/bin/varlock"),
            patch("harnessed.launchenv.subprocess.run", return_value=proc_mock),
        ):
            from harnessed.launchenv import _varlock_broker_health
            result = _varlock_broker_health()
        # Sentinels must never reach output — T-02-07
        assert _TOKEN_SENTINEL not in result
        assert _SECRET_SENTINEL not in result
        assert _PLACEHOLDER not in result
        assert "HTTPS_PROXY" not in result
        assert "HTTP_PROXY" not in result
        assert "SSL_CERT_FILE" not in result
        assert "RESOLVED" not in result
        # Safe fields DO appear
        assert "i0oku" in result
        assert "ba1a7bdb" in result
