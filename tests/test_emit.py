"""Tests for emit.py — profile artifact emission (C1)."""

import json
from pathlib import Path

from harnessed.emit import (
    HATAGO_ENDPOINT,
    HATAGO_MCP_KEY,
    write_mcp_json,
    write_settings_json,
    write_hatago_config,
    write_baked_manifest,
    write_derived_dockerfile,
)
from harnessed.schema import McpServer, Stack


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
