"""`mise.local.toml` — the project gets the same tool env the agent gets.

harnessed configured the agent it launched and nothing else in the repo. Everything else — a `bd`
you run in a terminal, a `claude` you started yourself, a hook — saw none of it. On 2026-07-27 three
live agents in one project had zero BEADS_ variables between them, so each fell back to bd's
auto-start and each hit the sidecar's exclusive lock.

Two properties carry the design, and both are the kind a later refactor breaks without noticing:
the secret must stay OUT of the repo, and a user's own mise config must never be rewritten.
"""

from __future__ import annotations

import pytest

from harnessed import launcher, paths


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, stack: (None, []))
    monkeypatch.setattr(launcher, "_recipe_env", lambda *a, **k: {"BEADS_DIR": "/p/.beads"})
    monkeypatch.setattr(
        launcher, "svc_client_env",
        lambda *a, **k: {"BEADS_DOLT_SERVER_PORT": "41234", "BEADS_DOLT_PASSWORD": "s3cret-token"},
    )
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj


def _env_file(tmp_path):
    return next((tmp_path / "state" / "harnessed" / "project-env").glob("*.env"))


class TestSecretPlacement:
    def test_the_password_never_lands_in_the_repo(self, project, tmp_path):
        """A secret in the source tree is one `git add -f`, one backup, one tree-walking tool away
        from leaving the machine. Gitignored is not the same guarantee as not being there."""
        launcher._write_project_tool_env("s", project)
        assert "s3cret-token" not in (project / "mise.local.toml").read_text()
        assert "s3cret-token" in _env_file(tmp_path).read_text()

    def test_the_env_file_is_owner_only(self, project, tmp_path):
        launcher._write_project_tool_env("s", project)
        f = _env_file(tmp_path)
        assert f.stat().st_mode & 0o077 == 0
        assert f.parent.stat().st_mode & 0o077 == 0

    def test_mise_local_points_at_the_env_file(self, project, tmp_path):
        launcher._write_project_tool_env("s", project)
        assert f'_.file = "{_env_file(tmp_path)}"' in (project / "mise.local.toml").read_text()


class TestExistingConfigIsUntouched:
    def test_a_users_mise_local_is_never_rewritten(self, project, capsys):
        """TOML has no safe blind-append — a second `[env]` table is a parse error — and silently
        reformatting someone's config is a worse bug than the one this fixes."""
        mine = '[tools]\nnode = "24"\n'
        (project / "mise.local.toml").write_text(mine)
        launcher._write_project_tool_env("s", project)
        assert (project / "mise.local.toml").read_text() == mine
        assert "_.file" in capsys.readouterr().out, "must tell the user what to add"

    def test_a_second_launch_is_idempotent(self, project):
        launcher._write_project_tool_env("s", project)
        first = (project / "mise.local.toml").read_text()
        launcher._write_project_tool_env("s", project)
        assert (project / "mise.local.toml").read_text() == first


class TestHousekeeping:
    def test_mise_local_is_gitignored(self, project, monkeypatch):
        seen = []
        monkeypatch.setattr(launcher, "_ensure_gitignore_entry", lambda p, n: seen.append(n))
        launcher._write_project_tool_env("s", project)
        assert seen == ["mise.local.toml"]

    def test_nothing_is_written_when_there_is_no_tool_env(self, project, monkeypatch):
        monkeypatch.setattr(launcher, "_recipe_env", lambda *a, **k: {})
        monkeypatch.setattr(launcher, "svc_client_env", lambda *a, **k: {})
        launcher._write_project_tool_env("s", project)
        assert not (project / "mise.local.toml").exists()

    def test_values_are_refreshed_on_every_launch(self, project, tmp_path, monkeypatch):
        """The env file is harnessed's, not the user's: a changed port must not need a manual edit."""
        launcher._write_project_tool_env("s", project)
        monkeypatch.setattr(
            launcher, "svc_client_env", lambda *a, **k: {"BEADS_DOLT_SERVER_PORT": "50000"}
        )
        launcher._write_project_tool_env("s", project)
        assert "BEADS_DOLT_SERVER_PORT=50000" in _env_file(tmp_path).read_text()
