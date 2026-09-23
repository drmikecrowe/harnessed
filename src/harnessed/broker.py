"""The host secrets broker: one `varlock proxy` per instance, on loopback, torn down with the pod.

Epic #388 Phase 1, Topology B. `varlock proxy` runs on the HOST — where 1Password, the keychain,
gpg-agent and a YubiKey can actually authenticate — binds `127.0.0.1` only, and injects real values
into outbound requests on the wire. The pod holds placeholders and reaches the broker through
pasta's `--map-host-loopback,169.254.1.1` (`mounts._mcp_remote_pasta_net_args`), which the egress
firewall permits (#436). Nothing off-host can reach it, so there is no `--expose` and no data-plane
token — Topology B deleted both, along with the WebSocket tunnel. Do not reintroduce them.

Three measurements against varlock 1.16.1 shape everything here. They are not obvious from the
`--help` text, and an implementation guessed from it would be wrong:

  * **`proxy start` does not daemonize.** It holds the terminal and streams a live request log
    until killed. So this module SPAWNS it and returns, rather than running it to completion.
  * **The session id is read back from `proxy status --format json`, matched on the port we
    chose** — never parsed from `start`'s stdout, which wraps the id in ANSI styling.
  * **`varlock` is invoked with `--path <schema_dir>`**, never by cwd: the mise shim resolves the
    binary only inside this repo, so a cwd-based call is not portable across callers.

WHAT IS PERSISTED, AND WHY SO LITTLE. `proxy status` returns an `endpointToken` (a control-plane
credential), `placeholderOverrides`, and the resolved proxy env. This module stores five fields —
instance, pod, session, port, cert dir — and nothing else, so "the state file leaks no secret" is
true by construction rather than by redaction. Anything added here must clear that bar.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths
from .console import _err

# The broker binds a real port and needs a moment to be listening before `status` reports it. Long
# enough for a cold node start on a loaded machine, short enough that a broker which will never
# come up fails the launch instead of hanging it.
_START_TIMEOUT = 30.0
_POLL_INTERVAL = 0.25

# `proxy stop`/`status` are quick control-plane calls against a local daemon. A hung one must not
# wedge a teardown path that other cleanup depends on.
_CONTROL_TIMEOUT = 30


class BrokerError(RuntimeError):
    """A broker could not be started, or could not be found after starting."""


@dataclass(frozen=True)
class Broker:
    """Exactly what is needed to find a running broker again and stop it. See the module docstring
    for why this record is not richer."""

    instance: str
    pod: str
    session: str
    port: int
    cert_dir: str


def state_dir() -> Path:
    """Where broker records live. Mirrors `launcher._attach_marker`'s convention."""
    return paths.xdg_state_home() / "harnessed" / "brokers"


def state_path(inst: str) -> Path:
    return state_dir() / f"{inst}.json"


def read(inst: str) -> Broker | None:
    """The recorded broker for `inst`, or None if there is none or the record is unreadable.

    A corrupt record reads as absent rather than raising: this is called from `harnessed list` and
    from every teardown path, and a half-written file must not take down a command whose job is to
    clean up. `reconcile` is what removes the corrupt file.
    """
    try:
        raw = json.loads(state_path(inst).read_text(encoding="utf-8"))
        return Broker(
            instance=raw["instance"], pod=raw["pod"], session=raw["session"],
            port=int(raw["port"]), cert_dir=raw["cert_dir"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def all_instances() -> list[str]:
    """Every instance with a broker record, corrupt ones included — `reconcile` must see those to
    delete them, so this reads filenames rather than contents."""
    try:
        return sorted(p.stem for p in state_dir().glob("*.json"))
    except OSError:
        return []


def _write(session: Broker) -> None:
    path = state_path(session.instance)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(session), indent=2, sort_keys=True), encoding="utf-8")
    # Atomic replace: `harnessed list` and a teardown can read this while a launch writes it, and a
    # half-written record would read as corrupt and get the live broker reaped.
    os.replace(tmp, path)


def forget(inst: str) -> None:
    try:
        state_path(inst).unlink()
    except OSError:
        pass


# --- ports -------------------------------------------------------------------

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _ephemeral_candidates() -> Iterator[int]:
    """An endless supply of ports the kernel just reported free.

    Binding port 0 and reading the assignment beats scanning a fixed range: it cannot collide with
    a service that legitimately owns a well-known port, and it encodes no range that will someday
    be wrong.
    """
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # Yield OUTSIDE the `with`. A generator suspends at its yield, so yielding inside would
        # hand out a port this very socket still holds — `_port_free` then cannot bind it, every
        # candidate reads as taken, and `pick_port()` fails on its own default path. It did.
        yield port


def pick_port(
    port_free: Callable[[int], bool] | None = None,
    candidates: Iterable[int] | None = None,
    attempts: int = 20,
) -> int:
    """A free loopback port for this instance's broker.

    NOT a fixed constant. `varlock proxy start --port` "fails to start if the port is in use"
    (measured, 1.16.1), so a hardcoded port would turn a second concurrent instance into a launch
    failure. `--port` is still passed explicitly — that is what varlock's own help means by a
    "fixed" port, as against letting it pick one internally — because the guest's `HTTPS_PROXY`
    must name a port before the process exists.

    Inherently racy and deliberately not locked: the kernel can hand the same port to someone else
    between this check and varlock's bind. varlock then fails loudly, which is the right outcome
    and is cheaper than a lock this module would have to hold for the life of the pod.
    """
    is_free = port_free or _port_free
    source = iter(candidates) if candidates is not None else _ephemeral_candidates()
    for _ in range(attempts):
        try:
            candidate = next(source)
        except StopIteration:
            break
        if is_free(candidate):
            return candidate
    raise BrokerError(f"no free loopback port for the secrets broker after {attempts} attempts")


# --- subprocess seams --------------------------------------------------------
#
# Injected rather than called directly so the tests can drive the whole lifecycle without spawning
# a real broker — which would resolve real secrets out of a real 1Password.

def _spawn(argv: list[str]) -> int:
    """Start the broker detached and return its pid. See the module docstring: `proxy start` runs
    in the foreground indefinitely, so this must not wait for it."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def _status() -> list[dict]:
    result = subprocess.run(
        ["varlock", "proxy", "status", "--format", "json"],
        capture_output=True, text=True, timeout=_CONTROL_TIMEOUT, check=False,
    )
    if result.returncode != 0:
        return []
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _run(argv: list[str]) -> int:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=_CONTROL_TIMEOUT, check=False,
    ).returncode


def _kill(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# --- lifecycle ---------------------------------------------------------------

def _session_on_port(rows: list[dict], port: int) -> str | None:
    """Our session is the one whose proxy env names the port we chose.

    Matched on the port rather than on list position or on `entryPaths`: the port is unique per
    instance by construction, while several sessions can share an entry path and the order of the
    list is not specified anywhere.
    """
    want = f":{port}"
    for row in rows:
        env = row.get("env") or {}
        # HTTPS_PROXY only. A measured session sets all six proxy vars to the same URL, so a
        # HTTP_PROXY fallback would be a second code path that no input can reach — unrequested
        # flexibility that mutation testing correctly reported as untested. One key, one meaning.
        url = env.get("HTTPS_PROXY") or ""
        if url.endswith(want) and row.get("id"):
            return str(row["id"])
    return None


def start(
    inst: str,
    pod: str,
    schema_dirs: str | Path | Sequence[str | Path],
    *,
    cert_dir: str | Path | None = None,
    spawn: Callable[[list[str]], int] = _spawn,
    status: Callable[[], list[dict]] = _status,
    kill: Callable[[int], None] = _kill,
    port_free: Callable[[int], bool] | None = None,
    candidates: Iterable[int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = _START_TIMEOUT,
) -> Broker:
    """Start a broker for `inst` and record it. Raises BrokerError if it never comes up.

    On failure the spawned process is killed and NO state file is written. That ordering is the
    point: a state file naming a dead session is merely stale, and `reconcile` fixes it — while a
    live broker with no state file is invisible to every cleanup path here and would hold real
    secrets until the machine reboots.
    """
    port = pick_port(port_free=port_free, candidates=candidates)
    certs = Path(cert_dir) if cert_dir is not None else state_dir() / f"{inst}-certs"
    certs.mkdir(parents=True, exist_ok=True)

    # `--path` is repeatable, and a launch composes up to two schemas: the user-global
    # ~/.config/harnessed and the project's own. Passing both is what makes the broker resolve the
    # SAME composed set the --env-file path resolves (launchenv._resolve_launch_secrets), rather
    # than a subset that silently omits half the user's secrets.
    dirs = [schema_dirs] if isinstance(schema_dirs, (str, Path)) else list(schema_dirs)
    argv = ["varlock", "proxy", "start"]
    for d in dirs:
        argv += ["--path", str(d)]
    argv += ["--port", str(port), "--cert-dir", str(certs)]
    pid = spawn(argv)

    # BaseException, not Exception: `spawn` uses start_new_session=True, so the broker does NOT
    # receive the terminal's SIGINT. A Ctrl-C anywhere in this loop — a window of up to `timeout` —
    # would otherwise leave a live broker holding real credentials with NO state file naming it,
    # which makes it invisible to `reconcile` (it reads filenames) and immortal short of a reboot.
    # That is the worst orphan this module can produce, and it is strictly worse than the timeout
    # case the loop already guards.
    waited = 0.0
    try:
        while True:
            session = _session_on_port(status(), port)
            if session:
                record = Broker(
                    instance=inst, pod=pod, session=session, port=port, cert_dir=str(certs),
                )
                _write(record)
                return record
            if waited >= timeout:
                break
            sleep(_POLL_INTERVAL)
            waited += _POLL_INTERVAL
    except BaseException:
        kill(pid)
        raise

    kill(pid)
    raise BrokerError(
        f"the secrets broker for {inst} did not come up on port {port} within {timeout:g}s. "
        f"Launch with --no-secrets to skip it."
    )


def _stop_session(
    record: Broker, run: Callable[[list[str]], int], status: Callable[[], list[dict]]
) -> bool:
    """Stop one session. True when it is gone afterwards and the record may be dropped.

    A non-zero `proxy stop` is ambiguous: the broker may be wedged and still holding secrets, or
    the session may simply have died already. The two need opposite handling — dropping the record
    of a LIVE broker leaves it orphaned with nothing naming it, while keeping the record of a dead
    one makes `harnessed list` report a phantom forever. So on failure we ask `status` which case
    it is, rather than guessing.
    """
    if run(["varlock", "proxy", "stop", "--session", record.session]) == 0:
        return True
    return _session_on_port(status(), record.port) is None


def stop(
    inst: str,
    *,
    run: Callable[[list[str]], int] = _run,
    status: Callable[[], list[dict]] = _status,
) -> None:
    """Stop `inst`'s broker and forget it. A no-op when there is nothing recorded.

    Never `--all`: that would stop brokers belonging to other instances and to the user's own
    terminals. Idempotent, because `_pod_teardown` runs on paths that may already have torn down.

    The record is kept when the stop failed AND the session is still running — see `_stop_session`.
    """
    record = read(inst)
    if record is None:
        # Still `forget`: `read` returns None for a CORRUPT record too, and that file would
        # otherwise be permanent.
        forget(inst)
        return
    if _stop_session(record, run, status):
        forget(inst)
        return
    _err.print(
        f"[yellow]warning:[/yellow] the secrets broker for {inst} (session {record.session}) did "
        f"not stop. Its record is kept so `harnessed list` still shows it; stop it by hand with "
        f"`varlock proxy stop --session {record.session}`."
    )


def reconcile(
    pod_exists: Callable[[str], bool],
    *,
    run: Callable[[list[str]], int] = _run,
    status: Callable[[], list[dict]] = _status,
) -> list[str]:
    """Stop every recorded broker whose pod is gone. Returns the instances reaped.

    The backstop for every path teardown never reached: a crashed launcher, a `podman pod rm` run
    by hand, a host reboot that left records behind. Without it a broker holding live secrets can
    outlive its pod indefinitely, which is the worst failure available here.

    A record that cannot be parsed is reaped too. It names no session to stop, so deleting it is
    all that is available — and leaving it would make it permanent.
    """
    reaped: list[str] = []
    for inst in all_instances():
        record = read(inst)
        if record is None:
            forget(inst)
            reaped.append(inst)
            continue
        if pod_exists(record.pod):
            continue
        if not _stop_session(record, run, status):
            # Same rule as `stop`: a broker that would not die keeps its record, so the next
            # sweep tries again and `harnessed list` keeps showing it. Not counted as reaped.
            continue
        forget(inst)
        reaped.append(inst)
    return reaped
