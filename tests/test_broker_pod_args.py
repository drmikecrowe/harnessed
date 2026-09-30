"""The pod's network args after the pasta broker door was retired — issues #437, #468.

#437 gave the pod a private route to the host broker at `169.254.1.1` via pasta's
`--map-host-loopback`, composed into the one `--network` value `mounts._mcp_remote_pod_args` owns.
The pasta on GitHub's runner (podman 4.9.3) rejects that option, so #468 replaced the door with one
that needs no network option (`paths.broker_door`, tests/test_broker_door.py).

What this file still pins is what that composition was protecting: mcp-remote's OAuth callback
keeps its pasta option, `podman pod create` never gets two `--network`s, and an explicit
HARNESSED_NET wins. Plus one guard that the retired door does not come back.
"""

import pytest

from harnessed import mounts
from harnessed.schema import McpServer

PORT = "32081"   # a positional argv value, so a str — matches tests/test_mcp_remote_auth.py
URL = "https://mcp.atlassian.com/v1/sse"
SPEC_ARG = "mcp-remote@0.1.29"

RETIRED_DOOR = "169.254.1.1"


def _atlassian(*extra: str) -> McpServer:
    """An mcp-remote server; with a port argument it wants an OAuth callback publish."""
    return McpServer(
        name="atlassian", command="pnpm",
        args=["dlx", SPEC_ARG, URL, *extra], transport="stdio",
    )


def _free(_port: int) -> bool:
    return True


class TestTheCallbackShapes:
    def test_no_publish_emits_nothing(self):
        assert mounts._mcp_remote_pod_args([], "", port_free=_free) == []

    def test_a_publish_carries_its_pasta_option(self):
        args = mounts._mcp_remote_pod_args([_atlassian(PORT)], "", port_free=_free)
        assert args == ["-p", f"127.0.0.1:{PORT}:{PORT}", "--network", "pasta:--host-lo-to-ns-lo"]


class TestTheRetiredDoorStaysRetired:
    @pytest.mark.parametrize("net", ["", "mynet"])
    @pytest.mark.parametrize("servers", [[], [_atlassian()], [_atlassian(PORT)]])
    def test_no_host_loopback_map_is_ever_requested(self, net, servers, capsys):
        args = mounts._mcp_remote_pod_args(servers, net, port_free=_free)
        capsys.readouterr()
        assert not any("map-host-loopback" in a or RETIRED_DOOR in a for a in args), args


class TestNetworkIsNeverPassedTwice:
    """`podman pod create` takes one `--network`; two is a hard launch failure."""

    @pytest.mark.parametrize("net", ["", "mynet"])
    @pytest.mark.parametrize("servers", [[], [_atlassian()], [_atlassian(PORT)]])
    def test_at_most_one_network_option(self, net, servers, capsys):
        args = mounts._mcp_remote_pod_args(servers, net, port_free=_free)
        capsys.readouterr()
        assert args.count("--network") <= 1, (net, servers, args)


class TestAnExplicitNetworkWins:
    def test_harnessed_net_is_passed_through(self):
        assert mounts._mcp_remote_pod_args([], "mynet", port_free=_free) == ["--network", "mynet"]
