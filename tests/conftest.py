"""Shared pytest fixtures."""

import os

import pytest

# MODULE LEVEL, NOT A FIXTURE — and that is the whole point. `rich` reads FORCE_COLOR when a
# `Console` is CONSTRUCTED, and launcher.py builds `_out`/`_err` at module import. An autouse
# fixture runs after that import and is therefore too late; it was tried and did not work.
# conftest.py is imported before any test module, so popping it here is early enough.
#
# Why it matters: rich emits plain text when stdout is not a TTY, which is the case under typer's
# `CliRunner`. FORCE_COLOR overrides that check, so ANSI escapes land INSIDE the captured output and
# any assertion on a plain substring fails — `"no such stack 'x'"` is not in
# `"\x1b[1;31merror:\x1b[0m no such stack \x1b[32m'x'\x1b[0m"`. Terminal shell-integration sets it
# (Ghostty exports FORCE_COLOR=3), so a developer hits this having never opted in, while CI — a bare
# environment — is green the whole time. Same machine-dependence class as `_isolated_user_catalog`.
#
# NOT `NO_COLOR`: that would suppress color the tests never asked about, diverging from CI in the
# other direction. The goal is parity with a plain environment, not forced monochrome.
os.environ.pop("FORCE_COLOR", None)


@pytest.fixture(autouse=True)
def _isolated_user_catalog(monkeypatch, tmp_path_factory):
    """Point $XDG_CONFIG_HOME at an empty dir for every test, so the suite is hermetic.

    `paths.catalog_roots()` puts the user overlay ($XDG_CONFIG_HOME/harnessed/catalog) AHEAD of the
    repo catalog, and the overlay wins on a name clash. Without this fixture, any test that resolves
    a stack/recipe by name silently reads whatever the developer happens to have in
    ~/.config/harnessed/catalog — so the suite's result depends on the machine it runs on. A
    developer whose overlay defines a stack that shadows a repo stack name gets a phantom failure
    (the test discovers the name from the repo catalog, then resolves it out of the overlay and
    asserts against the wrong stack). CI, with no overlay, passes the whole time.

    An empty XDG root means `user_catalog()` doesn't exist, so `catalog_roots()` falls back to the
    repo catalog alone and name resolution is deterministic.

    Tests that *want* an overlay (test_ensure_local_catalog_links, test_persist_*) set
    XDG_CONFIG_HOME themselves; their own monkeypatch runs after this one and overrides it.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))


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


