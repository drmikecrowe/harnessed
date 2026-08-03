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


def _assert_data_dir_not_self_served(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort when a host engine has initialized the sidecar's data dir AS a database.

    Dolt serves the *subdirectories* of its --data-dir as databases, so the beads-server entrypoint
    points it at `<data>/dolt/` and the project database lands at `<data>/dolt/<db>/`. A host `bd`
    that cannot reach a server auto-starts its own — chdir'd into that same `<data>/dolt/` and with
    NO --data-dir — and that run initializes the data dir itself as a repo. The directory is now a
    database in its own right, so ANY server later pointed at it serves exactly one database named
    `dolt`, and the project database becomes unreachable: every `bd` call dies with
    `database "<project>" not found` (errno 1049).

    Observed 2026-07-19 on harnessed's own checkout, where it survived three server restarts and
    five days. The failure is reported by the CLIENT as a missing database, and nothing in that
    message points at the data dir's shape — so the obvious readings ("the server is down", "the
    database was lost") are both wrong and both lead away from the fix.

    The signature is `repo_state.json`, NOT the mere existence of `<data>/dolt/.dolt/`: a perfectly
    healthy sql-server also creates that directory, for `sql-server.info` and a `tmp/`. Only an
    INITIALIZED repo carries `repo_state.json` (beside `noms/`, `config.json`, `stats/`). Keying on
    the directory alone would reject every healthy running server — both states were compared on
    disk before this was written.
    """
    if svc.exclusive_lock != "dolt":
        return
    data_dir = host_dir / "dolt"
    repo_state = data_dir / ".dolt" / "repo_state.json"
    if not repo_state.is_file():
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot start: {data_dir} is itself a "
        "Dolt database"
    )
    _err.print("  A host 'dolt' initialized the data dir in place. A server pointed at it serves")
    _err.print("  one database named 'dolt', so the project database is unreachable (errno 1049).")
    _err.print("  Move it aside (this preserves anything in it) and relaunch:")
    _err.print(f"    mv {data_dir / '.dolt'} {data_dir / '.dolt'}.poisoned")
    raise typer.Exit(1)


def _dolt_migration_sources(host_dir: Path, db: str) -> list[Path]:
    """Directories that hold database `db` and could be migrated into this data dir.

    Only two are guessable, and both are where the database actually ends up in practice:
      * `~/.beads/shared-server/dolt/<db>` — bd's own multi-project server, which a plain `bd init`
        adopts silently. This is where harnessed's own issues lived while every `bd` call reported
        the database missing.
      * `<data>/dolt.*/<db>` — a data dir quarantined out of the way by the self-served guard.

    Anything else is named explicitly with `--from`; guessing more widely would mean scanning the
    filesystem for something the user can point at in one argument.

    A candidate counts only if it carries `.dolt/repo_state.json` — the marker of an initialized
    repo, and the same signal `_assert_data_dir_not_self_served` keys on.
    """
    found: list[Path] = []
    for cand in [Path.home() / ".beads" / "shared-server" / "dolt" / db, *sorted(host_dir.glob(f"dolt.*/{db}"))]:
        if (cand / ".dolt" / "repo_state.json").is_file() and cand not in found:
            found.append(cand)
    return found


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _ensure_no_stale_socket_key(svc: ServiceDef, host_dir: Path) -> None:
    """Drop a `dolt_server_socket` left in metadata.json by a socket-era workspace.

    The migration for the socket→published-port reversal (BEADS.md §11). Every workspace
    initialized before it carries an absolute socket path in metadata.json, and **that key beats
    the environment on bd's data path** — verified 2026-07-26 on a real workspace, and it is a
    split inside bd rather than a precedence rule you can reason around:

        bd dolt status  → reads BEADS_DOLT_SERVER_HOST/PORT → finds the server, works
        bd list / stats → reads metadata.json dolt_server_socket → dials a socket that no longer
                          exists → "Auto-start is not supported in socket mode"

    So the workspace is hard-blocked on every data command while `status` cheerfully reports a
    healthy server. Nothing recreates the key — the entrypoint's metadata writer was deleted
    deliberately (BEADS.md §4) — so removing it once is permanent.

    This is not a workaround for the reversal; it restores the invariant §4 already stated. The key
    is an absolute host path in a file bd TRACKS, so committed it hands every teammate a path that
    cannot exist for them, and socket mode denies them the auto-start fallback. §4's words: "do not
    commit a metadata.json containing a dolt_server_socket."

    Announced when written. For `beads/team` this dirties a tracked file, and silently editing a
    file the user is about to commit is its own kind of surprise (same convention as
    `_ensure_dolt_autostart_disabled`).

    Skipped for a socket-backed service — there the key is not stale, it is the configuration.
    """
    if svc.exclusive_lock != "dolt" or svc.is_socket_only:
        return
    meta = host_dir / "metadata.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # no workspace yet, or one we did not write — leave it alone
    if not isinstance(data, dict) or "dolt_server_socket" not in data:
        return
    stale = data.pop("dolt_server_socket")
    # indent=2 + trailing newline is bd's own formatting, so the diff is one deleted line rather
    # than a whole-file reflow in a tracked file.
    meta.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _err.print(
        f"[yellow][NOTICE][/yellow] {meta}: removed stale 'dolt_server_socket' ({stale}).\n"
        "  This service is reached over a published port now; the key would have overridden that "
        "on bd's data path and blocked every command. Commit the change (see BEADS.md §11)."
    )


def _ensure_dolt_autostart_disabled(svc: "ServiceDef", host_dir: Path) -> None:
    """Turn bd's auto-start off in the workspace's own config, for everyone who touches this repo.

    `BEADS_DOLT_SERVER_SOCKET` only protects processes harnessed launched. This key protects the
    rest: a stray `bd` in a plain terminal, a git hook, a SessionStart hook — and a TEAMMATE who
    never runs harnessed at all. Without it bd starts a server chdir'd into its data dir with no
    --data-dir, which on an EMPTY data dir initializes that directory as a database and makes the
    project database permanently unreachable. A fresh clone is exactly that empty-data-dir case, so
    the teammate scenario is not hypothetical (two repos on this machine caught it independently).

    `config.yaml` is part of bd's tracked surface, so for `beads/team` this lands in a file the user
    will commit — deliberately, since the protection is only repo-wide if it is shared. Announced
    when written, because silently dirtying a tracked file is its own kind of surprise.

    Skipped when there is no workspace yet: `bd init` writes config.yaml, and the next launch adds
    the key. Additive and idempotent — an existing setting of either value is left alone, so a user
    who deliberately re-enables auto-start is not overridden on every launch.
    """
    if svc.exclusive_lock != "dolt":
        return
    cfg = host_dir / "config.yaml"
    try:
        text = cfg.read_text()
    except OSError:
        return
    if re.search(r"^\s*dolt\.auto-start\s*:", text, re.MULTILINE):
        return
    with cfg.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n# harnessed: bd auto-starts a dolt sql-server chdir'd into its data dir with no\n"
            "# --data-dir whenever it cannot reach one. On an empty data dir — a fresh clone —\n"
            "# that initializes the directory ITSELF as a database and the project database becomes\n"
            "# unreachable (errno 1049). Start the server explicitly instead: `bd dolt start`.\n"
            "dolt.auto-start: false\n"
        )
    _out.print(f"[blue][INFO][/blue] set dolt.auto-start: false in {cfg}")


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


def _beads_metadata(host_dir: Path) -> dict | None:
    """`metadata.json` from a beads data dir, or None when there is no readable workspace there."""
    try:
        meta = json.loads((host_dir / "metadata.json").read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _assert_named_database_present(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort when the workspace names a database this data dir does not contain.

    `metadata.json` records `dolt_database`, and the sidecar serves `<data>/dolt/` as its --data-dir,
    so that database MUST exist at `<data>/dolt/<name>/`. When it does not, the sidecar starts
    perfectly happily and every client then fails with `database "<name>" not found` (errno 1049) —
    a message that points at the server, not at the missing bytes, which is why the state is so hard
    to read from the client side.

    Two ways to get here, both real:
      * The workspace was pointed at ANOTHER server that holds the database — bd's own multi-project
        `~/.beads/shared-server`, for instance, which a plain `bd init` will silently adopt. The
        bytes exist, just not here; they have to be migrated in.
      * A `beads/team` checkout was cloned fresh. `metadata.json` is tracked, the Dolt bytes are not,
        so the workspace arrives naming a database that was never materialized locally. It needs
        `bd bootstrap` (or a Dolt remote that actually has data — see harnessed's own 2026-07-24
        failure, where the remote had none).

    Checked on the host, from the filesystem alone: no server, no client, no connection required.
    """
    if svc.exclusive_lock != "dolt":
        return
    meta = _beads_metadata(host_dir)
    if meta is None:
        return  # no workspace yet — first-run init owns that case, not this guard
    db = meta.get("dolt_database")
    if not db or (host_dir / "dolt" / str(db)).is_dir():
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot serve this workspace: it names "
        f"database '{db}', which is not in {host_dir / 'dolt'}"
    )
    _err.print("  The sidecar would start and every 'bd' call would fail with errno 1049.")
    _err.print("  The bytes live wherever this workspace was previously pointed (commonly bd's own")
    _err.print("  ~/.beads/shared-server/dolt). Bring them in with:")
    _err.print(f"    harnessed svc migrate {svc.name} --stack <stack>")
    _err.print("  or run 'bd bootstrap' if the Dolt remote has data.")
    raise typer.Exit(1)


def _assert_placement_matches(svc: "ServiceDef", location: str, project_path: Path) -> None:
    """Abort when a host-placed (stealth) launch would ignore an in-repo (team) workspace.

    The two beads recipes differ ONLY in placement: `beads/team` puts `.beads` in the repo,
    `beads/stealth` puts it on the host outside the repo. Nothing in either one notices the other,
    so launching the stealth stack over a checkout that already carries a team workspace silently
    starts a SECOND, empty workspace — the issues do not appear, nothing errors, and the obvious
    reading ("my data is gone") is wrong.

    Only this direction is detectable from placement alone: the team dir is at a known,
    recipe-independent path under the checkout, whereas the stealth dir is keyed by recipe name and
    a project hash, so a team launch cannot enumerate where a stealth workspace might be.
    """
    if location != "host":
        return
    team_dir = paths.persist_in_repo_dir(project_path, svc.data_persist)
    if _beads_metadata(team_dir) is None:
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' is running host-placed (stealth), but "
        f"{team_dir} already holds an in-repo workspace"
    )
    _err.print("  Launching stealth here would start a second, empty workspace and your issues")
    _err.print("  would simply not appear. Use the team stack for this checkout, or move the")
    _err.print(f"  in-repo workspace aside first: mv {team_dir} {team_dir}.bak")
    raise typer.Exit(1)


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
