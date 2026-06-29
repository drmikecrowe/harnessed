"""Tests for emit.py — profile artifact emission (C1)."""

import json
from pathlib import Path

from harnessed.emit import (
    HATAGO_ENDPOINT,
    HATAGO_MCP_KEY,
    merge_settings,
    read_baked_settings,
    required_settings,
    write_mcp_json,
    write_settings_json,
    write_hatago_config,
    write_baked_manifest,
    write_derived_dockerfile,
)
from harnessed.schema import McpServer, Stack

_GRANT = f"mcp__{HATAGO_MCP_KEY}"
_REQUIRED = {"permissions": {"allow": [_GRANT]}}


class TestWriteDerivedDockerfile:
    def _stack(self):
        return Stack(name="claude_time", harness="claude", recipes=["time"], services=[])

    def test_appends_supply_chain_scan_run_by_default(self, tmp_path):
        out = write_derived_dockerfile(tmp_path, self._stack(), [])
        body = out.read_text()
        assert "FROM harnessed-${HARNESS}:latest" in body
        # The final supply-chain layer (BLD-02) runs even when no recipe ships a Dockerfile.
        assert "harnessed-scan" in body
        assert "--mount=type=secret,id=snyk_token" in body

    def test_no_scan_when_disabled(self, tmp_path):
        out = write_derived_dockerfile(tmp_path, self._stack(), [], with_scan=False)
        assert "harnessed-scan" not in out.read_text()


class TestWriteMcpJson:
    def test_creates_mcp_json_at_profile_root(self, tmp_path):
        out = write_mcp_json(tmp_path)
        assert out == tmp_path / ".mcp.json"
        assert out.is_file()

    def test_content_has_single_hatago_entry(self, tmp_path):
        write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        servers = data["mcpServers"]
        assert HATAGO_MCP_KEY in servers
        assert len(servers) == 1

    def test_entry_has_http_type(self, tmp_path):
        write_mcp_json(tmp_path)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        entry = data["mcpServers"][HATAGO_MCP_KEY]
        assert entry["type"] == "http"
        assert entry["url"] == HATAGO_ENDPOINT

    def test_output_is_at_root_not_claude_subdir(self, tmp_path):
        out = write_mcp_json(tmp_path)
        # Must be profile_dir/.mcp.json, NOT profile_dir/.claude/.mcp.json
        assert ".claude" not in str(out)


class TestWriteSettingsJson:
    def test_no_servers_writes_empty_settings(self, tmp_path):
        out = write_settings_json(tmp_path, [])
        data = json.loads(out.read_text())
        assert data == {}

    def test_with_servers_pre_approves_hatago(self, tmp_path):
        servers = [McpServer(name="time", command="pnpm")]
        out = write_settings_json(tmp_path, servers)
        data = json.loads(out.read_text())
        assert f"mcp__{HATAGO_MCP_KEY}" in data["permissions"]["allow"]


class TestWriteHatagoConfig:
    def test_stdio_server_gets_command_entry(self, tmp_path):
        servers = [McpServer(name="time", command="pnpm", args=["dlx", "@time/server"])]
        write_hatago_config(tmp_path, servers)
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        entry = data["mcpServers"]["time"]
        assert entry["command"] == "pnpm"
        assert entry["args"] == ["dlx", "@time/server"]

    def test_http_server_gets_url_entry(self, tmp_path):
        servers = [McpServer(name="remote", transport="http", url="http://localhost:8080/mcp")]
        write_hatago_config(tmp_path, servers)
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        entry = data["mcpServers"]["remote"]
        assert entry["url"] == "http://localhost:8080/mcp"
        assert entry["type"] == "http"

    def test_version_is_1(self, tmp_path):
        write_hatago_config(tmp_path, [])
        data = json.loads((tmp_path / "hatago.config.json").read_text())
        assert data["version"] == 1


class TestWriteBakedManifest:
    def test_baked_manifest_lists_stdio_servers(self, tmp_path):
        stack = Stack(name="my-stack", harness="claude")
        baked = [McpServer(name="time", command="pnpm", args=["dlx", "@time/server"], transport="stdio")]
        write_baked_manifest(tmp_path, stack, baked)
        data = json.loads((tmp_path / "baked-servers.json").read_text())
        assert data["stack"] == "my-stack"
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "time"


class TestRequiredSettings:
    """harnessed's sole settings contribution — the single source of truth shared by the
    assemble-time floor and the post-build merge."""

    def test_grant_when_servers(self):
        assert required_settings([McpServer(name="time", command="pnpm")]) == _REQUIRED

    def test_empty_when_no_servers(self):
        assert required_settings([]) == {}


class TestReadBakedSettings:
    def test_none_text_returns_none_silently(self):
        warns: list[str] = []
        assert read_baked_settings(None, warn=warns.append) is None
        assert warns == []  # absent file / cp failure is not a warning

    def test_valid_object_parses(self):
        assert read_baked_settings('{"hooks": {"PreToolUse": []}}') == {"hooks": {"PreToolUse": []}}

    def test_malformed_json_returns_none_and_warns(self):
        warns: list[str] = []
        assert read_baked_settings("{not json", warn=warns.append) is None
        assert len(warns) == 1  # a recipe wrote broken JSON — warn, do not crash

    def test_non_object_json_treated_as_malformed(self):
        warns: list[str] = []
        assert read_baked_settings("[1, 2, 3]", warn=warns.append) is None
        assert len(warns) == 1


class TestMergeSettings:
    """The surgical settings.json patch — baked file is authoritative; harnessed only unions its
    required grant into permissions.allow (and wins over a conflicting deny)."""

    def test_baked_none_returns_required_floor(self):
        # No image file / cp failed → the assemble-time floor stub stands.
        assert merge_settings(None, _REQUIRED) == _REQUIRED
        assert merge_settings(None, {}) == {}

    def test_empty_baked_gets_grant_only(self):
        assert merge_settings({}, _REQUIRED) == _REQUIRED

    def test_baked_hooks_preserved_and_grant_added(self):
        # REGRESSION proof: the bug was that baked hooks were silently dropped at runtime.
        baked = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_existing_allow_is_unioned(self):
        baked = {"permissions": {"allow": ["mcp__other"]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["permissions"]["allow"] == ["mcp__other", _GRANT]

    def test_grant_already_present_is_not_duplicated(self):
        baked = {"permissions": {"allow": [_GRANT]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_deny_conflict_required_wins_and_warns(self):
        warns: list[str] = []
        baked = {"permissions": {"deny": [_GRANT, "mcp__keep"]}}
        merged = merge_settings(baked, _REQUIRED, warn=warns.append)
        assert _GRANT in merged["permissions"]["allow"]
        assert merged["permissions"]["deny"] == ["mcp__keep"]  # only the conflicting grant stripped
        assert len(warns) == 1

    def test_no_grant_when_required_empty_baked_untouched(self):
        # Serverless stack (required == {}): the baked file is returned verbatim, no grant injected.
        baked = {"hooks": {"PreToolUse": []}, "permissions": {"allow": ["mcp__x"]}}
        assert merge_settings(baked, {}) == baked

    def test_other_keys_carried_through_verbatim(self):
        baked = {"model": "opus", "env": {"FOO": "bar"}, "permissions": {"deny": ["mcp__x"]}}
        merged = merge_settings(baked, _REQUIRED)
        assert merged["model"] == "opus"
        assert merged["env"] == {"FOO": "bar"}
        assert merged["permissions"]["deny"] == ["mcp__x"]  # untouched (not the grant)
        assert merged["permissions"]["allow"] == [_GRANT]

    def test_does_not_mutate_input(self):
        baked = {"permissions": {"allow": ["mcp__other"]}}
        merge_settings(baked, _REQUIRED)
        assert baked == {"permissions": {"allow": ["mcp__other"]}}  # deepcopy — caller's dict safe
