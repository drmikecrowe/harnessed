"""Tests for `_omp_mcp_seed_mount` — wiring omp at the in-container hatago hub.

omp reads MCP servers only from ~/.omp/agent/mcp.json; harnessed must seed a per-instance copy with
the hatago endpoint added (and the host file preserved) and mount it ro over the shared file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessed import launcher, paths


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / ".omp" / "agent").mkdir(parents=True)
    return tmp_path


def _parse(mount_args: list[str]) -> tuple[Path, str]:
    assert mount_args[0] == "-v"
    src, dest, mode = mount_args[1].rsplit(":", 2)
    return Path(src), f"{dest}:{mode}"


def test_non_omp_harness_is_noop(home):
    assert launcher._omp_mcp_seed_mount("claude", "inst") == []
    assert launcher._omp_mcp_seed_mount("opencode", "inst") == []


def test_adds_hatago_and_preserves_host_servers(home):
    host_mcp = home / ".omp" / "agent" / "mcp.json"
    host_mcp.write_text(json.dumps({
        "$schema": "https://example/mcp-schema.json",
        "mcpServers": {"openbrain": {"type": "http", "url": "https://ob.example/mcp"}},
    }))

    args = launcher._omp_mcp_seed_mount("omp", "inst")
    src, dest_mode = _parse(args)

    # Mounted ro over the agent dir's mcp.json.
    assert dest_mode == f"{launcher._CONTAINER_HOME_STR}/.omp/agent/mcp.json:ro"
    cfg = json.loads(src.read_text())
    # Host entries + top-level keys preserved.
    assert cfg["$schema"] == "https://example/mcp-schema.json"
    assert cfg["mcpServers"]["openbrain"]["url"] == "https://ob.example/mcp"
    # hatago endpoint added.
    assert cfg["mcpServers"]["hatago"] == {"type": "http", "url": paths.hatago_endpoint()}


def test_no_host_file_seeds_hatago_only(home):
    args = launcher._omp_mcp_seed_mount("omp", "inst")
    src, _ = _parse(args)
    cfg = json.loads(src.read_text())
    assert cfg == {"mcpServers": {"hatago": {"type": "http", "url": paths.hatago_endpoint()}}}


def test_corrupt_host_file_is_tolerated(home):
    (home / ".omp" / "agent" / "mcp.json").write_text("{ not json")
    args = launcher._omp_mcp_seed_mount("omp", "inst")
    src, _ = _parse(args)
    cfg = json.loads(src.read_text())
    assert "hatago" in cfg["mcpServers"]


def test_seed_is_per_instance(home):
    a = launcher._omp_mcp_seed_mount("omp", "inst-a")
    b = launcher._omp_mcp_seed_mount("omp", "inst-b")
    assert _parse(a)[0] != _parse(b)[0]
    assert "inst-a" in str(_parse(a)[0]) and "inst-b" in str(_parse(b)[0])
