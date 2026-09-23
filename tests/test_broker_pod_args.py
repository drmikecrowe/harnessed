"""The pod's private door to the host secrets broker — issue #437, Group A.

Topology B (epic #388) puts `varlock proxy` on the host's `127.0.0.1` and gives the pod a private
route to it at `169.254.1.1`, via pasta's `--map-host-loopback`. `#436` opened the firewall for that
address; this is the half that actually asks podman for the route.

The whole difficulty is that **`--network` cannot be passed to `podman pod create` twice**, and
`mounts._mcp_remote_pod_args` already owns it for mcp-remote's `--host-lo-to-ns-lo` and for the
plain `HARNESSED_NET` passthrough. So the broker option cannot be a second `--network`; it has to
compose inside that one helper. The #388 Phase 0 spike verified the composed form
`pasta:--map-host-loopback,169.254.1.1,--host-lo-to-ns-lo` with both features live.

These tests assert the argv the launcher hands `pod create`. What they cannot show is a packet
crossing that route — no test in this repo starts a pod. See the EVIDENCE for #437.
"""

import pytest

from harnessed import mounts
from harnessed.schema import McpServer

PORT = "32081"   # a positional argv value, so a str — matches tests/test_mcp_remote_auth.py
URL = "https://mcp.atlassian.com/v1/sse"
SPEC_ARG = "mcp-remote@0.1.29"

BROKER_DOOR = "169.254.1.1"
BROKER_ONLY = f"pasta:--map-host-loopback,{BROKER_DOOR}"
BROKER_AND_CALLBACK = f"pasta:--map-host-loopback,{BROKER_DOOR},--host-lo-to-ns-lo"

# A capture that comes back empty makes an `assert "..." in err` vacuously... not pass, but the
# failure reads as "the warning text changed" when the real cause is "nothing was captured".
_CAPTURE_PROOF = "expected a warning on stderr and captured nothing at all"


def _atlassian(*extra: str) -> McpServer:
    """An mcp-remote server; with a port argument it wants an OAuth callback publish."""
    return McpServer(
        name="atlassian", command="pnpm",
        args=["dlx", SPEC_ARG, URL, *extra], transport="stdio",
    )


def _free(_port: int) -> bool:
    return True


class TestTheBrokerDoorIsRequestedWhenTheBrokerRuns:
    """A3, A4 — the two shapes the launcher actually emits."""

    def test_broker_alone_asks_for_the_host_loopback_map(self):
        # A3. The common case: a stack with no mcp-remote server, launched with a broker.
        args = mounts._mcp_remote_pod_args([], "", port_free=_free, broker=True)
        assert args == ["--network", BROKER_ONLY]

    def test_broker_and_callback_compose_into_one_network_option(self):
        # A4. The exact string the #388 spike verified with both features live, in that order.
        args = mounts._mcp_remote_pod_args([_atlassian(PORT)], "", port_free=_free, broker=True)
        assert args[:2] == ["-p", f"127.0.0.1:{PORT}:{PORT}"]
        assert args[-2:] == ["--network", BROKER_AND_CALLBACK]

    def test_the_callback_option_is_not_lost_when_the_broker_joins(self):
        # The failure this pins: composing the broker option by REPLACING the network string, which
        # would silently take mcp-remote's OAuth callback down with it. Asserted as presence in the
        # composed value rather than by equality, so it survives a reordering.
        args = mounts._mcp_remote_pod_args([_atlassian(PORT)], "", port_free=_free, broker=True)
        net = args[args.index("--network") + 1]
        assert "--host-lo-to-ns-lo" in net
        assert f"--map-host-loopback,{BROKER_DOOR}" in net


class TestTheBrokerDoorIsAbsentWhenTheBrokerDoesNot:
    """A1, A2 — every existing caller keeps today's behaviour. N1's argv half."""

    def test_no_broker_no_publish_emits_nothing(self):
        assert mounts._mcp_remote_pod_args([], "", port_free=_free) == []

    def test_no_broker_with_publish_is_unchanged(self):
        args = mounts._mcp_remote_pod_args([_atlassian(PORT)], "", port_free=_free)
        assert args == ["-p", f"127.0.0.1:{PORT}:{PORT}", "--network", "pasta:--host-lo-to-ns-lo"]

    def test_the_door_never_appears_without_a_broker(self):
        # The converse of A3: handing every stack in the catalog a route to the host's loopback
        # when nothing is listening there would be a silent widening of the pod's reach.
        for servers in ([], [_atlassian()], [_atlassian(PORT)]):
            args = mounts._mcp_remote_pod_args(servers, "", port_free=_free)
            assert not any(BROKER_DOOR in a for a in args), servers


class TestNetworkIsNeverPassedTwice:
    """A5 — `podman pod create` takes one `--network`; two is a hard launch failure.

    This is the invariant the composition exists to hold, so it is asserted over the whole space
    rather than at the two points that happen to be interesting.
    """

    @pytest.mark.parametrize("broker", [False, True])
    @pytest.mark.parametrize("net", ["", "mynet"])
    @pytest.mark.parametrize("servers", [[], [_atlassian()], [_atlassian(PORT)]])
    def test_at_most_one_network_option(self, broker, net, servers, capsys):
        args = mounts._mcp_remote_pod_args(servers, net, port_free=_free, broker=broker)
        capsys.readouterr()
        assert args.count("--network") <= 1, (broker, net, servers, args)

    @pytest.mark.parametrize("broker", [False, True])
    @pytest.mark.parametrize("net", ["", "mynet"])
    @pytest.mark.parametrize("servers", [[], [_atlassian()], [_atlassian(PORT)]])
    def test_pasta_options_are_never_split_across_two_values(self, broker, net, servers, capsys):
        """Both pasta options must ride one `pasta:` value. Emitting `pasta:--a` and `pasta:--b`
        would count as one `--network` each and still be rejected by podman."""
        args = mounts._mcp_remote_pod_args(servers, net, port_free=_free, broker=broker)
        capsys.readouterr()
        assert len([a for a in args if a.startswith("pasta:")]) <= 1, (broker, net, servers, args)


class TestAnExplicitNetworkWins:
    """A6 — the operator asked for a network; say what it costs rather than overriding them."""

    def test_harnessed_net_suppresses_the_broker_door(self):
        args = mounts._mcp_remote_pod_args([], "mynet", port_free=_free, broker=True)
        assert args == ["--network", "mynet"]

    def test_and_says_the_broker_will_be_unreachable(self, capsys):
        # Silence here is the bad outcome: the broker starts, the pod cannot reach it, and the
        # failure surfaces later as an unexplained proxy timeout.
        mounts._mcp_remote_pod_args([], "mynet", port_free=_free, broker=True)
        err = capsys.readouterr().err
        assert err, _CAPTURE_PROOF
        assert BROKER_DOOR in err

    def test_the_warning_names_no_secret_and_no_value(self, capsys):
        # N4 in miniature: this helper never sees a resolved value, and must never learn to.
        # `readouterr` is called exactly once per test: a second read returns empty and would
        # turn every assertion after it into a vacuous one.
        mounts._mcp_remote_pod_args([], "mynet", port_free=_free, broker=True)
        err = capsys.readouterr().err
        assert err, _CAPTURE_PROOF
        assert "vlk_ph_" not in err
        assert "token" not in err.lower()
