"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Give git a committer identity for every test.

    Several tests create throwaway repos and `git commit`. Locally that inherits
    the developer's `~/.gitconfig`, but CI runners have no global identity, so the
    commit fails with exit 128 ("Please tell me who you are"). Setting the GIT_*
    env vars satisfies git regardless of config and keeps the tests portable.
    """
    monkeypatch.setenv("GIT_AUTHOR_NAME", "harnessed-tests")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tests@harnessed.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "harnessed-tests")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tests@harnessed.local")
