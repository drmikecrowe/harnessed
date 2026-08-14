"""`hub_transport:` — how the harness reaches the hatago hub, and why stdio exists.

The failure this field removes is not a crash. With the hub on `type: http`, Claude Code classifies
it as a REMOTE server, so authenticating runs OAuth discovery and Dynamic Client Registration
against a hub that implements neither — observed as
`SDK auth failed: Dynamic Client Registration rejected (HTTP 404)` — while the prompt that actually
needed answering (mcp-remote's `Please authorize this client by visiting: <url>`) went to
/tmp/hatago.log, where no human was looking. Under stdio neither happens: there is no remote-auth
path to attempt, and the child's stderr reaches the harness.

So these tests assert the two SHAPES and the places that must agree about them. Each of the four
readers below infers the transport independently, and any pair disagreeing produces a stack that
looks configured and has no tools:

    schema      parses and validates the declaration
    emit        writes the .mcp.json the harness reads
    launcher    decides whether to wait for a hub, and tells the entrypoint
    entrypoint  decides whether to start one
"""

import json
import re
from pathlib import Path

import pytest

from harnessed import paths
from harnessed.emit import HATAGO_ENDPOINT, HATAGO_MCP_KEY, HATAGO_STDIO_COMMAND, write_mcp_json
from harnessed.schema import (
    HUB_TRANSPORT_HTTP,
    HUB_TRANSPORT_STDIO,
    SchemaError,
    Stack,
)


def _entry(profile_dir: Path) -> dict:
    """The single hub entry from an emitted .mcp.json."""
    data = json.loads((profile_dir / ".mcp.json").read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert list(servers) == [HATAGO_MCP_KEY], f"expected exactly one hub entry, got {list(servers)}"
    return servers[HATAGO_MCP_KEY]


class TestTheDeclarationIsParsedAndValidated:
    def test_a_stack_that_says_nothing_stays_on_http(self):
        """The default is load-bearing: flipping it would change every existing stack at once."""
        assert Stack(name="s").hub_transport == HUB_TRANSPORT_HTTP

    @pytest.mark.parametrize("value", [HUB_TRANSPORT_HTTP, HUB_TRANSPORT_STDIO])
    def test_both_transports_round_trip(self, value, tmp_path):
        from harnessed.schema import _parse_hub_transport
        assert _parse_hub_transport(value, tmp_path / "stack.yaml") == value

    @pytest.mark.parametrize("value", ["STDIO", "sse", "https", "stdio ", "", 1, True, ["stdio"]])
    def test_anything_else_is_an_error_rather_than_a_silent_default(self, value, tmp_path):
        """Stack parsing is otherwise tolerant of unknown fields (D-14), and that tolerance would be
        actively harmful here. A typo'd value falling back to `http` produces no config error — it
        produces the DCR 404 and the invisible prompt, i.e. exactly the symptom the author set this
        field to avoid, with nothing anywhere naming the cause."""
        from harnessed.schema import _parse_hub_transport
        with pytest.raises(SchemaError) as exc:
            _parse_hub_transport(value, tmp_path / "stack.yaml")
        assert "hub_transport" in str(exc.value)

    def test_the_error_names_what_is_allowed(self, tmp_path):
        """A rejection that does not say what would be accepted just moves the guessing."""
        from harnessed.schema import _parse_hub_transport
        with pytest.raises(SchemaError) as exc:
            _parse_hub_transport("htp", tmp_path / "stack.yaml")
        msg = str(exc.value)
        assert HUB_TRANSPORT_HTTP in msg and HUB_TRANSPORT_STDIO in msg


class TestTheEmittedConfigMatchesTheDeclaration:
    """The guard: whatever the stack declared is what the harness is handed. These two shapes are
    mutually exclusive — Claude Code infers stdio from `command` and http from `type`/`url`, so an
    entry carrying keys from both is not a hybrid, it is undefined behaviour."""

    def test_http_points_at_the_running_hub(self, tmp_path):
        write_mcp_json(tmp_path, HUB_TRANSPORT_HTTP)
        assert _entry(tmp_path) == {"type": "http", "url": HATAGO_ENDPOINT}

    def test_http_is_still_what_a_caller_gets_by_default(self, tmp_path):
        """Pinned separately from the parametrised case: the default is what every stack that never
        heard of this field receives, and it must not move when the signature does."""
        write_mcp_json(tmp_path)
        assert _entry(tmp_path) == {"type": "http", "url": HATAGO_ENDPOINT}

    def test_stdio_spawns_the_hub_instead_of_dialling_it(self, tmp_path):
        write_mcp_json(tmp_path, HUB_TRANSPORT_STDIO)
        entry = _entry(tmp_path)
        assert entry["command"] == HATAGO_STDIO_COMMAND
        assert entry["args"] == [
            "serve", "--stdio", "--config", str(paths.hatago_config_container())
        ]

    def test_stdio_carries_no_url_or_type(self, tmp_path):
        """Asserted as an ABSENCE. A leftover `type: http` alongside `command` is the one shape that
        would put Claude Code back on the remote-auth path this field exists to leave."""
        write_mcp_json(tmp_path, HUB_TRANSPORT_STDIO)
        entry = _entry(tmp_path)
        assert "url" not in entry
        assert "type" not in entry

    def test_http_carries_no_command(self, tmp_path):
        """The mirror of the above, so neither shape can grow the other's keys unnoticed."""
        write_mcp_json(tmp_path, HUB_TRANSPORT_HTTP)
        entry = _entry(tmp_path)
        assert "command" not in entry
        assert "args" not in entry

    def test_the_stdio_config_path_is_where_the_launcher_mounts_it(self, tmp_path):
        """The `--config` argument is a CONTAINER path. Emitting a host path here would produce a
        hub that starts and finds no servers — an agent with no tools and no error."""
        write_mcp_json(tmp_path, HUB_TRANSPORT_STDIO)
        cfg = _entry(tmp_path)["args"][-1]
        assert cfg == str(paths.hatago_config_container())
        assert cfg.startswith(str(paths.CONTAINER_HOME))


class TestOnlyAHarnessWhoseWiringIsEmittedMayDeclareStdio:
    """codex bakes `[mcp_servers.hatago]` with a URL into its IMAGE; only claude's entry is written
    per stack. Assembling stdio for a baked harness yields a harness still dialling HTTP while the
    entrypoint starts no hub — tools silently absent. Refused at build time instead."""

    def test_claude_may(self):
        from harnessed.assemble import _validate_hub_transport
        _validate_hub_transport(Stack(name="s", hub_transport=HUB_TRANSPORT_STDIO), "claude")

    @pytest.mark.parametrize("harness", ["codex", "omp", "opencode", "antigravity"])
    def test_a_baked_harness_may_not(self, harness):
        from harnessed.assemble import _validate_hub_transport
        with pytest.raises(SchemaError) as exc:
            _validate_hub_transport(Stack(name="s", hub_transport=HUB_TRANSPORT_STDIO), harness)
        assert harness in str(exc.value)

    @pytest.mark.parametrize("harness", ["claude", "codex", "omp"])
    def test_http_is_never_refused_for_anyone(self, harness):
        """The restriction belongs to stdio alone. Rejecting an http stack for a baked harness would
        break every stack that exists today."""
        from harnessed.assemble import _validate_hub_transport
        _validate_hub_transport(Stack(name="s", hub_transport=HUB_TRANSPORT_HTTP), harness)

    def test_the_refusal_offers_the_way_out(self):
        from harnessed.assemble import _validate_hub_transport
        with pytest.raises(SchemaError) as exc:
            _validate_hub_transport(Stack(name="s", hub_transport=HUB_TRANSPORT_STDIO), "codex")
        assert "hub_transport: http" in str(exc.value)


class TestTheTwoSchemasAgreeAboutWhatAStackMayDeclare:
    """`schemas/stack.schema.json` sets `additionalProperties: false`, so it is not documentation —
    it is a gate. A field added to the parser and not to the JSON schema makes every stack that uses
    it INVALID, and the failure lands on the stack author rather than on whoever added the field.
    Caught exactly that way while writing `hub_transport`.
    """

    # `hatago` is knowingly one-sided: the parser keeps it so `_reject_removed_hatago_override` can
    # explain what replaced it (bd harnessed-1t4.1), while the JSON schema simply refuses it.
    _PARSER_ONLY = frozenset({"hatago"})

    def _schema_properties(self) -> set:
        body = (paths.harnessed_home() / "schemas" / "stack.schema.json").read_text(encoding="utf-8")
        return set(json.loads(body)["properties"])

    def test_every_field_the_parser_accepts_is_permitted_by_the_json_schema(self):
        from harnessed.schema import KNOWN_STACK_FIELDS
        missing = (KNOWN_STACK_FIELDS - self._PARSER_ONLY) - self._schema_properties()
        assert not missing, (
            f"stack.schema.json rejects {sorted(missing)} — additionalProperties is false, so any "
            f"stack declaring one is invalid"
        )

    def test_the_json_schema_permits_nothing_the_parser_would_drop(self):
        from harnessed.schema import KNOWN_STACK_FIELDS
        extra = self._schema_properties() - KNOWN_STACK_FIELDS
        assert not extra, f"{sorted(extra)} validate but are silently ignored by the parser"

    def test_hub_transport_is_constrained_to_the_same_two_values(self):
        """Both gates must name the same set. A schema that allowed `sse` would pass validation and
        then die in the parser, which is a worse error than either alone."""
        prop = json.loads(
            (paths.harnessed_home() / "schemas" / "stack.schema.json").read_text(encoding="utf-8")
        )["properties"]["hub_transport"]
        assert set(prop["enum"]) == {HUB_TRANSPORT_HTTP, HUB_TRANSPORT_STDIO}
        assert prop["default"] == HUB_TRANSPORT_HTTP


class TestTheEntrypointAndTheLauncherAgree:
    """Two processes decide independently whether a hub exists: the entrypoint starts one, the
    launcher waits for one. Both read `Stack.hub_transport`. If they ever disagree the stack either
    waits out a timeout for a hub nobody started, or runs two hubs — and under stdio a second hub
    means a second copy of every child, which for mcp-remote is two processes contending for one
    lockfile and one callback port."""

    def _entrypoint(self) -> str:
        return (paths.harnessed_home() / "catalog" / "base" / "harnessed-start").read_text(
            encoding="utf-8"
        )

    def test_the_entrypoint_starts_a_hub_only_for_http(self):
        body = self._entrypoint()
        start = next(ln for ln in body.splitlines() if "hatago serve --http" in ln)
        guard = next(
            ln for ln in body.splitlines()
            if ln.startswith("if [") and "HATAGO_CFG" in ln
        )
        assert "HATAGO_TRANSPORT" in guard, (
            f"the hub start is not gated on the transport — every stdio stack would get a second "
            f"hub. Guard found: {guard}"
        )
        assert start, "the http start line vanished"

    def test_an_older_launcher_still_gets_a_hub(self):
        """Unset must mean http. The entrypoint is baked into the IMAGE and outlives the launcher
        that created any given container, so an image built from this commit has to keep working
        when something starts it without the variable."""
        body = self._entrypoint()
        assert re.search(r'HATAGO_TRANSPORT="\$\{HATAGO_TRANSPORT:-http\}"', body), (
            "no http fallback for an unset HATAGO_TRANSPORT"
        )

    def test_the_launcher_hands_the_transport_to_the_entrypoint(self):
        """The value the entrypoint branches on comes from the same field the emitter read, so the
        config and the process cannot drift."""
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        assert 'f"HATAGO_TRANSPORT={self.stk.hub_transport}"' in src

    def test_the_launcher_does_not_wait_for_a_hub_it_never_started(self):
        """Probing under stdio would burn the full timeout and then report a degraded hub — and in
        headless mode that is a hard exit. Correct configuration must not read as failure."""
        src = (paths.harnessed_home() / "src" / "harnessed" / "launcher.py").read_text(
            encoding="utf-8"
        )
        guard = re.search(
            r"if stk\.hub_transport == HUB_TRANSPORT_STDIO:\s*\n\s*hatago_up = True", src
        )
        assert guard, "_wait_hatago is not skipped for stdio stacks"
