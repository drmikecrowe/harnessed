"""GH-571 S8 — `tools/acp-smoke.py` drives `host-acp` too, and `container-acp` exactly as before.

Only the argv is tested here: the smoke script itself starts a real agent, which is its job and not
a unit test's. Loaded by path because the file name has a hyphen.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "acp-smoke.py"
_spec = importlib.util.spec_from_file_location("acp_smoke", _SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def test_s8_3_container_acp_argv_is_unchanged():
    argv = smoke._launch_argv("uv run harnessed", "container-acp", "omp", Path("/p/proj"), "s")
    assert argv == ["uv", "run", "harnessed", "container-acp", "omp", "/p/proj", "--stack", "s"]


def test_s8_host_acp_argv_names_no_project():
    argv = smoke._launch_argv("uv run harnessed", "host-acp", "claude", Path("/p/proj"), "s")
    assert argv == ["uv", "run", "harnessed", "host-acp", "claude", "--stack", "s"]


def test_s8_the_default_verb_is_container_acp():
    args = smoke._parser().parse_args(["/p/proj", "--stack", "s"])
    assert args.verb == "container-acp"
    assert args.check_cwd is None
