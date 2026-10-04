#!/usr/bin/env python3
"""Drive `harnessed container-acp` the way an ACP client would, and check its stdout (#529).

    tools/acp-smoke.py <project> --stack <name> [--prompt "Reply with OK"] [--harnessed CMD]

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
import shlex
import subprocess
import sys
import threading
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


def _request(proc, lines: queue.Queue, req_id: int, method: str, params: dict, timeout: float):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        msg = _next_message(lines, timeout)
        if msg.get("id") == req_id and "method" not in msg:
            if "error" in msg:
                raise SystemExit(f"FAIL: {method} returned an error: {msg['error']}")
            print(f"ok: {method}", file=sys.stderr)
            return msg["result"]
        if "method" in msg and "id" in msg:
            # A request from the agent (permission, fs). This client grants nothing.
            proc.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32601, "message": "not supported by acp-smoke"},
            }) + "\n")
            proc.stdin.flush()
        # Anything else is a notification, such as session/update. It parsed, which is the check.


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--harness", default="omp")
    ap.add_argument("--prompt", help="also run one prompt turn (needs agent credentials)")
    ap.add_argument("--harnessed", default="uv run harnessed", help="command that runs harnessed")
    ap.add_argument("--launch-timeout", type=float, default=900, help="seconds to wait for initialize")
    ap.add_argument("--timeout", type=float, default=300, help="seconds to wait for later replies")
    args = ap.parse_args()

    project = args.project.resolve()
    argv = [*shlex.split(args.harnessed), "container-acp", args.harness, str(project), "--stack", args.stack]
    print(f"run: {shlex.join(argv)}", file=sys.stderr)
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    try:
        _request(proc, lines, 1, "initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        }, args.launch_timeout)
        session = _request(proc, lines, 2, "session/new", {"cwd": str(project), "mcpServers": []}, args.timeout)
        if args.prompt:
            result = _request(proc, lines, 3, "session/prompt", {
                "sessionId": session["sessionId"],
                "prompt": [{"type": "text", "text": args.prompt}],
            }, args.timeout)
            print(f"ok: stopReason={result.get('stopReason')}", file=sys.stderr)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.terminate()
    # Whatever the agent wrote after the last reply must parse too.
    while (raw := lines.get(timeout=30)) is not None:
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            raise SystemExit(f"FAIL: stdout byte that is not JSON-RPC: {raw!r}") from None
    print("PASS: every stdout byte parsed as JSON-RPC", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
