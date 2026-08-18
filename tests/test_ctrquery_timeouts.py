"""Timeout behaviour for ctrquery.py — Issue #295.

Each podman predicate must return a safe sentinel value when podman hangs (rc=124 from _bounded)
rather than blocking indefinitely.  These tests verify the rc=124 fall-through in each of the five
public predicates.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from harnessed import ctrquery


# ---------------------------------------------------------------------------
# Helper: build a CompletedProcess that _bounded would return on timeout
# ---------------------------------------------------------------------------

def _timeout_result(*, text: bool = False) -> subprocess.CompletedProcess:
    """Simulate a _bounded timeout: rc=124, empty output."""
    stdout = "" if text else b""
    stderr = "" if text else b""
    return subprocess.CompletedProcess(args=[], returncode=124, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# rc=124 fall-through tests (spec scenarios)
# ---------------------------------------------------------------------------

class TestRc124FallThrough:
    """Each function must return a safe False / "" on timeout (rc=124) without raising."""

    def test_image_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery.subprocess.run", return_value=result):
            assert ctrquery._image_exists("podman", "myimage:latest") is False

    def test_container_running_timeout_returns_false(self):
        """rc=124 short-circuits at returncode==0 check => False."""
        result = _timeout_result(text=True)
        with patch("harnessed.ctrquery.subprocess.run", return_value=result):
            assert ctrquery._container_running("podman", "mycontainer") is False

    def test_container_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery.subprocess.run", return_value=result):
            assert ctrquery._container_exists("podman", "mycontainer") is False

    def test_pod_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery.subprocess.run", return_value=result):
            assert ctrquery._pod_exists("podman", "mypod") is False

    def test_inspect_id_timeout_returns_empty_string(self):
        """rc=124 => takes the else branch => ""."""
        result = _timeout_result(text=True)
        with patch("harnessed.ctrquery.subprocess.run", return_value=result):
            assert ctrquery._inspect_id("podman", "container", "mycontainer", "{{.Id}}") == ""


class TestTimeoutConstantPresent:
    """_PODMAN_QUERY_TIMEOUT must be defined in ctrquery and equal 30."""

    def test_constant_is_defined(self):
        assert hasattr(ctrquery, "_PODMAN_QUERY_TIMEOUT"), (
            "ctrquery._PODMAN_QUERY_TIMEOUT not found — Issue #295 requires this constant"
        )

    def test_constant_value_is_30(self):
        assert ctrquery._PODMAN_QUERY_TIMEOUT == 30


class TestBoundedIsUsed:
    """subprocess.run must NOT be called directly; _bounded must be used instead.

    These tests verify that the call dispatches through _bounded (which carries a timeout),
    rather than bare subprocess.run.  We do this by verifying that _bounded is called with
    a timeout= keyword argument, while a direct subprocess.run would not be.
    """

    @pytest.mark.parametrize("fn,args,kwargs", [
        ("_image_exists", ("podman", "myimage"), {}),
        ("_container_running", ("podman", "myname"), {}),
        ("_container_exists", ("podman", "myname"), {}),
        ("_pod_exists", ("podman", "mypod"), {}),
        ("_inspect_id", ("podman", "container", "myref", "{{.Id}}"), {}),
    ])
    def test_bounded_called_with_timeout(self, fn, args, kwargs):
        """Each ctrquery function must call _bounded (not subprocess.run) with timeout= set."""
        calls = []

        def _fake_bounded(cmd, *, timeout, warn=True, **kw):
            calls.append(timeout)
            text = kw.get("text", False)
            stdout = "" if text else b""
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr=stdout)

        with patch("harnessed.ctrquery._bounded", side_effect=_fake_bounded):
            getattr(ctrquery, fn)(*args, **kwargs)

        assert calls, f"ctrquery.{fn} did not call _bounded at all"
        assert all(t is not None and t > 0 for t in calls), (
            f"ctrquery.{fn} called _bounded without a real timeout: {calls}"
        )
