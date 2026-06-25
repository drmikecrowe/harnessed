"""Tests for paths.py resolver (B6 — single source of truth)."""

import os
from pathlib import Path

import pytest

from harnessed import paths


class TestProfileDir:
    def test_uses_xdg_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.profile_dir("my-stack") == tmp_path / "harnessed" / "profiles" / "my-stack"

    def test_falls_back_to_local_share(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        home = Path.home()
        assert paths.profile_dir("my-stack") == home / ".local" / "share" / "harnessed" / "profiles" / "my-stack"

    def test_different_stacks_different_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.profile_dir("a") != paths.profile_dir("b")


class TestIsBuilt:
    def test_missing_profile_not_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert not paths.is_built("nonexistent")

    def test_profile_with_mcp_json_is_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        prof = paths.profile_dir("my-stack")
        prof.mkdir(parents=True)
        (prof / ".mcp.json").write_text('{"mcpServers":{}}')
        assert paths.is_built("my-stack")

    def test_profile_without_mcp_json_not_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        prof = paths.profile_dir("my-stack")
        prof.mkdir(parents=True)
        # No .mcp.json — profile dir exists but not "built"
        assert not paths.is_built("my-stack")


class TestInstanceName:
    def test_stable_for_same_inputs(self):
        a = paths.instance_name("my-stack", "/home/user/project")
        b = paths.instance_name("my-stack", "/home/user/project")
        assert a == b

    def test_format_matches_pattern(self):
        name = paths.instance_name("tracer-time", "/home/user/myproject")
        assert name.startswith("harnessed-tracer-time-")
        assert len(name.split("-")[-1]) == 8

    def test_different_projects_different_names(self):
        a = paths.instance_name("stack", "/home/user/proj-a")
        b = paths.instance_name("stack", "/home/user/proj-b")
        assert a != b

    def test_different_stacks_different_names(self):
        a = paths.instance_name("stack-a", "/home/user/proj")
        b = paths.instance_name("stack-b", "/home/user/proj")
        assert a != b

    def test_trailing_slash_stripped(self):
        a = paths.instance_name("stack", "/home/user/project")
        b = paths.instance_name("stack", "/home/user/project/")
        assert a == b


class TestProjectRelpath:
    def test_path_under_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        p = tmp_path / "Programming" / "myproject"
        assert paths.project_relpath(p) == "Programming/myproject"

    def test_path_outside_home_uses_basename(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home" / "user")
        p = Path("/opt/projects/myproject")
        assert paths.project_relpath(p) == "myproject"


class TestContainerPaths:
    def test_mcp_config_at_container_home_root(self):
        p = paths.container_mcp_config()
        assert p == Path("/home/harnessed/.mcp.json")

    def test_hatago_config_at_container_home(self):
        p = paths.hatago_config_container()
        assert p == Path("/home/harnessed/hatago.config.json")
