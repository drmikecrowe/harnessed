"""`container-acp` as a host-side ACP proxy (#566).

An editor can start the agent anywhere and kill it if `initialize` is slow: Atlas starts it in its own
working directory and waits 60 s. So the proxy answers `initialize` itself, from `INITIALIZE_RESULTS`,
and defers everything that needs a project to the first `session/new` or `session/load`. That request
names the project — the path argument when one was given, else its `cwd` — and the proxy starts the
agent through `launch`, replays the client's `initialize` to it, and from then on forwards every line
both ways unchanged. One process serves one project.

Line-delimited JSON-RPC 2.0 on both sides, the same framing ACP uses on stdio.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import IO, Callable, Optional, TextIO

import typer

from . import paths

# What each harness's own `initialize` returns, at the version catalog/agents/<harness>/agent.yaml pins:
# omp 18.6.1 (`omp acp`) and claude-agent-acp 0.85.1. The proxy has to answer before the agent runs,
# so the reply is held here. On every session the agent's real reply is compared against it in
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

DRIFT_FIELDS = ("protocolVersion", "agentCapabilities", "authMethods")

_SESSION_METHODS = ("session/new", "session/load")

# JSON-RPC 2.0 error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# The id the proxy gives `initialize` when the client opened a session without sending one.
_SYNTHETIC_INIT_ID = "harnessed-initialize"

Launch = Callable[[Path], "tuple[subprocess.Popen[bytes], Path]"]


class _Session:
    """The running agent: the child, its pipes, the directory it starts in, and the project."""

    def __init__(self, child: subprocess.Popen[bytes], start_dir: Path, project: Path) -> None:
        if child.stdin is None or child.stdout is None:
            raise ValueError("the launch must pipe the agent's stdin and stdout")
        self.child = child
        self.stdin: IO[bytes] = child.stdin
        self.stdout: IO[bytes] = child.stdout
        self.start_dir = start_dir
        self.project = project

    def send(self, raw: bytes) -> bool:
        """Write one line to the agent. False when it is gone."""
        try:
            self.stdin.write(raw if raw.endswith(b"\n") else raw + b"\n")
            self.stdin.flush()
        except (BrokenPipeError, ValueError):
            return False
        return True


class _Proxy:
    def __init__(self, harness: str, path: Optional[Path], launch: Launch,
                 stdout: IO[bytes], stderr: TextIO) -> None:
        self.harness = harness
        self.path = path
        self.launch = launch
        self.stdout = stdout
        self.stderr = stderr
        self.lock = threading.Lock()
        self.init_request: Optional[dict] = None
        self.session: Optional[_Session] = None

    def write(self, raw: bytes) -> None:
        with self.lock:
            self.stdout.write(raw if raw.endswith(b"\n") else raw + b"\n")
            self.stdout.flush()

    def send(self, msg: dict) -> None:
        self.write(json.dumps(msg).encode())

    def error(self, id_, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})

    def note(self, line: str) -> None:
        print(f"harnessed: {line}", file=self.stderr, flush=True)

    # --- before the agent runs -------------------------------------------------------------------

    def before_session(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            self.error(None, _PARSE_ERROR, "not JSON")
            return
        if not isinstance(msg, dict):
            self.error(None, _INVALID_REQUEST, "not a JSON-RPC message")
            return
        method, id_ = msg.get("method"), msg.get("id")
        if method == "initialize":
            self.init_request = msg
            self.send({"jsonrpc": "2.0", "id": id_, "result": INITIALIZE_RESULTS[self.harness]})
        elif method in _SESSION_METHODS:
            self.open_session(msg)
        elif method is not None and "id" in msg:
            self.error(id_, _INVALID_REQUEST, f"no session yet: {method} needs session/new first")
        # A notification or a response before any session has nobody to go to.

    def requested_project(self, msg: dict) -> Optional[Path]:
        """The project a session request names, or None after answering it with an error."""
        if self.path is not None:
            return self.path
        cwd = (msg.get("params") or {}).get("cwd")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            self.error(msg.get("id"), _INVALID_PARAMS, f"cwd must be an absolute path, got {cwd!r}")
            return None
        project = Path(cwd)
        if not project.is_dir():
            self.error(msg.get("id"), _INVALID_PARAMS, f"cwd is not a directory: {cwd}")
            return None
        return project

    def open_session(self, msg: dict) -> None:
        project = self.requested_project(msg)
        if project is None:
            return
        try:
            child, start_dir = self.launch(project)
        except typer.Exit as exc:
            self.error(msg.get("id"), _INTERNAL_ERROR, f"launch failed (exit {exc.exit_code}); see stderr")
            return
        session = _Session(child, start_dir, project)
        if not self.handshake(session):
            code = child.wait()
            self.error(msg.get("id"), _INTERNAL_ERROR, f"launch failed (exit {code}); see stderr")
            return
        self.session = session
        self.forward_session(session, msg)

    def handshake(self, session: _Session) -> bool:
        """Replay `initialize` to the agent and consume its reply. False when it exits first."""
        init = self.init_request or {
            "jsonrpc": "2.0", "id": _SYNTHETIC_INIT_ID, "method": "initialize",
            "params": {"protocolVersion": 1},
        }
        if not session.send(json.dumps(init).encode()):
            return False
        for raw in session.stdout:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                self.write(raw)  # not ours to judge; the client sees what the agent sent
                continue
            if isinstance(msg, dict) and msg.get("id") == init["id"] and "method" not in msg:
                self.check_drift(msg.get("result") or {})
                return True
            self.write(raw)
        return False

    def check_drift(self, real: dict) -> None:
        canned = INITIALIZE_RESULTS[self.harness]
        for field in DRIFT_FIELDS:
            if real.get(field) != canned.get(field):
                self.note(f"ACP initialize drift: {self.harness}: {field}")

    # --- with the agent running ------------------------------------------------------------------

    def forward_session(self, session: _Session, msg: dict) -> None:
        """Send a session request to the agent with `cwd` set to where the agent runs."""
        params = dict(msg.get("params") or {})
        params["cwd"] = str(paths.container_project_path(session.start_dir))
        session.send(json.dumps({**msg, "params": params}).encode())

    def during_session(self, session: _Session, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            session.send(raw)
            return
        if not isinstance(msg, dict) or msg.get("method") not in _SESSION_METHODS:
            session.send(raw)
            return
        if self.path is None:
            project = self.requested_project(msg)
            if project is None:
                return
            if project.resolve() != session.project.resolve():
                self.error(msg.get("id"), _INVALID_PARAMS, f"one project per process: {session.project}")
                return
        self.forward_session(session, msg)

    def feed(self, session: _Session, stdin: IO[bytes]) -> None:
        for raw in stdin:
            self.during_session(session, raw)
        try:
            session.stdin.close()
        except BrokenPipeError:
            pass

    def pump(self, session: _Session) -> int:
        for raw in session.stdout:
            self.write(raw)
        return session.child.wait()


def serve(harness: str, *, path: Optional[Path], launch: Launch,
          stdin: IO[bytes], stdout: IO[bytes], stderr: TextIO) -> int:
    """Run the proxy until the agent exits, or until stdin closes before any session. Return the
    agent's exit code, or 0 when no agent ever ran."""
    proxy = _Proxy(harness, path, launch, stdout, stderr)
    for raw in stdin:
        proxy.before_session(raw)
        if proxy.session is not None:
            break
    session = proxy.session
    if session is None:
        return 0
    # The rest of stdin goes to the agent on a thread of its own; this one carries the agent's stdout.
    # Daemon, so an agent that exits first ends the proxy even while the client holds stdin open.
    threading.Thread(target=proxy.feed, args=(session, stdin), daemon=True).start()
    return proxy.pump(session)
