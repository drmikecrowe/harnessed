#!/usr/bin/env python3
"""Drive `harnessed container-acp` the way an ACP client would, and check its stdout (#529).

    tools/acp-smoke.py <project> --stack <name> [--prompt "Reply with OK"] [--harnessed CMD]
    tools/acp-smoke.py <project> --stack <name> --verb host-acp [--check-cwd <B>]
    tools/acp-smoke.py <project> --stack <name> --no-path [--launch-timeout 60] [--check-cwd <B>]

`--verb host-acp` (GH-571) runs `host-acp`, which takes no project path: it starts in a new empty
folder, as an editor starts it, and the project reaches it only as the `session/new` cwd.
`--check-cwd <B>` opens a second session in B, asks each session for its working directory, and
fails when a reply does not name that session's folder. It needs agent credentials.
`--no-path` (GH-566) runs `container-acp` the way `host-acp` runs: from a new empty folder, with no
project path, so the project reaches it only as the `session/new` cwd. With `--launch-timeout 60` it
holds `initialize` to Atlas's 60 s limit. Stderr is read as it passes through, and a line starting
`harnessed: ACP initialize drift` fails the run: the proxy's canned `initialize` reply no longer
matches the agent's own.

Sends `initialize` and `session/new`, and with `--prompt` one `session/prompt` turn. Fails when any
byte on stdout is not a JSON-RPC 2.0 message, when a request gets no result, or on timeout. Stderr
passes through, so the launch messages stay visible.

Run it twice for the issue's "Done when": once with no pod (it creates one), once with the pod up
(it attaches). The prompt turn needs omp credentials, which a CI runner may not have.

Not a pytest test: it starts a real pod. Run it from the worktree with `uv run`, never the global
`harnessed`, which is an editable install of main/.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _reader(stream, out: queue.Queue) -> None:
    for raw in stream:
        out.put(raw)
    out.put(None)


def _next_message(lines: queue.Queue, timeout: float) -> dict:
    try:
        raw = lines.get(timeout=timeout)
    except queue.Empty:
        raise SystemExit(f"FAIL: no message on stdout within {timeout:.0f}s") from None
    if raw is None:
        raise SystemExit("FAIL: stdout closed before the exchange finished")
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"FAIL: stdout byte that is not JSON-RPC: {raw!r}") from None
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise SystemExit(f"FAIL: stdout message that is not JSON-RPC 2.0: {raw!r}")
    return msg


def _send(proc, msg: dict, what: str) -> None:
    try:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        raise SystemExit(f"FAIL: process closed stdin before {what} could be sent") from None


def _request(
    proc, lines: queue.Queue, req_id: int, method: str, params: dict, timeout: float,
    text: list | None = None,
):
    """Send one request and return its result. `text`, when given, collects the agent's reply text."""
    _send(proc, {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}, method)
    while True:
        msg = _next_message(lines, timeout)
        if text is not None and msg.get("method") == "session/update":
            update = msg.get("params", {}).get("update", {})
            content = update.get("content", {})
            if update.get("sessionUpdate") == "agent_message_chunk" and content.get("type") == "text":
                text.append(content["text"])
        if msg.get("id") == req_id and "method" not in msg:
            if "error" in msg:
                raise SystemExit(f"FAIL: {method} returned an error: {msg['error']}")
            print(f"ok: {method}", file=sys.stderr)
            return msg["result"]
        if "method" in msg and "id" in msg:
            # A request from the agent (permission, fs). This client grants nothing.
            _send(proc, {
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32601, "message": "not supported by acp-smoke"},
            }, f"the reply to {msg['method']}")
        # Anything else is a notification, such as session/update. It parsed, which is the check.


_CWD_QUESTION = "What is your current working directory? Reply with only the absolute path, nothing else."


def _launch_argv(harnessed: str, verb: str, harness: str, project: Path, stack: str,
                 no_path: bool = False) -> list[str]:
    """`container-acp` takes the project as its path unless `no_path` (GH-566); `host-acp` takes
    none (GH-571)."""
    where = [str(project)] if verb == "container-acp" and not no_path else []
    return [*shlex.split(harnessed), verb, harness, *where, "--stack", stack]


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--harness", default="omp")
    ap.add_argument("--prompt", help="also run one prompt turn (needs agent credentials)")
    ap.add_argument("--harnessed", default="uv run harnessed", help="command that runs harnessed")
    ap.add_argument("--launch-timeout", type=float, default=900, help="seconds to wait for initialize")
    ap.add_argument("--timeout", type=float, default=300, help="seconds to wait for later replies")
    ap.add_argument("--verb", choices=["container-acp", "host-acp"], default="container-acp")
    ap.add_argument("--check-cwd", type=Path, help="open a second session here and check both cwds")
    ap.add_argument("--no-path", action="store_true",
                    help="start container-acp with no project path, in a new empty folder (GH-566)")
    return ap


_DRIFT = "harnessed: ACP initialize drift"


def _watch_stderr(stream, drift: list[str]) -> None:
    """Pass the launched process's stderr through, and keep every drift line (GH-566 S5.3)."""
    for line in stream:
        sys.stderr.write(line)
        sys.stderr.flush()
        if line.startswith(_DRIFT):
            drift.append(line.strip())


def _cwd_matches(reply: str, folder: Path) -> bool:
    """Whether `reply` names `folder` as a whole path. Not a substring test: `/a/b-check` and the
    file `/a/b.txt` are not `/a/b` (PR #572 review). The path may contain spaces (adversary round
    3), may sit in quotes, backticks or brackets, and may be followed by any non-path character; a
    `.` counts only when it ends the sentence."""
    before = r"(?:^|[\s`'\"(\[<])"
    after = r"(?=$|[^\w/.-]|\.(?=$|\s))"
    return re.search(before + re.escape(str(folder)) + r"/?" + after, reply) is not None


def _check_cwd(proc, lines: queue.Queue, sessions: list[tuple[str, Path]], timeout: float) -> None:
    for n, (session_id, folder) in enumerate(sessions):
        text: list = []
        _request(proc, lines, 10 + n, "session/prompt", {
            "sessionId": session_id, "prompt": [{"type": "text", "text": _CWD_QUESTION}],
        }, timeout, text)
        reply = "".join(text).strip()
        if not _cwd_matches(reply, folder):
            raise SystemExit(f"FAIL: the session in {folder} reported its cwd as {reply!r}")
        print(f"ok: the session in {folder} reported {reply!r}", file=sys.stderr)


def main() -> int:
    ap = _parser()
    args = ap.parse_args()
    if args.no_path and args.verb != "container-acp":
        ap.error("--no-path applies to container-acp only; host-acp never takes a path")

    project = args.project.resolve()
    argv = _launch_argv(args.harnessed, args.verb, args.harness, project, args.stack, args.no_path)
    # host-acp, and container-acp with --no-path, start where the editor starts them, never in the
    # project.
    pathless = args.verb == "host-acp" or args.no_path
    launch_dir = tempfile.mkdtemp(prefix="acp-smoke-launch-") if pathless else None
    print(f"run: {shlex.join(argv)}" + (f" (in {launch_dir})" if launch_dir else ""), file=sys.stderr)
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            bufsize=1, cwd=launch_dir,
        )
    except OSError as exc:
        # Before the `try` whose `finally` removes the launch folder, so remove it here (PR #572).
        if launch_dir:
            shutil.rmtree(launch_dir, ignore_errors=True)
        raise SystemExit(f"FAIL: could not start {argv[0]}: {exc}") from None
    if proc.stdin is None or proc.stdout is None:  # unreachable with PIPE; narrows the types
        raise SystemExit("FAIL: could not open pipes to harnessed")
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    drift: list[str] = []
    errs = threading.Thread(target=_watch_stderr, args=(proc.stderr, drift), daemon=True)
    errs.start()
    started = time.monotonic()
    try:
        _request(proc, lines, 1, "initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        }, args.launch_timeout)
        print(f"ok: initialize answered in {time.monotonic() - started:.1f}s", file=sys.stderr)
        session = _request(proc, lines, 2, "session/new", {"cwd": str(project), "mcpServers": []}, args.timeout)
        if args.prompt:
            result = _request(proc, lines, 3, "session/prompt", {
                "sessionId": session["sessionId"],
                "prompt": [{"type": "text", "text": args.prompt}],
            }, args.timeout)
            print(f"ok: stopReason={result.get('stopReason')}", file=sys.stderr)
        if args.check_cwd:
            second = args.check_cwd.resolve()
            other = _request(proc, lines, 4, "session/new", {"cwd": str(second), "mcpServers": []}, args.timeout)
            _check_cwd(proc, lines, [(session["sessionId"], project), (other["sessionId"], second)], args.timeout)
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if launch_dir:
            shutil.rmtree(launch_dir, ignore_errors=True)
    # After the `finally`, so a failure raised in the exchange is never masked by this one.
    if proc.returncode < 0:
        raise SystemExit("FAIL: the agent did not exit within 30s of stdin closing")
    # Whatever the agent wrote after the last reply must parse too.
    try:
        while (raw := lines.get(timeout=30)) is not None:
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                raise SystemExit(f"FAIL: stdout byte that is not JSON-RPC: {raw!r}") from None
    except queue.Empty:
        raise SystemExit("FAIL: stdout did not close within 30s") from None
    if proc.returncode != 0:
        raise SystemExit(f"FAIL: harnessed exited with {proc.returncode}")
    errs.join(timeout=30)
    if drift:
        raise SystemExit("FAIL: the canned initialize reply drifted from the agent's own: " + "; ".join(drift))
    print("PASS: every stdout byte parsed as JSON-RPC", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
