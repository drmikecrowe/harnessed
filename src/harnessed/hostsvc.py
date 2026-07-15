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
from collections.abc import Callable
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


def tcp_open(port: int) -> bool:
    """True if something is accepting on 127.0.0.1:port — the generic readiness signal for an
    HTTP daemon (e.g. hatago: a bound hub means its children are wired, per the capability oracle)."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _spawn(argv: list[str], cwd: Path, log: Path) -> subprocess.Popen:
    lf = open(log, "ab")  # noqa: SIM115 — handed to the child; closed when it exits
    # start_new_session: own process group, so it SURVIVES harnessed's exit (persist default).
    # --rm mode still holds the pid and kills it explicitly.
    return subprocess.Popen(argv, stdout=lf, stderr=lf, start_new_session=True, cwd=str(cwd))


def _await_ready(proc: subprocess.Popen, ready: Callable[[], bool], timeout: float, log: Path) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log.read_text(encoding="utf-8", errors="replace")[-800:] if log.is_file() else ""
            raise RuntimeError(f"daemon exited (code {proc.returncode}). Log tail:\n{tail}")
        if ready():
            return
        time.sleep(0.3)
    raise RuntimeError(f"daemon not ready within {timeout:.0f}s (see {log})")


def ensure(service: str, project_path: Path, *, argv, ready, cwd: Path,
           prestart=None, meta=None, timeout: float = 30.0) -> tuple[dict, bool]:
    """Generic host-daemon supervisor: ensure ONE (service, project) daemon. Returns (entry, started).

    `argv(port)` builds the command, `ready(port)` is the readiness/liveness probe (used for both the
    startup wait AND the reuse check), `prestart()` runs once right before spawn (dir/socket setup),
    `meta(port)` adds extra registry fields (socket, endpoint, ...). The single-daemon-per-project
    invariant + reap-before-start live here — this is the layer every host service reuses.
    """
    key = _key(service, project_path)
    reg = _read()
    entry = reg.get(key)
    if entry and _pid_alive(int(entry["pid"])) and ready(int(entry["port"])):
        return entry, False  # reuse — warm daemon, instant reconnect
    if entry:  # stale: daemon died without deregistering
        _cleanup_socket(entry.get("socket"))
        reg.pop(key, None)
        _write(reg)

    port = _free_port()
    log = _log_path(key)
    if prestart is not None:
        prestart()
    proc = _spawn(argv(port), cwd, log)
    try:
        _await_ready(proc, lambda: ready(port), timeout, log)
    except Exception:
        if proc.poll() is None:
            proc.terminate()
        raise
    reg = _read()
    entry = {"pid": proc.pid, "port": port, "log": str(log), **(meta(port) if meta else {})}
    reg[key] = entry
    _write(reg)
    return entry, True


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
