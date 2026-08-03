"""`publish: stable` — a host port the PROJECT can be told about.

`ephemeral` treats "nothing is written down, so nothing goes stale" as a pure win. It is half a
trade. The other half: nothing outside a harnessed launch can ever be configured with a value that
only exists inside a harnessed process. On 2026-07-27 every live agent in a project had zero BEADS_
variables — bd fell back to auto-start, hit the sidecar's exclusive lock, and told the user to run
`bd bootstrap`. A port that survives a reboot is what lets the project hold its own beads config.

The invariants below are the ones that make the value worth writing down: it must not move, and two
projects must never be handed the same one.
"""

from __future__ import annotations

import json
import socket

import pytest

from harnessed import launcher, paths
from harnessed.schema import SchemaError, ServiceDef, load_service
from tests.test_project_scoped_services import _svc_yaml
from support import patch_all


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """The registry is machine-wide by design, so a test must never touch the real one."""
    monkeypatch.setattr(paths, "xdg_data_home", lambda: tmp_path)


def _svc(name: str = "beads-server") -> ServiceDef:
    return ServiceDef(
        name=name, image="i", scope="project", port=3307, publish="stable",
        client_env={"BEADS_DOLT_SERVER_PORT": "{port}", "BEADS_DOLT_PASSWORD": "{password}"},
    )


class TestAllocation:
    def test_a_port_is_allocated_in_range(self, tmp_path):
        port = launcher._svc_stable_port(_svc(), tmp_path)
        assert launcher._STABLE_PORT_RANGE[0] <= port <= launcher._STABLE_PORT_RANGE[1]

    def test_the_same_project_gets_the_same_port_forever(self, tmp_path):
        """The whole point. If this drifts, every mise.local.toml harnessed ever wrote is a lie."""
        first = launcher._svc_stable_port(_svc(), tmp_path)
        assert launcher._svc_stable_port(_svc(), tmp_path) == first

    def test_a_recorded_port_survives_being_in_use(self, tmp_path):
        """The normal case is that OUR OWN sidecar holds the port. Re-allocating because the port
        is busy would move it on every second launch — the exact drift `stable` exists to stop."""
        port = launcher._svc_stable_port(_svc(), tmp_path)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            assert launcher._svc_stable_port(_svc(), tmp_path) == port

    def test_two_projects_never_share_a_port(self, tmp_path):
        a = launcher._svc_stable_port(_svc(), tmp_path / "a")
        b = launcher._svc_stable_port(_svc(), tmp_path / "b")
        assert a != b

    def test_two_services_in_one_project_never_share_a_port(self, tmp_path):
        a = launcher._svc_stable_port(_svc("beads-server"), tmp_path)
        b = launcher._svc_stable_port(_svc("other-server"), tmp_path)
        assert a != b

    def test_the_registry_is_machine_wide_not_per_project(self, tmp_path):
        """A per-project file cannot answer "is this port already promised to someone else?"."""
        launcher._svc_stable_port(_svc(), tmp_path / "a")
        launcher._svc_stable_port(_svc(), tmp_path / "b")
        registry = json.loads(paths.svc_ports_file().read_text())
        assert len(registry) == 2
        assert len(set(registry.values())) == 2


class TestPublishing:
    def test_the_port_is_bound_to_loopback_only(self, tmp_path):
        """An unqualified -p publishes on every interface, which would put a project's issue
        database on the LAN."""
        port = launcher._svc_stable_port(_svc(), tmp_path)
        assert f"127.0.0.1:{port}:3307".startswith("127.0.0.1:")

    def test_client_env_uses_the_registry_not_podman(self, tmp_path, monkeypatch):
        """`podman port` can only answer while the container is running. A plain `bd` in the repo
        needs a configured environment when it is NOT."""
        patch_all(monkeypatch, "_service_refs", lambda stack: ["beads-server"]
        )
        patch_all(monkeypatch, "load_service", lambda root, name: _svc())
        patch_all(monkeypatch, "_svc_published_port",
            lambda *a, **k: pytest.fail("stable ports must not consult podman"),
        )
        patch_all(monkeypatch, "_svc_password", lambda *a, **k: "pw")
        env = launcher.svc_client_env("s", tmp_path, "host")
        expected = launcher._svc_stable_port(_svc(), tmp_path)
        assert env["BEADS_DOLT_SERVER_PORT"] == str(expected)


class TestSchema:
    def test_stable_is_accepted(self):
        assert load_service(None, "beads-server").publish == "stable"

    def test_beads_server_is_stable_now(self):
        """Pinned deliberately: reverting this to ephemeral silently un-configures every non-
        harnessed bd in every project, which is not a change anyone would notice in a diff."""
        svc = load_service(None, "beads-server")
        assert svc.is_stable_port and not svc.is_ephemeral_port

    def test_an_unknown_publish_is_rejected(self, tmp_path):
        body = "name: s\nimage: i\nport: 1\npublish: whenever\n"
        with pytest.raises(SchemaError, match="'ephemeral' or 'stable'"):
            load_service(_svc_yaml(tmp_path, body, name="s"), "s")
