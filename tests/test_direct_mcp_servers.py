"""`direct:` — a server the harness connects to itself, bypassing the hatago hub.

WHY IT EXISTS. hatago has no OAuth client of its own (its published dist contains no `oauth`,
`client_id`, `code_verifier`, `/register` or `authorization_endpoint` at all), so an OAuth remote
behind the hub has to be reached through an mcp-remote shim — and that shim is a GRANDCHILD of the
harness, whose `Please authorize this client by visiting: <url>` lands on a stderr nobody reads.
A harness that speaks Streamable-HTTP with OAuth natively can just do it, and then the authorize
URL renders in its own UI.

WHY IT IS PER-SERVER AND OPT-IN. Going direct forfeits everything the hub adds for that server:
tool filtering, per-server `instructions`, `description`, `tags`. For a server whose value is a
curated subset that is a bad trade; for one the hub only adds a hop to, it is free. Only the recipe
knows which it is — and unlike `hub_transport`, which describes the ONE hub N recipes share, this
describes ONE server, so there is no merge to get wrong.

THE INVARIANT THAT MATTERS. Direct and hub are mutually exclusive. A server listed in both is
reachable by two routes, so its tools appear twice with nothing saying which copy answered.
"""

import json
from pathlib import Path

import pytest

from harnessed import emit, mounts
from harnessed.emit import HATAGO_MCP_KEY, write_hatago_config, write_mcp_json
from harnessed.schema import McpServer, SchemaError, _parse_servers

URL = "https://mcp.example.com/v1/mcp"
PORT = 32090


def _direct(
    name: str = "widgets", url: str = URL, port: int | None = PORT, **kw
) -> McpServer:
    return McpServer(
        name=name, transport="http", url=url, direct=True, oauth_callback_port=port, **kw
    )


def _hub_child(name="context-mode") -> McpServer:
    return McpServer(name=name, command="context-mode", args=[])


def _servers_of(profile: Path) -> dict:
    return json.loads((profile / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def _hatago_of(profile: Path) -> dict:
    return json.loads((profile / "hatago.config.json").read_text(encoding="utf-8"))["mcpServers"]


class TestTheRecipeDeclaresIt:
    def test_a_server_is_hub_routed_unless_it_says_otherwise(self):
        parsed = _parse_servers({"servers": [{"name": "a", "command": "x"}]})
        assert parsed[0].direct is False

    def test_direct_requires_somewhere_to_connect(self):
        """A direct server is addressed by URL. Without one there is nothing to emit, and the
        failure would otherwise surface as a harness starting with a malformed entry."""
        with pytest.raises(SchemaError) as exc:
            _parse_servers({"servers": [{"name": "a", "direct": True}]})
        assert "url" in str(exc.value)

    def test_url_env_satisfies_it(self):
        parsed = _parse_servers({"servers": [{"name": "a", "direct": True, "url_env": "A_URL"}]})
        assert parsed[0].direct is True

    def test_direct_and_service_are_mutually_exclusive(self):
        """`service:` resolves to a hatago proxy entry — precisely what direct bypasses."""
        with pytest.raises(SchemaError) as exc:
            _parse_servers({"servers": [{"name": "a", "direct": True, "service": "svc"}]})
        assert "mutually exclusive" in str(exc.value)

    def test_a_direct_server_is_not_a_hub_child(self):
        """`is_stdio_child` gates baking, the mcp-remote consent, and the argv-keyed pod publish.
        A direct server is not hatago's child at all, so none of those may pick it up — even if it
        somehow carries a command."""
        assert McpServer(name="a", command="x", url=URL, direct=True).is_stdio_child is False
        assert McpServer(name="a", command="x").is_stdio_child is True


class TestTheCallbackPortIsValidatedNotTrusted:
    def test_a_port_is_optional(self):
        parsed = _parse_servers({"servers": [{"name": "a", "direct": True, "url": URL}]})
        assert parsed[0].oauth_callback_port is None

    def test_a_valid_port_survives(self):
        parsed = _parse_servers(
            {"servers": [{"name": "a", "direct": True, "url": URL, "oauth": {"callback_port": 32090}}]}
        )
        assert parsed[0].oauth_callback_port == 32090

    @pytest.mark.parametrize("port", [80, 443, 1023, 0, -1, 65536, 99999])
    def test_a_port_the_pod_cannot_publish_is_refused(self, port):
        """Floor 1024: the pod is ROOTLESS, so publishing a privileged port fails at `pod create`
        and turns a recipe typo into a dead launch rather than an unpublished callback."""
        with pytest.raises(SchemaError):
            _parse_servers(
                {"servers": [{"name": "a", "direct": True, "url": URL,
                              "oauth": {"callback_port": port}}]}
            )

    @pytest.mark.parametrize("port", ["32090", 32090.5, True, None if False else [32090]])
    def test_a_non_integer_port_is_refused(self, port):
        """`True` included deliberately: it is an int in Python and a nonsense port everywhere."""
        with pytest.raises(SchemaError):
            _parse_servers(
                {"servers": [{"name": "a", "direct": True, "url": URL,
                              "oauth": {"callback_port": port}}]}
            )

    def test_a_port_on_a_hub_child_is_refused(self):
        """A hub child's callback port lives in its `args` — that is the only interface mcp-remote's
        CLI offers. Accepting it here would silently do nothing."""
        with pytest.raises(SchemaError) as exc:
            _parse_servers(
                {"servers": [{"name": "a", "command": "x", "oauth": {"callback_port": 32090}}]}
            )
        assert "direct" in str(exc.value)


class TestEachServerIsReachableByExactlyOneRoute:
    """The core invariant. Emitted into `.mcp.json` XOR `hatago.config.json`, never both."""

    def test_a_direct_server_reaches_the_harness_config(self, tmp_path):
        write_mcp_json(tmp_path, "http", [_direct()])
        assert "widgets" in _servers_of(tmp_path)

    def test_and_is_absent_from_the_hub_config(self, tmp_path):
        write_hatago_config(tmp_path, [_direct()])
        assert _hatago_of(tmp_path) == {}

    def test_a_hub_server_reaches_the_hub_config(self, tmp_path):
        write_hatago_config(tmp_path, [_hub_child()])
        assert "context-mode" in _hatago_of(tmp_path)

    def test_and_is_absent_from_the_harness_config(self, tmp_path):
        write_mcp_json(tmp_path, "http", [_hub_child()])
        assert list(_servers_of(tmp_path)) == [HATAGO_MCP_KEY]

    def test_a_mixed_stack_splits_cleanly(self, tmp_path):
        both = [_direct(), _hub_child()]
        write_mcp_json(tmp_path, "http", both)
        write_hatago_config(tmp_path, both)
        harness, hub = _servers_of(tmp_path), _hatago_of(tmp_path)
        assert set(harness) == {HATAGO_MCP_KEY, "widgets"}
        assert set(hub) == {"context-mode"}
        # The invariant, stated as an intersection rather than two separate memberships.
        assert not (set(harness) - {HATAGO_MCP_KEY}) & set(hub)

    def test_the_hub_entry_survives_alongside_a_direct_server(self, tmp_path):
        """Direct servers are ADDITIONAL. Losing the hub entry would strand every other recipe."""
        write_mcp_json(tmp_path, "http", [_direct()])
        assert _servers_of(tmp_path)[HATAGO_MCP_KEY] == {
            "type": "http", "url": emit.HATAGO_ENDPOINT
        }

    def test_a_direct_server_may_not_take_the_hubs_name(self, tmp_path):
        """Overwriting it would replace the hub with the direct server and quietly strand everything
        else the stack declares."""
        with pytest.raises(SchemaError) as exc:
            write_mcp_json(tmp_path, "http", [_direct(name=HATAGO_MCP_KEY)])
        assert "reserved" in str(exc.value)

    def test_no_direct_servers_leaves_the_file_exactly_as_before(self, tmp_path):
        """The default path must not move: every existing stack emits one entry."""
        write_mcp_json(tmp_path, "http", [_hub_child()])
        assert list(_servers_of(tmp_path)) == [HATAGO_MCP_KEY]


class TestTheEmittedEntryIsWhatTheHarnessReads:
    """The shape is Claude Code's, verified against what `claude mcp add --transport http
    --callback-port` actually writes — not inferred from the recipe's own spelling."""

    def test_it_carries_type_and_url(self, tmp_path):
        write_mcp_json(tmp_path, "http", [_direct()])
        entry = _servers_of(tmp_path)["widgets"]
        assert entry["type"] == "http"
        assert entry["url"] == URL

    def test_the_callback_port_is_camel_cased_for_the_harness(self, tmp_path):
        """`callback_port` in the recipe, `callbackPort` in the harness config. Two file formats,
        two conventions; emitting the recipe's spelling would be silently ignored."""
        write_mcp_json(tmp_path, "http", [_direct()])
        assert _servers_of(tmp_path)["widgets"]["oauth"] == {"callbackPort": PORT}

    def test_no_oauth_block_when_no_port_is_declared(self, tmp_path):
        write_mcp_json(tmp_path, "http", [_direct(port=None)])
        assert "oauth" not in _servers_of(tmp_path)["widgets"]

    def test_headers_are_carried_through(self, tmp_path):
        srv = _direct(headers={"X-Api-Key": "abc"})
        write_mcp_json(tmp_path, "http", [srv])
        assert _servers_of(tmp_path)["widgets"]["headers"] == {"X-Api-Key": "abc"}

    def test_the_entry_carries_no_command(self, tmp_path):
        """A direct server is never spawned. A stray `command` would make Claude Code treat it as
        stdio and ignore the URL entirely."""
        write_mcp_json(tmp_path, "http", [_direct()])
        assert "command" not in _servers_of(tmp_path)["widgets"]


class TestThePortIsPublishedWhicheverKindDeclaredIt:
    """A direct server declares `oauth.callback_port`; a hub child carries it in `args`. The pod
    does not care which — both are a loopback listener in a netns the browser is not in."""

    def test_a_direct_servers_port_is_published(self):
        args = mounts._mcp_remote_pod_args([_direct()], "", port_free=lambda _p: True)
        assert f"127.0.0.1:{PORT}:{PORT}" in args

    def test_it_comes_with_the_pasta_option(self):
        """Same coupling as mcp-remote's: a publish without `--host-lo-to-ns-lo` forwards past a
        loopback-bound listener and changes nothing, while looking correct in `pod inspect`."""
        args = mounts._mcp_remote_pod_args([_direct()], "", port_free=lambda _p: True)
        assert "pasta:--host-lo-to-ns-lo" in " ".join(args)

    def test_a_direct_server_without_a_port_publishes_nothing(self):
        args = mounts._mcp_remote_pod_args([_direct(port=None)], "", port_free=lambda _p: True)
        assert "-p" not in args

    def test_both_kinds_publish_together(self):
        mcp_remote = McpServer(
            name="atlassian", command="pnpm",
            args=["dlx", "@drmikecrowe/mcp-remote@0.1.38", "https://mcp.atlassian.com/x", "32081"],
        )
        args = mounts._mcp_remote_pod_args(
            [mcp_remote, _direct()], "", port_free=lambda _p: True
        )
        assert "127.0.0.1:32081:32081" in args
        assert f"127.0.0.1:{PORT}:{PORT}" in args

    def test_a_taken_port_is_skipped_not_fatal(self):
        args = mounts._mcp_remote_pod_args([_direct()], "", port_free=lambda _p: False)
        assert "-p" not in args

    def test_the_publish_is_loopback_only(self):
        """An OAuth callback listener has no business on the LAN."""
        args = mounts._mcp_remote_pod_args([_direct()], "", port_free=lambda _p: True)
        wildcard = "0.0.0." + "0"
        assert all(wildcard not in a for a in args)

    def test_a_stack_with_no_oauth_server_publishes_nothing(self):
        args = mounts._mcp_remote_pod_args([_hub_child()], "", port_free=lambda _p: True)
        assert "-p" not in args


class TestOnlyAHarnessWhoseConfigIsEmittedMayGoDirect:
    """Same boundary as `hub_transport: stdio`. codex and omp bake their MCP wiring into the IMAGE,
    so a direct server declared for one would be absent from the harness AND from the hub, which
    `direct` removed it from — configured in the recipe, reachable nowhere."""

    def test_claude_may(self):
        from harnessed.assemble import _validate_direct_servers
        _validate_direct_servers([_direct()], "claude")

    @pytest.mark.parametrize("harness", ["codex", "omp", "opencode", "antigravity"])
    def test_a_baked_harness_may_not(self, harness):
        from harnessed.assemble import _validate_direct_servers
        with pytest.raises(SchemaError) as exc:
            _validate_direct_servers([_direct()], harness)
        assert "widgets" in str(exc.value)

    @pytest.mark.parametrize("harness", ["claude", "codex", "omp"])
    def test_a_hub_only_stack_is_never_refused(self, harness):
        from harnessed.assemble import _validate_direct_servers
        _validate_direct_servers([_hub_child()], harness)
