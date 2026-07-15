"""Host-native service supervisor — run a project-scoped daemon (e.g. beads-server's `dolt
sql-server`) directly on the host, one per project, tracked in a registry so a second launch reuses
it instead of starting a rival.

This is the host analog of the container `_ensure_services` path. Host-native, almost all of the
container beads-server complexity (uid mapping, bind-mount dual-path sockets, netns loopback traps,
metadata migration) evaporates: one host, one dolt process, one socket path everyone sees. What
remains — and what this module owns — is the ONE hard invariant: exactly one server per project
(dolt takes an exclusive flock on its data dir), plus lifecycle (start / reuse / reap / stop).

Primitives only: callers resolve the data dir + socket (via the recipe's persist placement) and pass
them in. Keeps this module free of launcher imports, so launcher can import it without a cycle.
"""

from __future__ import annotations

import json
import os
import signal
import socket as _socket
import subprocess
import time
from pathlib import Path

from . import paths


def _registry_file() -> Path:
    """Registry of running host services (XDG_STATE). Keyed `<service>|<project-hash>`."""
    return paths.xdg_state_home() / "harnessed" / "host-services.json"


def _read() -> dict:
    f = _registry_file()
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(reg: dict) -> None:
    f = _registry_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _key(service: str, project_path: Path | str) -> str:
    return f"{service}|{paths.project_hash(project_path)}"


def _pid_alive(pid: int) -> bool:
    """True if `pid` is a live process. A zombie (killed-but-unreaped child) counts as DEAD — else a
    just-SIGKILLed daemon whose parent hasn't waited on it would read as alive and block reuse."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, not ours to signal
    # Exists — but a zombie is a corpse. /proc state 'Z' → treat as dead (Linux).
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        state = stat.rpartition(")")[2].split()[0]  # field after "(comm)"; comm may hold spaces/parens
        return state != "Z"
    except (OSError, IndexError):
        return True


def _free_port() -> int:
    """Grab an ephemeral loopback port. Used for the per-project TCP listener the healthcheck and
    `bd dolt push` need — clients connect over the socket, so this only has to be collision-free
    across concurrently-served projects (the container's fixed 3307 would clash host-side)."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cleanup_socket(sock: str | None) -> None:
    if sock:
        try:
            Path(sock).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _log_path(key: str) -> Path:
    d = paths.xdg_state_home() / "harnessed" / "host-services-logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / (key.replace("|", "_") + ".log")


def _start_dolt(data_dir: Path, sock: Path, port: int, log: Path) -> subprocess.Popen:
    """Launch `dolt sql-server` as a detached host process against the project's data dir."""
    doltdir = data_dir / "dolt"
    doltdir.mkdir(parents=True, exist_ok=True)
    sock.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_socket(str(sock))  # a stale socket makes dolt refuse to bind
    lf = open(log, "ab")  # noqa: SIM115 — handed to the child; closed when it exits
    # start_new_session: own process group, so it SURVIVES harnessed's exit (persist default).
    # --rm mode still holds the pid and kills it explicitly.
    return subprocess.Popen(
        [
            "dolt", "sql-server",
            "--host", "127.0.0.1", "--port", str(port),
            "--socket", str(sock),
            "--data-dir", str(doltdir),
        ],
        stdout=lf, stderr=lf, start_new_session=True, cwd=str(data_dir),
    )


def _reachable(port: int) -> bool:
    r = subprocess.run(
        ["dolt", "--host", "127.0.0.1", "--port", str(port), "--user", "root",
         "--password", "", "--no-tls", "sql", "-q", "SELECT 1"],
        capture_output=True,
    )
    return r.returncode == 0


def _await_ready(proc: subprocess.Popen, sock: Path, port: int, timeout: float, log: Path) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log.read_text(encoding="utf-8", errors="replace")[-800:] if log.is_file() else ""
            raise RuntimeError(f"dolt sql-server exited (code {proc.returncode}). Log tail:\n{tail}")
        if sock.exists() and _reachable(port):
            return
        time.sleep(0.3)
    raise RuntimeError(f"dolt sql-server not ready within {timeout:.0f}s (see {log})")


def ensure(service: str, project_path: Path, data_dir: Path, sock: Path,
           *, timeout: float = 30.0) -> tuple[str, bool]:
    """Ensure a host daemon for (service, project). Returns (socket_path, started_now).

    Reuses a live registered server; reaps a dead entry (stale pid → drop it + its socket) before
    starting a fresh one. The single-server-per-project invariant lives here.
    """
    key = _key(service, project_path)
    reg = _read()
    entry = reg.get(key)
    if entry and _pid_alive(int(entry["pid"])) and Path(entry["socket"]).exists():
        return entry["socket"], False  # reuse — warm server, instant reconnect
    if entry:  # stale: server died without deregistering
        _cleanup_socket(entry.get("socket"))
        reg.pop(key, None)
        _write(reg)

    port = _free_port()
    log = _log_path(key)
    proc = _start_dolt(data_dir, sock, port, log)
    try:
        _await_ready(proc, sock, port, timeout, log)
    except Exception:
        if proc.poll() is None:
            proc.terminate()
        raise
    reg = _read()
    reg[key] = {"pid": proc.pid, "socket": str(sock), "port": port,
                "data_dir": str(data_dir), "log": str(log)}
    _write(reg)
    return str(sock), True


def stop(service: str, project_path: Path) -> bool:
    """Stop and deregister the host daemon for (service, project). Returns True if one was running."""
    key = _key(service, project_path)
    reg = _read()
    entry = reg.pop(key, None)
    if entry is None:
        return False
    _write(reg)
    pid = int(entry["pid"])
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # Reap if it was our child (persist mode reparents it to init, where ECHILD is expected and fine)
    # so it doesn't linger as a zombie that _pid_alive would otherwise now correctly report dead.
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass
    _cleanup_socket(entry.get("socket"))
    return True


def reap() -> list[str]:
    """Drop registry entries whose process is dead (for `svc prune`). Returns the reaped keys."""
    reg = _read()
    dead = [k for k, e in reg.items() if not _pid_alive(int(e["pid"]))]
    for k in dead:
        _cleanup_socket(reg[k].get("socket"))
        reg.pop(k, None)
    if dead:
        _write(reg)
    return dead
