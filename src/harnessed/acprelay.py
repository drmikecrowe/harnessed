"""The `host-acp` relay (GH-571): one host agent process, many editor projects.

An editor such as Atlas starts one ACP agent per entry and reuses it across projects, naming each
session's folder in `session/new`. The agent follows that folder itself. What it cannot do is the
per-project half of a `host-run` launch (recipe setup and init scripts, the project tool env file),
so the relay runs `project-setup` for a folder the first time a `session/new` names it, and only then
hands the request to the agent.

Given the stack's MCP servers, the relay also adds them to the `mcpServers` of every `session/new`,
`session/load` and `session/resume`: omp in ACP mode connects only the servers those requests name.

Everything else is forwarded byte for byte. Stdout is the editor's JSON-RPC channel, so every write
to it goes through one lock: the agent's lines and the relay's own error replies would otherwise
interleave inside a line once a message outgrows the pipe's atomic write size.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Sequence

# JSON-RPC 2.0: -32602 is "invalid params"; -32000..-32099 is reserved for implementation errors.
_INVALID_PARAMS = -32602
_SETUP_FAILED = -32000

# The ACP requests that carry the session's `mcpServers`.
_MCP_METHODS = frozenset({"session/new", "session/load", "session/resume"})
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class _Filler:
    """Fills `${VAR}` placeholders from `env`, noting in `missing` each name `env` lacks."""

    def __init__(self, env: dict[str, str], missing: list[str]) -> None:
        self._env = env
        self._missing = missing

    def _sub(self, m: re.Match) -> str:
        if m.group(1) not in self._env:
            self._missing.append(m.group(1))
            return m.group(0)
        return self._env[m.group(1)]

    def __call__(self, value: str) -> str:
        return _PLACEHOLDER.sub(self._sub, value)

    def pairs(self, mapping: Optional[dict]) -> list[dict]:
        """A `{name: value}` map as ACP's `[{name, value}]` list, filled."""
        return [{"name": k, "value": self(str(v))} for k, v in (mapping or {}).items()]


def acp_mcp_servers(mcp_servers: dict, env: dict[str, str]) -> list[dict]:
    """The stack's `mcpServers` (the `.mcp.json` shape `wire_mcp` writes) as ACP `McpServer` entries.

    `${VAR}` placeholders are filled from `env`, the agent's own environment, so a secret URL
    travels only over the agent's pipe and never to disk. omp fails the whole session when one
    server fails to connect, so a server that cannot start for a reason known here (an unset
    variable, a stdio command not on PATH) is dropped with a warning on stderr instead.
    """
    out: list[dict] = []
    for name, spec in mcp_servers.items():
        missing: list[str] = []
        fill = _Filler(env, missing)
        if "command" in spec:
            entry = {"name": name, "command": fill(spec["command"]),
                     "args": [fill(str(a)) for a in spec.get("args", [])], "env": fill.pairs(spec.get("env"))}
            if not missing and shutil.which(entry["command"], path=env.get("PATH")) is None:
                print(f"harnessed: MCP server '{name}' skipped: '{entry['command']}' is not on PATH",
                      file=sys.stderr)
                continue
        else:
            entry = {"type": spec.get("type", "http"), "name": name, "url": fill(spec["url"]),
                     "headers": fill.pairs(spec.get("headers"))}
        if missing:
            print(f"harnessed: MCP server '{name}' skipped: {', '.join(sorted(set(missing)))} not set",
                  file=sys.stderr)
            continue
        out.append(entry)
    return out


def _add_mcp(line: bytes, servers: Sequence[dict]) -> bytes:
    """`line` with `servers` added to its `mcpServers` when it is a request that carries them.

    An entry the editor already names wins: it is the editor user's own choice for that session.
    Any other line comes back unchanged, byte for byte.
    """
    try:
        msg = json.loads(line)
    except ValueError:
        return line
    if not isinstance(msg, dict) or msg.get("method") not in _MCP_METHODS:
        return line
    params = msg.get("params")
    if not isinstance(params, dict):
        return line
    editor = params.get("mcpServers")
    editor = editor if isinstance(editor, list) else []
    named = {s.get("name") for s in editor if isinstance(s, dict)}
    params["mcpServers"] = editor + [s for s in servers if s["name"] not in named]
    return json.dumps(msg, separators=(",", ":")).encode() + b"\n"


def _error(rid, code: int, message: str) -> bytes:
    msg = {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
    return json.dumps(msg, separators=(",", ":")).encode() + b"\n"


class _Setups:
    """The project-setup processes in flight, shared by the editor's thread (which starts them) and
    `run` (which stops them when the relay ends). One lock covers both, and once `close` has run no
    new setup starts, so none can slip in after the stop and outlive the relay (PR #572 review)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: list[subprocess.Popen] = []
        self._closed = False

    def start(self, argv: list[str]) -> Optional[subprocess.Popen]:
        """Start one setup, or return None once the relay is ending. Raises OSError as Popen does."""
        with self._lock:
            if self._closed:
                return None
            # Its own session, so `_stop` can end everything it started (scripts, service
            # containers), not only its pid.
            setup = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=sys.stderr.fileno(), start_new_session=True,
            )
            self._running.append(setup)
            return setup

    def finished(self, setup: subprocess.Popen) -> None:
        with self._lock:
            self._running.remove(setup)

    def close(self) -> None:
        """Refuse new setups, then stop the ones still running."""
        with self._lock:
            self._closed = True
            running = list(self._running)
        for setup in running:
            _stop(setup)


def _intercept(
    line: bytes, done: set[Path], setup_argv: Callable[[Path], list[str]], setups: _Setups,
) -> Optional[bytes]:
    """The reply to send the editor INSTEAD of forwarding `line`, or None to forward it.

    Only a `session/new` request is ever held back. Its folder is set up once per relay, keyed on
    the resolved path so a symlink to a set-up project is the same project. A failed setup is not
    remembered, so the next `session/new` for that folder tries again. Setups start through
    `setups`, so `run` can stop one if the relay ends first.
    """
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("method") != "session/new" or "id" not in msg:
        return None
    params = msg.get("params")
    cwd = params.get("cwd") if isinstance(params, dict) else None
    if not isinstance(cwd, str) or not Path(cwd).is_dir():
        return _error(msg["id"], _INVALID_PARAMS, f"session/new cwd does not exist: {cwd}")
    project = Path(cwd).resolve()
    if project in done:
        return None
    # stdout to stderr: the child's output must never reach the editor's channel. stdin from
    # /dev/null: nobody is at a keyboard, so a setup that would prompt takes its no-TTY branch.
    # unbounded: per-project setup runs recipe setup and init scripts, which host-run runs with no
    # deadline either; a timeout here would fail a slow first setup that host-run lets finish.
    argv = setup_argv(project)
    try:
        setup = setups.start(argv)
    except OSError as exc:  # the setup command could not start at all
        return _error(msg["id"], _SETUP_FAILED, f"per-project setup failed for {cwd} ({exc})")
    if setup is None:
        return _error(msg["id"], _SETUP_FAILED, f"per-project setup not started for {cwd}: the relay is ending")
    try:
        rc = setup.wait()
    finally:
        setups.finished(setup)
    if rc != 0:
        return _error(msg["id"], _SETUP_FAILED, f"per-project setup failed for {cwd} (exit {rc})")
    done.add(project)
    return None


def _stop(setup: subprocess.Popen) -> None:
    """End a setup and its whole process group: TERM, up to 10 s for the leader to exit, then KILL
    the group whatever the leader did. A child that ignores TERM outlives a leader that obeys it,
    so the leader exiting proves nothing about the rest of the group (adversary round 3)."""
    try:
        os.killpg(setup.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        setup.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(setup.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # the whole group is already gone
    setup.wait()


def run(
    agent_argv: list[str],
    agent_env: dict[str, str],
    setup_argv: Callable[[Path], list[str]],
    *,
    cwd: Path,
    stdin: BinaryIO,
    stdout: BinaryIO,
    mcp_servers: Sequence[dict] = (),
) -> int:
    """Start the agent in `cwd` and relay until it exits. Returns the agent's exit code.

    `mcp_servers` (ACP `McpServer` entries, see `acp_mcp_servers`) are added to every request that
    carries the session's MCP servers.

    The editor's stdin is read on a daemon thread: when the agent exits first, nothing can unblock
    a read on the editor's pipe, and the process must still end. Closing the editor's stdin closes
    the agent's, which is how an ACP agent is told to stop.
    """
    # unbounded: this IS the agent session, as in host-run.
    agent = subprocess.Popen(
        agent_argv, env=agent_env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    if agent.stdin is None or agent.stdout is None:  # unreachable with PIPE; narrows the types
        raise RuntimeError("could not open pipes to the agent")
    agent_in, agent_out = agent.stdin, agent.stdout
    lock = threading.Lock()

    def emit(line: bytes) -> None:
        with lock:
            stdout.write(line)
            stdout.flush()

    def from_agent() -> None:
        for line in iter(agent_out.readline, b""):
            try:
                emit(line)
            except (OSError, ValueError):  # ValueError: the stream was closed
                # The editor's channel is gone. Left running, the agent fills its stdout pipe and
                # blocks, and `run` waits on it forever.
                agent.kill()
                return

    setups = _Setups()

    def from_editor() -> None:
        done: set[Path] = set()
        try:
            for line in iter(stdin.readline, b""):
                reply = _intercept(line, done, setup_argv, setups)
                if reply is not None:
                    emit(reply)
                    continue
                if mcp_servers:
                    line = _add_mcp(line, mcp_servers)
                agent_in.write(line)
                agent_in.flush()
        except (BrokenPipeError, ValueError):
            return  # the agent is gone; `run` returns its exit code
        finally:
            try:
                agent_in.close()
            except BrokenPipeError:
                pass

    pump = threading.Thread(target=from_agent, daemon=True)
    pump.start()
    threading.Thread(target=from_editor, daemon=True).start()
    code = agent.wait()
    pump.join()
    # A setup the editor's thread still waits on would outlive the relay: host-acp ends with
    # os._exit, and the setup would go on starting services for an editor that is gone.
    setups.close()
    return code
