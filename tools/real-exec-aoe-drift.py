#!/usr/bin/env python3
"""Real-execution check for aoe command-drift repair (bd harnessed-cn9).

Run from the repo root:  tools/real-exec-aoe-drift.py

The test suite mocks `_run`/`_spawn`, so no test in it ever touches aoe. This drives the real
binary, in a throwaway profile it creates and deletes. It exists because the mocked suite was
GREEN, 8/8 mutants killed, and the repair was still wrong: the first implementation removed the
drifted row and re-added it, and against the real aoe that loses the row and writes nothing in
its place, because `aoe remove` only trashes a row and a trashed row still holds the (title, path)
key aoe dedupes on. Green tests said nothing about that. This did.

Requires `aoe` on PATH and initialised. Prints a verdict per property; exits non-zero if any fails.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from harnessed import aoe  # noqa: E402

SCRATCH = "harnessed-cn9-realexec"


def sh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["aoe", *args], capture_output=True, text=True)


def rows() -> list[dict]:
    try:
        return json.loads(sh("list", "--json", "-p", SCRATCH).stdout)
    except json.JSONDecodeError:
        return []


def show(label: str) -> None:
    print(f"  {label}: " + " | ".join(f"{r['title']!r} -> {r['command']!r}" for r in rows()))


def main() -> int:
    if shutil.which("aoe") is None:
        print("SKIP: aoe is not on PATH")
        return 0

    workdir = Path(tempfile.mkdtemp(prefix="harnessed-cn9-"))
    proj = workdir / "cn9proj"
    proj.mkdir()
    aoe.PROFILE = SCRATCH  # scope every write to the throwaway workspace
    sh("profile", "create", SCRATCH)

    try:
        title = aoe.title_for("host-run", "serena", "claude", proj)
        stale_cmd = "harnessed host-run claude /some/old/path --"
        print(f"1. seeding a drifted row: {title!r} -> {stale_cmd!r}")
        sh("add", str(proj), "-p", SCRATCH, "-g", "grp", "-t", title, "--cmd-override", stale_cmd)
        show("before")

        print("2. sync_session, blocking so the writes are real and their status is checked")
        reports: list[tuple[str, bool]] = []
        ok = aoe.sync_session(
            "host-run", "serena", "claude", proj, background=False,
            on_drift=lambda m, r: reports.append((m, r)),
        )
        print(f"   returned: {ok}")
        for message, repairing in reports:
            print(f"   reported (repairing={repairing}):")
            for line in message.splitlines():
                print(f"     {line}")
        show("after")

        print("3. relaunching must converge: no second report, no duplicate row")
        aoe.sync_session("host-run", "serena", "claude", proj, background=False,
                         on_drift=lambda m, r: reports.append((m, r)))
        show("after relaunch")

        current = rows()
        checks = {
            "drift was reported exactly once": len(reports) == 1,
            "correct row registered": [r["command"] for r in current].count(
                aoe.mise_command("claude")) == 1,
            "stale row preserved with its command": [r["command"] for r in current].count(
                stale_cmd) == 1,
            "stale row renamed, not deleted": any(
                r["command"] == stale_cmd and r["title"] != title for r in current),
            "no duplicate rows after relaunch": len(current) == 2,
        }
    finally:
        subprocess.run(["bash", "-c", f"yes | aoe profile delete {SCRATCH}"],
                       capture_output=True, text=True)
        shutil.rmtree(workdir, ignore_errors=True)

    checks["scratch profile deleted"] = SCRATCH not in sh("profile", "list").stdout
    print("\nVERDICT")
    for label, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
