"""Tests for `_omp_config_seed_mount` — removing stale local bridge paths for omp pods."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from harnessed import launcher


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


def _load_yaml(path: Path):
    return YAML().load(path.read_text(encoding="utf-8"))


def test_non_omp_harness_is_noop(home):
    assert launcher._omp_config_seed_mount("claude", "inst") == []
    assert launcher._omp_config_seed_mount("opencode", "inst") == []


def test_missing_host_config_is_noop(home):
    assert launcher._omp_config_seed_mount("omp", "inst") == []


def test_no_legacy_bridge_entry_is_noop(home):
    config = home / ".omp" / "agent" / "config.yml"
    config.write_text("extensions:\n  - ~/other-extension\nmodel: test\n", encoding="utf-8")

    assert launcher._omp_config_seed_mount("omp", "inst") == []


def test_removes_legacy_bridge_entry_and_preserves_other_config(home):
    config = home / ".omp" / "agent" / "config.yml"
    config.write_text(
        "extensions:\n"
        "  - ~/Programming/AI/omp-extensions/claude-hooks-bridge\n"
        "  - ~/Programming/AI/omp-extensions/other\n"
        "model: test-model\n",
        encoding="utf-8",
    )

    args = launcher._omp_config_seed_mount("omp", "inst")
    src, dest_mode = _parse(args)

    assert dest_mode == f"{launcher._CONTAINER_HOME_STR}/.omp/agent/config.yml:ro"
    seeded = _load_yaml(src)
    assert seeded == {
        "extensions": ["~/Programming/AI/omp-extensions/other"],
        "model": "test-model",
    }
    assert config.read_text(encoding="utf-8").count("claude-hooks-bridge") == 1


def test_removes_empty_extensions_key_when_only_legacy_bridge_was_configured(home):
    config = home / ".omp" / "agent" / "config.yml"
    config.write_text(
        "extensions:\n  - /home/mcrowe/Programming/AI/omp-extensions/claude-hooks-bridge/\n",
        encoding="utf-8",
    )

    args = launcher._omp_config_seed_mount("omp", "inst")
    src, _ = _parse(args)

    assert _load_yaml(src) == {}


def test_malformed_host_config_is_tolerated(home):
    config = home / ".omp" / "agent" / "config.yml"
    config.write_text("extensions: [", encoding="utf-8")

    assert launcher._omp_config_seed_mount("omp", "inst") == []
