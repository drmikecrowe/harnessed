"""`lastrun` — the record `--last` replays, and the aoe row's stable command (bd harnessed-7mt).

Replaces the `[tasks.<harness>]` table harnessed used to write into every project's
`mise.local.toml`. The behaviours pinned here are the ones that made that file worth removing and
the ones that make the replacement safe to trust.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import aoe, lastrun, launcher

runner = CliRunner()


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    """Every test writes to a scratch XDG_STATE_HOME, never the developer's real one."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


class TestRoundTrip:
    def test_a_recorded_launch_comes_back(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun.load("host-run", "claude", proj)["stack"] == "serena"

    def test_flags_survive(self, proj):
        lastrun.record(
            "host-run", "serena", "claude", proj,
            group="g", title="t", no_strict_mcp=True,
        )
        entry = lastrun.load("host-run", "claude", proj)
        assert (entry["aoe_group"], entry["aoe_title"], entry["no_strict_mcp"]) == ("g", "t", True)

    def test_relaunch_overwrites_rather_than_accumulates(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        lastrun.record("host-run", "other", "claude", proj)
        assert lastrun.load("host-run", "claude", proj)["stack"] == "other"

    def test_a_trailing_slash_is_the_same_project(self, proj):
        """`project_hash` normalizes, so a path typed two ways must not be two records."""
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun.load("host-run", "claude", Path(str(proj) + "/")) is not None


class TestNothingToReplay:
    def test_an_unrecorded_project_is_none(self, proj):
        assert lastrun.load("host-run", "claude", proj) is None

    def test_a_different_harness_is_none(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun.load("host-run", "omp", proj) is None

    def test_a_different_verb_is_none(self, proj):
        """host-run and container-run are different launches; one must not replay as the other."""
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun.load("container-run", "claude", proj) is None

    def test_a_corrupt_record_reads_as_absent(self, proj):
        """Better to say "nothing to replay" than to guess at half a record — the caller fails
        loudly on None, which is the safe end of this."""
        lastrun.record("host-run", "serena", "claude", proj)
        store = lastrun._store(proj)
        store.write_text("{not json", encoding="utf-8")
        assert lastrun.load("host-run", "claude", proj) is None

    def test_an_unknown_version_reads_as_absent(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        store = lastrun._store(proj)
        store.write_text(store.read_text().replace('"version": 1', '"version": 999'), "utf-8")
        assert lastrun.load("host-run", "claude", proj) is None


class TestCheckoutKeying:
    """THE keying decision (bd harnessed-7mt): ONE record per checkout, shared by every worktree —
    the same key the project tool env uses. Keying per worktree was implemented first and rejected
    for multiplying records per repo."""

    def test_worktrees_of_one_repo_share_a_record(self, tmp_path, monkeypatch):
        a, b = tmp_path / "wt-a", tmp_path / "wt-b"
        a.mkdir()
        b.mkdir()
        # One checkout, two worktrees: git_common_dir is the same for both.
        monkeypatch.setattr(lastrun.paths, "git_common_dir", lambda _p: tmp_path / "repo.git")
        lastrun.record("host-run", "stack-a", "claude", a)
        assert lastrun.load("host-run", "claude", b)["stack"] == "stack-a"

    def test_the_last_launch_wins_across_worktrees(self, tmp_path, monkeypatch):
        """The accepted cost of sharing, pinned so it is a decision and not a surprise: a worktree
        running a different stack overwrites the record the other one would replay."""
        a, b = tmp_path / "wt-a", tmp_path / "wt-b"
        a.mkdir()
        b.mkdir()
        monkeypatch.setattr(lastrun.paths, "git_common_dir", lambda _p: tmp_path / "repo.git")
        lastrun.record("host-run", "stack-a", "claude", a)
        lastrun.record("host-run", "stack-b", "claude", b)
        assert lastrun.load("host-run", "claude", a)["stack"] == "stack-b"

    def test_separate_repos_do_not_share(self, tmp_path):
        a, b = tmp_path / "repo-a", tmp_path / "repo-b"
        a.mkdir()
        b.mkdir()
        lastrun.record("host-run", "stack-a", "claude", a)
        lastrun.record("host-run", "stack-b", "claude", b)
        assert lastrun.load("host-run", "claude", a)["stack"] == "stack-a"


class TestNeverFatal:
    def test_an_unwritable_state_dir_does_not_raise(self, proj, monkeypatch):
        """A launch that got this far has already done the useful work. Losing the shortcut is not
        worth killing it."""
        monkeypatch.setattr(lastrun, "_store", lambda _p: Path("/proc/nope/x.json"))
        lastrun.record("host-run", "serena", "claude", proj)  # must not raise


class TestLifecycleFlagsAreNotRecorded:
    def test_no_fresh_or_rm_in_the_record(self, proj):
        """`--fresh`/`--rm` say what you want THIS time, not what the stack is. Recording them
        would make a replay quietly destructive; `aoe.command_for` omits them for the same reason."""
        lastrun.record("host-run", "serena", "claude", proj)
        assert set(lastrun.load("host-run", "claude", proj)) == {
            "stack", "no_strict_mcp", "aoe_group", "aoe_title"
        }


class TestReplayCommandIsAStableKey:
    """Why the flags live in the record rather than in the command: the aoe row's command IS its
    identity, so anything that varies per launch would re-key every existing row."""

    def test_the_command_names_no_stack(self):
        assert "serena" not in aoe.replay_command("host-run", "claude")

    def test_the_command_is_identical_across_launches(self):
        assert aoe.replay_command("host-run", "claude") == aoe.replay_command("host-run", "claude")

    def test_the_verb_is_named(self):
        """A row must restart the backend it says it restarts — the one identity change of the
        switch away from `mise run <harness> --`, which named neither verb nor stack."""
        assert aoe.replay_command("host-run", "claude") != aoe.replay_command(
            "container-run", "claude"
        )

    def test_it_ends_with_the_passthrough_separator(self):
        """aoe appends the recorded tool's resume flags on restart; they have to sail past
        harnessed's own option parsing to reach the agent. See `aoe.command_for`."""
        assert aoe.replay_command("host-run", "claude").endswith(" --")

    def test_it_is_recognized_as_ours(self):
        """The licence to repair a drifted row. A shape we write that reads as foreign would strand
        every row harnessed created."""
        assert aoe._is_ours(aoe.replay_command("host-run", "claude"))

    def test_the_retired_mise_shape_is_still_ours(self):
        """Retiring a shape means we stop WRITING it, not that we forget we wrote it — rows created
        before the switch must stay repairable."""
        assert aoe._is_ours("mise run claude --")


class TestLastFlagAtTheCli:
    """`--last` refuses rather than guesses. Both branches end a launch before anything is built,
    so they are safe to drive through the real CLI."""

    def test_no_record_is_a_loud_failure_not_a_baseline_launch(self, proj):
        """THE failure this design exists to prevent. Falling back to `default` here would start
        the wrong stack and report success — see `_resolve_last`."""
        result = runner.invoke(launcher.app, ["host-run", "claude", str(proj), "--last"])
        assert result.exit_code == 1
        # Short fragment on purpose: rich hard-wraps the console at the terminal width, so any
        # phrase long enough to straddle a line break is not assertable.
        assert "no recorded" in result.output

    def test_the_error_says_how_to_create_a_record(self, proj):
        result = runner.invoke(launcher.app, ["host-run", "claude", str(proj), "--last"])
        assert "harnessed host-run claude" in result.output

    @pytest.mark.parametrize("selector", (["--stack", "serena"], ["--recipe", "serena"]))
    def test_last_with_an_explicit_stack_selector_is_rejected(self, proj, selector):
        """Not an override but a contradiction: --last says "the one from before", --stack/--recipe
        say "this other one". Resolving it silently either way would surprise somebody."""
        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(proj), "--last", *selector]
        )
        assert result.exit_code == 1
        assert "--last replays the last launch here" in result.output

    def test_container_run_takes_the_flag_too(self, proj):
        """Both verbs, or the aoe row for one of them has nothing to invoke."""
        result = runner.invoke(launcher.app, ["container-run", "claude", str(proj), "--last"])
        assert result.exit_code == 1
        # Short fragment on purpose: rich hard-wraps the console at the terminal width, so any
        # phrase long enough to straddle a line break is not assertable.
        assert "no recorded" in result.output
