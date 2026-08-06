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


class TestFilePermissions:
    def test_the_record_is_owner_only(self, proj):
        """`replace()` keeps the TEMP file's mode, so the temp is what has to be chmod'ed — and
        before the write, not after. Found by adversarial review: this landed 0644."""
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun._store(proj).stat().st_mode & 0o077 == 0

    def test_the_directory_is_owner_only(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        assert lastrun._store(proj).parent.stat().st_mode & 0o077 == 0

    def test_no_temp_file_is_left_behind(self, proj):
        lastrun.record("host-run", "serena", "claude", proj)
        assert list(lastrun._store(proj).parent.glob("*.tmp")) == []

    def test_a_second_record_stays_owner_only(self, proj):
        """The temp path is reused, so a stale 0644 temp must not be inherited by the next write."""
        lastrun.record("host-run", "serena", "claude", proj)
        lastrun.record("host-run", "other", "claude", proj)
        assert lastrun._store(proj).stat().st_mode & 0o077 == 0


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


class TestUpgradeFromTheMiseRow:
    """THE upgrade path, pinned end to end (bd harnessed-7mt).

    Adversarial review suspected old rows were orphaned — that the title had changed, so
    `_drifted_rows` would never see them and a stale `mise run claude --` row would sit in the
    dashboard forever. It has not: `title_for` is untouched by this change, so an existing row
    agrees on (title, path) and differs only on command, which is exactly what drift repair is for.
    Pinned here because the reasoning is not local to any one function.
    """

    def _existing_mise_row(self, tmp_path, title):
        return f'[{{"id": "s1", "path": "{tmp_path}", "title": "{title}", ' \
               f'"command": "mise run claude --"}}]'

    def test_an_old_row_is_repaired_rather_than_left_behind(self, tmp_path, monkeypatch):
        from tests.test_aoe import Recorder, _flag

        title = aoe.title_for("host-run", "serena", "claude", tmp_path)
        rec = Recorder(sessions=self._existing_mise_row(tmp_path, title))
        rec.install(monkeypatch)
        aoe.sync_session("host-run", "serena", "claude", tmp_path, on_drift=lambda *a: None)

        renames = [c for c in rec.calls if c[:2] == ["session", "rename"]]
        assert renames, "the stale mise row must be renamed aside, not left holding the key"
        [add] = rec.registrations()
        assert _flag(add, "--cmd-override") == "harnessed host-run claude --last --"


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

    @pytest.mark.parametrize("selector", (
        ["--stack", "serena"],
        ["--recipe", "serena"],
        ["--service", "redis"],
        ["--extends", "something-else"],
        ["--no-extends"],
    ))
    def test_last_with_any_stack_selector_is_rejected(self, proj, selector):
        """EVERY input that feeds `_resolve_stack`, not just --stack/--recipe.

        `--last` skips `_resolve_stack` entirely, so anything merely "allowed" here would be
        accepted and then silently dropped — `--last --service redis` would start no redis and say
        nothing about it. Found by adversarial review; --service/--extends/--no-extends were
        exactly that silent drop.
        """
        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(proj), "--last", *selector]
        )
        assert result.exit_code == 1
        assert "--last replays" in result.output
        assert selector[0] in result.output, "the error must name the flag that conflicts"

    @pytest.mark.parametrize("lifecycle", (["--rm"], []))
    def test_lifecycle_flags_are_not_treated_as_conflicts(self, proj, lifecycle):
        """`--rm`/`--fresh` say what you want THIS time and apply to a replay like any other
        launch. Rejecting them would be wrong; this pins that only SELECTION conflicts."""
        result = runner.invoke(
            launcher.app, ["host-run", "claude", str(proj), "--last", *lifecycle]
        )
        # Still exit 1 — there is no record — but it must be the "nothing to replay" failure,
        # not the conflict one.
        assert "no recorded" in result.output
        assert "--last replays" not in result.output

    def test_container_run_takes_the_flag_too(self, proj):
        """Both verbs, or the aoe row for one of them has nothing to invoke."""
        result = runner.invoke(launcher.app, ["container-run", "claude", str(proj), "--last"])
        assert result.exit_code == 1
        # Short fragment on purpose: rich hard-wraps the console at the terminal width, so any
        # phrase long enough to straddle a line break is not assertable.
        assert "no recorded" in result.output
