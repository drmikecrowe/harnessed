"""`container-acp` as a host-side ACP proxy (#566).

An editor can start the agent anywhere, kill it if `initialize` is slow, and reuse one agent process
for every project it opens: Atlas starts it in its own working directory, waits 60 s for
`initialize`, and sends each project's `session/new` to the same process. So the proxy answers
`initialize` itself, from `INITIALIZE_RESULTS`, and runs one agent per project. Each session request
(`session/new`, `session/load`, `session/resume`) names its project — the path argument when one was
given, else its `cwd`. The first request for a project starts that project's agent through `launch`
on a thread of its own, replays the client's `initialize` to it, and forwards the request. After
that, every line goes to the agent of the session it names.

The agents' requests to the client (`session/request_permission`, ...) get proxy-wide ids, because
two agents both number theirs from 0; the client's reply goes back to the agent that asked, under
its own id.

Line-delimited JSON-RPC 2.0 on both sides, the same framing ACP uses on stdio. Every write to stdout
goes through one lock, so lines from different agents never interleave inside a line.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import IO, Any, Callable, NamedTuple, Optional, TextIO

import typer

from . import paths

# What each harness's own `initialize` returns, at the version catalog/agents/<harness>/agent.yaml pins:
# omp 18.6.1 (`omp acp`) and claude-agent-acp 0.85.1. The proxy has to answer before the agent runs,
# so the reply is held here. On every agent start the agent's real reply is compared against it in
# `DRIFT_FIELDS`, and a difference is reported on stderr: update this table when a pin moves.
INITIALIZE_RESULTS: dict[str, dict] = {
    "omp": {
        "protocolVersion": 1,
        "agentInfo": {"name": "omp", "title": "omp", "version": "18.6.1"},
        "authMethods": [{
            "id": "agent",
            "name": "Use existing local credentials",
            "description": "Authenticate via the provider keys/OAuth state already configured under ~/.omp.",
        }],
        "agentCapabilities": {
            "loadSession": True,
            "mcpCapabilities": {"http": True, "sse": True},
            "promptCapabilities": {"embeddedContext": True, "image": True},
            "sessionCapabilities": {"list": {}, "fork": {}, "resume": {}, "close": {}},
        },
    },
    "claude": {
        "protocolVersion": 1,
        "agentCapabilities": {
            "_meta": {"claudeCode": {"promptQueueing": True}, "authStatus": {}},
            "promptCapabilities": {"image": True, "embeddedContext": True},
            "mcpCapabilities": {"http": True, "sse": True},
            "auth": {"logout": {}},
            "providers": {},
            "loadSession": True,
            "sessionCapabilities": {
                "additionalDirectories": {}, "close": {}, "delete": {}, "fork": {}, "list": {},
                "resume": {}, "subagents": {},
            },
        },
        "agentInfo": {
            "name": "@agentclientprotocol/claude-agent-acp", "title": "Claude Agent", "version": "0.85.1",
        },
        "authMethods": [],
        "_meta": {"steering": {"supported": True}},
    },
}

# `authMethods` is not compared: it follows the agent's login state, so it differs between a host and
# a pod for the same pinned version (GH-566 story, AC-5).
DRIFT_FIELDS = ("protocolVersion", "agentCapabilities")

_OPEN_METHODS = ("session/new", "session/load", "session/resume")

# JSON-RPC 2.0 error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# The id the proxy gives `initialize` when the client opened a session without sending one.
_SYNTHETIC_INIT_ID = "harnessed-initialize"

Launch = Callable[[Path], "tuple[subprocess.Popen[bytes], Path]"]

_LAUNCHING, _READY, _GONE = "launching", "ready", "gone"


def _params(msg: dict) -> dict:
    params = msg.get("params")
    return params if isinstance(params, dict) else {}


def _key(value: Any) -> Optional[Any]:
    """`value` when it can be a table key for a JSON-RPC id, else None. A bool is not an id."""
    return value if isinstance(value, (str, int)) and not isinstance(value, bool) else None


class _Line(NamedTuple):
    """One client line on its way to an agent. `kind` "raw" goes as `raw`; "open" and "list" are
    re-encoded at send time with `cwd` set to where the agent runs, which is known only then."""

    kind: str
    raw: bytes
    msg: Optional[dict]

    @property
    def id(self) -> Any:
        return self.msg.get("id") if self.msg is not None else None

    @property
    def is_request(self) -> bool:
        return self.msg is not None and "id" in self.msg and "method" in self.msg


class _Child:
    """One project's agent. `lock` covers `state`, `pending` and writes to the agent's stdin; the
    thread that reads the agent's stdout never takes it, so a full pipe cannot deadlock the two."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self.lock = threading.Lock()
        self.state = _LAUNCHING
        self.pending: list[_Line] = []
        self.proc: Optional[subprocess.Popen[bytes]] = None
        self.stdin: Optional[IO[bytes]] = None
        self.start_dir = project

    def encode(self, line: _Line) -> bytes:
        if line.kind == "raw" or line.msg is None:
            return line.raw
        params = dict(_params(line.msg))
        if line.kind == "open" or "cwd" in params:
            params["cwd"] = str(paths.container_project_path(self.start_dir))
        return json.dumps({**line.msg, "params": params}).encode()

    def write(self, raw: bytes) -> bool:
        """Write one line to the agent. False when it is gone. Call with `lock` held."""
        if self.stdin is None:
            return False
        try:
            self.stdin.write(raw if raw.endswith(b"\n") else raw + b"\n")
            self.stdin.flush()
        except (OSError, ValueError):
            return False
        return True

    def close(self) -> None:
        with self.lock:
            if self.stdin is not None:
                try:
                    self.stdin.close()
                except (OSError, ValueError):
                    pass


class _Proxy:
    def __init__(self, harness: str, path: Optional[Path], launch: Launch,
                 stdout: IO[bytes], stderr: TextIO) -> None:
        self.harness = harness
        self.path = path
        self.launch = launch
        self.stdout = stdout
        self.stderr = stderr
        self.out_lock = threading.Lock()
        # `lock` covers the tables below. Never held while writing to an agent or to stdout.
        self.lock = threading.Lock()
        self.children: dict[Path, _Child] = {}
        self.sessions: dict[str, _Child] = {}
        self.opening: dict[Any, _Child] = {}  # session request id -> its agent, to learn session ids
        self.outgoing: dict[int, tuple[_Child, Any]] = {}  # proxy id -> (agent, the agent's own id)
        self.next_out = 0
        self.codes: list[int] = []  # agents' exit codes, in the order they exited
        self.threads: list[threading.Thread] = []
        self.started: list[_Child] = []  # every agent ever started, for `finish`
        self.closing = False  # stdin has closed; an agent that becomes ready now is told to stop
        self.init_request: Optional[dict] = None

    # --- output ----------------------------------------------------------------------------------

    def write(self, raw: bytes) -> None:
        with self.out_lock:
            self.stdout.write(raw if raw.endswith(b"\n") else raw + b"\n")
            self.stdout.flush()

    def send(self, msg: dict) -> None:
        self.write(json.dumps(msg).encode())

    def error(self, id_, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})

    def refuse(self, line: _Line, code: int, message: str) -> None:
        """Answer `line` with an error when it is a request; a notification has nobody to answer."""
        if line.is_request:
            self.error(line.id, code, message)
        else:
            self.note(f"dropped a notification: {message}")

    def note(self, line: str) -> None:
        print(f"harnessed: {line}", file=self.stderr, flush=True)

    # --- the client's lines ----------------------------------------------------------------------

    def handle(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            self.error(None, _PARSE_ERROR, "not JSON")
            return
        if not isinstance(msg, dict):
            self.error(None, _INVALID_REQUEST, "not a JSON-RPC message")
            return
        line = _Line("raw", raw, msg)
        method = msg.get("method")
        if method is None:
            self.client_reply(msg)
        elif method == "initialize":
            self.init_request = msg
            if "id" in msg:
                self.send({"jsonrpc": "2.0", "id": msg["id"], "result": INITIALIZE_RESULTS[self.harness]})
        elif method in _OPEN_METHODS:
            self.open(line)
        elif method == "session/list":
            self.list_sessions(line)
        else:
            self.route(line)

    def requested_project(self, line: _Line) -> Optional[Path]:
        """The project a session request names, or None after answering it with an error."""
        if self.path is not None:
            return self.path
        cwd = _params(line.msg or {}).get("cwd")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            self.refuse(line, _INVALID_PARAMS, f"cwd must be an absolute path, got {cwd!r}")
            return None
        if not Path(cwd).is_dir():
            self.refuse(line, _INVALID_PARAMS, f"cwd is not a directory: {cwd}")
            return None
        return Path(cwd)

    def open(self, line: _Line) -> None:
        project = self.requested_project(line)
        if project is None:
            return
        key = project.resolve()
        msg = line.msg or {}
        with self.lock:
            child = self.children.get(key)
            start = False
            if child is None or child.state == _GONE:
                child, start = _Child(key), True
                self.children[key] = child
                self.started.append(child)
            sid = _params(msg).get("sessionId")
            if msg.get("method") != "session/new" and isinstance(sid, str):
                self.sessions[sid] = child
            if _key(msg.get("id")) is not None:
                self.opening[msg["id"]] = child
        # Queued before the launch starts, so a launch that fails at once still answers it.
        self.deliver(child, _Line("open", line.raw, msg))
        if start:
            thread = threading.Thread(target=self.run_child, args=(child,), daemon=True)
            with self.lock:
                self.threads.append(thread)
            thread.start()

    def list_sessions(self, line: _Line) -> None:
        # S10: never an error. A project this process runs no agent for has no sessions to show yet.
        project = self.path
        if project is None:
            cwd = _params(line.msg or {}).get("cwd")
            if isinstance(cwd, str) and Path(cwd).is_absolute() and Path(cwd).is_dir():
                project = Path(cwd)
        with self.lock:
            child = self.children.get(project.resolve()) if project is not None else None
        if child is None or child.state == _GONE:
            if line.is_request:
                self.send({"jsonrpc": "2.0", "id": line.id, "result": {"sessions": []}})
            return
        self.deliver(child, _Line("list", line.raw, line.msg))

    def route(self, line: _Line) -> None:
        msg = line.msg or {}
        params = _params(msg)
        if "sessionId" in params:
            sid = params["sessionId"]
            with self.lock:
                child = self.sessions.get(sid) if isinstance(sid, str) else None
            if child is None:
                self.refuse(line, _INVALID_PARAMS, f"unknown session: {sid}")
                return
            self.deliver(child, line)
            return
        method = msg.get("method")
        with self.lock:
            live = [c for c in self.children.values() if c.state != _GONE]
        if not live:
            self.refuse(line, _INVALID_REQUEST, f"no session yet: {method} needs session/new first")
        elif len(live) > 1:
            self.refuse(line, _INVALID_REQUEST, f"cannot route {method}: it names no session")
        else:
            self.deliver(live[0], line)

    def client_reply(self, msg: dict) -> None:
        """The client's reply to an agent's request: back to that agent, under its own id."""
        id_ = _key(msg.get("id"))
        with self.lock:
            entry = self.outgoing.pop(id_, None) if id_ is not None else None
        if entry is None:
            self.note(f"dropped a reply to an unknown request id {msg.get('id')!r}")
            return
        child, own_id = entry
        self.deliver(child, _Line("raw", json.dumps({**msg, "id": own_id}).encode(), None))

    def deliver(self, child: _Child, line: _Line) -> None:
        """Send `line` to `child` now, or queue it while the agent starts."""
        with child.lock:
            if child.state == _LAUNCHING:
                child.pending.append(line)
                return
            if child.state == _READY and child.write(child.encode(line)):
                return
        self.refuse(line, _INTERNAL_ERROR, f"agent for {child.project} exited")

    # --- one project's agent ---------------------------------------------------------------------

    def run_child(self, child: _Child) -> None:
        """Start `child`'s agent, initialize it, release the lines that waited, then carry its stdout."""
        try:
            proc, start_dir = self.launch(child.project)
            if proc.stdin is None or proc.stdout is None:
                raise ValueError("the launch must pipe the agent's stdin and stdout")
        except typer.Exit as exc:
            self.fail(child, f"launch failed (exit {exc.exit_code}); see stderr")
            return
        except Exception as exc:  # noqa: BLE001 - the editor waits on this request; any failure must answer it
            self.note(f"launch for {child.project} failed: {exc!r}")
            self.fail(child, f"launch failed ({type(exc).__name__}: {exc}); see stderr")
            return
        child.proc, child.stdin, child.start_dir = proc, proc.stdin, start_dir
        self.note(f"ACP proxy {os.getpid()}: {child.project}")
        if not self.handshake(child, proc.stdout):
            code = proc.wait()
            with self.lock:
                self.codes.append(code)
            self.fail(child, f"launch failed (exit {code}); see stderr")
            return
        with child.lock:
            for line in child.pending:
                if not child.write(child.encode(line)):
                    self.refuse(line, _INTERNAL_ERROR, f"agent for {child.project} exited")
            child.pending.clear()
            child.state = _READY
            if self.closing:
                proc.stdin.close()
        self.pump(child, proc, proc.stdout)

    def handshake(self, child: _Child, out: IO[bytes]) -> bool:
        """Replay `initialize` to the agent and consume its reply. False when it exits first."""
        init = self.init_request or {
            "jsonrpc": "2.0", "id": _SYNTHETIC_INIT_ID, "method": "initialize",
            "params": {"protocolVersion": 1},
        }
        if "id" not in init:  # a notification is owed no reply; ask as a request (PR #599)
            init = {**init, "id": _SYNTHETIC_INIT_ID}
        with child.lock:
            if not child.write(json.dumps(init).encode()):
                return False
        for raw in out:
            try:
                msg = json.loads(raw)
            except ValueError:
                self.write(raw)  # not ours to judge; the client sees what the agent sent
                continue
            if isinstance(msg, dict) and msg.get("id") == init.get("id") and "method" not in msg:
                self.check_drift(msg.get("result") or {})
                return True
            self.from_agent(child, raw, msg)
        return False

    def check_drift(self, real: dict) -> None:
        canned = INITIALIZE_RESULTS[self.harness]
        for field in DRIFT_FIELDS:
            if real.get(field) != canned.get(field):
                self.note(f"ACP initialize drift: {self.harness}: {field}")

    def fail(self, child: _Child, message: str) -> None:
        """The agent never started: answer every line that waited for it, and forget it, so the next
        session request for the project launches again."""
        with child.lock:
            child.state = _GONE
            waiting, child.pending = child.pending, []
        with self.lock:
            if self.children.get(child.project) is child:
                del self.children[child.project]
        for line in waiting:
            self.refuse(line, _INTERNAL_ERROR, message)

    def pump(self, child: _Child, proc: subprocess.Popen[bytes], out: IO[bytes]) -> None:
        for raw in out:
            try:
                msg = json.loads(raw)
            except ValueError:
                self.write(raw)
                continue
            self.from_agent(child, raw, msg)
        code = proc.wait()
        with child.lock:
            child.state = _GONE
        with self.lock:
            self.codes.append(code)

    def from_agent(self, child: _Child, raw: bytes, msg: Any) -> None:
        if isinstance(msg, dict) and "id" in msg:
            if "method" in msg:
                # A request to the client: renumber it, so two agents' ids never meet.
                with self.lock:
                    n = self.next_out
                    self.next_out += 1
                    self.outgoing[n] = (child, msg["id"])
                self.send({**msg, "id": n})
                return
            result = msg.get("result")
            sid = result.get("sessionId") if isinstance(result, dict) else None
            with self.lock:
                id_ = _key(msg["id"])
                if id_ is not None and self.opening.get(id_) is child:
                    del self.opening[id_]
                    if isinstance(sid, str):
                        self.sessions[sid] = child
        self.write(raw)

    # --- the end ---------------------------------------------------------------------------------

    def finish(self) -> int:
        """stdin closed: close every agent's stdin, and wait for every agent to exit. An agent still
        starting is closed by its own thread once it is ready (`closing`)."""
        with self.lock:
            self.closing = True
            started, threads = list(self.started), list(self.threads)
        for child in started:
            # Only a ready agent: one still starting has lines waiting for it, and its own thread
            # closes it after sending them (adversary round 2).
            with child.lock:
                ready = child.state == _READY
            if ready:
                child.close()
        for thread in threads:
            thread.join()
        with self.lock:
            return next((c for c in self.codes if c != 0), 0)


def serve(harness: str, *, path: Optional[Path], launch: Launch,
          stdin: IO[bytes], stdout: IO[bytes], stderr: TextIO) -> int:
    """Run the proxy until stdin closes and every agent it started has exited. Return 0 when every
    agent exited 0 (or none ran), else the first nonzero exit code."""
    proxy = _Proxy(harness, path, launch, stdout, stderr)
    for raw in stdin:
        proxy.handle(raw)
    return proxy.finish()
