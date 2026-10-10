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



import subprocess
import sys

import pytest


@pytest.mark.parametrize(("reply", "ok"), [
    ("/a/b", True),
    ("`/a/b`", True),
    ("The working directory is /a/b.", True),
    ("/a/b-check", False),
    ("/a/b/c", False),
    ("/a", False),
])
def test_pr572_the_cwd_check_matches_a_whole_path(reply, ok):
    """PR #572 review comment 3: a substring test passed `/a/b-check` for `/a/b`."""
    assert smoke._cwd_matches(reply, Path("/a/b")) is ok


_FAKE_HARNESSED = r"""
import json, os, sys
open(sys.argv[1], "w").write(os.getcwd())
for raw in sys.stdin:
    m = json.loads(raw)
    result = {"sessionId": "s0"} if m["method"] == "session/new" else {"protocolVersion": 1}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}) + "\n")
    sys.stdout.flush()
"""


def test_pr572_the_launch_folder_is_removed_after_a_run(tmp_path):
    """PR #572 review comment 4: every host-acp smoke run left an acp-smoke-launch-* folder."""
    fake = tmp_path / "fake_harnessed.py"
    fake.write_text(_FAKE_HARNESSED)
    where = tmp_path / "launched-in"
    project = tmp_path / "proj"
    project.mkdir()
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(project), "--stack", "s", "--verb", "host-acp",
         "--harnessed", f"{sys.executable} {fake} {where} --"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    launch_dir = Path(where.read_text())
    assert launch_dir.name.startswith("acp-smoke-launch-")
    assert not launch_dir.exists(), "the smoke run left its launch folder behind"
