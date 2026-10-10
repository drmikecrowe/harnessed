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
if len(sys.argv) > 3:  # the launcher-level tests read the env the agent was started with
    import os
    with open(sys.argv[3], "w") as f:
        json.dump({"env": dict(os.environ), "cwd": os.getcwd()}, f)
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

    def __init__(self, tmp: Path, *, setup_rc: int = 0, setup_cmd: list[str] | None = None) -> None:
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
            if setup_cmd is not None:
                return setup_cmd
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


# --- The verb: `host-acp` as a real process ------------------------------------------------------
#
# A real process, because the stdout contract is about file descriptors: an INFO line printed by
# harnessed, an init script's echo, and the setup verb's output all reach fd 1 unless the launch
# keeps them off it, and CliRunner captures none of those. The driver swaps in only the agent
# command (`_host_acp_agent_argv`) and, where a scenario says so, `assemble`; everything else runs.

import subprocess

from harnessed import hostrun, launcher, paths, setupenv
from harnessed.assemble import assemble

_DRIVER = r"""
import json, sys
from harnessed import launcher as L
stub = json.loads(sys.argv.pop(1))
if stub.get("agent"):
    L._host_acp_agent_argv = lambda harness, home, no_strict_mcp: stub["agent"]
if stub.get("no_assemble"):
    def _never(*a, **k):
        raise SystemExit("assemble must not run")
    L.assemble = _never
sys.argv[0] = "harnessed"
L.main()
"""

_STACK = "acpspike"
_INHERITED = ("PROJECT_DIR", "MAIN_REPO_DIR", "HARNESS", "HARNESSED_GIT_COMMON_DIR",
              "CONTAINER_WORKSPACE_DIR", "HOST_WORKSPACE_DIR", "G", "P", "R")
_RECIPE = (
    "name: acpinit\n"
    "description: GH-571 test recipe with an init line and an env value.\n"
    "init:\n"
    "  run: echo INIT-OUT; pwd > \"$PROJECT_DIR/.init-cwd\"\n"
    "env:\n"
    "  R: \"1\"\n"
)
_STACK_BODY = f"name: {_STACK}\ninstructions: GH-571 tracer.\nrecipes: [greet, acpinit]\nservices: []\n"


class _Host:
    """A temporary HOME and XDG tree with the overlay stack authored, and helpers to run the verb."""

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.tmp = tmp
        self.env = dict(os.environ)
        for var, sub in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                         ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
            (tmp / sub).mkdir(exist_ok=True)
            self.env[var] = str(tmp / sub)
            monkeypatch.setenv(var, str(tmp / sub))
        self.env["CLAUDE_CONFIG_DIR"] = str(tmp / "no-host-src")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp / "no-host-src"))
        self.env.pop("HARNESSED_DIR", None)
        # A developer running this suite inside a harnessed session inherits that session's
        # folder-env contract; the scenarios are about what THIS launch sets.
        for var in _INHERITED:
            self.env.pop(var, None)
            monkeypatch.delenv(var, raising=False)
        catalog = tmp / "config" / "harnessed" / "catalog"
        (catalog / "recipes" / "acpinit").mkdir(parents=True)
        (catalog / "recipes" / "acpinit" / "recipe.yaml").write_text(_RECIPE)
        (catalog / "stacks" / _STACK).mkdir(parents=True)
        (catalog / "stacks" / _STACK / "stack.yaml").write_text(_STACK_BODY)
        self.launch = tmp / "launch"
        self.launch.mkdir()
        self.agent_log = tmp / "agent.log"
        self.events = tmp / "events.log"
        self.started = tmp / "agent-start.json"
        self.agent = tmp / "stub_agent.py"
        self.agent.write_text(_STUB_AGENT)

    def build(self, harness: str) -> None:
        assemble(None, _STACK, paths.profiles_root().parent, harness, strict=True, shared_identity=False)

    def adapter(self, version: str) -> Path:
        """A `claude-agent-acp` as pnpm and mise install it: a wrapper script that answers --version."""
        bindir = self.tmp / "npm" / "bin"
        bindir.mkdir(parents=True)
        entry = bindir / "claude-agent-acp"
        entry.write_text(f'#!/bin/sh\n[ "$1" = --version ] && echo {version}\nexit 0\n')
        entry.chmod(0o755)
        return bindir

    def run(self, harness: str, *extra: str, msgs: tuple[dict, ...] | list[dict] = (), stub: dict | None = None,
            path_prefix: Path | None = None) -> subprocess.CompletedProcess:
        stub = {"agent": [sys.executable, str(self.agent), str(self.agent_log), str(self.events), str(self.started)]} \
            if stub is None else stub
        env = dict(self.env)
        if path_prefix is not None:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
        stdin = b"".join(json.dumps(m).encode() + b"\n" for m in msgs)
        return subprocess.run(
            [sys.executable, "-c", _DRIVER, json.dumps(stub), "host-acp", harness, "--stack", _STACK, *extra],
            input=stdin, capture_output=True, cwd=self.launch, env=env, timeout=180,
        )

    def agent_start(self) -> dict:
        return json.loads(self.started.read_text())


def _rpc(rid, method, params):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


def _stdout_messages(proc: subprocess.CompletedProcess) -> list[dict]:
    out = [json.loads(line) for line in proc.stdout.splitlines()]
    assert all(isinstance(m, dict) and m.get("jsonrpc") == "2.0" for m in out), proc.stdout
    return out


@pytest.fixture
def host(tmp_path, monkeypatch):
    return _Host(tmp_path, monkeypatch)


class TestStdoutIsJsonRpcOnly:
    @pytest.mark.parametrize("harness", ["omp", "claude"])
    def test_s1_1_and_s1_3_initialize_and_session_new_answer_on_a_clean_stdout(self, host, tmp_path, harness):
        host.build(harness)
        a = tmp_path / "projA"
        a.mkdir()
        prefix = host.adapter("0.85.1") if harness == "claude" else None
        proc = host.run(harness, path_prefix=prefix, msgs=[
            _rpc(1, "initialize", {"protocolVersion": 1}),
            _rpc(2, "session/new", {"cwd": str(a), "mcpServers": []}),
        ])
        assert proc.returncode == 0, proc.stderr.decode()
        out = _stdout_messages(proc)
        assert [m.get("id") for m in out] == [1, 2]
        assert all("result" in m for m in out)

    def test_s1_2_launch_and_init_output_go_to_stderr(self, host, tmp_path):
        host.build("omp")
        a = tmp_path / "projA"
        a.mkdir()
        proc = host.run("omp", msgs=[_rpc(1, "session/new", {"cwd": str(a), "mcpServers": []})])
        assert proc.returncode == 0, proc.stderr.decode()
        assert b"INIT-OUT" in proc.stderr
        assert b"Assembling" in proc.stderr
        assert b"INIT-OUT" not in proc.stdout and b"Assembling" not in proc.stdout
        _stdout_messages(proc)

    def test_s1_4_the_launch_folder_gets_no_per_project_setup(self, host):
        host.build("omp")
        proc = host.run("omp", msgs=[_rpc(1, "initialize", {"protocolVersion": 1})])
        assert proc.returncode == 0, proc.stderr.decode()
        assert b"INIT-OUT" not in proc.stderr
        assert not (host.launch / ".init-cwd").exists()
        # And no project tool env file. The recipe's `env: {R: "1"}` means one is written for any
        # folder the per-project setup runs in, so its absence is the setup's absence.
        assert not setupenv.project_env_path(host.launch).exists()

    def test_s1_5_a_harness_without_acp_is_refused_before_any_work(self, host):
        proc = host.run("opencode", stub={"no_assemble": True})
        assert proc.returncode == 2
        assert b"opencode has no ACP mode; host-acp supports: omp, claude" in proc.stderr
        assert proc.stdout == b""


class TestUnbuiltStack:
    def test_s2_2_an_unbuilt_stack_names_the_build_command(self, host):
        proc = host.run("omp", stub={"no_assemble": True})
        assert proc.returncode == 1
        assert proc.stdout == b""
        assert f"harnessed build {_STACK} omp".encode() in proc.stderr


class TestHostRunSharesTheSetup:
    @staticmethod
    def _record(monkeypatch) -> list[str]:
        """Record the four per-project steps, in call order, running each for real."""
        order: list[str] = []
        real_services = launcher.HostBackend.wire_services
        real_provision = launcher.HostBackend.provision_tools
        real_env_file = launcher._write_project_tool_env
        real_notices = launcher._prompt_setup_notices

        def services(self, spec):
            order.append("wire_services")
            return real_services(self, spec)

        def provision(self, spec, phase):
            order.append(f"provision:{phase}")
            return real_provision(self, spec, phase)

        def env_file(*a, **k):
            order.append("project_tool_env")
            return real_env_file(*a, **k)

        def notices(*a, **k):
            order.append("setup_notices")
            return real_notices(*a, **k)

        monkeypatch.setattr(launcher.HostBackend, "wire_services", services)
        monkeypatch.setattr(launcher.HostBackend, "provision_tools", provision)
        monkeypatch.setattr(launcher, "_write_project_tool_env", env_file)
        monkeypatch.setattr(launcher, "_prompt_setup_notices", notices)
        return order

    _STEPS = ("wire_services", "project_tool_env", f"provision:{launcher.ATTACH}", "setup_notices")

    def test_s4_5_host_run_and_project_setup_run_the_same_steps_in_the_same_order(
        self, host, tmp_path, monkeypatch,
    ):
        """SPEC revision 6: one code path. project-setup runs `_launch_host` in its project-only mode,
        so both verbs execute the same four per-project lines, once each, in the same order."""
        from typer.testing import CliRunner

        order = self._record(monkeypatch)
        entered: list[bool] = []
        real_launch_host = launcher._launch_host

        def launch_host(*a, **k):
            entered.append(bool(k.get("project_only")))
            return real_launch_host(*a, **k)

        monkeypatch.setattr(launcher, "_launch_host", launch_host)
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        monkeypatch.setattr(launcher.aoe, "_bin", lambda: None)
        project = tmp_path / "proj"
        project.mkdir()
        result = CliRunner().invoke(launcher.app, ["host-run", "omp", str(project), "--stack", _STACK])
        assert result.exit_code == 0, result.output
        host_run = [step for step in order if step in self._STEPS]
        assert host_run == list(self._STEPS)
        assert (project / ".init-cwd").read_text().strip() == str(project)

        order.clear()
        other = tmp_path / "other"
        other.mkdir()
        result = CliRunner().invoke(launcher.app, ["project-setup", "omp", str(other), "--stack", _STACK])
        assert result.exit_code == 0, result.output
        assert order == list(self._STEPS)
        assert entered == [False, True], "host-run and project-setup must both run _launch_host"
        assert (other / ".init-cwd").read_text().strip() == str(other)

    def test_s4_6_project_setup_alone_sets_up_one_project(self, host, tmp_path):
        host.build("omp")
        a = tmp_path / "projA"
        a.mkdir()
        subprocess.run(["git", "-C", str(a), "init", "-q"], check=True, timeout=30)
        proc = subprocess.run(
            [sys.executable, "-m", "harnessed", "project-setup", "omp", str(a), "--stack", _STACK],
            capture_output=True, cwd=host.launch, env=host.env, timeout=180, stdin=subprocess.DEVNULL,
        )
        assert proc.returncode == 0, proc.stderr.decode()
        assert (a / ".init-cwd").read_text().strip() == str(a)
        assert "R=1" in setupenv.project_env_path(a).read_text()
        # Never the per-stack half: under host-acp an agent is already running on this home, and
        # materializing it would rmtree the agent's config dir.
        assert not paths.host_home(_STACK, "omp").exists()


class TestClaudeMcpAndEnv:
    def test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict(self, host):
        host.build("claude")
        proc = host.run("claude", path_prefix=host.adapter("0.85.1"), msgs=[_rpc(1, "initialize", {})])
        assert proc.returncode == 0, proc.stderr.decode()
        env = host.agent_start()["env"]
        home = paths.host_home(_STACK, "claude")
        assert env["CLAUDE_CONFIG_DIR"] == str(home)
        assert env["CLAUDE_CODE_EXECUTABLE"] == str(paths.harnessed_home() / "catalog" / "base" / "harnessed-claude-acp-cli")
        assert env["HARNESSED_MCP_CONFIG"] == str(home / ".mcp.json")
        assert env["HARNESSED_STRICT_MCP"] == "1"
        assert "mcpServers" in json.loads((home / ".mcp.json").read_text())

    def test_s5_2_no_strict_keeps_the_file_and_drops_strict(self, host):
        host.build("claude")
        proc = host.run("claude", "--no-strict-mcp-config", path_prefix=host.adapter("0.85.1"),
                        msgs=[_rpc(1, "initialize", {})])
        assert proc.returncode == 0, proc.stderr.decode()
        env = host.agent_start()["env"]
        assert env["HARNESSED_MCP_CONFIG"] == str(paths.host_home(_STACK, "claude") / ".mcp.json")
        assert "HARNESSED_STRICT_MCP" not in env

    @pytest.mark.parametrize("harness", ["omp", "claude"])
    def test_s5_4_the_agent_gets_per_stack_env_only(self, host, tmp_path, harness):
        host.build(harness)
        (host.tmp / "home" / ".config" / "harnessed").mkdir(parents=True)
        (host.tmp / "home" / ".config" / "harnessed" / ".env").write_text("G=1\n")
        (host.launch / ".env").write_text("P=1\n")
        host.env["MISE_DATA_DIR"] = "/users/own/mise"
        a = tmp_path / "projA"
        a.mkdir()
        prefix = host.adapter("0.85.1") if harness == "claude" else None
        proc = host.run(harness, path_prefix=prefix, msgs=[_rpc(1, "session/new", {"cwd": str(a), "mcpServers": []})])
        assert proc.returncode == 0, proc.stderr.decode()
        start = host.agent_start()
        env = start["env"]
        assert start["cwd"] == str(host.launch)
        assert env["G"] == "1"
        assert "P" not in env and "R" not in env and "PROJECT_DIR" not in env
        assert env["PATH"].split(os.pathsep)[0] == hostrun._stack_tool_path_prefix(_STACK)[0]
        assert env["MISE_DATA_DIR"] == "/users/own/mise"
        home = paths.host_home(_STACK, harness)
        if harness == "omp":
            assert env["PI_CODING_AGENT_DIR"] == str(home)
            assert env["CLAUDE_CONFIG_DIR"] == str(launcher._host_omp_claude_dir(home))
        else:
            assert env["CLAUDE_CONFIG_DIR"] == str(home)


class TestTheAdapterAtLaunch:
    def test_s6_8_a_missing_adapter_refuses_on_stderr(self, host):
        host.build("claude")
        host.env["PATH"] = os.pathsep.join(
            d for d in host.env["PATH"].split(os.pathsep) if not (Path(d) / "claude-agent-acp").exists()
        )
        proc = host.run("claude", msgs=[_rpc(1, "initialize", {})])
        assert proc.returncode == 1
        assert proc.stdout == b""
        assert b"npm i -g @agentclientprotocol/claude-agent-acp@0.85.1" in proc.stderr
        assert not host.started.exists()

    def test_s6_10_another_version_runs_with_a_warning(self, host):
        host.build("claude")
        proc = host.run("claude", path_prefix=host.adapter("0.84.0"), msgs=[_rpc(1, "initialize", {})])
        assert proc.returncode == 0, proc.stderr.decode()
        assert b"0.84.0" in proc.stderr and b"0.85.1" in proc.stderr
        assert host.started.exists()
        _stdout_messages(proc)


class TestTheAgentExitsFirst:
    def test_host_acp_exits_with_the_agents_code_while_the_editor_is_still_connected(self, host):
        """Found by the claude smoke run: an agent that dies at start left the relay's editor
        thread blocked on stdin, and the interpreter aborted at shutdown (`Fatal Python error:
        _enter_buffered_busy`) instead of exiting with the agent's code."""
        host.build("omp")
        stub = {"agent": [sys.executable, "-c", "import sys; sys.exit(3)"]}
        out_path, err_path = host.tmp / "out", host.tmp / "err"
        with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
            # stdin is a pipe this test holds open and never writes to or closes, as an editor would
            proc = subprocess.Popen(
                [sys.executable, "-c", _DRIVER, json.dumps(stub), "host-acp", "omp", "--stack", _STACK],
                stdin=subprocess.PIPE, stdout=out_f, stderr=err_f, cwd=host.launch, env=host.env,
            )
            try:
                code = proc.wait(timeout=120)
            finally:
                proc.kill()
                if proc.stdin:
                    proc.stdin.close()
        err = err_path.read_bytes()
        assert b"Fatal Python error" not in err, err.decode()
        assert code == 3, err.decode()
        assert out_path.read_bytes() == b""


class TestAdversaryRound1:
    """Hunches from adversary round 1 (findings-code-round1.md), each seen failing first."""

    def test_a_setup_that_cannot_start_is_an_error_not_a_dead_relay(self, tmp_path):
        r = _Relay(tmp_path, setup_cmd=[str(tmp_path / "no-such-setup-binary")])
        try:
            a, _ = _dirs(tmp_path)
            reply, _ = r.request(1, "session/new", {"cwd": str(a), "mcpServers": []})
            assert reply["error"]["code"] == -32000
            assert str(a) in reply["error"]["message"]
            pong, _ = r.request(2, "initialize", {})  # the relay is still serving
            assert "result" in pong
        finally:
            r.close()

    def test_a_lost_editor_stdout_stops_the_agent_instead_of_hanging(self, tmp_path):
        """The editor's read end of our stdout goes away; the agent then writes far more than a
        pipe holds. run() must return rather than wait forever on an agent blocked writing."""
        agent = tmp_path / "loud.py"
        agent.write_text(
            "import sys, time\n"
            "for _ in range(2000):\n"
            "    sys.stdout.write('{\"jsonrpc\":\"2.0\",\"method\":\"x\",\"params\":{\"p\":\"' + 'y' * 4096 + '\"}}\\n')\n"
            "    sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        out_r, out_w = os.pipe()
        os.close(out_r)  # nobody will ever read the editor's channel
        in_r, in_w = os.pipe()
        result: dict = {}

        def run() -> None:
            # Not closed here: the relay's reader thread stays blocked reading stdin, as on a real
            # editor pipe, and closing a reader another thread holds would block this thread.
            stdin, stdout = os.fdopen(in_r, "rb"), os.fdopen(out_w, "wb")
            result["code"] = acprelay.run(
                [sys.executable, str(agent)], dict(os.environ), lambda p: ["true"],
                cwd=tmp_path, stdin=stdin, stdout=stdout,
            )
            done.set()

        done = threading.Event()
        threading.Thread(target=run, daemon=True).start()
        returned = done.wait(30)
        os.close(in_w)
        assert returned, "run() hung after the editor's stdout went away"
        assert result["code"] != 0


class TestExitStatus:
    def test_a_signal_death_maps_to_128_plus_the_signal(self):
        assert launcher._exit_status(-9) == 137
        assert launcher._exit_status(3) == 3
        assert launcher._exit_status(0) == 0


def _gone(pid: int, wait: float = 10.0) -> bool:
    """Whether `pid` has exited (or is a zombie awaiting its reaper), polling up to `wait` s."""
    import time
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
        except FileNotFoundError:
            return True
        if state == "Z":
            return True
        time.sleep(0.1)
    return False


class TestPrReview572:
    """PR #572 review comments, each seen failing first."""

    def test_a_setup_still_running_when_the_relay_ends_is_stopped_with_its_children(self, tmp_path):
        """Comment 2: the editor goes away (here: the agent exits) while project-setup is still
        running. The setup and everything it started must not outlive the relay."""
        pids = tmp_path / "pids"
        setup = tmp_path / "slow_setup.py"
        setup.write_text(
            "import os, subprocess, sys, time\n"
            "child = subprocess.Popen(['sleep', '60'])\n"
            f"open({str(pids)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
            "time.sleep(60)\n"
        )
        a = tmp_path / "projA"
        a.mkdir()
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        result: dict = {}
        done = threading.Event()

        def run() -> None:
            stdin, stdout = os.fdopen(in_r, "rb"), os.fdopen(out_w, "wb")
            result["code"] = acprelay.run(
                # the agent outlives the moment the setup starts, then exits on its own
                [sys.executable, "-c", "import time; time.sleep(2)"], dict(os.environ),
                lambda p: [sys.executable, str(setup)], cwd=tmp_path, stdin=stdin, stdout=stdout,
            )
            done.set()

        threading.Thread(target=run, daemon=True).start()
        os.write(in_w, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session/new",
                                   "params": {"cwd": str(a), "mcpServers": []}}).encode() + b"\n")
        assert done.wait(30), "run() did not return after the agent exited"
        os.close(in_w)
        os.close(out_r)
        setup_pid, child_pid = (int(x) for x in pids.read_text().split())
        assert _gone(setup_pid), "the project-setup process outlived the relay"
        assert _gone(child_pid), "a process project-setup started outlived the relay"

    def test_a_closed_editor_stream_stops_the_agent_too(self, tmp_path):
        """Comment 1: `emit` on a closed stdout raises ValueError, not OSError."""
        import io

        agent = tmp_path / "loud.py"
        agent.write_text(
            "import sys, time\n"
            "for _ in range(2000):\n"
            "    sys.stdout.write('{\"jsonrpc\":\"2.0\",\"method\":\"x\",\"params\":{}}' + ' ' * 4096 + '\\n')\n"
            "    sys.stdout.flush()\n"
            "time.sleep(60)\n"
        )
        closed = io.BytesIO()
        closed.close()
        in_r, in_w = os.pipe()
        result: dict = {}
        done = threading.Event()

        def run() -> None:
            stdin = os.fdopen(in_r, "rb")
            result["code"] = acprelay.run(
                [sys.executable, str(agent)], dict(os.environ), lambda p: ["true"],
                cwd=tmp_path, stdin=stdin, stdout=closed,
            )
            done.set()

        threading.Thread(target=run, daemon=True).start()
        returned = done.wait(30)
        os.close(in_w)
        assert returned, "run() hung after the editor's stream was closed"
        assert result["code"] != 0
