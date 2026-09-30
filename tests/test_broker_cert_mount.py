"""The broker's CA reaches the pod, read-only — issue #438.

Topology B (epic #388) trusts the broker's CA through files on disk. `varlock proxy env --full`
emits seven CA-path variables, all pointing into one `--cert-dir`, so that directory has to exist
inside the pod at the path the env names. varlock's own container sandbox mounts it read-only at
`/etc/varlock/proxy-certs` (src/proxy/sandbox-docker.ts, GUEST_CA_DIR); we use the same path.

Read-only because the pod is the thing being contained: a writable mount would let it swap the CA
that every other client of this broker trusts.

These tests assert the argv. The live half — the seven paths resolving to readable files, and a
TLS handshake through the broker — is in tests/test_external_contracts_live.py.
"""

from pathlib import Path

import pytest

from harnessed import broker, launcher, mounts, paths

CERTS = "/state/inst-certs"


def _broker(cert_dir: str = CERTS) -> broker.Broker:
    return broker.Broker(instance="inst", pod="pod", session="s1", port=39443, cert_dir=cert_dir)


class TestTheMountArgs:
    def test_a_broker_gets_its_cert_dir_mounted_read_only(self):
        assert mounts._broker_cert_mount_args(_broker()) == [
            "-v", f"{CERTS}:{paths.BROKER_GUEST_CERT_DIR}:ro",
        ]

    def test_no_broker_mounts_nothing(self):
        assert mounts._broker_cert_mount_args(None) == []

    def test_the_guest_path_is_varlocks_own(self):
        """One path for every guest varlock wires, so a CA var from either source resolves."""
        assert paths.BROKER_GUEST_CERT_DIR == "/etc/varlock/proxy-certs"


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    """Run ContainerBackend's BOUNDARY phase with everything but the argv assembly stubbed.

    Returns a callable taking the broker `_broker_start_for` should hand back; it returns the
    member `run` argv the launcher built.
    """
    runs: list[list[str]] = []
    monkeypatch.setattr(launcher, "_run", lambda cmd, **kw: runs.append(list(cmd)))
    monkeypatch.setattr(launcher, "harnessed_env", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "_pending_setup_scripts", lambda *a, **k: [])
    monkeypatch.setattr(launcher, "_container_setup_env", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "_recipe_env", lambda *a, **k: {})
    monkeypatch.setattr(launcher, "_claude_oauth_token_args", lambda *a, **k: [])
    monkeypatch.setattr(launcher, "proxy_schema_dirs", lambda *a, **k: [])
    # The reachability probe (#468) is not what this file tests; tests/test_broker_door.py is.
    monkeypatch.setattr(launcher, "_broker_gateway", lambda *a, **k: "172.17.0.1")
    monkeypatch.delenv("HARNESSED_NET", raising=False)

    def run(brk: broker.Broker | None) -> list[str]:
        monkeypatch.setattr(launcher, "_broker_start_for", lambda *a, **k: brk)
        b = launcher.ContainerBackend.__new__(launcher.ContainerBackend)
        b.rt, b.inst, b.pod, b.recipes, b.servers = "podman", "inst", "pod", [], []
        b.harness_image, b.mount_path = "img", Path("/workspace")
        b.member_mounts, b.secrets_env_files, b.secrets_temp_files = [], [], []
        b.stk = type("Stk", (), {"isolated_auth": False, "hub_transport": "stdio"})()
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=tmp_path)
        b.apply_isolation(spec, launcher.BOUNDARY)
        member = [c for c in runs if c[1:3] == ["run", "-d"]]
        assert len(member) == 1, f"expected one member run, saw {runs}"
        return member[0]

    return run


class TestTheLauncherDeliversIt:
    def test_the_member_run_carries_the_read_only_cert_mount(self, boundary):
        argv = boundary(_broker())
        i = argv.index(f"{CERTS}:{paths.BROKER_GUEST_CERT_DIR}:ro")
        assert argv[i - 1] == "-v"

    def test_it_precedes_the_image(self, boundary):
        """podman reads everything after the image as the command, so a late `-v` is inert."""
        argv = boundary(_broker())
        assert argv.index(f"{CERTS}:{paths.BROKER_GUEST_CERT_DIR}:ro") < argv.index("img")

    def test_without_a_broker_no_cert_dir_reaches_the_pod(self, boundary):
        argv = boundary(None)
        assert not any(paths.BROKER_GUEST_CERT_DIR in a for a in argv)

    def test_the_host_cert_dir_comes_from_the_broker_record(self, boundary, tmp_path):
        """Not re-derived: broker.start owns the path, and a second derivation would drift."""
        other = str(Path(tmp_path) / "elsewhere")
        argv = boundary(_broker(other))
        assert f"{other}:{paths.BROKER_GUEST_CERT_DIR}:ro" in argv
