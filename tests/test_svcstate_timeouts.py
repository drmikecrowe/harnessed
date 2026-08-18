"""Timeout behaviour for svcstate.py — Issue #391.

The three direct subprocess callers (_svc_published_port, _repo_project_hashes,
_svc_stacks_from_instances) must return a safe sentinel when their _bounded call times out
(rc=124) rather than blocking indefinitely.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harnessed import svcstate


# ---------------------------------------------------------------------------
# Helper: build a CompletedProcess that _bounded would return on timeout
# ---------------------------------------------------------------------------


def _timeout_result(*, text: bool = True) -> subprocess.CompletedProcess:
    """Simulate a _bounded timeout: rc=124, empty output."""
    stdout = "" if text else b""
    stderr = "" if text else b""
    return subprocess.CompletedProcess(args=[], returncode=124, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Sentinel-return tests
# ---------------------------------------------------------------------------


class TestRc124FallThrough:
    """Each direct subprocess caller returns a safe value on timeout (rc=124) without raising."""

    def test_svc_published_port_timeout_returns_zero(self):
        """returncode != 0 => 0 (no port found)."""
        with patch("harnessed.svcstate._bounded", return_value=_timeout_result()):
            assert svcstate._svc_published_port("podman", "myctr", 3307) == 0

    def test_repo_project_hashes_timeout_returns_only_local_hash(self, tmp_path):
        """On git timeout the function returns only the local project hash, not sibling hashes."""
        fake_hash = "deadbeef"
        with (
            patch("harnessed.svcstate._bounded", return_value=_timeout_result()),
            patch("harnessed.svcstate.paths.project_hash", return_value=fake_hash),
        ):
            result = svcstate._repo_project_hashes(tmp_path)
        assert result == {fake_hash}

    def test_svc_stacks_from_instances_timeout_returns_empty_list(self):
        """returncode != 0 => []."""
        with patch("harnessed.svcstate._bounded", return_value=_timeout_result()):
            assert svcstate._svc_stacks_from_instances("podman", Path("/tmp")) == []


# ---------------------------------------------------------------------------
# Constant presence
# ---------------------------------------------------------------------------


class TestTimeoutConstantPresent:
    def test_constant_is_defined(self):
        assert hasattr(svcstate, "_PODMAN_QUERY_TIMEOUT")

    def test_constant_value_is_30(self):
        assert svcstate._PODMAN_QUERY_TIMEOUT == 30

    def test_svcstate_is_in_audit(self):
        """svcstate.py must be in the audit tuple; dropping it would let a future bare
        subprocess.run() in svcstate go undetected.
        """
        from tests.test_subprocess_timeout_audit import _AUDITED  # type: ignore[import]

        assert "svcstate.py" in _AUDITED


# ---------------------------------------------------------------------------
# _bounded is called with timeout= for each call site
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn, args, kwargs",
    [
        (
            svcstate._svc_published_port,
            ("podman", "myctr", 3307),
            {},
        ),
        (
            svcstate._svc_stacks_from_instances,
            ("podman", Path("/tmp")),
            {},
        ),
    ],
)
class TestBoundedIsUsedForPodman:
    def test_bounded_called_with_timeout(self, fn, args, kwargs):
        recorded = {}

        def _fake_bounded(cmd, *, timeout, warn=True, **kw):
            recorded["timeout"] = timeout
            wants_str = bool(kw.get("text") or kw.get("encoding"))
            empty = "" if wants_str else b""
            return subprocess.CompletedProcess(args=cmd, returncode=124, stdout=empty, stderr=empty)

        with patch("harnessed.svcstate._bounded", side_effect=_fake_bounded):
            fn(*args, **kwargs)

        assert "timeout" in recorded
        assert recorded["timeout"] == svcstate._PODMAN_QUERY_TIMEOUT


class TestBoundedIsUsedForGit:
    """Separate parametrize because _repo_project_hashes needs paths.project_hash mocked."""

    def test_bounded_called_with_timeout(self, tmp_path):
        recorded = {}

        def _fake_bounded(cmd, *, timeout, warn=True, **kw):
            recorded["timeout"] = timeout
            return subprocess.CompletedProcess(args=cmd, returncode=124, stdout="", stderr="")

        with (
            patch("harnessed.svcstate._bounded", side_effect=_fake_bounded),
            patch("harnessed.svcstate.paths.project_hash", return_value="deadbeef"),
        ):
            svcstate._repo_project_hashes(tmp_path)

        assert "timeout" in recorded
        assert recorded["timeout"] == svcstate._PODMAN_QUERY_TIMEOUT
