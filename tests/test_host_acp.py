"""GH-571 — `host-acp`: one host process serves an editor's ACP sessions across project folders.

The relay sits between the editor and the agent. It forwards every line untouched, except that the
first `session/new` for a project folder waits for that folder's per-project setup (`project-setup`)
and a `session/new` it cannot honour is answered with a JSON-RPC error instead of forwarded.

The stubs stand in for the boundaries, never for the relay: the stub agent is a real process that
speaks newline-delimited JSON-RPC and logs every raw line it receives, and the stub setup verb is a
real process that logs its argv and exits with the code the test sets.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harnessed import acprelay

_STUB_AGENT = r'''
import json, sys
log, events = sys.argv[1], sys.argv[2]
sessions = {}
out = sys.stdout.buffer
def send(msg):
    out.write(json.dumps(msg).encode() + b"\n")
    out.flush()
for raw in sys.stdin.buffer:
    with open(log, "ab") as f:
        f.write(raw)
    try:
        m = json.loads(raw)
    except ValueError:
        continue
    if not isinstance(m, dict) or "id" not in m or "method" not in m:
        continue
    meth, params = m["method"], m.get("params") or {}
    if meth == "initialize":
        send({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        with open(events, "a") as f:
            f.write("agent session/new " + params["cwd"] + "\n")
        sid = "s%d" % len(sessions)
        sessions[sid] = params["cwd"]
        send({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": sid}})
    elif meth == "session/prompt":
        sid = params["sessionId"]
        send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": sessions[sid]}}}})
        send({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
    elif meth == "blast":
        for size in params["sizes"]:
            send({"jsonrpc": "2.0", "method": "noise", "params": {"pad": "x" * size}})
        send({"jsonrpc": "2.0", "id": m["id"], "result": {}})
    else:
        send({"jsonrpc": "2.0", "id": m["id"], "result": {}})
'''

_STUB_SETUP = r'''
import sys
events, rc = sys.argv[1], int(sys.argv[2])
with open(events, "a") as f:
    f.write("setup " + " ".join(sys.argv[3:]) + "\n")
print("SETUP-STDOUT-NOISE")
sys.exit(rc)
'''


class _Relay:
    """`acprelay.run` on a thread, with the editor's two pipes in the test's hands."""

    def __init__(self, tmp: Path, *, setup_rc: int = 0) -> None:
        self.tmp = tmp
        self.log = tmp / "agent.log"
        self.events = tmp / "events.log"
        self.log.touch()
        self.events.touch()
        agent = tmp / "stub_agent.py"
        agent.write_text(_STUB_AGENT)
        setup = tmp / "stub_setup.py"
        setup.write_text(_STUB_SETUP)
        self.setup_rc = setup_rc
        launch = tmp / "launch"
        launch.mkdir(exist_ok=True)
        in_r, self._in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._stdin = os.fdopen(in_r, "rb")
        self._stdout = os.fdopen(out_w, "wb")
        self._editor_in = os.fdopen(self._in_w, "wb")
        self.lines: queue.Queue = queue.Queue()
        self.raw: list[bytes] = []
        self.code: int | None = None

        def setup_argv(project: Path) -> list[str]:
            return [sys.executable, str(setup), str(self.events), str(self.setup_rc),
                    "omp", str(project), "--stack", "s"]

        def run() -> None:
            try:
                self.code = acprelay.run(
                    [sys.executable, str(agent), str(self.log), str(self.events)],
                    dict(os.environ), setup_argv, cwd=launch,
                    stdin=self._stdin, stdout=self._stdout,
                )
            finally:
                self._stdout.close()

        def read() -> None:
            with os.fdopen(out_r, "rb") as f:
                for line in f:
                    self.raw.append(line)
                    self.lines.put(line)
            self.lines.put(None)

        self._runner = threading.Thread(target=run, daemon=True)
        self._reader = threading.Thread(target=read, daemon=True)
        self._runner.start()
        self._reader.start()

    def send_raw(self, line: bytes) -> None:
        self._editor_in.write(line)
        self._editor_in.flush()

    def send(self, msg: dict) -> None:
        self.send_raw(json.dumps(msg).encode() + b"\n")

    def next(self, timeout: float = 20) -> dict:
        raw = self.lines.get(timeout=timeout)
        assert raw is not None, "relay stdout closed early"
        return json.loads(raw)

    def until_id(self, rid, timeout: float = 20) -> tuple[dict, list[dict]]:
        seen = []
        while True:
            m = self.next(timeout)
            if m.get("id") == rid and "method" not in m:
                return m, seen
            seen.append(m)

    def request(self, rid, method: str, params: dict) -> tuple[dict, list[dict]]:
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return self.until_id(rid)

    def close(self) -> int | None:
        self._editor_in.close()
        self._runner.join(20)
        self._reader.join(20)
        return self.code

    def setup_runs(self) -> list[str]:
        return [ln for ln in self.events.read_text().splitlines() if ln.startswith("setup ")]


@pytest.fixture
def relay(tmp_path):
    r = _Relay(tmp_path)
    yield r
    r.close()


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    a, b = tmp_path / "projA", tmp_path / "projB"
    a.mkdir()
    b.mkdir()
    return a, b


class TestOneProcessManyProjects:
    def test_s3_1_each_session_reports_its_own_folder(self, relay, tmp_path):
        a, b = _dirs(tmp_path)
        relay.request(1, "initialize", {"protocolVersion": 1})
        sa, _ = relay.request(2, "session/new", {"cwd": str(a), "mcpServers": []})
        sb, _ = relay.request(3, "session/new", {"cwd": str(b), "mcpServers": []})
        _, chunks_a = relay.request(4, "session/prompt", {"sessionId": sa["result"]["sessionId"], "prompt": []})
        _, chunks_b = relay.request(5, "session/prompt", {"sessionId": sb["result"]["sessionId"], "prompt": []})
        assert chunks_a[0]["params"]["update"]["content"]["text"] == str(a)
        assert chunks_b[0]["params"]["update"]["content"]["text"] == str(b)

    def test_s3_2_the_agent_gets_each_cwd_unchanged(self, relay, tmp_path):
        a, b = _dirs(tmp_path)
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": str(a), "mcpServers": []}},
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(b), "mcpServers": []}},
        ]
        for m in msgs:
            relay.send(m)
            relay.until_id(m["id"])
        got = [json.loads(ln) for ln in relay.log.read_bytes().splitlines()]
        assert got == msgs

    def test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent(self, relay, tmp_path):
        gone = tmp_path / "does-not-exist"
        relay.send({"jsonrpc": "2.0", "id": 7, "method": "session/new", "params": {"cwd": str(gone), "mcpServers": []}})
        raw = relay.lines.get(timeout=20)
        assert raw == (
            b'{"jsonrpc":"2.0","id":7,"error":{"code":-32602,"message":"session/new cwd does not exist: '
            + str(gone).encode() + b'"}}\n'
        )
        relay.request(8, "initialize", {})  # a later request proves the relay is still serving
        assert relay.setup_runs() == []
        assert b"session/new" not in relay.log.read_bytes()


class TestPerProjectSetup:
    def test_s4_1_the_first_session_runs_setup_before_the_agent_sees_it(self, relay, tmp_path):
        a, _ = _dirs(tmp_path)
        relay.request(1, "session/new", {"cwd": str(a), "mcpServers": []})
        assert relay.events.read_text().splitlines() == [
            f"setup omp {a.resolve()} --stack s",
            f"agent session/new {a}",
        ]

    def test_s4_2_a_second_session_in_the_same_project_does_not_rerun_it(self, relay, tmp_path):
        a, _ = _dirs(tmp_path)
        link = tmp_path / "link-to-A"
        link.symlink_to(a)
        relay.request(1, "session/new", {"cwd": str(a), "mcpServers": []})
        relay.request(2, "session/new", {"cwd": str(a), "mcpServers": []})
        relay.request(3, "session/new", {"cwd": str(link), "mcpServers": []})
        assert len(relay.setup_runs()) == 1

    def test_setup_output_never_reaches_stdout(self, relay, tmp_path):
        a, _ = _dirs(tmp_path)
        relay.request(1, "session/new", {"cwd": str(a), "mcpServers": []})
        relay.close()
        assert all(b"SETUP-STDOUT-NOISE" not in ln for ln in relay.raw)


class TestFailedSetup:
    def test_s4_3_a_failed_setup_is_an_error_naming_the_project(self, tmp_path):
        r = _Relay(tmp_path, setup_rc=3)
        try:
            a, _ = _dirs(tmp_path)
            reply, _ = r.request(9, "session/new", {"cwd": str(a), "mcpServers": []})
            assert reply["error"]["code"] == -32000
            assert str(a) in reply["error"]["message"]
            assert b"session/new" not in r.log.read_bytes()
        finally:
            r.close()

    def test_s4_4_a_failed_project_is_set_up_again_next_time(self, tmp_path):
        r = _Relay(tmp_path, setup_rc=3)
        try:
            a, _ = _dirs(tmp_path)
            r.request(1, "session/new", {"cwd": str(a), "mcpServers": []})
            r.request(2, "session/new", {"cwd": str(a), "mcpServers": []})
            assert len(r.setup_runs()) == 2
        finally:
            r.close()


class TestLifecycle:
    def test_closing_stdin_ends_the_relay_with_the_agents_exit_code(self, tmp_path):
        r = _Relay(tmp_path)
        r.request(1, "initialize", {})
        assert r.close() == 0


_FAST = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@_FAST
@given(sizes=st.lists(st.integers(1, 256 * 1024), min_size=1, max_size=4), errors=st.integers(1, 4))
def test_s3_5_concurrent_writers_never_interleave_a_line(tmp_path_factory, sizes, errors):
    tmp = tmp_path_factory.mktemp("s35")
    r = _Relay(tmp)
    try:
        r.send({"jsonrpc": "2.0", "id": "blast", "method": "blast", "params": {"sizes": sizes}})
        for i in range(errors):
            r.send({"jsonrpc": "2.0", "id": f"e{i}", "method": "session/new",
                    "params": {"cwd": str(tmp / "missing"), "mcpServers": []}})
        r.request("sync", "ping", {})
    finally:
        r.close()
    parsed = [json.loads(ln) for ln in r.raw]  # any interleaving fails here
    assert len(parsed) == len(sizes) + 1 + errors + 1


def _not_session_new(line: bytes) -> bool:
    try:
        m = json.loads(line)
    except ValueError:
        return True
    return not (isinstance(m, dict) and m.get("method") == "session/new")


@_FAST
@given(lines=st.lists(st.binary(max_size=200).filter(lambda b: b"\n" not in b).filter(_not_session_new), max_size=6))
def test_s3_6_every_other_line_is_forwarded_byte_for_byte(tmp_path_factory, lines):
    tmp = tmp_path_factory.mktemp("s36")
    r = _Relay(tmp)
    try:
        for line in lines:
            r.send_raw(line + b"\n")
        sync = b'{"jsonrpc":"2.0","id":"sync","method":"ping"}\n'
        r.send_raw(sync)
        r.until_id("sync")
    finally:
        r.close()
    assert r.log.read_bytes() == b"".join(line + b"\n" for line in lines) + sync
