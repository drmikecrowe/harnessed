"""#566 — `container-acp` as a host-side proxy.

The proxy answers `initialize` itself, from a per-harness table, so an editor that kills a slow agent
(Atlas: 60 s) gets its reply before any pod work. Each session request (`session/new`, `session/load`,
`session/resume`) names a project — the path argument when one was given, else the request's `cwd`.
The first request for a project starts that project's agent, replays `initialize` to it, and from then
on every line goes to the agent of the session it names. One process serves every project an editor
opens in it (Atlas reuses one process per entry).

Each test drives `acpproxy.serve` with fake agents: a small Python script that answers `initialize`
with the result it is given, answers `session/new` with a session id of its own, echoes every other
request back as its result with its own name, and echoes notifications.
"""
from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import typer
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harnessed import acpproxy, paths
from harnessed.attachcmd import _ACP_HARNESSES

_FAKE_AGENT = r'''
import json, os, sys
init = json.loads(os.environ["FAKE_INIT"])
name = os.environ["FAKE_NAME"]
if os.environ.get("FAKE_DIE"):
    sys.exit(int(os.environ["FAKE_DIE"]))
sessions = 0
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": init}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "method": "_auth/status_update", "params": {}}), flush=True)
    elif meth == "session/new":
        sessions += 1
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {
            "sessionId": f"{name}-s{sessions}", "agent": name, "method": meth, "params": m.get("params")}}),
            flush=True)
    elif meth == "session/prompt":
        print(json.dumps({"jsonrpc": "2.0", "id": 0, "method": "session/request_permission",
                          "params": {"agent": name}}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {
            "stopReason": "end_turn", "agent": name, "params": m.get("params")}}), flush=True)
        if os.environ.get("FAKE_QUIT") == meth:
            sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    elif meth and "id" in m:
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"],
                          "result": {"agent": name, "method": meth, "params": m.get("params")}}), flush=True)
        if os.environ.get("FAKE_QUIT") == meth:
            sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    else:
        print(json.dumps({"jsonrpc": "2.0", "method": "echo", "params": {"agent": name, "line": m}}), flush=True)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


def _req(id_, method, params=None):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _init(id_=1):
    return _req(id_, "initialize", {"protocolVersion": 1})


def _new(id_, project):
    return _req(id_, "session/new", {"cwd": str(project), "mcpServers": []})


def _prompt(id_, session, text="hi"):
    return _req(id_, "session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": text}]})


class _Fake:
    """A launch callback that starts a fake agent named after the project's folder, and records what
    it was asked to launch. `per` gives one project's agent extra env; `slow` delays one project's
    launch; `fail` makes one project's launch raise."""

    def __init__(self, tmp_path: Path, *, init=None, start_dir=None, raises=None,
                 per=None, slow=None, fail=None, **env):
        self.script = tmp_path / "fake_agent.py"
        self.script.write_text(_FAKE_AGENT)
        self.init = init
        self.start_dir = start_dir
        self.raises = raises
        self.per = per or {}
        self.slow = slow or {}
        self.fail = fail or {}
        self.env = env
        self.calls: list[Path] = []
        self.procs: dict[str, subprocess.Popen] = {}

    def __call__(self, project: Path):
        self.calls.append(project)
        if self.raises is not None:
            raise self.raises
        if project.name in self.fail:
            raise self.fail[project.name]
        time.sleep(self.slow.get(project.name, 0))
        env = {**os.environ, "FAKE_INIT": json.dumps(self.init), "FAKE_NAME": project.name,
               **self.env, **self.per.get(project.name, {})}
        proc = subprocess.Popen(
            [sys.executable, str(self.script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
        )
        self.procs[project.name] = proc
        return proc, (self.start_dir or project)


def _check_stdout(out: str) -> list[dict]:
    msgs = [json.loads(raw) for raw in out.splitlines()]
    # S4.7: every byte on stdout is a JSON-RPC 2.0 message.
    assert out == "" or out.endswith("\n")
    assert all(isinstance(m, dict) and m.get("jsonrpc") == "2.0" for m in msgs), out
    return msgs


class _Live:
    """The proxy on real pipes, for tests where the client must answer what the agents send."""

    def __init__(self, harness, launch, *, path=None):
        r_in, self._w_in = os.pipe()
        self._r_out, w_out = os.pipe()
        self.stderr = io.StringIO()
        self.result: dict = {}
        self._stdin = os.fdopen(r_in, "rb")
        self._stdout = os.fdopen(w_out, "wb")
        self._lines: queue.Queue = queue.Queue()
        self.seen: list[dict] = []

        def run():
            try:
                self.result["code"] = acpproxy.serve(
                    harness, path=path, launch=launch, stdin=self._stdin, stdout=self._stdout, stderr=self.stderr
                )
            finally:
                self._stdout.close()

        def read():
            with os.fdopen(self._r_out, "rb") as out:
                for raw in out:
                    self._lines.put(raw)
            self._lines.put(None)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        threading.Thread(target=read, daemon=True).start()

    def send(self, msg) -> None:
        os.write(self._w_in, (msg if isinstance(msg, bytes) else json.dumps(msg).encode()) + b"\n")

    def wait_for(self, pred, timeout=20.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            for m in self.seen:
                if pred(m):
                    return m
            raw = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
            assert raw is not None, f"stdout closed; seen {self.seen}"
            self.seen.extend(_check_stdout(raw.decode()))

    def reply(self, id_) -> dict:
        return self.wait_for(lambda m: m.get("id") == id_ and "method" not in m)

    def close(self) -> int:
        os.close(self._w_in)
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "the proxy did not exit after stdin closed"
        while (raw := self._lines.get(timeout=10)) is not None:
            self.seen.extend(_check_stdout(raw.decode()))
        return self.result["code"]


def _serve(harness, lines, launch, *, path=None):
    """Run the proxy over `lines`, then close stdin. Like an editor, wait for the reply to each session
    request before the next line: a client learns a session id only from that reply. Return (exit
    code, stdout messages, stderr)."""
    live = _Live(harness, launch, path=path)
    for m in lines:
        live.send(m)
        if isinstance(m, dict) and m.get("method") in ("session/new", "session/load", "session/resume") \
                and "id" in m:
            live.reply(m["id"])
    code = live.close()
    return code, live.seen, live.stderr.getvalue()


def _reply(msgs, id_):
    found = [m for m in msgs if m.get("id") == id_ and "method" not in m]
    assert len(found) == 1, msgs
    return found[0]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def other(tmp_path):
    p = tmp_path / "other"
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

    def test_a_request_before_any_session_is_refused(self, tmp_path):  # Known limits
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "authenticate")], fake)
        assert _reply(msgs, 2)["error"]["code"] == -32600
        assert fake.calls == []


class TestTheProjectComesFromCwd:
    @pytest.mark.parametrize("method", ["session/new", "session/load", "session/resume"])
    def test_cwd_names_the_project(self, tmp_path, project, method):  # S2.1, S2.2, S4.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, method, {"cwd": str(project), "sessionId": "old"})], fake)
        assert fake.calls == [project]
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(paths.container_project_path(project))
        # The child's own initialize reply is consumed; the client sees only the canned one.
        assert _reply(msgs, 1)["result"] == _real("omp")
        # A notification the agent sends around its initialize reply still reaches the client.
        assert any(m.get("method") == "_auth/status_update" for m in msgs)

    def test_a_session_before_initialize_still_initializes_the_agent(self, tmp_path, project):  # S4.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_new(2, project)], fake)
        # The proxy's own initialize is consumed: the client sees only its session/new reply.
        assert [m.get("id") for m in msgs if "id" in m] == [2]
        assert _reply(msgs, 2)["result"]["sessionId"] == "proj-s1"

    def test_a_cwd_that_does_not_exist_is_an_error(self, tmp_path, project):  # S2.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(),
            _req(2, "session/new", {"cwd": "/nonexistent-gh566"}),
            _new(3, project),
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
    def test_path_beats_cwd(self, tmp_path, project, other, monkeypatch):  # S3.1
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, other)], fake, path=project)
        assert fake.calls == [project]
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(paths.container_project_path(project))

    def test_the_start_folder_is_the_cwd_the_agent_gets(self, tmp_path, project):  # S3.2
        sub = project / "sub"
        sub.mkdir()
        fake = _Fake(tmp_path, init=_real("omp"), start_dir=sub)
        _, msgs, _ = _serve("omp", [_init(), _new(2, project)], fake, path=project)
        assert _reply(msgs, 2)["result"]["params"]["cwd"] == str(paths.container_project_path(sub))

    def test_a_second_cwd_still_goes_to_the_path_project(self, tmp_path, project, other):  # S3.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, other)], fake, path=project)
        assert fake.calls == [project]
        assert _reply(msgs, 3)["result"]["agent"] == "proj"
        assert _reply(msgs, 3)["result"]["params"]["cwd"] == str(paths.container_project_path(project))


class TestForwarding:
    def test_later_lines_reach_the_agent_in_order(self, tmp_path, project):  # S4.2, S4.3
        fake = _Fake(tmp_path, init=_real("omp"))
        live = _Live("omp", fake)
        live.send(_init())
        live.send(_new(2, project))
        live.reply(2)
        live.send(_prompt(3, "proj-s1"))
        live.wait_for(lambda m: m.get("method") == "session/request_permission")
        live.send({"jsonrpc": "2.0", "id": 0, "result": {"outcome": "allow"}})
        live.send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "proj-s1"}})
        live.close()
        msgs = live.seen
        ids = [m.get("id") for m in msgs if "id" in m]
        assert ids == [1, 2, 0, 3]
        assert any(m.get("method") == "session/request_permission" for m in msgs)
        echoed = [m["params"]["line"] for m in msgs if m.get("method") == "echo"]
        assert echoed == [
            {"jsonrpc": "2.0", "id": 0, "result": {"outcome": "allow"}},
            {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "proj-s1"}},
        ]

    def test_the_exit_code_is_the_agents(self, tmp_path, project):  # S4.4, stdin closes first
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_EXIT="3")
        code, _, _ = _serve("omp", [_init(), _new(2, project)], fake)
        assert code == 3

    def test_every_agent_ends_and_the_first_nonzero_code_wins(self, tmp_path, project, other):  # S4.4
        fake = _Fake(tmp_path, init=_real("omp"), per={"other": {"FAKE_EXIT": "4"}})
        code, _, _ = _serve("omp", [_init(), _new(2, project), _new(3, other)], fake)
        assert code == 4
        assert all(p.poll() is not None for p in fake.procs.values())

    def test_all_agents_ending_cleanly_exit_zero(self, tmp_path, project, other):  # S4.4
        fake = _Fake(tmp_path, init=_real("omp"))
        code, _, _ = _serve("omp", [_init(), _new(2, project), _new(3, other)], fake)
        assert code == 0

    def test_one_agent_exiting_leaves_the_others_working(self, tmp_path, project, other):  # S4.5
        fake = _Fake(tmp_path, init=_real("omp"), per={"proj": {"FAKE_QUIT": "session/prompt", "FAKE_EXIT": "6"}})
        live = _Live("omp", fake)
        live.send(_init())
        live.send(_new(2, project))
        live.send(_new(3, other))
        live.reply(2)
        live.reply(3)
        live.send(_prompt(4, "proj-s1"))
        live.reply(4)
        fake.procs["proj"].wait(timeout=20)
        time.sleep(0.5)  # the proxy notices the closed pipe
        live.send(_prompt(5, "proj-s1"))
        assert live.reply(5)["error"] == {"code": -32603, "message": f"agent for {project} exited"}
        live.send(_prompt(6, "other-s1"))
        assert live.reply(6)["result"]["agent"] == "other"
        live.send(_new(7, project))
        assert live.reply(7)["result"]["sessionId"] == "proj-s1"
        assert fake.calls == [project, other, project]
        assert live.close() == 6


class TestDrift:
    def test_a_differing_reply_is_reported_per_field(self, tmp_path, project):  # S5.1
        changed = {**_real("omp"), "protocolVersion": 2, "agentCapabilities": {}}
        fake = _Fake(tmp_path, init=changed)
        _, _, err = _serve("omp", [_init(), _new(2, project)], fake)
        drift = [ln for ln in err.splitlines() if "ACP initialize drift" in ln]
        assert drift == [
            "harnessed: ACP initialize drift: omp: protocolVersion",
            "harnessed: ACP initialize drift: omp: agentCapabilities",
        ]

    def test_auth_methods_are_not_drift(self, tmp_path, project):  # S5.2
        fake = _Fake(tmp_path, init={**_real("omp"), "authMethods": [{"id": "x"}], "agentInfo": {"version": "other"}})
        _, _, err = _serve("omp", [_init(), _new(2, project)], fake)
        assert "drift" not in err


class TestALaunchThatFails:
    def test_a_launch_that_exits_answers_the_request(self, tmp_path, project):  # S6.1
        fake = _Fake(tmp_path, init=_real("omp"), raises=typer.Exit(1))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project)], fake)
        assert _reply(msgs, 2)["error"] == {"code": -32603, "message": "launch failed (exit 1); see stderr"}

    def test_a_child_that_dies_before_initialize_answers_the_request(self, tmp_path, project):  # S6.1
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_DIE="1")
        _, msgs, _ = _serve("omp", [_init(), _new(2, project)], fake)
        assert _reply(msgs, 2)["error"] == {"code": -32603, "message": "launch failed (exit 1); see stderr"}

    @pytest.mark.parametrize("exc", [OSError(24, "Too many open files"), ValueError("no pipes"), RuntimeError("x")])
    def test_a_launch_that_raises_anything_answers_and_can_retry(self, tmp_path, project, exc):  # S6.1, adversary
        attempts = {"n": 0}
        fake = _Fake(tmp_path, init=_real("omp"))

        def broken_once(p):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise exc
            return fake(p)

        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, project)], broken_once)
        assert _reply(msgs, 2)["error"] == {
            "code": -32603, "message": f"launch failed ({type(exc).__name__}: {exc}); see stderr",
        }
        assert _reply(msgs, 3)["result"]["sessionId"] == "proj-s1"

    def test_a_child_that_dies_before_initialize_sets_the_exit_code(self, tmp_path, project):  # S4.4, adversary
        fake = _Fake(tmp_path, init=_real("omp"), FAKE_DIE="7")
        code, _, _ = _serve("omp", [_init(), _new(2, project)], fake)
        assert code == 7

    def test_a_failed_project_leaves_the_others_working(self, tmp_path, project, other):  # S6.1
        fake = _Fake(tmp_path, init=_real("omp"), fail={"other": typer.Exit(1)})
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, other), _prompt(4, "proj-s1")], fake)
        assert _reply(msgs, 3)["error"]["code"] == -32603
        assert _reply(msgs, 4)["result"]["agent"] == "proj"

    def test_a_failed_project_can_be_launched_again(self, tmp_path, project):  # S6.1
        attempts = {"n": 0}
        fake = _Fake(tmp_path, init=_real("omp"))

        def flaky(p):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise typer.Exit(1)
            return fake(p)

        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, project)], flaky)
        assert "error" in _reply(msgs, 2)
        assert _reply(msgs, 3)["result"]["sessionId"] == "proj-s1"


class TestTheProcessIsNamed:
    def test_each_agent_start_names_the_proxy_and_project(self, tmp_path, project, other):  # S8.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, _, err = _serve("omp", [_init(), _new(2, project), _new(3, other), _new(4, project)], fake)
        lines = sorted(ln for ln in err.splitlines() if ln.startswith("harnessed: ACP proxy "))
        assert lines == sorted([
            f"harnessed: ACP proxy {os.getpid()}: {project}",
            f"harnessed: ACP proxy {os.getpid()}: {other}",
        ])


class TestSeveralProjects:
    def test_a_second_project_gets_its_own_agent(self, tmp_path, project, other):  # S9.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, other)], fake)
        assert fake.calls == [project, other]
        assert _reply(msgs, 2)["result"]["agent"] == "proj"
        assert _reply(msgs, 3)["result"]["agent"] == "other"
        assert _reply(msgs, 3)["result"]["params"]["cwd"] == str(paths.container_project_path(other))

    def test_a_session_id_routes_to_the_agent_that_made_it(self, tmp_path, project, other):  # S9.2
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(), _new(2, project), _new(3, other),
            _prompt(4, "other-s1"), _prompt(5, "proj-s1"), _prompt(6, "other-s1"),
        ], fake)
        assert [_reply(msgs, i)["result"]["agent"] for i in (4, 5, 6)] == ["other", "proj", "other"]

    def test_a_loaded_session_routes_to_its_project(self, tmp_path, project, other):  # S9.2
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(), _new(2, project),
            _req(3, "session/load", {"cwd": str(other), "sessionId": "saved-1", "mcpServers": []}),
            _prompt(4, "saved-1"),
        ], fake)
        assert _reply(msgs, 3)["result"]["agent"] == "other"
        assert _reply(msgs, 4)["result"]["agent"] == "other"

    def test_a_slow_launch_does_not_hold_up_another_project(self, tmp_path, project, other):  # S9.3
        fake = _Fake(tmp_path, init=_real("omp"), slow={"other": 3})
        live = _Live("omp", fake)
        live.send(_init())
        live.send(_new(2, project))
        live.reply(2)
        live.send(_new(3, other))
        started = time.monotonic()
        live.send(_prompt(4, "proj-s1"))
        live.reply(4)
        assert time.monotonic() - started < 2, "the prompt waited for the other project's launch"
        live.reply(3)
        live.close()

    def test_agent_request_ids_never_collide(self, tmp_path, project, other):  # S9.4
        fake = _Fake(tmp_path, init=_real("omp"))
        live = _Live("omp", fake)
        live.send(_init())
        live.send(_new(2, project))
        live.send(_new(3, other))
        live.reply(2)
        live.reply(3)
        live.send(_prompt(4, "proj-s1"))
        live.send(_prompt(5, "other-s1"))
        live.reply(4)
        live.reply(5)
        for agent in ("proj", "other"):
            live.wait_for(lambda m, a=agent: m.get("method") == "session/request_permission" and m["params"]["agent"] == a)
        perms = {m["params"]["agent"]: m["id"] for m in live.seen if m.get("method") == "session/request_permission"}
        assert perms["proj"] != perms["other"]
        for agent, pid in perms.items():
            live.send({"jsonrpc": "2.0", "id": pid, "result": {"for": agent}})
        for agent in ("proj", "other"):
            echo = live.wait_for(lambda m, a=agent: m.get("method") == "echo" and m["params"]["agent"] == a)
            # The agent gets its own id back, whatever the client saw.
            assert echo["params"]["line"] == {"jsonrpc": "2.0", "id": 0, "result": {"for": agent}}
        live.close()

    @pytest.mark.parametrize("spelling", ["same", "slash", "symlink"])
    def test_one_project_by_any_spelling_is_one_agent(self, tmp_path, project, spelling):  # S9.5
        cwd = {"same": str(project), "slash": f"{project}/", "symlink": str(tmp_path / "link")}[spelling]
        if spelling == "symlink":
            (tmp_path / "link").symlink_to(project)
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _req(3, "session/new", {"cwd": cwd})], fake)
        assert fake.calls == [project]
        assert _reply(msgs, 3)["result"]["sessionId"] == "proj-s2"

    @pytest.mark.parametrize("session", ["nobody-s1", 7, None])
    def test_an_unknown_session_is_an_error(self, tmp_path, project, session):  # S9.6
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _req(3, "session/prompt", {"sessionId": session})], fake)
        assert _reply(msgs, 3)["error"] == {"code": -32602, "message": f"unknown session: {session}"}

    def test_a_request_naming_no_session_is_refused_with_two_agents(self, tmp_path, project, other):  # S9.7
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _new(3, other), _req(4, "authenticate")], fake)
        assert _reply(msgs, 4)["error"] == {"code": -32600, "message": "cannot route authenticate: it names no session"}

    def test_a_request_naming_no_session_goes_to_the_only_agent(self, tmp_path, project):  # S9.7
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _req(3, "authenticate")], fake)
        assert _reply(msgs, 3)["result"] == {"agent": "proj", "method": "authenticate", "params": {}}


class TestSessionList:
    def test_before_any_session_the_list_is_empty(self, tmp_path, project):  # S10.1
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/list", {"cwd": str(project)})], fake)
        assert _reply(msgs, 2)["result"] == {"sessions": []}
        assert fake.calls == []

    def test_with_the_projects_agent_running_it_answers(self, tmp_path, project, other):  # S10.2
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [
            _init(), _new(2, project), _new(3, other), _req(4, "session/list", {"cwd": str(other)}),
        ], fake)
        assert _reply(msgs, 4)["result"]["agent"] == "other"
        assert _reply(msgs, 4)["result"]["method"] == "session/list"

    def test_no_cwd_uses_the_path_argument(self, tmp_path, project):  # S10.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _req(3, "session/list")], fake, path=project)
        assert _reply(msgs, 3)["result"]["agent"] == "proj"

    def test_no_cwd_and_no_path_is_empty(self, tmp_path, project):  # S10.3
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _req(3, "session/list")], fake)
        assert _reply(msgs, 3)["result"] == {"sessions": []}

    @pytest.mark.parametrize("cwd", ["relative", 7, "/nonexistent-gh566"])
    def test_a_bad_cwd_is_never_an_error(self, tmp_path, cwd):  # S10.4
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _req(2, "session/list", {"cwd": cwd})], fake)
        assert _reply(msgs, 2)["result"] == {"sessions": []}


class TestHostileInput:
    """The Failure model's last line: no client line stops the reader thread."""

    @pytest.mark.parametrize("bad, code", [
        (b"not json", -32700), (b"[1, 2]", -32600), (b"42", -32600), (b"\xff\xfe", -32700),
    ])
    def test_a_bad_line_is_answered_and_the_next_one_works(self, tmp_path, project, bad, code):
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), bad, _prompt(3, "proj-s1")], fake)
        assert [m["error"]["code"] for m in msgs if "error" in m] == [code]
        assert _reply(msgs, 3)["result"]["agent"] == "proj"

    def test_a_reply_to_a_request_nobody_sent_is_dropped(self, tmp_path, project):
        fake = _Fake(tmp_path, init=_real("omp"))
        _, msgs, err = _serve("omp", [
            _init(), _new(2, project), {"jsonrpc": "2.0", "id": 999, "result": {}}, _prompt(3, "proj-s1"),
        ], fake)
        assert not [m for m in msgs if m.get("method") == "echo"]
        assert "999" in err
        assert _reply(msgs, 3)["result"]["agent"] == "proj"

    def test_a_huge_line_goes_through_whole(self, tmp_path, project):
        fake = _Fake(tmp_path, init=_real("omp"))
        text = "x" * (2 * 1024 * 1024)
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), _prompt(3, "proj-s1", text)], fake)
        assert _reply(msgs, 3)["result"]["params"]["prompt"][0]["text"] == text

    @pytest.mark.parametrize("params", [None, [], "x", {"sessionId": {"a": 1}}])
    def test_odd_params_never_crash_the_reader(self, tmp_path, project, params):
        fake = _Fake(tmp_path, init=_real("omp"))
        weird = {"jsonrpc": "2.0", "id": 3, "method": "session/new", "params": params}
        _, msgs, _ = _serve("omp", [_init(), _new(2, project), weird, _prompt(4, "proj-s1")], fake)
        assert "error" in _reply(msgs, 3)
        assert _reply(msgs, 4)["result"]["agent"] == "proj"


_ROUTING = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@_ROUTING
@given(steps=st.lists(st.tuples(st.sampled_from(["proj", "other"]), st.sampled_from(["prompt", "note"]),
                                st.integers(0, 200_000)), min_size=1, max_size=12))
def test_routing_keeps_each_sessions_lines_with_its_agent_in_order(tmp_path_factory, steps):  # Tier 3 property
    tmp = tmp_path_factory.mktemp("routing")
    for name in ("proj", "other"):
        (tmp / name).mkdir()
    fake = _Fake(tmp, init=_real("omp"))
    lines: list = [_init(), _new(2, tmp / "proj"), _new(3, tmp / "other")]
    sent: dict[str, list] = {"proj": [], "other": []}
    for n, (agent, kind, size) in enumerate(steps, start=10):
        text = f"{n}:" + "y" * size
        if kind == "prompt":
            lines.append(_prompt(n, f"{agent}-s1", text))
        else:
            lines.append({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": f"{agent}-s1", "n": n}})
        sent[agent].append(n)
    _, msgs, _ = _serve("omp", lines, fake)
    got: dict[str, list] = {"proj": [], "other": []}
    for m in msgs:
        if m.get("method") == "echo":
            got[m["params"]["agent"]].append(m["params"]["line"]["params"]["n"])
        elif isinstance(m.get("id"), int) and m["id"] >= 10 and "result" in m:
            got[m["result"]["agent"]].append(m["id"])
            assert m["result"]["params"]["prompt"][0]["text"].startswith(f"{m['id']}:")
    assert got == sent
    perms = [m["id"] for m in msgs if m.get("method") == "session/request_permission"]
    assert len(perms) == len(set(perms))
