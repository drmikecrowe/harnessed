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
import shutil
import subprocess

import pytest

from harnessed import aoe


SCRATCH = "harnessed-cn9-realexec"
STALE_COMMAND = "harnessed host-run claude /some/old/path --"

pytestmark = pytest.mark.skipif(
    shutil.which("aoe") is None, reason="aoe is not installed; the real-execution check needs it"
)


def _aoe(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["aoe", *args], capture_output=True, text=True, check=False)


def _rows() -> list[dict]:
    try:
        return json.loads(_aoe("list", "--json", "-p", SCRATCH).stdout)
    except json.JSONDecodeError:
        return []


@pytest.fixture
def drifted(tmp_path, monkeypatch):
    """A real aoe profile holding one row whose stored command has drifted."""
    monkeypatch.setattr(aoe, "PROFILE", SCRATCH)
    project = tmp_path / "cn9proj"
    project.mkdir()
    _aoe("profile", "create", SCRATCH)
    title = aoe.title_for("host-run", "serena", "claude", project)
    _aoe("add", str(project), "-p", SCRATCH, "-g", "grp", "-t", title,
         "--cmd-override", STALE_COMMAND)
    try:
        yield project, title
    finally:
        subprocess.run(["bash", "-c", f"yes | aoe profile delete {SCRATCH}"],
                       capture_output=True, text=True, check=False)


def _sync(project, reports):
    return aoe.sync_session(
        "host-run", "serena", "claude", project, background=False,
        on_drift=lambda message, repairing: reports.append((message, repairing)),
    )


def test_aoe_refuses_a_duplicate_title_and_path_at_exit_zero(drifted):
    """The premise the whole fix rests on. If this ever stops holding, the fix is pointless."""
    project, title = drifted
    result = _aoe("add", str(project), "-p", SCRATCH, "-g", "grp", "-t", title,
                  "--cmd-override", aoe.mise_command("claude"))
    assert result.returncode == 0, "a refused duplicate exits ZERO — that is what hid the bug"
    assert "already exists" in result.stdout + result.stderr
    assert [r["command"] for r in _rows()] == [STALE_COMMAND], "the stale row survived"


def test_repair_registers_the_correct_row_and_keeps_the_old_one(drifted):
    project, title = drifted
    reports: list[tuple[str, bool]] = []

    assert _sync(project, reports) is True
    assert len(reports) == 1 and reports[0][1] is True

    commands = [r["command"] for r in _rows()]
    assert commands.count(aoe.mise_command("claude")) == 1, "the correct row was registered"
    assert commands.count(STALE_COMMAND) == 1, "the stale row was kept, not deleted"
    assert any(r["command"] == STALE_COMMAND and r["title"] != title for r in _rows()), \
        "the stale row was renamed aside rather than removed"


def test_relaunching_after_a_repair_converges(drifted):
    """No second warning, no duplicate row — the repair has to be a fixed point."""
    project, _ = drifted
    reports: list[tuple[str, bool]] = []

    _sync(project, reports)
    _sync(project, reports)

    assert len(reports) == 1, "the second launch must find nothing to report"
    assert len(_rows()) == 2, "and must not add a third row"


def test_remove_would_not_have_worked(drifted):
    """Pins the reason repair is a rename. This is a claim about aoe, so aoe has to answer it.

    A docstring saying "remove does not work here" rots silently. This fails the day aoe changes
    its trash semantics, which is exactly when the repair strategy should be revisited.
    """
    project, title = drifted
    row_id = _rows()[0]["id"]

    assert _aoe("remove", row_id, "-p", SCRATCH).returncode == 0
    assert any(r["id"] == row_id for r in _rows()), "a trashed row still comes back from list --json"

    refused = _aoe("add", str(project), "-p", SCRATCH, "-g", "grp", "-t", title,
                   "--cmd-override", aoe.mise_command("claude"))
    assert "already exists" in refused.stdout + refused.stderr, \
        "a trashed row still holds the (title, path) key, so remove+add loses the row entirely"
