"""`mise.local.toml` — the project gets the same tool env the agent gets.

harnessed configured the agent it launched and nothing else in the repo. Everything else — a `bd`
you run in a terminal, a `claude` you started yourself, a hook — saw none of it. On 2026-07-27 three
live agents in one project had zero BEADS_ variables between them, so each fell back to bd's
auto-start and each hit the sidecar's exclusive lock.

Two properties carry the design, and both are the kind a later refactor breaks without noticing:
the secret must stay OUT of the repo, and a user's own mise config must never be rewritten.
"""

from __future__ import annotations

import tomllib

import pytest

from harnessed import launcher, paths
from support import patch_all
from harnessed import setupenv


@pytest.fixture
def project(tmp_path, monkeypatch):
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
