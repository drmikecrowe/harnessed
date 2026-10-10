"""#566 — `container-acp` as a host-side proxy.

The proxy answers `initialize` itself, from a per-harness table, so an editor that kills a slow agent
(Atlas: 60 s) gets its reply before any pod work. The first `session/new` or `session/load` picks the
project — the path argument when one was given, else the request's `cwd` — starts the agent, replays
`initialize` to it, and from then on forwards every line both ways.

Each test drives `acpproxy.serve` with a fake agent: a small Python script that answers `initialize`
with the result it is given, echoes every other request back as its result, and echoes notifications.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import typer

from harnessed import acpproxy
from harnessed.attachcmd import _ACP_HARNESSES

_FAKE_AGENT = r'''
import json, os, sys
init = json.loads(os.environ["FAKE_INIT"])
if os.environ.get("FAKE_DIE"):
    sys.exit(int(os.environ["FAKE_DIE"]))
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": init}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "method": "_auth/status_update", "params": {}}), flush=True)
    elif meth == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "id": "perm1", "method": "session/request_permission",
                          "params": {}}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}}), flush=True)
    elif meth and "id" in m:
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"],
                          "result": {"method": meth, "params": m.get("params")}}), flush=True)
        if os.environ.get("FAKE_QUIT") == meth:
            sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    else:
        print(json.dumps({"jsonrpc": "2.0", "method": "echo", "params": m}), flush=True)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


def _req(id_, method, params=None):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _init(id_=1):
    return _req(id_, "initialize", {"protocolVersion": 1})


class _Fake:
    """A launch callback that starts the fake agent and records what it was asked to launch."""

    def __init__(self, tmp_path: Path, *, init=None, start_dir=None, raises=None, **env):
        self.script = tmp_path / "fake_agent.py"
        self.script.write_text(_FAKE_AGENT)
        self.init = init
        self.start_dir = start_dir
        self.raises = raises
        self.env = env
        self.calls: list[Path] = []

    def __call__(self, project: Path):
        self.calls.append(project)
        if self.raises is not None:
            raise self.raises
        env = {**os.environ, "FAKE_INIT": json.dumps(self.init), **self.env}
        proc = subprocess.Popen(
            [sys.executable, str(self.script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
        )
        return proc, (self.start_dir or project)


def _serve(harness, lines, launch, *, path=None):
    """Run the proxy over `lines` (stdin then EOF). Return (exit code, stdout messages, stderr)."""
    stdin = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in lines))
    stdout, stderr = io.BytesIO(), io.StringIO()
    code = acpproxy.serve(harness, path=path, launch=launch, stdin=stdin, stdout=stdout, stderr=stderr)
    out = stdout.getvalue().decode()
    msgs = [json.loads(raw) for raw in out.splitlines()]
    # S4.5: every byte on stdout is a JSON-RPC 2.0 message.
    assert out == "" or out.endswith("\n")
    assert all(isinstance(m, dict) and m.get("jsonrpc") == "2.0" for m in msgs), out
    return code, msgs, stderr.getvalue()


def _reply(msgs, id_):
    found = [m for m in msgs if m.get("id") == id_ and "method" not in m]
    assert len(found) == 1, msgs
    return found[0]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


def _real(harness):
    return acpproxy.INITIALIZE_RESULTS[harness]


class TestInitializeIsAnsweredAtOnce:
    def test_every_acp_harness_has_a_canned_reply(self):
        assert set(acpproxy.INITIALIZE_RESULTS) == set(_ACP_HARNESSES)

    @pytest.mark.parametrize("harness", _ACP_HARNESSES)
    def test_the_reply_is_the_table_entry_and_nothing_launches(self, tmp_path, harness):  # S1.1, S1.2
        fake = _Fake(tmp_path, init=_real(harness))
        code, msgs, _ = _serve(harness, [_init()], fake)
        assert code == 0
        assert _reply(msgs, 1)["result"] == _real(harness)
        assert fake.calls == []

    def test_a_request_before_any_session_is_refused(self, tmp_path):
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "authenticate")], fake)
        assert _reply(msgs, 2)["error"]["code"] == -32600
        assert fake.calls == []


class TestTheProjectComesFromCwd:
    @pytest.mark.parametrize("method", ["session/new", "session/load"])
    def test_cwd_names_the_project(self, tmp_path, project, method):  # S2.1, S2.2, S4.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, method, {"cwd": str(project)})], fake)
        assert fake.calls == [project]
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(project)
        # The child's own initialize reply is consumed; the client sees only the canned one.
        assert _reply(msgs, 1)["result"] == _real("omp")
        # A notification the agent sends around its initialize reply still reaches the client.
        assert any(m.get("method") == "_auth/status_update" for m in msgs)

    def test_a_session_before_initialize_still_initializes_the_agent(self, tmp_path, project):  # S4.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_req(2, "session/new", {"cwd": str(project)})], fake)
        # The proxy's own initialize is consumed: the client sees only its session/new reply.
        assert [m.get("id") for m in msgs if "id" in m] == [2]
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(project)

    def test_a_cwd_that_does_not_exist_is_an_error(self, tmp_path, project):  # S2.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(),
            _req(2, "session/new", {"cwd": "/nonexistent-gh566"}),
            _req(3, "session/new", {"cwd": str(project)}),
        ], fake)
        err = _reply(msgs, 2)["error"]
        assert err["code"] == -32602 and "/nonexistent-gh566" in err["message"]
        # The proxy kept reading: the next request launched.
        assert fake.calls == [project]
        assert "result" in _reply(msgs, 3)

    @pytest.mark.parametrize("params", [{}, {"cwd": "relative/dir"}, {"cwd": 7}])
    def test_a_missing_or_relative_cwd_is_an_error(self, tmp_path, params):  # S2.4
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/new", params)], fake)
        assert _reply(msgs, 2)["error"]["code"] == -32602
        assert fake.calls == []


class TestThePathArgumentWins:
    def test_path_beats_cwd(self, tmp_path, project, monkeypatch):  # S3.1
        other = tmp_path / "other"
        other.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(other)})], fake, path=project)
        assert fake.calls == [project]
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(project)

    def test_the_start_folder_is_the_cwd_the_agent_gets(self, tmp_path, project):  # S3.2
        sub = project / "sub"
        sub.mkdir()
        fake = _Fake(tmp_path, init=_real("omp"), start_dir=sub)
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake, path=project)
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(sub)


class TestForwarding:
    def test_later_lines_reach_the_agent_in_order(self, tmp_path, project):  # S4.2, S4.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(),
            _req(2, "session/new", {"cwd": str(project)}),
            _req(3, "session/prompt", {"sessionId": "s"}),
            {"jsonrpc": "2.0", "id": "perm1", "result": {"outcome": "allow"}},
            _req(4, "session/cancel"),
        ], fake)
        ids = [m.get("id") for m in msgs if "id" in m]
        assert ids == [1, 2, "perm1", 3, 4]
        assert any(m.get("method") == "session/request_permission" for m in msgs)
        echoed = [m["params"] for m in msgs if m.get("method") == "echo"]
        assert echoed == [{"jsonrpc": "2.0", "id": "perm1", "result": {"outcome": "allow"}}]

    def test_the_exit_code_is_the_agents(self, tmp_path, project):  # S4.4, stdin closes first
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_EXIT="3")
        code, _, _ = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake)
        assert code == 3

    def test_the_agent_exiting_first_ends_the_proxy(self, tmp_path, project):  # S4.4, child first
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_QUIT="session/new", FAKE_EXIT="5")
        r, w = os.pipe()
        os.write(w, b"".join(json.dumps(m).encode() + b"\n" for m in [
            _init(), _req(2, "session/new", {"cwd": str(project)}),
        ]))
        result: dict = {}
        stdout = io.BytesIO()
        with os.fdopen(r, "rb") as stdin:
            t = threading.Thread(target=lambda: result.update(code=acpproxy.serve(
                "omp", path=None, launch=fake, stdin=stdin, stdout=stdout, stderr=io.StringIO()
            )), daemon=True)
            t.start()
            t.join(timeout=20)
            os.close(w)
        assert not t.is_alive(), "the proxy kept waiting on stdin after the agent exited"
        assert result["code"] == 5


class TestDrift:
    def test_a_differing_reply_is_reported_per_field(self, tmp_path, project):  # S5.1
        changed = {**_real("omp"), "agentCapabilities": {}, "authMethods": [{"id": "x"}]}
        fake = _Fake(tmp_path, init=changed)
        _, _, err = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake)
        drift = [ln for ln in err.splitlines() if "ACP initialize drift" in ln]
        assert drift == [
            "harnessed: ACP initialize drift: omp: agentCapabilities",
            "harnessed: ACP initialize drift: omp: authMethods",
        ]

    def test_an_equal_reply_is_silent(self, tmp_path, project):  # S5.2
        fake = _Fake(tmp_path, init={**_real("omp"), "agentInfo": {"version": "other"}})
        _, _, err = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake)
        assert "drift" not in err


class TestALaunchThatFails:
    def test_a_launch_that_exits_answers_the_request(self, tmp_path, project):  # S6.1
        fake = _Fake(tmp_path, init=_real("omp"), raises=typer.Exit(1))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake)
        assert _reply(msgs, 2)["error"] == {"code": -32603, "message": "launch failed (exit 1); see stderr"}

    def test_a_child_that_dies_before_initialize_answers_the_request(self, tmp_path, project):  # S6.1
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_DIE="1")
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/new", {"cwd": str(project)})], fake)
        assert _reply(msgs, 2)["error"] == {"code": -32603, "message": "launch failed (exit 1); see stderr"}


class TestOneProjectPerProcess:
    def test_a_second_project_is_refused(self, tmp_path, project):  # S9.1
        other = tmp_path / "other"
        other.mkdir()
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(),
            _req(2, "session/new", {"cwd": str(project)}),
            _req(3, "session/new", {"cwd": str(other)}),
        ], fake)
        assert _reply(msgs, 3)["error"] == {"code": -32602, "message": f"one project per process: {project}"}
        assert fake.calls == [project]

    def test_the_same_project_is_forwarded(self, tmp_path, project):  # S9.2
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(),
            _req(2, "session/new", {"cwd": str(project)}),
            _req(3, "session/new", {"cwd": str(project)}),
        ], fake)
        assert _reply(msgs, 3)["result"]["params"]["cwd"] == str(project)
        assert fake.calls == [project]
