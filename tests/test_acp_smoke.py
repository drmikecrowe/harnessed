"""GH-571 S8 — `tools/acp-smoke.py` drives `host-acp` too, and `container-acp` exactly as before.

Only the argv is tested here: the smoke script itself starts a real agent, which is its job and not
a unit test's. Loaded by path because the file name has a hyphen.
"""
from __future__ import annotations

import importlib.util
import json
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



import os
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



@pytest.mark.parametrize(("reply", "ok"), [
    ("/srv/my project/a", True),
    ("`/srv/my project/a`", True),
    ("The working directory is /srv/my project/a.", True),
    ("/srv/my project/a-b", False),
    ("/srv/my project", False),
])
def test_round3_the_cwd_check_matches_a_path_with_a_space(reply, ok):
    """Adversary round 3 hunch 5: splitting on whitespace meant a folder with a space never matched."""
    assert smoke._cwd_matches(reply, Path("/srv/my project/a")) is ok



@pytest.mark.parametrize(("reply", "ok"), [
    ("(/a/b)", True),
    ("/a/b!", True),
    ("The cwd is (/a/b).", True),
    ("[/a/b]", True),
    ("</a/b>", True),
    ("/a/b - that is it", True),
    ("/a/b.txt", False),
    ("/a/b-check", False),
    ("/a/b_2", False),
    ("(/srv/my project/a)", False),
])
def test_pr572_the_cwd_check_allows_brackets_and_punctuation(reply, ok):
    """PR #572 review, third run: `(/a/b)` and `/a/b!` were rejected, so a correct agent reply could
    fail the smoke run. A file in the folder (`/a/b.txt`) still must not count as the folder."""
    assert smoke._cwd_matches(reply, Path("/a/b")) is ok


def test_pr572_a_launch_that_fails_to_start_leaves_no_launch_folder(tmp_path):
    """PR #572 review, fourth run: when the harnessed command cannot start, the launch folder made
    before the run's `try` was never removed."""
    project = tmp_path / "proj"
    project.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(project), "--stack", "s", "--verb", "host-acp",
         "--harnessed", str(tmp_path / "no-such-harnessed")],
        capture_output=True, text=True, timeout=60, env={**os.environ, "TMPDIR": str(temp)},
    )
    assert proc.returncode != 0
    assert "FAIL" in proc.stderr
    assert list(temp.iterdir()) == [], "the failed launch left its launch folder behind"


# GH-566 S7: `--no-path` runs container-acp the way an editor does, and a drift line fails the run.

_FAKE_PROXY = r"""
import json, os, sys
json.dump({"cwd": os.getcwd(), "argv": sys.argv[2:]}, open(sys.argv[1], "w"))
if os.environ.get("FAKE_DRIFT"):
    print("harnessed: ACP initialize drift: omp: agentCapabilities", file=sys.stderr, flush=True)
for raw in sys.stdin:
    m = json.loads(raw)
    result = {"sessionId": "s0"} if m["method"] == "session/new" else {"protocolVersion": 1}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}) + "\n")
    sys.stdout.flush()
"""


def _run_smoke(tmp_path, *extra, env=None):
    fake = tmp_path / "fake_proxy.py"
    fake.write_text(_FAKE_PROXY)
    record = tmp_path / "record.json"
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), str(project), "--stack", "s",
         "--harnessed", f"{sys.executable} {fake} {record} --", *extra],
        capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})},
    )
    return proc, record, project


def test_s7_1_no_path_container_acp_argv_names_no_project():
    argv = smoke._launch_argv("uv run harnessed", "container-acp", "omp", Path("/p/proj"), "s", no_path=True)
    assert argv == ["uv", "run", "harnessed", "container-acp", "omp", "--stack", "s"]


def test_s7_1_no_path_starts_in_a_fresh_folder_and_sends_the_project_as_cwd(tmp_path):
    proc, record, project = _run_smoke(tmp_path, "--no-path")
    assert proc.returncode == 0, proc.stderr
    seen = json.loads(record.read_text())
    assert str(project) not in seen["argv"]
    assert Path(seen["cwd"]).name.startswith("acp-smoke-launch-")
    assert not Path(seen["cwd"]).exists(), "the smoke run left its launch folder behind"


def test_s7_4_no_path_with_host_acp_is_a_usage_error(tmp_path):
    proc, record, _ = _run_smoke(tmp_path, "--no-path", "--verb", "host-acp")
    assert proc.returncode == 2
    assert "--no-path applies to container-acp only" in proc.stderr
    assert not record.exists(), "nothing may launch on a usage error"


def test_s5_3_a_drift_line_fails_the_run(tmp_path):
    proc, _, _ = _run_smoke(tmp_path, "--no-path", env={"FAKE_DRIFT": "1"})
    assert proc.returncode != 0
    assert "FAIL" in proc.stderr and "ACP initialize drift" in proc.stderr


def test_s5_3_stderr_still_reaches_the_terminal(tmp_path):
    proc, _, _ = _run_smoke(tmp_path, "--no-path")
    assert "PASS" in proc.stderr
