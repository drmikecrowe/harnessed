"""The one-way bridge that mirrors harnessed launches into Agent of Empires.

aoe is optional, so the load-bearing property under test is NEGATIVE: absent, disabled, broken or
slow, the bridge must do nothing and raise nothing. The rest pins identity — (path, stack, harness),
per-verb — which is what stops relaunches from stacking duplicate rows and stops the claude and omp
variants of one stack from collapsing onto each other.

No test shells out to a real `aoe`; `_run` is the seam.
"""
from __future__ import annotations

import shlex
import subprocess

from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup
from typer.testing import CliRunner

from harnessed import aoe, launcher
from harnessed.schema import SchemaError


PROFILE_LIST_EMPTY = "Profiles:\n  * default (default)\n\nTotal: 1 profiles\n"
PROFILE_LIST_PRESENT = "Profiles:\n  * default (default)\n    harnessed\n\nTotal: 2 profiles\n"
GROUP_LIST_EMPTY = "No groups found.\nCreate one with: aoe group create <name>\n"


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="nope")


class Recorder:
    """Stands in for both seams: `_run` answers the reads, `_spawn` collects the detached writes.

    `calls` is the union in issue order, so a test can assert on the whole interaction without
    caring which seam a given command went through.
    """

    def __init__(self, *, profiles=PROFILE_LIST_PRESENT, groups=GROUP_LIST_EMPTY, sessions="[]"):
        self.calls: list[list[str]] = []
        self.spawned: list[list[str]] = []
        self._profiles, self._groups, self._sessions = profiles, groups, sessions

    def run(self, exe: str, args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ["profile", "list"]:
            return _ok(self._profiles)
        if args[:2] == ["group", "list"]:
            return _ok(self._groups)
        if args[:2] == ["list", "--json"]:
            return _ok(self._sessions)
        return _ok()

    def spawn(self, exe: str, batch: list[list[str]]) -> bool:
        self.spawned.extend(batch)
        self.calls.extend(batch)
        return True

    def install(self, monkeypatch) -> "Recorder":
        monkeypatch.setattr(aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(aoe, "_run", self.run)
        monkeypatch.setattr(aoe, "_spawn", self.spawn)
        return self

    def verbs(self) -> list[tuple[str, ...]]:
        return [tuple(a[:2]) for a in self.calls]

    def added(self) -> list[list[str]]:
        """Every `add` issued. One registration issues TWO: a `--tool`-labelled attempt and, because
        aoe rejects a `--tool` it cannot resolve on the invoking PATH, a plain retry behind it."""
        return [a for a in self.calls if a[0] == "add"]

    def registrations(self) -> list[list[str]]:
        """One entry per registration — the labelled attempt, which carries every other flag too."""
        return [a for a in self.added() if "--tool" in a]

    def removed(self) -> list[str]:
        return [a[1] for a in self.calls if a[0] == "remove"]


@pytest.fixture
def rec(monkeypatch):
    return Recorder().install(monkeypatch)


def _flag(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


class TestDetection:
    """`_bin` is the whole opt-in: no aoe, no behaviour."""

    def test_absent_binary_is_a_no_op(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.shutil, "which", lambda _: None)
        assert aoe._bin() is None

    def test_binary_without_config_dir_is_a_no_op(self, monkeypatch, tmp_path):
        # A stray `aoe` on PATH that was never set up is not a user who runs aoe.
        monkeypatch.setattr(aoe.shutil, "which", lambda _: "/usr/bin/aoe")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert aoe._bin() is None

    def test_binary_with_config_dir_is_usable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.shutil, "which", lambda _: "/usr/bin/aoe")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        (tmp_path / "agent-of-empires").mkdir()
        assert aoe._bin() == "/usr/bin/aoe"

    def test_env_var_opts_out_even_when_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.shutil, "which", lambda _: "/usr/bin/aoe")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        (tmp_path / "agent-of-empires").mkdir()
        monkeypatch.setenv("HARNESSED_NO_AOE", "1")
        assert aoe._bin() is None

    def test_sync_runs_nothing_when_unavailable(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(aoe, "_bin", lambda: None)
        monkeypatch.setattr(aoe, "_run", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(aoe, "_spawn", lambda *a, **k: calls.append(a))
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert calls == []


class TestSyncSession:
    def test_registers_profile_group_and_session(self, rec, tmp_path):
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert ("group", "create") in rec.verbs()
        [add] = rec.registrations()
        assert add[1] == str(tmp_path)
        assert _flag(add, "-p") == aoe.PROFILE
        assert _flag(add, "--cmd-override") == f"harnessed container-run claude {tmp_path} --stack serena --"

    def test_uses_cmd_override_not_cmd(self, rec, tmp_path):
        # `--cmd` is validated against aoe's tool list and silently substitutes its configured
        # default, which would destroy both the replay and the identity key.
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert "--cmd" not in rec.added()[0]

    def test_existing_profile_is_not_recreated(self, rec, tmp_path):
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert ("profile", "create") not in rec.verbs()

    def test_missing_profile_is_created(self, monkeypatch, tmp_path):
        rec = Recorder(profiles=PROFILE_LIST_EMPTY)
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert ["profile", "create", aoe.PROFILE] in rec.calls

    def test_existing_group_is_not_recreated(self, monkeypatch, tmp_path):
        rec = Recorder(groups=f"Groups:\n\n• {tmp_path.name} (2 sessions)\n\nTotal: 1 groups\n")
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert ("group", "create") not in rec.verbs()

    def test_add_passes_only_flags_aoe_accepts(self, rec, tmp_path):
        # `aoe add` is a clap CLI: an unknown flag exits 2 before adding anything, and on the
        # detached write path that is invisible — the dashboard just stays empty. Regression cover
        # for `--no-cockpit`, which is not an aoe flag and lost every registration.
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        flags = {a for a in rec.added()[0] if a.startswith("-")}
        assert flags <= {"-p", "-g", "-t", "--cmd-override", "--tool"}

    def test_terminal_view_is_left_to_the_default(self, rec, tmp_path):
        # `aoe add` defaults to the raw tmux/PTY view, which is the one we need: the structured
        # view's ACP transport cannot reach through the `podman exec` attach `launch` ends in.
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert "--structured-view" not in rec.added()[0]
        assert "--agent" not in rec.added()[0]

    def test_default_stack_is_skipped(self, rec, tmp_path):
        aoe.sync_session("container-run", "default", "claude", tmp_path)
        assert rec.calls == []

    def test_title_carries_folder_harness_and_stack(self, rec, tmp_path):
        aoe.sync_session("container-run", "serena", "omp", tmp_path)
        assert _flag(rec.added()[0], "-t") == f"{tmp_path.name} [omp/container] serena"


class TestToolLabel:
    """Which agent aoe thinks the row runs — it decides which resume flags a restart appends.

    `--cmd-override` leaves the recorded tool at aoe's default (`claude`), so an unlabelled omp row
    got claude's `--resume <uuid>` appended on restart. `command_for`'s trailing `--` then forwarded
    it to the omp binary, which rejects a claude conversation id and dies; aoe respawns and loops.
    """

    def test_row_is_labelled_with_its_harness(self, rec, tmp_path):
        aoe.sync_session("container-run", "serena", "omp", tmp_path)
        assert _flag(rec.registrations()[0], "--tool") == "omp"

    def test_claude_rows_are_labelled_too(self, rec, tmp_path):
        # Same value aoe would have defaulted to, stated rather than left to the default.
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert _flag(rec.registrations()[0], "--tool") == "claude"

    def test_a_plain_add_follows_the_labelled_one(self, rec, tmp_path):
        # aoe resolves `--tool` against the invoking PATH and adds NOTHING when it cannot — which is
        # the norm for a harness that lives in the pod. The retry keeps that from costing the row.
        aoe.sync_session("container-run", "serena", "omp", tmp_path)
        labelled, plain = rec.added()
        assert labelled == [*plain, "--tool", "omp"]

    def test_the_retry_is_identical_apart_from_the_label(self, rec, tmp_path):
        # Same title and path is what makes aoe refuse it as a duplicate at exit 0 when the labelled
        # add won. Diverge on either and the retry would add a SECOND row.
        aoe.sync_session("container-run", "serena", "omp", tmp_path)
        labelled, plain = rec.added()
        assert _flag(plain, "-t") == _flag(labelled, "-t")
        assert plain[1] == labelled[1]

    def test_a_rejected_label_does_not_fail_a_blocking_register(self, monkeypatch, tmp_path):
        # `--create-aoe-only` reports its exit status to the user. A `--tool` aoe would not resolve
        # is an expected outcome, not the failure that flag is there to surface.
        rec = Recorder()
        rec.install(monkeypatch)
        monkeypatch.setattr(
            aoe, "_run", lambda exe, args, **k: _fail() if "--tool" in args else rec.run(exe, args)
        )
        assert aoe.sync_session("container-run", "serena", "omp", tmp_path, background=False) is True

    def test_a_failed_plain_add_still_fails_a_blocking_register(self, monkeypatch, tmp_path):
        rec = Recorder()
        rec.install(monkeypatch)
        monkeypatch.setattr(
            aoe, "_run", lambda exe, args, **k: _fail() if args[0] == "add" else rec.run(exe, args)
        )
        assert aoe.sync_session("container-run", "serena", "omp", tmp_path, background=False) is False


class TestTitleUniqueness:
    """aoe dedupes `add` on (title, path) and exits 0, so a title collision is a LOST row.

    That makes the title part of identity whether we like it or not: it must separate everything
    we treat as distinct. Regression cover for host-run registrations vanishing behind their
    `launch` twin.
    """

    def test_backend_is_part_of_the_title(self, tmp_path):
        container = aoe.title_for("container-run", "serena", "claude", tmp_path)
        host = aoe.title_for("host-run", "serena", "claude", tmp_path)
        assert container != host

    def test_harness_is_part_of_the_title(self, tmp_path):
        assert aoe.title_for("container-run", "serena", "claude", tmp_path) != aoe.title_for(
            "container-run", "serena", "omp", tmp_path
        )

    def test_stack_is_part_of_the_title(self, tmp_path):
        assert aoe.title_for("container-run", "serena", "claude", tmp_path) != aoe.title_for(
            "container-run", "superpowers", "claude", tmp_path
        )

    def test_the_mcp_mode_is_part_of_the_title(self, tmp_path):
        # It is recorded on the command, so it is identity — and identity the title cannot express
        # is identity aoe discards. Same title and path means the second `add` is refused at exit 0
        # and the row keeps replaying whichever command it was registered with first.
        assert aoe.title_for("host-run", "serena", "claude", tmp_path) != aoe.title_for(
            "host-run", "serena", "claude", tmp_path, no_strict_mcp=True
        )

    def test_strict_titles_are_unchanged(self, tmp_path):
        # The default must not churn: every existing row was registered under this exact label.
        assert aoe.title_for("host-run", "serena", "claude", tmp_path) == (
            f"{tmp_path.name} [claude/host] serena"
        )

    def test_open_mcp_rows_do_not_collide_end_to_end(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        aoe.sync_session("host-run", "serena", "claude", tmp_path)
        aoe.sync_session("host-run", "serena", "claude", tmp_path, no_strict_mcp=True)
        titles = [_flag(a, "-t") for a in rec.registrations()]
        assert len(titles) == 2 and len(set(titles)) == 2, titles

    def test_host_and_container_titles_do_not_collide_end_to_end(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        aoe.sync_session("host-run", "serena", "claude", tmp_path)
        titles = [_flag(a, "-t") for a in rec.registrations()]
        assert len(titles) == 2 and len(set(titles)) == 2, titles


class TestIdentity:
    """(path, stack, harness) per verb — the key that decides duplicate vs distinct."""

    def _existing(self, tmp_path: Path, command: str) -> str:
        return f'[{{"id": "s1", "path": "{tmp_path}", "command": "{command}"}}]'

    def test_relaunch_does_not_duplicate(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --"))
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert rec.added() == []

    def test_a_second_harness_is_a_second_session(self, monkeypatch, tmp_path):
        # One stack has an assembled profile PER harness, so claude and omp are two rows.
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --"))
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "omp", tmp_path)
        assert len(rec.registrations()) == 1

    def test_host_and_container_verbs_do_not_collide(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --"))
        rec.install(monkeypatch)
        aoe.sync_session("host-run", "serena", "claude", tmp_path)
        assert len(rec.registrations()) == 1

    def test_an_open_mcp_relaunch_does_not_duplicate(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --no-strict-mcp-config --"))
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path, no_strict_mcp=True)
        assert rec.added() == []

    def test_strict_and_open_mcp_are_two_sessions(self, monkeypatch, tmp_path):
        # Different MCP surface, so two things to run. The cost is one-time and unavoidable: a row
        # registered before the flag was echoed does not match and is registered once more.
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --"))
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path, no_strict_mcp=True)
        assert len(rec.registrations()) == 1

    def test_same_stack_in_another_folder_is_a_second_session(self, monkeypatch, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed container-run claude {tmp_path} --stack serena --"))
        rec.install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", other)
        assert len(rec.registrations()) == 1


class TestGroup:
    def test_worktrees_of_one_repo_share_a_group(self, monkeypatch, tmp_path):
        # Keyed on the git COMMON dir, which is identical across a checkout's worktrees.
        monkeypatch.setattr(aoe.paths, "git_common_dir", lambda _: tmp_path / "myrepo" / ".git")
        assert aoe._group_for(tmp_path / "myrepo" / "wt-a") == "myrepo"
        assert aoe._group_for(tmp_path / "elsewhere" / "wt-b") == "myrepo"

    def test_bare_layout_resolves_to_the_repo_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.paths, "git_common_dir", lambda _: tmp_path / "myrepo" / ".bare")
        assert aoe._group_for(tmp_path / "myrepo" / "main") == "myrepo"

    def test_non_git_falls_back_to_the_folder_name(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.paths, "git_common_dir", lambda _: None)
        assert aoe._group_for(tmp_path / "scratch") == "scratch"

    def test_an_explicit_group_wins_over_the_derived_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr(aoe.paths, "git_common_dir", lambda _: tmp_path / "myrepo" / ".git")
        wt = tmp_path / "myrepo" / "wt-a"
        assert aoe.group_for(wt, group="a-chosen-group") == "a-chosen-group"
        assert aoe.group_for(wt) == "myrepo"


class TestUserNamedRows:
    """`--aoe-group` / `--aoe-title`: the user placing and labelling a row themselves.

    Supplying BOTH also replaces the identity key with (group, title). That is the only match that
    can find a row harnessed did not write — a hand-placed one carries flags `command_for` never
    emits and records the path as typed, so by command it is invisible and a duplicate lands beside
    it under the derived group. Either flag alone must NOT switch matching: a group holds many
    sessions and a title is unique only within one.
    """

    def _row(self, *, group: str, title: str, key: str = "group") -> str:
        # Modelled on a real hand-added row: an unresolved path with a trailing slash, and a
        # `--no-strict-mcp-config` that `command_for` does not emit.
        return (
            f'[{{"id": "s1", "path": "/p/1-unconfigured/", "title": "{title}", "{key}": "{group}",'
            ' "command": "harnessed host-run claude /p/1-unconfigured/ --stack s'
            ' --no-strict-mcp-config --"}]'
        )

    def test_group_places_the_row_and_is_created(self, rec, tmp_path):
        aoe.sync_session("host-run", "s", "claude", tmp_path, group="a-chosen-group")
        assert ["group", "create", "a-chosen-group", "-p", aoe.PROFILE] in rec.calls
        assert _flag(rec.registrations()[0], "-g") == "a-chosen-group"

    def test_title_labels_the_row(self, rec, tmp_path):
        aoe.sync_session("host-run", "s", "claude", tmp_path, title="a chosen title")
        assert _flag(rec.registrations()[0], "-t") == "a chosen title"

    def test_both_are_echoed_on_the_recorded_command(self, rec, tmp_path):
        # Left off, a restart from the dashboard would re-derive group and title and add a SECOND
        # row beside the one the user placed — the duplicate these flags exist to prevent.
        aoe.sync_session(
            "host-run", "s", "claude", tmp_path, group="a-chosen-group", title="a titled row"
        )
        tokens = shlex.split(_flag(rec.registrations()[0], "--cmd-override"))
        assert tokens[-5:] == ["--aoe-group", "a-chosen-group", "--aoe-title", "a titled row", "--"]

    def test_an_existing_row_is_adopted_not_duplicated(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._row(group="a-chosen-group", title="a titled row"))
        rec.install(monkeypatch)
        aoe.sync_session(
            "host-run", "s", "claude", tmp_path, group="a-chosen-group", title="a titled row"
        )
        assert rec.added() == []

    def test_the_on_disk_group_key_is_accepted_too(self, monkeypatch, tmp_path):
        # `aoe list --json` renames the stored `group_path` to `group`; tolerate either so a rename
        # upstream costs a duplicate row at worst, never an exception.
        rec = Recorder(sessions=self._row(group="a-chosen-group", title="a titled row", key="group_path"))
        rec.install(monkeypatch)
        aoe.sync_session(
            "host-run", "s", "claude", tmp_path, group="a-chosen-group", title="a titled row"
        )
        assert rec.added() == []

    def test_a_different_title_in_the_same_group_is_a_new_row(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._row(group="a-chosen-group", title="some other row"))
        rec.install(monkeypatch)
        aoe.sync_session(
            "host-run", "s", "claude", tmp_path, group="a-chosen-group", title="a titled row"
        )
        assert len(rec.registrations()) == 1

    def test_group_alone_does_not_adopt_a_row(self, monkeypatch, tmp_path):
        # Every session in a group shares its group; matching on it would swallow unrelated rows.
        rec = Recorder(sessions=self._row(group="a-chosen-group", title="a titled row"))
        rec.install(monkeypatch)
        aoe.sync_session("host-run", "s", "claude", tmp_path, group="a-chosen-group")
        assert len(rec.registrations()) == 1

    def test_title_alone_does_not_adopt_a_row(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._row(group="a-chosen-group", title="a titled row"))
        rec.install(monkeypatch)
        aoe.sync_session("host-run", "s", "claude", tmp_path, title="a titled row")
        assert len(rec.registrations()) == 1

    @pytest.mark.parametrize("flag", ["--aoe-group", "--aoe-title"])
    @pytest.mark.parametrize("verb", ["container-run", "host-run"])
    def test_every_launch_verb_accepts_the_flags(self, verb, flag):
        # On the declaration, not on rendered `--help` — see test_every_launch_verb_accepts_the_flag.
        group = typer.main.get_command(launcher.app)
        assert isinstance(group, TyperGroup)  # narrows to the .commands mapping
        assert any(flag in p.opts for p in group.commands[verb].params)


class TestForgetStack:
    SESSIONS = (
        '[{"id": "a", "command": "harnessed container-run claude /p --stack serena --"},'
        ' {"id": "b", "command": "harnessed container-run omp /p --stack serena --"},'
        ' {"id": "c", "command": "harnessed container-run claude /p --stack other --"},'
        ' {"id": "d", "command": "harnessed host-run claude /p --stack serena --"}]'
    )

    def _rec(self, monkeypatch) -> Recorder:
        rec = Recorder(sessions=self.SESSIONS)
        rec.install(monkeypatch)
        return rec

    def test_removes_every_harness_of_the_named_stack(self, monkeypatch):
        rec = self._rec(monkeypatch)
        aoe.forget_stack("container-run", "serena")
        assert sorted(rec.removed()) == ["a", "b"]

    def test_leaves_other_stacks_and_the_host_verb_alone(self, monkeypatch):
        # `harnessed rm` tears down CONTAINERS; a host-native session owns none.
        rec = self._rec(monkeypatch)
        aoe.forget_stack("container-run", "serena")
        assert "c" not in rec.removed()
        assert "d" not in rec.removed()

    def test_no_op_without_aoe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(aoe, "_bin", lambda: None)
        monkeypatch.setattr(aoe, "_run", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(aoe, "_spawn", lambda *a, **k: calls.append(a))
        aoe.forget_stack("container-run", "serena")
        assert calls == []


class TestNeverRaises:
    """A dashboard is not worth failing a launch over."""

    @pytest.mark.parametrize("exc", [OSError("boom"), subprocess.TimeoutExpired("aoe", 10), ValueError("x")])
    def test_sync_swallows_subprocess_failure(self, monkeypatch, tmp_path, exc):
        monkeypatch.setattr(aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(aoe, "_run", lambda *a: (_ for _ in ()).throw(exc))
        aoe.sync_session("container-run", "serena", "claude", tmp_path)

    def test_forget_swallows_subprocess_failure(self, monkeypatch):
        monkeypatch.setattr(aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(aoe, "_run", lambda *a: (_ for _ in ()).throw(OSError("boom")))
        aoe.forget_stack("container-run", "serena")

    def test_run_returns_none_instead_of_propagating(self, monkeypatch):
        def blow_up(*_a, **_k):
            raise subprocess.TimeoutExpired("aoe", 10)

        monkeypatch.setattr(aoe.subprocess, "run", blow_up)
        assert aoe._run("/usr/bin/aoe", ["list"]) is None

    def test_malformed_session_json_yields_no_sessions(self, monkeypatch):
        monkeypatch.setattr(aoe, "_run", lambda *a: _ok("not json at all"))
        assert aoe._sessions("/usr/bin/aoe") == []

    def test_non_list_session_json_yields_no_sessions(self, monkeypatch):
        monkeypatch.setattr(aoe, "_run", lambda *a: _ok('{"error": "nope"}'))
        assert aoe._sessions("/usr/bin/aoe") == []


class TestWriteDispatch:
    """Reads block, writes do not — `aoe add` takes ~12s and a launch must not wait on it."""

    def test_registration_is_detached_by_default(self, rec, tmp_path):
        # The `rec` fixture reports the profile as already present, so only the group and the
        # session are written. Asserted explicitly, because the expected batch below depends on it.
        assert aoe._has_profile("/usr/bin/aoe") is True
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert [a[0] for a in rec.spawned] == ["group", "add", "add"]

    def test_a_missing_profile_is_created_in_the_same_batch(self, monkeypatch, tmp_path):
        # Ordering matters: the profile must exist before the group, the group before the session.
        rec = Recorder(profiles=PROFILE_LIST_EMPTY).install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert [a[0] for a in rec.spawned] == ["profile", "group", "add", "add"]

    def test_writes_are_sequenced_with_semicolons_not_and(self, monkeypatch):
        # `aoe profile create` / `group create` exit 1 when the thing ALREADY EXISTS, and the reads
        # that build the batch are not atomic with it. Under `&&`, a launch that raced another and
        # lost would abort on that benign error and never add its session.
        seen = {}

        class FakePopen:
            def __init__(self, argv, **kwargs):
                seen["script"] = argv[2]

        monkeypatch.setattr(aoe.subprocess, "Popen", FakePopen)
        aoe._spawn("/usr/bin/aoe", [["profile", "create", "harnessed"], ["add", "/p"]])
        assert "&&" not in seen["script"]
        assert seen["script"].count(";") == 1

    def test_reads_never_go_through_the_detached_path(self, rec, tmp_path):
        aoe.sync_session("container-run", "serena", "claude", tmp_path)
        assert not any(a[:2] in (["list", "--json"], ["group", "list"]) for a in rec.spawned)

    def test_blocking_mode_runs_writes_inline(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        aoe.sync_session("container-run", "serena", "claude", tmp_path, background=False)
        assert rec.spawned == []
        assert [a[0] for a in rec.added()] == ["add", "add"]

    def test_blocking_mode_reports_a_failed_write(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        monkeypatch.setattr(
            aoe, "_run",
            lambda exe, args, **k: rec.run(exe, args) if args[1:2] == ["list"] else _fail(),
        )
        assert aoe.sync_session("container-run", "serena", "claude", tmp_path, background=False) is False

    def test_detached_dispatch_is_reported_as_success(self, rec, tmp_path):
        assert aoe.sync_session("container-run", "serena", "claude", tmp_path) is True

    def test_already_registered_is_success_without_writing(self, monkeypatch, tmp_path):
        rec = Recorder(
            sessions=f'[{{"id": "s1", "path": "{tmp_path}",'
                     f' "command": "harnessed container-run claude {tmp_path} --stack serena --"}}]'
        ).install(monkeypatch)
        assert aoe.sync_session("container-run", "serena", "claude", tmp_path) is True
        assert rec.spawned == []

    def test_unavailable_aoe_is_reported_as_failure(self, monkeypatch, tmp_path):
        # What `--create-aoe-only` turns into a non-zero exit.
        monkeypatch.setattr(aoe, "_bin", lambda: None)
        assert aoe.sync_session("container-run", "serena", "claude", tmp_path) is False

    def test_skipped_stack_is_reported_as_failure(self, rec, tmp_path):
        assert aoe.sync_session("container-run", "default", "claude", tmp_path) is False

    def test_spawn_survives_the_exec(self, monkeypatch):
        # start_new_session is the whole reason the detached `aoe add` is not killed when
        # harnessed os.execvp's moments later.
        seen = {}

        class FakePopen:
            def __init__(self, argv, **kwargs):
                seen["argv"], seen["kwargs"] = argv, kwargs

        monkeypatch.setattr(aoe.subprocess, "Popen", FakePopen)
        assert aoe._spawn("/usr/bin/aoe", [["group", "create", "g"], ["add", "/p"]]) is True
        assert seen["kwargs"]["start_new_session"] is True
        assert seen["argv"][:2] == ["sh", "-c"]
        # Ordered: the group must exist before the session that joins it.
        assert seen["argv"][2] == "/usr/bin/aoe group create g; /usr/bin/aoe add /p"

    def test_spawn_failure_is_swallowed(self, monkeypatch):
        def blow_up(*_a, **_k):
            raise OSError("no fork for you")

        monkeypatch.setattr(aoe.subprocess, "Popen", blow_up)
        assert aoe._spawn("/usr/bin/aoe", [["add", "/p"]]) is False

    def test_empty_batch_spawns_nothing(self, monkeypatch):
        def unexpected(*_a, **_k):
            raise AssertionError("should not spawn for an empty batch")

        monkeypatch.setattr(aoe.subprocess, "Popen", unexpected)
        assert aoe._spawn("/usr/bin/aoe", []) is True


class TestCreateAoeOnly:
    """`--create-aoe-only`: register the row, run nothing.

    All three launch verbs funnel through `_aoe_register`, so the flag's semantics are pinned here
    once rather than three times through the CLI.
    """

    def _register(self, monkeypatch, *, ok: bool, only: bool) -> dict:
        seen: dict = {}

        def fake_sync(
            verb, stack, harness, project_path, *, background=True, group=None, title=None,
            no_strict_mcp=False,
        ):
            seen.update(verb=verb, stack=stack, harness=harness, background=background)
            return ok

        monkeypatch.setattr(launcher.aoe, "sync_session", fake_sync)
        seen["exit"] = None
        try:
            launcher._aoe_register("container-run", "serena", "claude", Path("/p"), only=only)
        except typer.Exit as exc:
            seen["exit"] = exc.exit_code
        return seen

    def test_passive_mirror_does_not_block(self, monkeypatch):
        seen = self._register(monkeypatch, ok=True, only=False)
        assert seen["background"] is True
        assert seen["exit"] is None, "a normal launch must carry on past the mirror"

    def test_passive_mirror_ignores_failure(self, monkeypatch):
        # aoe absent, broken or slow must never turn into a failed launch.
        seen = self._register(monkeypatch, ok=False, only=False)
        assert seen["exit"] is None

    def test_flag_blocks_on_the_write(self, monkeypatch):
        seen = self._register(monkeypatch, ok=True, only=True)
        assert seen["background"] is False, "the user is waiting for this write's result"

    def test_flag_exits_zero_without_launching(self, monkeypatch):
        seen = self._register(monkeypatch, ok=True, only=True)
        assert seen["exit"] == 0

    def test_flag_exits_nonzero_when_registration_fails(self, monkeypatch):
        # An explicit request, unlike the passive mirror: failing silently would be a lie.
        seen = self._register(monkeypatch, ok=False, only=True)
        assert seen["exit"] == 1

    @pytest.mark.parametrize("verb", ["container-run", "host-run"])
    def test_every_launch_verb_accepts_the_flag(self, verb):
        """Assert on the PARAMETER, not on rendered `--help`.

        Help text is laid out by rich against the terminal width and painted with ANSI, so an
        earlier version of this test passed locally and failed in CI purely because the flag name
        wrapped. The declaration is what the assertion is actually about.
        """
        group = typer.main.get_command(launcher.app)
        assert isinstance(group, TyperGroup)  # narrows to the .commands mapping
        assert any("--create-aoe-only" in p.opts for p in group.commands[verb].params)


class TestHookPlacement:
    """A row must never outlive the launch that created it.

    Both backends register only after their last validation gate — `is_built`/staleness for the
    container path, in-process assembly for the host path. Registering earlier leaves a bookmark
    for a launch that died, and it would fail identically every time it was started from the
    dashboard.
    """

    def _host_run(self, monkeypatch, tmp_path, *, assembly_fails: bool):
        registered: list = []
        (tmp_path / "stack.yaml").write_text("name: broken\n")
        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a: tmp_path)
        monkeypatch.setattr(
            launcher.aoe, "sync_session",
            lambda *a, **k: (registered.append(a), True)[1],
        )

        def assemble(*_a, **_k):
            if assembly_fails:
                raise SchemaError("recipe 'gone' no longer resolves")
            return None

        monkeypatch.setattr(launcher, "assemble", assemble)
        # create_aoe_only=True makes the hook itself the stopping point, so a successful assembly
        # never reaches the launch machinery this test is not about. Both paths raise typer.Exit —
        # 1 for the assembly failure, 0 for the registration — so the assertion is on what was
        # registered, not on the exception.
        with pytest.raises(typer.Exit):
            launcher._launch_host("broken", "claude", str(tmp_path), create_aoe_only=True)
        return registered

    def test_failed_assembly_registers_nothing(self, monkeypatch, tmp_path):
        assert self._host_run(monkeypatch, tmp_path, assembly_fails=True) == []

    def test_registration_happens_once_assembly_succeeds(self, monkeypatch, tmp_path):
        # Guards the test above from passing vacuously: if the hook were simply gone, both pass.
        registered = self._host_run(monkeypatch, tmp_path, assembly_fails=False)
        assert [a[0] for a in registered] == ["host-run"]


class TestLaunchFlagsReachTheRow:
    """`--no-strict-mcp-config` has to survive the trip from argv to the recorded command.

    It is threaded separately on each verb — `host-run` through `_launch_host`, `container-run`
    inline — so a wiring test per verb is a wiring test per call site. Both stop at
    `--create-aoe-only`, which raises typer.Exit(0) from the register hook and never reaches the
    launch machinery.
    """

    def _seen(self, monkeypatch, tmp_path) -> dict:
        seen: dict = {}
        monkeypatch.setattr(
            launcher.aoe, "sync_session", lambda *a, **k: (seen.update(k), True)[1]
        )
        (tmp_path / "stack.yaml").write_text("name: s\n")
        monkeypatch.setattr(launcher.paths, "find_in_catalog", lambda *a: tmp_path)
        return seen

    def test_host_run_records_it(self, monkeypatch, tmp_path):
        seen = self._seen(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher, "assemble", lambda *a, **k: None)
        with pytest.raises(typer.Exit):
            launcher._launch_host(
                "s", "claude", str(tmp_path), create_aoe_only=True, no_strict_mcp=True
            )
        assert seen["no_strict_mcp"] is True

    def test_host_run_defaults_to_strict(self, monkeypatch, tmp_path):
        seen = self._seen(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher, "assemble", lambda *a, **k: None)
        with pytest.raises(typer.Exit):
            launcher._launch_host("s", "claude", str(tmp_path), create_aoe_only=True)
        assert seen["no_strict_mcp"] is False

    def _container_run(self, monkeypatch, tmp_path, argv: list[str]) -> dict:
        seen = self._seen(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "is_built", lambda *a: True)
        monkeypatch.setattr(launcher.staleness, "check_profile_fresh", lambda *a: None)
        project = tmp_path / "proj"
        project.mkdir()
        CliRunner().invoke(
            launcher.app,
            ["container-run", "claude", str(project), "--stack", "s", "--create-aoe-only", *argv],
        )
        return seen

    def test_container_run_records_it(self, monkeypatch, tmp_path):
        seen = self._container_run(monkeypatch, tmp_path, ["--no-strict-mcp-config"])
        assert seen["no_strict_mcp"] is True

    def test_container_run_defaults_to_strict(self, monkeypatch, tmp_path):
        assert self._container_run(monkeypatch, tmp_path, [])["no_strict_mcp"] is False


class TestCommandFor:
    def test_quotes_paths_with_spaces(self):
        cmd = aoe.command_for("container-run", "serena", "claude", Path("/tmp/my project"))
        assert cmd == "harnessed container-run claude '/tmp/my project' --stack serena --"

    def test_terminates_with_a_bare_double_dash(self):
        # aoe's auto-resume appends the RECORDED TOOL's flags (claude: `--fork-session
        # --session-id <uuid>`) on restart. Without the terminator they hit harnessed's Click
        # parser, which exits on `No such option: --session-id`; with it they become passthrough
        # args for the agent.
        cmd = aoe.command_for("host-run", "serena", "claude", Path("/p"))
        assert cmd.split() == [
            "harnessed", "host-run", "claude", "/p", "--stack", "serena", "--",
        ]

    def test_no_strict_mcp_is_recorded(self):
        # Dropped, claude also loads the project's `.mcp.json` and the user's config. A row that
        # forgets it restarts with a different MCP surface than the one that was registered.
        cmd = aoe.command_for("host-run", "serena", "claude", Path("/p"), no_strict_mcp=True)
        assert cmd == "harnessed host-run claude /p --stack serena --no-strict-mcp-config --"

    def test_strict_is_the_default_and_records_nothing(self):
        cmd = aoe.command_for("host-run", "serena", "claude", Path("/p"))
        assert "--no-strict-mcp-config" not in cmd

    def test_the_whole_recorded_shape_with_every_echoed_flag(self):
        # Pins ORDER as well as content: the command is the identity key on the fallback path, so
        # two launches that differ only in how the flags are arranged must not become two rows.
        cmd = aoe.command_for(
            "host-run", "serena", "claude", Path("/p"),
            no_strict_mcp=True, group="g", title="a titled row",
        )
        assert cmd == (
            "harnessed host-run claude /p --stack serena --no-strict-mcp-config "
            "--aoe-group g --aoe-title 'a titled row' --"
        )

    def test_records_the_resolved_stack_name(self):
        # Dynamic stacks are minted before this is called, so the derived name replays exactly —
        # a `--recipe` invocation and a `--stack` one record the same shape.
        cmd = aoe.command_for("container-run", "default.serena.superpowers", "claude", Path("/p"))
        assert cmd == "harnessed container-run claude /p --stack default.serena.superpowers --"
