"""One door to the secrets broker, on both runtimes — issue #468.

#437 bound the broker to host loopback and gave the pod pasta's `--map-host-loopback,169.254.1.1`.
The pasta on GitHub's runner (podman 4.9.3) rejects that option, and docker has no pasta at all, so
a docker launch started no broker and printed a note. #439 makes the pod's env placeholders that
only the broker can redeem, which would have left both gaps holding real values or no proxy.

varlock's own answer for a guest that is not on host loopback is `proxy start --expose`: the proxy
binds off-loopback and every off-loopback client must present a data-plane token, as proxy Basic
auth. So the broker is always exposed, and each runtime reaches it at its host-gateway name
(`paths.broker_door`). varlock mints the token; harnessed reads it back when it needs it and never
writes it anywhere.

A host firewall can still drop container-to-host traffic (ufw's default INPUT policy does for
docker0). That cannot be fixed from here without root, so the launch probes the route from where
the agent will run and REFUSES rather than start an agent whose proxy is unreachable.
"""

import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import broker, launcher, mounts, paths

PORT = 39443
GATEWAY = "172.17.0.1"


def _broker(cert_dir: str = "/state/inst-certs") -> broker.Broker:
    return broker.Broker(instance="inst", pod="pod", session="s1", port=PORT, cert_dir=cert_dir)


class TestTheBrokerIsAlwaysExposed:
    def _argv(self, tmp_path, monkeypatch) -> list[str]:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        spawned: list[list[str]] = []
        broker.start(
            "inst", "pod", "/proj",
            spawn=lambda argv: spawned.append(argv) or 1,
            status=lambda: [{"id": "s1", "env": {"HTTPS_PROXY": f"http://127.0.0.1:{PORT}"}}],
            candidates=[PORT], port_free=lambda p: True, cert_dir=tmp_path / "certs",
        )
        return spawned[0]

    def test_the_bare_flag_is_passed(self, tmp_path, monkeypatch):
        assert "--expose" in self._argv(tmp_path, monkeypatch)

    def test_never_bound_to_one_address(self, tmp_path, monkeypatch):
        """`--expose=<addr>` hides the session from `proxy status` and `proxy env` in 1.16.1, which
        broker.start polls. Measured: a 172.17.0.1 bind reported "No active proxy sessions"."""
        assert not any(a.startswith("--expose=") for a in self._argv(tmp_path, monkeypatch))


class TestTheTokenNeverPassesThroughHarnessed:
    """varlock embeds it into the guest env itself (`proxy env --full`), so nothing here reads it."""

    def test_the_record_has_no_token_field(self):
        assert "token" not in broker.Broker.__dataclass_fields__

    def test_there_is_no_token_reader(self):
        assert not hasattr(broker, "token")


class TestTheDoorName:
    def test_podman_uses_the_name_it_writes_itself(self):
        assert paths.broker_door("podman") == "host.containers.internal"

    def test_docker_uses_the_name_varlocks_own_sandbox_dials(self):
        assert paths.broker_door("docker") == "host.docker.internal"


class TestTheDoorArgs:
    def test_docker_with_a_broker_resolves_the_host_gateway(self):
        assert launcher._broker_door_args("docker", _broker()) == [
            "--add-host", "host.docker.internal:host-gateway",
        ]

    def test_docker_without_a_broker_adds_nothing(self):
        assert launcher._broker_door_args("docker", None) == []

    def test_podman_needs_none(self):
        assert launcher._broker_door_args("podman", _broker()) == []


class TestTheReachabilityProbe:
    def _probe(self, monkeypatch, rt, rc=0, out=f"{GATEWAY}\n"):
        seen: dict = {}

        def bounded(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return subprocess.CompletedProcess(cmd, rc, out, "")

        monkeypatch.setattr(launcher, "_bounded", bounded)
        return launcher._broker_gateway(rt, "img", PORT, "pod"), seen

    def test_docker_dials_its_door_from_the_agents_own_image(self, monkeypatch):
        got, seen = self._probe(monkeypatch, "docker")
        assert got == GATEWAY
        cmd = seen["cmd"]
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "host.docker.internal:host-gateway" in cmd
        assert "--pod" not in cmd
        assert cmd[cmd.index("--entrypoint") + 1] == "bash"
        assert f"/dev/tcp/host.docker.internal/{PORT}" in cmd[-1]
        assert seen["kw"].get("timeout"), "a dropped route hangs; the probe must be bounded"
        # IPv4 only: the address goes to an iptables rule, and ahosts may list AAAA first.
        assert "getent ahostsv4 host.docker.internal" in cmd[-1]

    def test_podman_dials_from_inside_the_pod(self, monkeypatch):
        """Same netns and /etc/hosts as the agent. podman rejects --userns on a pod member."""
        got, seen = self._probe(monkeypatch, "podman")
        assert got == GATEWAY
        cmd = seen["cmd"]
        assert cmd[cmd.index("--pod") + 1] == "pod"
        assert "--add-host" not in cmd
        assert not any(a.startswith("--userns") for a in cmd)
        assert f"/dev/tcp/host.containers.internal/{PORT}" in cmd[-1]

    def test_a_refused_or_dropped_route_is_unreachable(self, monkeypatch):
        got, _ = self._probe(monkeypatch, "docker", rc=1)
        assert got is None

    def test_a_reachable_door_with_no_address_is_not_trusted(self, monkeypatch):
        """The address feeds the firewall allowlist. Without it the agent's proxy would be dropped."""
        got, _ = self._probe(monkeypatch, "docker", out="\n")
        assert got is None


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    """ContainerBackend's BOUNDARY phase, with everything but the broker wiring stubbed.

    Returns (run, calls): `run(rt, brk, reachable=True, run_fails=False)` drives the phase and
    returns the backend; `calls` records every runtime argv, broker stops, teardowns and probes.
    """
    calls: dict = {"stop": [], "teardown": [], "runs": [], "probe": []}

    def fake_run(cmd, **kw):
        calls["runs"].append(list(cmd))
        if calls.get("run_fails") and cmd[1:3] == ["run", "-d"]:
            raise subprocess.CalledProcessError(125, cmd)

    monkeypatch.setattr(launcher, "_run", fake_run)
    for name, value in (
        ("harnessed_env", {}), ("_pending_setup_scripts", []), ("_container_setup_env", {}),
        ("_recipe_env", {}), ("_claude_oauth_token_args", []), ("_agent_placement_args", []),
    ):
        monkeypatch.setattr(launcher, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(launcher, "_broker_stop_for", lambda inst: calls["stop"].append(inst))
    monkeypatch.setattr(
        launcher, "_pod_teardown", lambda rt, inst, pod: calls["teardown"].append((rt, inst, pod)),
    )
    # The broker-built env (#439) is tests/test_proxy_env_file.py's subject, not this file's.
    monkeypatch.setattr(launcher.ContainerBackend, "_add_broker_env", lambda self, spec, brk: None)
    monkeypatch.delenv("HARNESSED_NET", raising=False)

    def run(rt, brk, *, reachable=True, run_fails=False):
        calls["run_fails"] = run_fails
        monkeypatch.setattr(launcher, "_broker_start_for", lambda *a, **k: brk)

        def probe(rt_, image, port, pod):
            calls["probe"].append((rt_, port, pod, len(calls["runs"])))
            return GATEWAY if reachable else None

        monkeypatch.setattr(launcher, "_broker_gateway", probe)
        b = launcher.ContainerBackend.__new__(launcher.ContainerBackend)
        b.rt, b.inst, b.pod, b.recipes, b.servers = rt, "inst", "pod", [], []
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


class TestDockerGetsTheBroker:
    def test_the_agent_can_resolve_the_door(self, boundary):
        run, calls = boundary
        run("docker", _broker())
        argv = _member(calls)
        i = argv.index("host.docker.internal:host-gateway")
        assert argv[i - 1] == "--add-host"
        assert i < argv.index("img")

    def test_the_agent_gets_the_ca_mount(self, boundary):
        run, calls = boundary
        run("docker", _broker())
        assert mounts._broker_cert_mount_args(_broker())[1] in _member(calls)

    def test_the_old_note_is_gone(self, boundary, capsys):
        """A note that only informs is what let #468 sit unnoticed."""
        run, _ = boundary
        run("docker", _broker())
        assert "does not use pods" not in capsys.readouterr().err

    def test_no_broker_means_no_door_no_mount_no_probe(self, boundary):
        run, calls = boundary
        run("docker", None)
        argv = _member(calls)
        assert not any("host.docker.internal" in a for a in argv)
        assert not any(paths.BROKER_GUEST_CERT_DIR in a for a in argv)
        assert calls["probe"] == []


class TestPodmanUsesTheSameDoor:
    def test_the_pod_gets_no_pasta_broker_option(self, boundary):
        run, calls = boundary
        run("podman", _broker())
        pod_create = next(c for c in calls["runs"] if c[1:3] == ["pod", "create"])
        assert not any("map-host-loopback" in a for a in pod_create)

    def test_the_probe_runs_after_the_pod_exists(self, boundary):
        run, calls = boundary
        run("podman", _broker())
        pod_create_at = next(i for i, c in enumerate(calls["runs"]) if c[1:3] == ["pod", "create"])
        (rt, port, pod, runs_before_probe), = calls["probe"]
        assert (rt, port, pod) == ("podman", PORT, "pod")
        assert runs_before_probe > pod_create_at

    def test_the_member_gets_the_ca_mount_and_no_add_host(self, boundary):
        run, calls = boundary
        run("podman", _broker())
        argv = _member(calls)
        assert mounts._broker_cert_mount_args(_broker())[1] in argv
        assert "--add-host" not in argv


class TestAnUnreachableBrokerRefusesTheLaunch:
    @pytest.mark.parametrize("rt", ["docker", "podman"])
    def test_it_exits_before_the_agent_starts(self, boundary, rt):
        run, calls = boundary
        with pytest.raises(typer.Exit):
            run(rt, _broker(), reachable=False)
        assert not [c for c in calls["runs"] if c[1:3] == ["run", "-d"]]

    @pytest.mark.parametrize("rt", ["docker", "podman"])
    def test_everything_it_created_is_torn_down(self, boundary, rt):
        """_pod_teardown stops the broker first, then removes the pod or container."""
        run, calls = boundary
        with pytest.raises(typer.Exit):
            run(rt, _broker(), reachable=False)
        assert calls["teardown"] == [(rt, "inst", "pod")]

    def test_the_message_names_the_door_and_the_way_out(self, boundary, capsys):
        run, _ = boundary
        with pytest.raises(typer.Exit):
            run("docker", _broker(), reachable=False)
        err = capsys.readouterr().err
        assert f"host.docker.internal:{PORT}" in err
        assert "--no-secrets" in err and "docker0" in err


class TestAFailedAgentStartDoesNotStrandTheBroker:
    def test_on_docker_the_broker_is_stopped_and_the_error_propagates(self, boundary):
        run, calls = boundary
        with pytest.raises(subprocess.CalledProcessError):
            run("docker", _broker(), run_fails=True)
        assert calls["stop"] == ["inst"]


class TestTheFirewallAdmitsTheDoor:
    """The firewall runner joins the agent's netns but not its /etc/hosts, and docker refuses
    `--add-host` alongside `--network=container:`. So the script cannot resolve the door itself;
    the probe's resolved address is handed to it as `--broker=<ip>`, which it installs with
    `require` (tests/test_egress_firewall_broker_door.py runs that half)."""

    def _egress(self, monkeypatch, backend) -> dict:
        seen: dict = {}
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(launcher, "_resolve_launch_env", lambda *a, **k: {})
        monkeypatch.setattr(launcher, "api_endpoint_egress_hosts", lambda *a, **k: [])
        monkeypatch.setattr(
            launcher, "_apply_firewall",
            lambda rt, inst, domains, **kw: seen.update(domains=domains, **kw),
        )
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=Path("/nonexistent"))
        backend.apply_isolation(spec, launcher.EGRESS)
        return seen

    @pytest.mark.parametrize("rt", ["docker", "podman"])
    def test_the_probed_gateway_reaches_the_firewall_as_the_broker(self, boundary, monkeypatch, rt):
        run, _ = boundary
        b = run(rt, _broker())
        seen = self._egress(monkeypatch, b)
        assert seen["broker_gateway"] == GATEWAY
        assert GATEWAY not in seen["domains"], "the best-effort domain loop must not carry it"

    def test_no_broker_passes_no_gateway(self, boundary, monkeypatch):
        run, _ = boundary
        b = run("docker", None)
        assert self._egress(monkeypatch, b)["broker_gateway"] is None

    def test_apply_firewall_hands_the_script_a_broker_argument(self, monkeypatch):
        seen: dict = {}
        monkeypatch.delenv("NO_FIREWALL", raising=False)
        monkeypatch.setattr(launcher, "_bounded", lambda cmd, **kw: seen.update(cmd=cmd) or
                            subprocess.CompletedProcess(cmd, 1, b"", b""))
        with pytest.raises(typer.Exit):  # rc 1 fails closed; only the argv matters here
            launcher._apply_firewall("docker", "inst", ["a.example"], netns_anchor="inst",
                                     image="img", broker_gateway=GATEWAY)
        cmd = seen["cmd"]
        script = cmd.index("/usr/local/sbin/egress-firewall")
        assert cmd[script + 1:] == [f"--broker={GATEWAY}", "a.example"]
