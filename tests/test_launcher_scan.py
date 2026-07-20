"""`harnessed scan` dispatch and argument binding (bd main-pv5).

Two bugs fixed here, covered separately:

* `main()`'s shorthand-vs-subcommand dispatch (`_COMMANDS`) didn't know about `scan`, so a bare
  `harnessed scan` (or `harnessed scan <stack> [harness]`) got silently rewritten into
  `harnessed launch scan ...` — `launch`'s STACK/HARNESS positionals then bound to the wrong
  values (`TestMainDispatch`).
* `scan` itself: STACK is required, HARNESS is optional and fans out to every supported harness
  when omitted (mirrors `build`'s `<stack> [harness]` shape) — covered by `TestScanCommand`.
"""

import re
import sys

import pytest
from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Strip ANSI color codes and collapse whitespace so usage-text assertions are stable across
    TTY vs. non-interactive (CI) rendering."""
    return " ".join(_ANSI.sub("", output).split())


class TestMainDispatch:
    """`main()` rewrites an unrecognized first token into `launch <token> ...` — `scan` must be
    recognized as a real subcommand and passed through untouched."""

    def test_scan_is_dispatched_as_a_subcommand_not_rewritten_to_launch(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(launcher, "app", lambda: captured.setdefault("argv", list(sys.argv)))
        monkeypatch.setattr(sys, "argv", ["harnessed", "scan", "mystack"])
        launcher.main()
        assert captured["argv"] == ["harnessed", "scan", "mystack"]

    def test_bare_scan_is_dispatched_as_a_subcommand_not_rewritten_to_launch(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(launcher, "app", lambda: captured.setdefault("argv", list(sys.argv)))
        monkeypatch.setattr(sys, "argv", ["harnessed", "scan"])
        launcher.main()
        assert captured["argv"] == ["harnessed", "scan"]

    def test_unrecognized_token_still_shorthands_to_launch(self, monkeypatch):
        """Regression guard: fixing `scan`'s dispatch must not disturb the `harnessed <stack>
        [project]` shorthand the README documents for genuinely unknown first tokens."""
        captured = {}
        monkeypatch.setattr(launcher, "app", lambda: captured.setdefault("argv", list(sys.argv)))
        monkeypatch.setattr(sys, "argv", ["harnessed", "my-stack", "claude"])
        launcher.main()
        assert captured["argv"] == ["harnessed", "launch", "my-stack", "claude"]


@pytest.fixture
def stack(monkeypatch, tmp_path):
    """A real catalog stack (via the user overlay) named 'demo', so `scan`'s stack-existence
    check passes without touching the repo catalog."""
    xdg = tmp_path / "xdg"
    stack_dir = xdg / "harnessed" / "catalog" / "stacks" / "demo"
    stack_dir.mkdir(parents=True)
    (stack_dir / "stack.yaml").write_text("name: demo\nrecipes: []\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return "demo"


@pytest.fixture
def scanned(monkeypatch):
    """Record every image `scan` hands to `_scan_image`, doing no real podman/network work."""
    calls: list[str] = []

    def fake_scan_image(rt, run_env, image):
        calls.append(image)
        return True

    monkeypatch.setattr(launcher, "_scan_image", fake_scan_image)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    return calls


def _mark_built(monkeypatch, built_pairs: set[tuple[str, str]]):
    monkeypatch.setattr(launcher, "is_built", lambda s, h: (s, h) in built_pairs)


class TestScanCommand:
    def test_bare_scan_shows_its_own_usage_not_launchs(self):
        result = runner.invoke(launcher.app, ["scan"])
        assert result.exit_code != 0
        output = plain(result.output)
        assert "Usage: harnessed scan " in output
        assert "STACK" in output
        assert "harnessed launch" not in output

    def test_explicit_harness_scans_only_that_pair(self, stack, scanned, monkeypatch):
        _mark_built(monkeypatch, {(stack, "claude")})
        result = runner.invoke(launcher.app, ["scan", stack, "claude"])
        assert result.exit_code == 0, result.output
        assert scanned == ["harnessed-claude-demo:latest"]

    def test_explicit_harness_not_built_errors_without_scanning(self, stack, scanned, monkeypatch):
        _mark_built(monkeypatch, set())
        result = runner.invoke(launcher.app, ["scan", stack, "claude"])
        assert result.exit_code == 1
        assert "has no assembled profile" in result.output
        assert scanned == []

    def test_unsupported_harness_errors_and_does_not_scan_the_stack_name(self, stack, scanned, monkeypatch):
        # bd main-pv5 symptom 2: the STACK positional must never be validated as if it were HARNESS.
        _mark_built(monkeypatch, {(stack, "claude")})
        result = runner.invoke(launcher.app, ["scan", stack, "bogus-harness"])
        assert result.exit_code == 1
        assert "unsupported harness 'bogus-harness'" in plain(result.output)
        assert f"unsupported harness '{stack}'" not in plain(result.output)
        assert scanned == []

    def test_omitted_harness_scans_every_built_harness(self, stack, scanned, monkeypatch):
        _mark_built(monkeypatch, {(stack, "claude"), (stack, "omp")})
        result = runner.invoke(launcher.app, ["scan", stack])
        assert result.exit_code == 0, result.output
        assert sorted(scanned) == ["harnessed-claude-demo:latest", "harnessed-omp-demo:latest"]

    def test_omitted_harness_with_nothing_built_reports_and_exits_zero(self, stack, scanned, monkeypatch):
        _mark_built(monkeypatch, set())
        result = runner.invoke(launcher.app, ["scan", stack])
        assert result.exit_code == 0, result.output
        assert "nothing to scan" in result.output
        assert scanned == []

    def test_unknown_stack_errors(self, scanned, monkeypatch):
        _mark_built(monkeypatch, set())
        result = runner.invoke(launcher.app, ["scan", "no-such-stack"])
        assert result.exit_code == 1
        assert "no such stack 'no-such-stack'" in plain(result.output)
        assert scanned == []

    def test_scan_failure_exits_nonzero(self, stack, monkeypatch):
        _mark_built(monkeypatch, {(stack, "claude")})
        monkeypatch.setattr(launcher, "_scan_image", lambda rt, run_env, image: False)
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        result = runner.invoke(launcher.app, ["scan", stack, "claude"])
        assert result.exit_code == 1
