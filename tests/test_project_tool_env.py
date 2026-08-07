"""The project tool env — the project gets the same tool env the agent gets, with NOTHING in the repo.

harnessed configured the agent it launched and nothing else in the repo. Everything else — a `bd`
you run in a terminal, a `claude` you started yourself, a hook — saw none of it. On 2026-07-27 three
live agents in one project had zero BEADS_ variables between them, so each fell back to bd's
auto-start and each hit the sidecar's exclusive lock.

This used to be delivered by a `mise.local.toml` harnessed wrote into every project. That file is
gone (bd harnessed-7mt): mise keys trust per config FILE and trust does not cascade from a trusted
ancestor, so a file dropped into each repo re-prompted in every new worktree. Automating the trust
was rejected — a mise config can carry `_.source`, so trusting one grants code execution.

Three properties carry the design now, and each is the kind a later refactor breaks without
noticing: the secret stays OUT of the repo, NOTHING is written into the repo at all, and the path
a project's env lives at is computable from the project alone (which is what lets one line in the
user's global mise config serve every project).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from harnessed import launcher, paths, setupenv
from support import patch_all

runner = CliRunner()


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


class TestSecretPlacement:
    def test_the_password_never_lands_in_the_repo(self, project, tmp_path):
        """A secret in the source tree is one `git add -f`, one backup, one tree-walking tool away
        from leaving the machine. Gitignored is not the same guarantee as not being there."""
        _write(project)
        assert "s3cret-token" in _env_file(tmp_path).read_text()
        assert not any("s3cret-token" in p.read_text() for p in project.rglob("*") if p.is_file())

    def test_the_env_file_is_owner_only(self, project, tmp_path):
        _write(project)
        f = _env_file(tmp_path)
        assert f.stat().st_mode & 0o077 == 0
        assert f.parent.stat().st_mode & 0o077 == 0

    def test_values_are_refreshed_on_every_launch(self, project, tmp_path, monkeypatch):
        _write(project)
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {"BEADS_DOLT_SERVER_PORT": "9999"})
        _write(project)
        assert "9999" in _env_file(tmp_path).read_text()


class TestNothingIsWrittenIntoTheRepo:
    """THE property this change bought (bd harnessed-7mt). A launch must leave the working tree
    byte-for-byte as it found it — no config, no gitignore entry, no trust prompt."""

    def test_the_project_directory_is_untouched(self, project):
        _write(project)
        assert list(project.iterdir()) == []

    def test_no_mise_local_is_created(self, project):
        _write(project)
        assert not (project / "mise.local.toml").exists()

    def test_no_gitignore_entry_is_added(self, project):
        """There is no longer anything to ignore, and writing to someone's .gitignore for a file we
        do not create is pure noise in their diff."""
        _write(project)
        assert not (project / ".gitignore").exists()

    def test_a_users_own_mise_local_is_never_rewritten(self, project):
        """The guarantee that survived the removal: harnessed does not write your mise config."""
        mine = '[tools]\nnode = "22"\n'
        (project / "mise.local.toml").write_text(mine)
        _write(project)
        assert (project / "mise.local.toml").read_text() == mine


class TestProjectEnvPath:
    """Pure and computable from the project alone — what lets ONE line in the user's global mise
    config (`_.file = "{{ exec(command='harnessed project-env-path ' ~ cwd) }}"`) serve every
    project instead of a file per repo."""

    def test_it_creates_nothing(self, project, tmp_path):
        """Called on every directory the user cd's into, so a side effect here would be a side
        effect everywhere."""
        setupenv.project_env_path(project)
        assert not (tmp_path / "state").exists()

    def test_it_answers_for_a_project_with_no_env(self, tmp_path):
        """mise tolerates a missing `_.file` silently, so an unlaunched directory must still get a
        path rather than an error — that silence is what makes the global line safe."""
        assert setupenv.project_env_path(tmp_path / "never-launched").suffix == ".env"

    def test_it_matches_what_a_launch_actually_wrote(self, project, tmp_path):
        _write(project)
        assert setupenv.project_env_path(project) == _env_file(tmp_path)

    def test_worktrees_of_one_checkout_share_an_env(self, tmp_path, monkeypatch):
        """Keyed on git_common_dir: worktrees differ in what they build, never in which tools the
        project needs."""
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: tmp_path / "repo.git")
        a, b = tmp_path / "wt-a", tmp_path / "wt-b"
        assert setupenv.project_env_path(a) == setupenv.project_env_path(b)


class TestTheCliCommand:
    def test_it_prints_the_path(self, project, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        result = runner.invoke(launcher.app, ["project-env-path", str(project)])
        assert result.exit_code == 0
        assert result.output.strip().endswith(".env")

    def test_it_prints_one_bare_line(self, project, tmp_path, monkeypatch):
        """The output is consumed by mise's `exec()` as a filename, so it must survive verbatim.

        REGRESSION PIN: this was `_out.print`, and rich hard-wraps at the terminal width — a path
        longer than the window came back with a newline in the middle of it. mise tolerates a
        missing `_.file`, so the project env would simply never load and nothing would say why.
        A deep tmp_path is what makes the line long enough to have wrapped.
        """
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        result = runner.invoke(launcher.app, ["project-env-path", str(project)])
        assert len(result.output.strip().splitlines()) == 1
        assert result.output.strip() == str(setupenv.project_env_path(project))

    def test_a_bracket_in_the_path_survives(self, tmp_path, monkeypatch):
        """The other half of the same bug: rich reads `[...]` as markup and eats the span."""
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        bracketed = tmp_path / "proj [wt]"
        bracketed.mkdir()
        result = runner.invoke(launcher.app, ["project-env-path", str(bracketed)])
        assert result.output.strip() == str(setupenv.project_env_path(bracketed))


class TestStaleFileFromAnOlderHarnessed:
    """A `mise.local.toml` an older harnessed wrote is REPORTED, never deleted. It is in the user's
    repo and may since have been edited; removing it to complete our own migration is the
    "harnessed does not write your mise config" guarantee running backwards."""

    def test_ours_is_reported(self, project, capsys):
        (project / "mise.local.toml").write_text("# managed by harnessed\n")
        _write(project)
        assert "older harnessed" in capsys.readouterr().out

    def test_ours_is_not_deleted(self, project):
        (project / "mise.local.toml").write_text("# managed by harnessed\n")
        _write(project)
        assert (project / "mise.local.toml").exists()

    def test_a_file_that_was_never_ours_is_not_mentioned(self, project, capsys):
        """They never had our file and have nothing to clean up."""
        (project / "mise.local.toml").write_text('[tools]\nnode = "22"\n')
        _write(project)
        assert "older harnessed" not in capsys.readouterr().out

    def test_a_non_utf8_file_does_not_abort_the_launch(self, project):
        """UnicodeDecodeError is a ValueError, not an OSError, so it needed naming separately
        (found by CodeRabbit). The file is the user's and may be in any encoding; an advisory
        notice that cannot read it must stay silent rather than kill the launch."""
        (project / "mise.local.toml").write_bytes(b"\xff\xfe not utf-8 at all")
        _write(project)  # must not raise

    def test_the_notice_says_what_deleting_costs(self, project, capsys):
        """"Safe to delete" alone was wrong for both audiences: `mise run <harness>` stops
        existing, and a shell fed by the pointer goes unconfigured. Both losses are silent."""
        (project / "mise.local.toml").write_text("# managed by harnessed\n")
        _write(project)
        out = capsys.readouterr().out
        assert "--last" in out and "project-env-path" in out
