"""The one-way bridge that mirrors harnessed launches into Agent of Empires.

aoe is optional, so the load-bearing property under test is NEGATIVE: absent, disabled, broken or
slow, the bridge must do nothing and raise nothing. The rest pins identity — (path, stack, harness),
per-verb — which is what stops relaunches from stacking duplicate rows and stops the claude and omp
variants of one stack from collapsing onto each other.

No test shells out to a real `aoe`; `_run` is the seam.
"""
from __future__ import annotations

import subprocess

from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup

from harnessed import aoe, launcher


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
        return [a for a in self.calls if a[0] == "add"]

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
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert calls == []


class TestSyncSession:
    def test_registers_profile_group_and_session(self, rec, tmp_path):
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert ("group", "create") in rec.verbs()
        [add] = rec.added()
        assert add[1] == str(tmp_path)
        assert _flag(add, "-p") == aoe.PROFILE
        assert _flag(add, "--cmd-override") == f"harnessed launch serena claude {tmp_path}"

    def test_uses_cmd_override_not_cmd(self, rec, tmp_path):
        # `--cmd` is validated against aoe's tool list and silently substitutes its configured
        # default, which would destroy both the replay and the identity key.
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert "--cmd" not in rec.added()[0]

    def test_existing_profile_is_not_recreated(self, rec, tmp_path):
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert ("profile", "create") not in rec.verbs()

    def test_missing_profile_is_created(self, monkeypatch, tmp_path):
        rec = Recorder(profiles=PROFILE_LIST_EMPTY)
        rec.install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert ["profile", "create", aoe.PROFILE] in rec.calls

    def test_existing_group_is_not_recreated(self, monkeypatch, tmp_path):
        rec = Recorder(groups=f"Groups:\n\n• {tmp_path.name} (2 sessions)\n\nTotal: 1 groups\n")
        rec.install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert ("group", "create") not in rec.verbs()

    def test_pty_mode_is_forced(self, rec, tmp_path):
        # Cockpit's ACP transport cannot reach through the `podman exec` attach `launch` ends in.
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert "--no-cockpit" in rec.added()[0]

    def test_default_stack_is_skipped(self, rec, tmp_path):
        aoe.sync_session("launch", "default", "claude", tmp_path)
        assert rec.calls == []

    def test_title_carries_folder_harness_and_stack(self, rec, tmp_path):
        aoe.sync_session("launch", "serena", "omp", tmp_path)
        assert _flag(rec.added()[0], "-t") == f"{tmp_path.name} [omp/container] serena"


class TestTitleUniqueness:
    """aoe dedupes `add` on (title, path) and exits 0, so a title collision is a LOST row.

    That makes the title part of identity whether we like it or not: it must separate everything
    we treat as distinct. Regression cover for host-run registrations vanishing behind their
    `launch` twin.
    """

    def test_backend_is_part_of_the_title(self, tmp_path):
        container = aoe.title_for("launch", "serena", "claude", tmp_path)
        host = aoe.title_for("host-run", "serena", "claude", tmp_path)
        assert container != host

    def test_harness_is_part_of_the_title(self, tmp_path):
        assert aoe.title_for("launch", "serena", "claude", tmp_path) != aoe.title_for(
            "launch", "serena", "omp", tmp_path
        )

    def test_stack_is_part_of_the_title(self, tmp_path):
        assert aoe.title_for("launch", "serena", "claude", tmp_path) != aoe.title_for(
            "launch", "superpowers", "claude", tmp_path
        )

    def test_host_and_container_titles_do_not_collide_end_to_end(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        aoe.sync_session("host-run", "serena", "claude", tmp_path)
        titles = [_flag(a, "-t") for a in rec.added()]
        assert len(titles) == 2 and len(set(titles)) == 2, titles


class TestIdentity:
    """(path, stack, harness) per verb — the key that decides duplicate vs distinct."""

    def _existing(self, tmp_path: Path, command: str) -> str:
        return f'[{{"id": "s1", "path": "{tmp_path}", "command": "{command}"}}]'

    def test_relaunch_does_not_duplicate(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed launch serena claude {tmp_path}"))
        rec.install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert rec.added() == []

    def test_a_second_harness_is_a_second_session(self, monkeypatch, tmp_path):
        # One stack has an assembled profile PER harness, so claude and omp are two rows.
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed launch serena claude {tmp_path}"))
        rec.install(monkeypatch)
        aoe.sync_session("launch", "serena", "omp", tmp_path)
        assert len(rec.added()) == 1

    def test_host_and_container_verbs_do_not_collide(self, monkeypatch, tmp_path):
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed launch serena claude {tmp_path}"))
        rec.install(monkeypatch)
        aoe.sync_session("host-run", "serena", "claude", tmp_path)
        assert len(rec.added()) == 1

    def test_same_stack_in_another_folder_is_a_second_session(self, monkeypatch, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        rec = Recorder(sessions=self._existing(tmp_path, f"harnessed launch serena claude {tmp_path}"))
        rec.install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", other)
        assert len(rec.added()) == 1


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


class TestForgetStack:
    SESSIONS = (
        '[{"id": "a", "command": "harnessed launch serena claude /p"},'
        ' {"id": "b", "command": "harnessed launch serena omp /p"},'
        ' {"id": "c", "command": "harnessed launch other claude /p"},'
        ' {"id": "d", "command": "harnessed host-run serena claude /p"}]'
    )

    def _rec(self, monkeypatch) -> Recorder:
        rec = Recorder(sessions=self.SESSIONS)
        rec.install(monkeypatch)
        return rec

    def test_removes_every_harness_of_the_named_stack(self, monkeypatch):
        rec = self._rec(monkeypatch)
        aoe.forget_stack("launch", "serena")
        assert sorted(rec.removed()) == ["a", "b"]

    def test_leaves_other_stacks_and_the_host_verb_alone(self, monkeypatch):
        # `harnessed rm` tears down CONTAINERS; a host-native session owns none.
        rec = self._rec(monkeypatch)
        aoe.forget_stack("launch", "serena")
        assert "c" not in rec.removed()
        assert "d" not in rec.removed()

    def test_no_op_without_aoe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(aoe, "_bin", lambda: None)
        monkeypatch.setattr(aoe, "_run", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(aoe, "_spawn", lambda *a, **k: calls.append(a))
        aoe.forget_stack("launch", "serena")
        assert calls == []


class TestNeverRaises:
    """A dashboard is not worth failing a launch over."""

    @pytest.mark.parametrize("exc", [OSError("boom"), subprocess.TimeoutExpired("aoe", 10), ValueError("x")])
    def test_sync_swallows_subprocess_failure(self, monkeypatch, tmp_path, exc):
        monkeypatch.setattr(aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(aoe, "_run", lambda *a: (_ for _ in ()).throw(exc))
        aoe.sync_session("launch", "serena", "claude", tmp_path)

    def test_forget_swallows_subprocess_failure(self, monkeypatch):
        monkeypatch.setattr(aoe, "_bin", lambda: "/usr/bin/aoe")
        monkeypatch.setattr(aoe, "_run", lambda *a: (_ for _ in ()).throw(OSError("boom")))
        aoe.forget_stack("launch", "serena")

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
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert [a[0] for a in rec.spawned] == ["group", "add"]

    def test_reads_never_go_through_the_detached_path(self, rec, tmp_path):
        aoe.sync_session("launch", "serena", "claude", tmp_path)
        assert not any(a[:2] in (["list", "--json"], ["group", "list"]) for a in rec.spawned)

    def test_blocking_mode_runs_writes_inline(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        aoe.sync_session("launch", "serena", "claude", tmp_path, background=False)
        assert rec.spawned == []
        assert [a[0] for a in rec.added()] == ["add"]

    def test_blocking_mode_reports_a_failed_write(self, monkeypatch, tmp_path):
        rec = Recorder().install(monkeypatch)
        monkeypatch.setattr(
            aoe, "_run",
            lambda exe, args, **k: rec.run(exe, args) if args[1:2] == ["list"] else _fail(),
        )
        assert aoe.sync_session("launch", "serena", "claude", tmp_path, background=False) is False

    def test_detached_dispatch_is_reported_as_success(self, rec, tmp_path):
        assert aoe.sync_session("launch", "serena", "claude", tmp_path) is True

    def test_already_registered_is_success_without_writing(self, monkeypatch, tmp_path):
        rec = Recorder(
            sessions=f'[{{"id": "s1", "path": "{tmp_path}",'
                     f' "command": "harnessed launch serena claude {tmp_path}"}}]'
        ).install(monkeypatch)
        assert aoe.sync_session("launch", "serena", "claude", tmp_path) is True
        assert rec.spawned == []

    def test_unavailable_aoe_is_reported_as_failure(self, monkeypatch, tmp_path):
        # What `--create-aoe-only` turns into a non-zero exit.
        monkeypatch.setattr(aoe, "_bin", lambda: None)
        assert aoe.sync_session("launch", "serena", "claude", tmp_path) is False

    def test_skipped_stack_is_reported_as_failure(self, rec, tmp_path):
        assert aoe.sync_session("launch", "default", "claude", tmp_path) is False

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

        def fake_sync(verb, stack, harness, project_path, *, background=True):
            seen.update(verb=verb, stack=stack, harness=harness, background=background)
            return ok

        monkeypatch.setattr(launcher.aoe, "sync_session", fake_sync)
        seen["exit"] = None
        try:
            launcher._aoe_register("launch", "serena", "claude", Path("/p"), only=only)
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

    @pytest.mark.parametrize("verb", ["launch", "run", "host-run"])
    def test_every_launch_verb_accepts_the_flag(self, verb):
        """Assert on the PARAMETER, not on rendered `--help`.

        Help text is laid out by rich against the terminal width and painted with ANSI, so an
        earlier version of this test passed locally and failed in CI purely because the flag name
        wrapped. The declaration is what the assertion is actually about.
        """
        group = typer.main.get_command(launcher.app)
        assert isinstance(group, TyperGroup)  # narrows to the .commands mapping
        assert any("--create-aoe-only" in p.opts for p in group.commands[verb].params)


class TestCommandFor:
    def test_quotes_paths_with_spaces(self):
        cmd = aoe.command_for("launch", "serena", "claude", Path("/tmp/my project"))
        assert cmd == "harnessed launch serena claude '/tmp/my project'"

    def test_records_the_resolved_stack_name(self):
        # Dynamic stacks are minted before this is called, so the derived name replays exactly.
        cmd = aoe.command_for("run", "default.serena.superpowers", "claude", Path("/p"))
        assert cmd == "harnessed run default.serena.superpowers claude /p"
