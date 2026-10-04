"""Drift repair against the REAL `aoe` binary, not the mocked seam (bd harnessed-cn9).

Every other aoe test patches `_run`/`_spawn`, so none of them touches aoe. That gap is not
theoretical: the first implementation of this repair removed the drifted row and re-added it, the
mocked suite was green, every mutant died, and the repair could not work — `aoe remove` only
trashes a row, a trashed row still comes back from `aoe list --json`, and it still holds the
(title, path) key aoe dedupes on, so the replacement `add` is refused at exit 0 too. Only running
the binary showed it.

Skipped when `aoe` is absent, so it is free in CI and real on a developer machine. Everything it
writes goes to a throwaway profile it creates and deletes; the user's own aoe workspace is never
touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from harnessed import aoe, launchscript


STALE_COMMAND = "harnessed host-run claude /some/old/path --"

pytestmark = pytest.mark.skipif(
    shutil.which("aoe") is None, reason="aoe is not installed; the real-execution check needs it"
)


def _aoe(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["aoe", *args], capture_output=True, text=True, check=False)


def _rows(profile: str) -> list[dict]:
    try:
        return json.loads(_aoe("list", "--json", "-p", profile).stdout)
    except json.JSONDecodeError:
        return []


@pytest.fixture
def drifted(tmp_path, monkeypatch):
    """A real aoe profile holding one row whose stored command has drifted."""
    # Generate a unique name so parallel test workers and a developer's own aoe workspace
    # cannot share or clobber this fixture's profile.
    profile = f"harnessed-cn9-realexec-{uuid4().hex[:8]}"
    monkeypatch.setattr(aoe, "PROFILE", profile)
    project = tmp_path / "cn9proj"
    project.mkdir()
    _aoe("profile", "create", profile)
    title = aoe.title_for("host-run", "serena", "claude", project)
    _aoe("add", str(project), "-p", profile, "-g", "grp", "-t", title,
         "--cmd-override", STALE_COMMAND)
    try:
        yield project, title, profile
    finally:
        subprocess.run(["bash", "-c", f"yes | aoe profile delete {profile}"],
                       capture_output=True, text=True, check=False)


def _sync(project, reports):
    return aoe.sync_session(
        "host-run", "serena", "claude", project, background=False,
        on_drift=lambda message, repairing: reports.append((message, repairing)),
    )


def test_aoe_refuses_a_duplicate_title_and_path(drifted):
    """The premise the whole fix rests on. If this ever stops holding, the fix is pointless.

    THE EXIT CODE IS DELIBERATELY NOT ASSERTED. aoe 1.13.2 refused at exit 0; aoe 1.14.1 refuses at
    exit 1. Pinning either one makes this test a version check rather than a behavior check, and
    `sync_session` no longer reads that code — it re-reads the session list instead, precisely so
    the next change here cannot turn a working registration into a reported failure.

    What matters, and what is asserted: the add is REFUSED and the stale row SURVIVES. That is what
    makes a remove-then-add strategy lose the row, and it is why the repair is a rename.
    """
    project, title, profile = drifted
    result = _aoe("add", str(project), "-p", profile, "-g", "grp", "-t", title,
                  "--cmd-override", aoe.replay_command("host-run", "serena", "claude", project))
    assert "already exists" in result.stdout + result.stderr
    assert [r["command"] for r in _rows(profile)] == [STALE_COMMAND], "the stale row survived"


def test_repair_registers_the_correct_row_and_keeps_the_old_one(drifted):
    project, title, profile = drifted
    reports: list[tuple[str, bool]] = []

    assert _sync(project, reports) is True
    assert len(reports) == 1 and reports[0][1] is True

    commands = [r["command"] for r in _rows(profile)]
    assert commands.count(aoe.replay_command("host-run", "serena", "claude", project)) == 1, "the correct row was registered"
    assert commands.count(STALE_COMMAND) == 1, "the stale row was kept, not deleted"
    assert any(r["command"] == STALE_COMMAND and r["title"] != title for r in _rows(profile)), \
        "the stale row was renamed aside rather than removed"


def test_relaunching_after_a_repair_converges(drifted):
    """No second warning, no duplicate row — the repair has to be a fixed point."""
    project, _, profile = drifted
    reports: list[tuple[str, bool]] = []

    _sync(project, reports)
    _sync(project, reports)

    assert len(reports) == 1, "the second launch must find nothing to report"
    assert len(_rows(profile)) == 2, "and must not add a third row"


def test_remove_would_not_have_worked(drifted):
    """Pins the reason repair is a rename. This is a claim about aoe, so aoe has to answer it.

    A docstring saying "remove does not work here" rots silently. This fails the day aoe changes
    its trash semantics, which is exactly when the repair strategy should be revisited.

    The trashed row coming back from `list --json` is also why `_sessions` subtracts
    `session list-trash` — see `test_a_trashed_row_is_not_a_live_row` below.
    """
    project, title, profile = drifted
    row_id = _rows(profile)[0]["id"]

    assert _aoe("remove", row_id, "-p", profile).returncode == 0
    assert any(r["id"] == row_id for r in _rows(profile)), "a trashed row still comes back from list --json"

    refused = _aoe("add", str(project), "-p", profile, "-g", "grp", "-t", title,
                   "--cmd-override", aoe.replay_command("host-run", "serena", "claude", project))
    assert "already exists" in refused.stdout + refused.stderr, \
        "a trashed row still holds the (title, path) key, so remove+add loses the row entirely"


def test_a_trashed_row_is_not_a_live_row(drifted):
    """`_sessions` must not hand a trashed row to `_registered`, and only aoe can prove it does not.

    aoe returns a trashed session from `list --json` with the same fields as a live one — no
    status, no `trashed_at`. Left in, deleting a row makes it impossible to recreate: the launch
    matches the trashed row, skips the `add`, and reports success over an empty dashboard.
    """
    _project, _, profile = drifted
    row_id = _rows(profile)[0]["id"]
    assert _aoe("remove", row_id, "-p", profile).returncode == 0

    assert any(r["id"] == row_id for r in _rows(profile)), \
        "precondition: aoe still lists the trashed row"
    assert all(s["id"] != row_id for s in aoe._sessions("aoe")), \
        "_sessions must subtract it"


def test_a_deleted_row_can_be_registered_again(drifted):
    """The user-visible half of the same bug: delete a row, relaunch, get the row back."""
    project, _, profile = drifted
    reports: list[tuple[str, bool]] = []
    assert _sync(project, reports) is True
    ours = aoe.replay_command("host-run", "serena", "claude", project)
    mine = [r for r in _rows(profile) if r["command"] == ours]
    assert len(mine) == 1

    assert _aoe("rm", "--purge", mine[0]["id"], "-p", profile).returncode == 0
    assert not [r for r in _rows(profile) if r["command"] == ours], "precondition: it is gone"

    assert _sync(project, []) is True, "a relaunch must register it again"
    assert len([r for r in _rows(profile) if r["command"] == ours]) == 1


def _git(*args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True,
    )


@pytest.fixture
def renamable(tmp_path, monkeypatch):
    """An ISOLATED aoe home with `tie_workdir_to_name` on, and a bare repo with one linked worktree.

    Isolated rather than a throwaway profile in the user's home, because the setting under test is
    global config: a run must not depend on, or change, how the developer has aoe configured.
    """
    cfg = tmp_path / "cfg"
    (cfg / "agent-of-empires").mkdir(parents=True)
    (cfg / "agent-of-empires" / "config.toml").write_text("[session]\ntie_workdir_to_name = true\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HARNESSED_NO_AOE", raising=False)
    profile = f"harnessed-544-realexec-{uuid4().hex[:8]}"
    monkeypatch.setattr(aoe, "PROFILE", profile)
    assert _aoe("profile", "create", profile).returncode == 0

    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "--bare", str(repo / ".bare"))
    (repo / ".git").write_text("gitdir: ./.bare\n")
    _git("-C", str(repo), "worktree", "add", "-q", "--orphan", "-b", "main", str(repo / "main"))
    _git("-C", str(repo / "main"), "commit", "-q", "--allow-empty", "-m", "init")
    worktree = repo / "1-GH-97-split"
    _git("-C", str(repo / "main"), "worktree", "add", "-q", "-b", "1-GH-97-split", str(worktree))
    return repo, worktree.resolve(), profile


def _launch(project, *, title: str) -> bool:
    """What the wrapper does on every launch: rewrite itself, then re-register under its baked title."""
    launchscript.write("host-run", "serena", "claude", project, group="spec-evidence", title=title)
    return aoe.sync_session(
        "host-run", "serena", "claude", project, background=False,
        group="spec-evidence", title=title, managed_worktree=True,
    )


def test_an_aoe_rename_leaves_the_row_launchable_and_unduplicated(renamable, tmp_path):
    """#544. A rename with `tie_workdir_to_name` moves the worktree; the row must survive it."""
    repo, worktree, profile = renamable
    assert _launch(worktree, title="se-1-GH-97-split") is True
    [row] = _rows(profile)
    assert row["worktree"]["managed_by_aoe"] is True, "D4: marked AOE-managed with no script"

    renamed = _aoe("session", "rename", row["id"], "-t", "4-GH-97-jira-split", "-p", profile)
    assert renamed.returncode == 0, renamed.stderr
    moved = repo / "4-gh-97-jira-split"
    assert moved.is_dir() and not worktree.exists(), "precondition: aoe moved the worktree"
    [row] = _rows(profile)
    assert Path(row["path"]).resolve() == moved.resolve()

    # D1: start the row the way aoe does, cwd at the row's path, with a stand-in harnessed.
    fake = tmp_path / "bin"
    fake.mkdir()
    record = tmp_path / "argv.txt"
    (fake / "harnessed").write_text(f'#!/bin/sh\npwd -P > {record}\nprintf "%s\\n" "$@" >> {record}\n')
    (fake / "harnessed").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    subprocess.run(["sh", "-c", row["command"]], cwd=row["path"], env=env, check=True)
    recorded = record.read_text().split("\n")
    assert recorded[0] == str(moved.resolve()), "the wrapper ran from the moved folder"
    assert recorded[1:4] == ["host-run", "claude", "."], "and named that folder, not the old one"

    # D2: the wrapper still bakes the OLD title; the relaunch must find the renamed row anyway.
    assert _launch(moved, title="se-1-GH-97-split") is True
    assert len(_rows(profile)) == 1, "no duplicate row"


def test_a_stale_absolute_command_is_repaired_in_place(renamable):
    """D3. A row from before #544 records an absolute script path, which dies with a move."""
    _repo, worktree, profile = renamable
    _launch(worktree, title="se-x")
    [row] = _rows(profile)
    stale = f"{worktree.parent / 'gone'}/claude-serena-host --"
    assert aoe._rewrite_row(row["id"], lambda r: r.update(command=stale)) is None
    assert _rows(profile)[0]["command"] == stale, "precondition"

    reports: list[tuple[str, bool]] = []
    assert aoe.sync_session(
        "host-run", "serena", "claude", worktree, background=False,
        group="spec-evidence", title="se-x",
        on_drift=lambda message, repairing: reports.append((message, repairing)),
    ) is True
    [row] = _rows(profile)
    assert row["id"] and row["command"] == "./claude-serena-host --"
    assert len(reports) == 1 and reports[0][1] is True, "the repair is reported, never silent"
