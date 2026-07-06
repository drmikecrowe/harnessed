"""Unit tests for the recipe-authored bash-tests oracle (main-c98).

Covers the PURE, podman-free surface: discovery of `tests/*.sh`, folding an exit code into a
`CapabilityResult(kind=TEST)`, the report-level gating those results feed, and the report rendering.
The live `podman cp` + `podman exec` path (`run_recipe_tests`) is podman-gated and exercised only as
manual acceptance — not here.
"""

from __future__ import annotations

from pathlib import Path

from harnessed import report
from harnessed.capability import (
    TEST,
    CapabilityReport,
    CapabilityResult,
    RecipeTest,
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
