"""Refuse to start a shared service that would corrupt or silently shadow existing data.

A service (design §3/§9) owns a data directory on the host. These guards run BEFORE it starts and
abort the launch when starting would be destructive: another process already serving that directory,
a lock held, a stale socket key, a database that is not the one the manifest names, or a placement
that changed since the data was written.

Each is an assertion about host state, not an action — they read the filesystem and raise. Starting,
stopping and health-checking the container stays in launcher.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from pathlib import Path

import typer

from . import paths
from .console import _err, _out
from .schema import ServiceDef

def _host_process_in_dir(exe: str, host_dir: Path) -> tuple[int, str] | None:
    """Find a HOST process named `exe` whose cwd is inside `host_dir`. None if there is none.

    Matching on cwd (not on the command line) is what makes this precise: a dolt sql-server chdirs
    into the data dir it locks, so cwd identifies the *contended resource*, whereas the port or db
    name on the command line does not.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # Other users' processes raise PermissionError here — not our contention to worry about.
            if not (entry / "cwd").resolve().is_relative_to(host_dir):
                continue
            if Path(os.readlink(entry / "exe")).name != exe:
                continue
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue  # the process exited mid-scan, or is not ours to inspect
        return int(entry.name), cmdline.strip()
    return None


def _assert_data_dir_unlocked(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort BEFORE starting a sidecar whose data dir is already locked by a host process.

    A `scope: project` service exists because it holds an exclusive on-disk lock over per-project
    data. The sidecar shape removes contention between CONTAINERS by construction — but a HOST
    process on the same data dir still wins the lock, and the sidecar then dies on startup. The
    symptom lands far from the cause: clients fail against a socket that was never created, and the
    engine's own advice ("start the server yourself") is unactionable inside an agent container that
    deliberately ships no engine binary. Catching it here keeps the diagnosis next to the problem.
    """
    if not svc.exclusive_lock:
        return
    holder = _host_process_in_dir(svc.exclusive_lock, host_dir.resolve())
    if holder is None:
        return
    pid, cmdline = holder
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot start: a host "
        f"'{svc.exclusive_lock}' process already holds {host_dir}"
    )
    _err.print(f"  PID {pid}: {cmdline}")
    _err.print("  Stop it and retry, or run this stack with --host so it uses that server instead.")
    raise typer.Exit(1)












def _placement_marker(project_path: Path) -> Path | None:
    """Where the active placement is recorded — inside the git COMMON dir, or None outside a repo.

    The git dir is deliberate on both counts: it is shared by every worktree of the checkout (so the
    record cannot disagree between them), and git never tracks its own internals, so this stays
    invisible — which `beads/stealth`, whose entire purpose is invisibility, requires.
    """
    gcd = paths.git_common_dir(project_path)
    return None if gcd is None else gcd / "harnessed-placement.json"


def _assert_placement_unchanged(svc: "ServiceDef", location: str, project_path: Path) -> None:
    """Abort when this service's data was last placed somewhere else, and record it when it was not.

    `_assert_placement_matches` catches only stealth-over-team, because the team dir sits at a known
    recipe-independent path while a stealth dir is keyed by recipe name plus a project hash — a team
    launch cannot enumerate where a stealth workspace might be. Recording the placement closes the
    other direction: whichever ran first leaves a note, and a later launch in the other placement is
    refused instead of silently starting a second, EMPTY workspace whose missing issues read as data
    loss.

    Deliberately not self-healing. Both placements may hold real data by the time they disagree, and
    picking one would discard the other; the user has to say which they meant.
    """
    marker = _placement_marker(project_path)
    if marker is None:
        return  # not a git checkout — nothing stable to key the record on
    try:
        seen = json.loads(marker.read_text()).get(svc.name)
    except (OSError, ValueError):
        seen = None
    if seen is not None and seen != location:
        _err.print(
            f"[bold red]error:[/bold red] service '{svc.name}' was last used with "
            f"'{seen}' placement, but this stack wants '{location}'"
        )
        _err.print("  Launching would start a second, empty workspace — your issues would simply")
        _err.print("  not appear. Use the stack matching the placement above, or, once you are sure")
        _err.print(f"  which copy you want, delete the record: rm {marker}")
        raise typer.Exit(1)
    if seen == location:
        return
    try:
        current = json.loads(marker.read_text()) if marker.is_file() else {}
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[svc.name] = location
    # Best-effort: this record only ever PREVENTS a future mistake, so failing to write it must not
    # take down the launch in front of us (a read-only git dir, or one that does not exist yet).
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass








def _service_container_status(rt: str, cname: str) -> str:
    """Container status ('running', 'exited', ...), or '' if the container is gone."""
    result = subprocess.run(
        [rt, "inspect", "-f", "{{.State.Status}}", cname],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _abort_dead_service(rt: str, cname: str, svc: "ServiceDef") -> None:
    """Report why a service container died and abort the launch.

    `podman run -d` returns 0 once the container is CREATED, so a service whose process dies a
    moment later leaves the launch believing it succeeded. The reason is already in the container's
    log — surface it rather than making the user go find it.
    """
    logs = subprocess.run([rt, "logs", "--tail", "20", cname], capture_output=True, text=True)
    _err.print(f"[bold red]error:[/bold red] service '{svc.name}' exited at startup ({cname})")
    detail = f"{logs.stdout}{logs.stderr}".strip()
    if detail:
        _err.print(f"[dim]--- {rt} logs --tail 20 {cname} ---[/dim]")
        _err.print(detail)
    raise typer.Exit(1)


def _assert_service_running(rt: str, cname: str, svc: "ServiceDef") -> None:
    """Fail the launch immediately if the container we just started is already dead."""
    if _service_container_status(rt, cname) != "running":
        _abort_dead_service(rt, cname, svc)
