"""Tests for the host-native service supervisor (hostsvc) + the launcher presence policy.

Primitives (registry/pid/reap/stop) are exercised with a plain `sleep` process — no dolt needed, so
they run everywhere. The full start/reuse/stop cycle against a REAL `dolt sql-server` is gated on
dolt being on PATH (skipped in CI, runs locally with mise-provided dolt).
"""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import typer

from harnessed import hostsvc, launcher


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    # Registry + logs live under XDG_STATE — pin it per-test so runs never share a registry.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(["sleep", "300"])


class TestPidAlive:
    def test_live_process_is_alive(self):
        p = _sleeper()
        try:
            assert hostsvc._pid_alive(p.pid) is True
        finally:
            p.kill()
            p.wait()

    def test_missing_pid_is_dead(self):
        assert hostsvc._pid_alive(2_000_000_000) is False

    def test_zombie_is_dead(self):
        # Killed but NOT waited on → zombie. os.kill(pid,0) still succeeds; we must report dead.
        p = subprocess.Popen(["sleep", "300"])
        p.kill()
        time.sleep(0.2)  # become a zombie (parent hasn't reaped)
        try:
            assert hostsvc._pid_alive(p.pid) is False
        finally:
            p.wait()


class TestUnixSockOpen:
    def test_live_socket_detected(self, tmp_path):
        sock_path = str(tmp_path / "live.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        try:
            assert hostsvc.unix_sock_open(sock_path) is True
        finally:
            srv.close()

    def test_missing_socket_is_false(self, tmp_path):
        assert hostsvc.unix_sock_open(str(tmp_path / "nope.sock")) is False

    def test_stale_socket_file_is_false(self, tmp_path):
        # A leftover file at the path with no listener (crashed server) → not reusable.
        p = tmp_path / "stale.sock"
        p.touch()
        assert hostsvc.unix_sock_open(str(p)) is False


class TestPrimitives:
    def test_free_port_returns_usable_port(self):
        assert 1024 < hostsvc._free_port() <= 65535

    def test_key_is_service_and_project_hash(self, tmp_path):
        k = hostsvc._key("beads-server", tmp_path)
        assert k.startswith("beads-server|")

    def test_registry_roundtrip(self):
        hostsvc._write({"a|b": {"pid": 1}})
        assert hostsvc._read() == {"a|b": {"pid": 1}}


class TestReapAndStop:
    def test_reap_drops_only_dead_entries(self, tmp_path):
        alive = _sleeper()
        dead = _sleeper()
        dead.kill()
        dead.wait()
        hostsvc._write({
            "svc|alive": {"pid": alive.pid, "socket": str(tmp_path / "a.sock")},
            "svc|dead": {"pid": dead.pid, "socket": str(tmp_path / "d.sock")},
        })
        try:
            reaped = hostsvc.reap()
            assert reaped == ["svc|dead"]
            assert list(hostsvc._read()) == ["svc|alive"]
        finally:
            alive.kill()
            alive.wait()

    def test_stop_kills_and_deregisters(self, tmp_path):
        p = _sleeper()
        sock = tmp_path / "x.sock"
        sock.touch()
        # register it as if ensure() had started it, keyed to this project path
        hostsvc._write({hostsvc._key("svc", tmp_path): {"pid": p.pid, "socket": str(sock)}})
        assert hostsvc.stop("svc", tmp_path) is True
        time.sleep(0.2)
        assert hostsvc._pid_alive(p.pid) is False
        assert not sock.exists()
        assert hostsvc._read() == {}
        p.wait()

    def test_stop_missing_is_false(self, tmp_path):
        assert hostsvc.stop("svc", tmp_path) is False


class TestStealthPolicy:
    def test_stealth_absent_workspace_hard_fails(self, monkeypatch, tmp_path):
        # Pretend the host tools are present so we reach the presence policy, not the tool check.
        monkeypatch.setattr(launcher.shutil, "which", lambda _n: "/usr/bin/stub")
        # hostbeads_stealth resolves .beads to a host-persisted dir with NO workspace → hard fail.
        with pytest.raises(typer.Exit):
            launcher._host_ensure_services("hostbeads_stealth", tmp_path)

    def test_missing_tools_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher.shutil, "which", lambda _n: None)
        with pytest.raises(typer.Exit):
            launcher._host_ensure_services("hostbeads_stealth", tmp_path)


class TestGenericSupervisor:
    """The generic ensure() start/reuse/stop cycle with a trivial HTTP daemon — no dolt/hatago needed,
    so it runs everywhere and proves the supervisor core both beads and hatago sit on."""

    def test_start_reuse_stop_with_http_daemon(self, tmp_path):
        import sys

        proj = tmp_path / "proj"
        proj.mkdir()
        argv = lambda p: [sys.executable, "-m", "http.server", str(p), "--bind", "127.0.0.1"]
        ready = lambda p: hostsvc.tcp_open(p)

        e1, started1 = hostsvc.ensure("demo", proj, argv=argv, ready=ready, cwd=proj, timeout=20)
        assert started1 is True
        assert hostsvc.tcp_open(e1["port"])
        pid = e1["pid"]

        e2, started2 = hostsvc.ensure("demo", proj, argv=argv, ready=ready, cwd=proj, timeout=20)
        assert started2 is False  # reused warm daemon
        assert e2["pid"] == pid

        assert hostsvc.stop("demo", proj) is True
        time.sleep(0.3)
        assert hostsvc._pid_alive(pid) is False
        assert hostsvc._read() == {}

    def test_prestart_and_meta_are_applied(self, tmp_path):
        import sys

        proj = tmp_path / "proj"
        proj.mkdir()
        marker = tmp_path / "prestart-ran"
        e, _ = hostsvc.ensure(
            "demo2", proj,
            argv=lambda p: [sys.executable, "-m", "http.server", str(p), "--bind", "127.0.0.1"],
            ready=lambda p: hostsvc.tcp_open(p),
            cwd=proj, prestart=lambda: marker.write_text("x"),
            meta=lambda p: {"endpoint": f"http://localhost:{p}/mcp"}, timeout=20,
        )
        try:
            assert marker.exists()
            assert e["endpoint"].endswith("/mcp")
        finally:
            hostsvc.stop("demo2", proj)


class TestNativeMcp:
    """Default host MCP path (hatago deferred): the stack's servers are emitted directly into the
    native .mcp.json — no hub."""

    def test_no_mcp_stack_returns_none(self):
        assert launcher._host_native_mcp("hostspike") is None  # greet: no MCP servers

    def test_stdio_server_emitted_natively(self):
        # hostmcp = [time]: an stdio MCP server (uvx mcp-server-time) → native {command,args} entry.
        servers = launcher._host_native_mcp("hostmcp")
        assert servers is not None
        assert "time" in servers
        entry = servers["time"]
        assert entry["command"] == "uvx"
        assert "mcp-server-time" in entry["args"]
        assert "url" not in entry  # stdio, not a hub pointer


@pytest.mark.skipif(shutil.which("dolt") is None, reason="needs dolt on PATH (host-native beads daemon)")
class TestDoltDaemonIntegration:
    def test_launcher_team_present_ensures_server_and_exports_socket(self, tmp_path):
        # Full launcher service path (minus the claude exec): team workspace present → no prompt,
        # daemon started, socket env exported for the agent's bd prime hook.
        proj = tmp_path / "proj"
        proj.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=proj)
        beads = proj / ".beads"
        beads.mkdir()
        (beads / "metadata.json").write_text("{}")  # workspace present → no init prompt

        env, started = launcher._host_ensure_services("hostbeads", proj)
        try:
            assert started == ["beads-server"]
            sock = env["HARNESSED_BEADS_SERVER_SOCKET"]
            assert Path(sock).exists()
        finally:
            hostsvc.stop("beads-server", proj)
