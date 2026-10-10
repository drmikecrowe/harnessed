"""The `host-acp` relay (GH-571): one host agent process, many editor projects.

An editor such as Atlas starts one ACP agent per entry and reuses it across projects, naming each
session's folder in `session/new`. The agent follows that folder itself. What it cannot do is the
per-project half of a `host-run` launch (recipe setup and init scripts, the project tool env file),
so the relay runs `project-setup` for a folder the first time a `session/new` names it, and only then
hands the request to the agent.

Everything else is forwarded byte for byte. Stdout is the editor's JSON-RPC channel, so every write
to it goes through one lock: the agent's lines and the relay's own error replies would otherwise
interleave inside a line once a message outgrows the pipe's atomic write size.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO, Callable, Optional

# JSON-RPC 2.0: -32602 is "invalid params"; -32000..-32099 is reserved for implementation errors.
_INVALID_PARAMS = -32602
_SETUP_FAILED = -32000


def _error(rid, code: int, message: str) -> bytes:
    msg = {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
    return json.dumps(msg, separators=(",", ":")).encode() + b"\n"


def _intercept(
    line: bytes, done: set[Path], setup_argv: Callable[[Path], list[str]]
) -> Optional[bytes]:
    """The reply to send the editor INSTEAD of forwarding `line`, or None to forward it.

    Only a `session/new` request is ever held back. Its folder is set up once per relay, keyed on
    the resolved path so a symlink to a set-up project is the same project. A failed setup is not
    remembered, so the next `session/new` for that folder tries again.
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
    try:
        rc = subprocess.run(
            setup_argv(project), stdin=subprocess.DEVNULL, stdout=sys.stderr.fileno(), check=False,
        ).returncode
    except OSError as exc:  # the setup command could not start at all
        return _error(msg["id"], _SETUP_FAILED, f"per-project setup failed for {cwd} ({exc})")
    if rc != 0:
        return _error(msg["id"], _SETUP_FAILED, f"per-project setup failed for {cwd} (exit {rc})")
    done.add(project)
    return None


def run(
    agent_argv: list[str],
    agent_env: dict[str, str],
    setup_argv: Callable[[Path], list[str]],
    *,
    cwd: Path,
    stdin: BinaryIO,
    stdout: BinaryIO,
) -> int:
    """Start the agent in `cwd` and relay until it exits. Returns the agent's exit code.

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
            except OSError:
                # The editor's channel is gone. Left running, the agent fills its stdout pipe and
                # blocks, and `run` waits on it forever.
                agent.kill()
                return

    def from_editor() -> None:
        done: set[Path] = set()
        try:
            for line in iter(stdin.readline, b""):
                reply = _intercept(line, done, setup_argv)
                if reply is not None:
                    emit(reply)
                    continue
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
    return code
