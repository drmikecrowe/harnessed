"""Docker reaches the secrets broker too — issue #468.

podman reaches the host broker through pasta's `--map-host-loopback` (#437). docker has no pods and
no pasta, so it used to start no broker and print a note. #439 makes the pod's env placeholders that
only the broker can redeem, which would have left docker with real values and nothing but that note.

varlock's own answer for a guest that is not on host loopback is `proxy start --expose`: the proxy
binds off-loopback and every off-loopback client must present a data-plane token, as proxy Basic
auth. So on docker the broker is exposed, the container resolves `host.docker.internal` to the host
gateway, and the token travels in the proxy URL #439 builds. varlock mints the token; harnessed reads
it back when it needs it and never writes it anywhere.

A host firewall can still drop container-to-host traffic (ufw's default INPUT policy does). That
cannot be fixed from here without root, so the launch probes the route first and REFUSES rather
than start an agent whose proxy is unreachable.
"""

import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import broker, launcher, mounts, paths

PORT = 39443


def _broker(cert_dir: str = "/state/inst-certs") -> broker.Broker:
    return broker.Broker(instance="inst", pod="pod", session="s1", port=PORT, cert_dir=cert_dir)


class TestTheBrokerIsExposedOnlyWhenAsked:
    def _argv(self, tmp_path, monkeypatch, **kw) -> list[str]:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        spawned: list[list[str]] = []
        broker.start(
            "inst", "pod", "/proj",
            spawn=lambda argv: spawned.append(argv) or 1,
            status=lambda: [{"id": "s1", "env": {"HTTPS_PROXY": f"http://127.0.0.1:{PORT}"}}],
            candidates=[PORT], port_free=lambda p: True, cert_dir=tmp_path / "certs", **kw,
        )
        return spawned[0]

    def test_expose_adds_the_bare_flag(self, tmp_path, monkeypatch):
        assert "--expose" in self._argv(tmp_path, monkeypatch, expose=True)

    def test_the_default_stays_on_loopback(self, tmp_path, monkeypatch):
        """podman reaches loopback through pasta, so exposing it there would widen nothing useful."""
        assert not any(a.startswith("--expose") for a in self._argv(tmp_path, monkeypatch))

    def test_bare_not_bound_to_one_address(self, tmp_path, monkeypatch):
        """`--expose=<addr>` hides the session from `proxy status` and `proxy env` in 1.16.1, which
        broker.start polls. Measured: a 172.17.0.1 bind reported "No active proxy sessions"."""
        argv = self._argv(tmp_path, monkeypatch, expose=True)
        assert not any(a.startswith("--expose=") for a in argv)


class TestTheTokenIsReadBackNotStored:
    def test_it_asks_varlock_for_this_sessions_token(self):
        seen: dict = {}

        def run(argv, **kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, stdout="tok-123\n", stderr="")

        assert broker.token(_broker(), run=run) == "tok-123"
        assert seen["argv"] == ["varlock", "proxy", "token", "--session", "s1"]

    def test_a_failure_raises_without_echoing_output(self):
        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, stdout="leak-me", stderr="leak-me-too")

        with pytest.raises(broker.BrokerError) as exc:
            broker.token(_broker(), run=run)
        assert "leak-me" not in str(exc.value)

    def test_the_record_has_no_token_field(self):
        assert "token" not in broker.Broker.__dataclass_fields__


class TestTheDoorArgs:
    def test_docker_with_a_broker_resolves_the_host_gateway(self):
        assert launcher._broker_door_args("docker", _broker()) == [
            "--add-host", f"{paths.BROKER_DOCKER_DOOR}:host-gateway",
        ]

    def test_docker_without_a_broker_adds_nothing(self):
        assert launcher._broker_door_args("docker", None) == []

    def test_podman_uses_the_pasta_door_not_this(self):
        assert launcher._broker_door_args("podman", _broker()) == []


class TestTheReachabilityProbe:
    def test_it_dials_the_door_from_the_agents_own_image(self, monkeypatch):
        seen: dict = {}

        def bounded(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return subprocess.CompletedProcess(cmd, 0, "172.17.0.1\n", "")

        monkeypatch.setattr(launcher, "_bounded", bounded)
        assert launcher._broker_gateway("docker", "img", PORT) == "172.17.0.1"
        cmd = seen["cmd"]
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert f"{paths.BROKER_DOCKER_DOOR}:host-gateway" in cmd
        assert cmd[cmd.index("--entrypoint") + 1] == "bash"
        assert f"/dev/tcp/{paths.BROKER_DOCKER_DOOR}/{PORT}" in cmd[-1]
        assert seen["kw"].get("timeout"), "a dropped route hangs; the probe must be bounded"

    def test_a_refused_or_dropped_route_is_unreachable(self, monkeypatch):
        monkeypatch.setattr(
            launcher, "_bounded",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "172.17.0.1\n", ""),
        )
        assert launcher._broker_gateway("docker", "img", PORT) is None

    def test_a_reachable_door_with_no_address_is_not_trusted(self, monkeypatch):
        """The address feeds the firewall allowlist. Without it the agent's proxy would be dropped."""
        monkeypatch.setattr(
            launcher, "_bounded", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "\n", ""),
        )
        assert launcher._broker_gateway("docker", "img", PORT) is None


@pytest.fixture
def docker_boundary(monkeypatch, tmp_path):
    """ContainerBackend's BOUNDARY phase on docker, with everything but the broker wiring stubbed.

    Returns (run, calls): `run(brk, reachable=True, run_fails=False)` drives the phase; `calls`
    records broker starts, stops and every runtime argv.
    """
    calls: dict = {"start": [], "stop": [], "runs": []}

    def fake_run(cmd, **kw):
        calls["runs"].append(list(cmd))
        if calls.get("run_fails") and cmd[1:3] == ["run", "-d"]:
            raise subprocess.CalledProcessError(125, cmd)

    monkeypatch.setattr(launcher, "_run", fake_run)
    for name, value in (
        ("harnessed_env", {}), ("_pending_setup_scripts", []), ("_container_setup_env", {}),
        ("_recipe_env", {}), ("_claude_oauth_token_args", []), ("proxy_schema_dirs", []),
        ("_agent_placement_args", []),
    ):
        monkeypatch.setattr(launcher, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(launcher, "_broker_stop_for", lambda inst: calls["stop"].append(inst))
    monkeypatch.delenv("HARNESSED_NET", raising=False)

    def run(brk, *, reachable=True, run_fails=False):
        calls["run_fails"] = run_fails

        def start_for(inst, pod, project_path, **kw):
            calls["start"].append(kw)
            return brk

        monkeypatch.setattr(launcher, "_broker_start_for", start_for)
        monkeypatch.setattr(
            launcher, "_broker_gateway", lambda *a, **k: "172.17.0.1" if reachable else None,
        )
        b = launcher.ContainerBackend.__new__(launcher.ContainerBackend)
        b.rt, b.inst, b.pod, b.recipes, b.servers = "docker", "inst", "pod", [], []
        b.harness_image, b.mount_path, b.broker = "img", Path("/workspace"), None
        b.broker_gateway = None
        b.member_mounts, b.secrets_env_files, b.secrets_temp_files = [], [], []
        b.stk = type("Stk", (), {"isolated_auth": False, "hub_transport": "stdio"})()
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=tmp_path)
        b.apply_isolation(spec, launcher.BOUNDARY)
        return b

    return run, calls


def _member(calls) -> list[str]:
    member = [c for c in calls["runs"] if c[1:3] == ["run", "-d"]]
    assert len(member) == 1, calls["runs"]
    return member[0]


class TestADockerLaunchGetsTheBroker:
    def test_the_broker_is_started_exposed(self, docker_boundary):
        run, calls = docker_boundary
        run(_broker())
        assert calls["start"] == [{"expose": True}]

    def test_the_agent_can_resolve_the_door(self, docker_boundary):
        run, calls = docker_boundary
        run(_broker())
        argv = _member(calls)
        i = argv.index(f"{paths.BROKER_DOCKER_DOOR}:host-gateway")
        assert argv[i - 1] == "--add-host"
        assert i < argv.index("img")

    def test_the_agent_gets_the_ca_mount(self, docker_boundary):
        run, calls = docker_boundary
        run(_broker())
        assert mounts._broker_cert_mount_args(_broker())[1] in _member(calls)

    def test_the_old_note_is_gone(self, docker_boundary, capsys):
        """A note that only informs is what let #468 sit unnoticed."""
        run, _ = docker_boundary
        run(_broker())
        assert "does not use pods" not in capsys.readouterr().err

    def test_no_broker_means_no_door_and_no_mount(self, docker_boundary):
        run, calls = docker_boundary
        run(None)
        argv = _member(calls)
        assert not any(paths.BROKER_DOCKER_DOOR in a for a in argv)
        assert not any(paths.BROKER_GUEST_CERT_DIR in a for a in argv)


class TestAnUnreachableBrokerRefusesTheLaunch:
    def test_it_exits_before_the_agent_starts(self, docker_boundary):
        run, calls = docker_boundary
        with pytest.raises(typer.Exit):
            run(_broker(), reachable=False)
        assert not [c for c in calls["runs"] if c[1:3] == ["run", "-d"]]

    def test_the_broker_is_stopped(self, docker_boundary):
        run, calls = docker_boundary
        with pytest.raises(typer.Exit):
            run(_broker(), reachable=False)
        assert calls["stop"] == ["inst"]

    def test_the_message_names_the_way_out(self, docker_boundary, capsys):
        run, _ = docker_boundary
        with pytest.raises(typer.Exit):
            run(_broker(), reachable=False)
        err = capsys.readouterr().err
        assert "--no-secrets" in err and "docker0" in err


class TestAFailedAgentStartDoesNotStrandTheBroker:
    def test_the_broker_is_stopped_and_the_error_propagates(self, docker_boundary):
        run, calls = docker_boundary
        with pytest.raises(subprocess.CalledProcessError):
            run(_broker(), run_fails=True)
        assert calls["stop"] == ["inst"]


class TestTheFirewallAdmitsTheDoor:
    """The firewall runner joins the agent's netns but not its /etc/hosts, and docker refuses
    `--add-host` alongside `--network=container:`. So the script cannot resolve the door itself;
    the probe's resolved address is handed to it as one more allowlist entry. `getent ahosts`
    returns an IP literal unchanged, so the script needs no special case."""

    def _egress(self, monkeypatch, backend) -> list[str]:
        seen: dict = {}
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(launcher, "_resolve_launch_env", lambda *a, **k: {})
        monkeypatch.setattr(launcher, "api_endpoint_egress_hosts", lambda *a, **k: [])
        monkeypatch.setattr(
            launcher, "_apply_firewall", lambda rt, inst, domains, **kw: seen.update(d=domains),
        )
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=Path("/nonexistent"))
        backend.apply_isolation(spec, launcher.EGRESS)
        return seen["d"]

    def test_the_probed_gateway_joins_the_allowlist(self, docker_boundary, monkeypatch):
        run, _ = docker_boundary
        b = run(_broker())
        assert b.broker_gateway == "172.17.0.1"
        assert "172.17.0.1" in self._egress(monkeypatch, b)

    def test_no_broker_adds_no_address(self, docker_boundary, monkeypatch):
        run, _ = docker_boundary
        b = run(None)
        assert b.broker_gateway is None
        assert "172.17.0.1" not in self._egress(monkeypatch, b)
