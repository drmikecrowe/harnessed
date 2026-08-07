"""A git lookup that cannot COMPLETE is not the same as one that finds no repository.

bd harnessed-654. `paths.git_common_dir` returned None for both, and `project_env_path` fell back to
the project path in either case — so a transient git failure produced a DIFFERENT key than the
launch had written, and every consumer of that path failed silently. mise and direnv both ignore a
missing env file, so the tools simply came up unconfigured with nothing to explain why.

What is an ANSWER (stable, fallback is safe): not a repository, git not installed, the directory
does not exist. What is a FAILURE (transient, fallback is a guess): a timeout, a permission error,
an unrecognised git error, or a common dir git names that is not there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessed import launcher, paths, setupenv

runner = CliRunner()


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    return tmp_path / "r"


class TestAnswersDoNotRaise:
    def test_a_real_repo_returns_its_common_dir(self, repo):
        assert paths.git_common_dir_checked(repo) is not None

    def test_a_non_repo_directory_is_none(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert paths.git_common_dir_checked(plain) is None

    def test_a_missing_directory_is_none(self, tmp_path):
        """`git -C` cannot chdir there and will not be able to next time either — stable, so the
        caller's fallback is stable. git's stderr says "cannot change to" and never mentions a
        repository, which is why this is checked directly rather than matched out of stderr."""
        assert paths.git_common_dir_checked(tmp_path / "nope") is None

    def test_git_not_installed_is_none(self, tmp_path, monkeypatch):
        """Stable across calls, so the fallback it triggers is stable too."""
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.setattr(
            paths.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
        )
        assert paths.git_common_dir_checked(plain) is None


class TestFailuresRaise:
    def _explode(self, monkeypatch, exc):
        monkeypatch.setattr(
            paths.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(exc)
        )

    def test_a_timeout_raises(self, repo, monkeypatch):
        self._explode(monkeypatch, subprocess.TimeoutExpired(cmd="git", timeout=5))
        with pytest.raises(paths.GitLookupFailed):
            paths.git_common_dir_checked(repo)

    def test_an_unrecognised_git_error_raises(self, repo, monkeypatch):
        """Only "not a git repository" is an answer. Anything else git failed on is a failure."""
        self._explode(monkeypatch, subprocess.CalledProcessError(
            128, "git", stderr="fatal: detected dubious ownership"
        ))
        with pytest.raises(paths.GitLookupFailed):
            paths.git_common_dir_checked(repo)

    def test_a_permission_error_raises(self, repo, monkeypatch):
        self._explode(monkeypatch, PermissionError("nope"))
        with pytest.raises(paths.GitLookupFailed):
            paths.git_common_dir_checked(repo)

    def test_a_common_dir_that_does_not_exist_raises(self, repo, monkeypatch):
        """Not "no repo" — something is wrong underneath, and keying on the fallback is a guess."""
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            "git", 0, stdout="/definitely/not/here\n", stderr=""
        ))
        with pytest.raises(paths.GitLookupFailed):
            paths.git_common_dir_checked(repo)


class TestTheLossyWrapperIsUnchanged:
    """Fifteen-odd callers only want "a repo root if there is one" and must need no error handling."""

    def test_it_swallows_a_failure(self, repo, monkeypatch):
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="git", timeout=5)
        ))
        assert paths.git_common_dir(repo) is None

    def test_it_still_answers_for_a_real_repo(self, repo):
        assert paths.git_common_dir(repo) == paths.git_common_dir_checked(repo)


class TestProjectEnvPathRefusesToGuess:
    def test_it_propagates_the_failure(self, repo, monkeypatch):
        monkeypatch.setattr(paths, "git_common_dir_checked", lambda _p: (_ for _ in ()).throw(
            paths.GitLookupFailed("boom")
        ))
        with pytest.raises(paths.GitLookupFailed):
            setupenv.project_env_path(repo)

    def test_the_cli_prints_nothing_and_exits_non_zero(self, repo, monkeypatch):
        """The caller is a shell substitution in someone's env loader: a path printed here is used
        without question, so a plausible-looking wrong one is worse than none."""
        monkeypatch.setattr(paths, "git_common_dir_checked", lambda _p: (_ for _ in ()).throw(
            paths.GitLookupFailed("boom")
        ))
        result = runner.invoke(launcher.app, ["project-env-path", str(repo)])
        assert result.exit_code == 1
        assert not [ln for ln in result.stdout.splitlines() if ln.startswith("/")]

    def test_a_launch_survives_and_says_so(self, repo, monkeypatch, capsys):
        """The agent gets this env directly and always did — only the plain-shell copy is lost."""
        from support import patch_all

        patch_all(monkeypatch, "load_stack_with_recipes", lambda root, stack: (None, []))
        patch_all(monkeypatch, "_recipe_env", lambda *a, **k: {"BEADS_DIR": "/p/.beads"})
        patch_all(monkeypatch, "svc_client_env", lambda *a, **k: {})
        monkeypatch.setattr(paths, "git_common_dir_checked", lambda _p: (_ for _ in ()).throw(
            paths.GitLookupFailed("boom")
        ))
        launcher._write_project_tool_env(
            "s", repo, harness="claude", verb="host-run"
        )  # must not raise
        assert "was not written" in capsys.readouterr().out
