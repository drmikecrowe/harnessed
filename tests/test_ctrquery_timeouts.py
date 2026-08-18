"""Timeout behaviour for ctrquery.py — Issue #295.

The five direct podman callers (_image_exists, _container_running, _container_exists, _pod_exists,
_inspect_id) must return a safe sentinel (False or "") when podman hangs (rc=124 from _bounded)
rather than blocking indefinitely.  _stopped_leftover and _container_stale compose these five and
return False by induction — they carry no direct subprocess.run calls.
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
    """Each direct podman caller returns False or "" on timeout (rc=124) without raising.

    We patch _bounded directly (ctrquery no longer calls subprocess.run) and return
    the rc=124 CompletedProcess that _bounded produces on timeout.  _stopped_leftover and
    _container_stale are not tested here because they compose the five functions below —
    their safe behavior follows by induction.
    """

    def test_image_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery._bounded", return_value=result):
            assert ctrquery._image_exists("podman", "myimage:latest") is False

    def test_container_running_timeout_returns_false(self):
        """rc=124 short-circuits at returncode==0 check => False."""
        result = _timeout_result(text=True)
        with patch("harnessed.ctrquery._bounded", return_value=result):
            assert ctrquery._container_running("podman", "mycontainer") is False

    def test_container_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery._bounded", return_value=result):
            assert ctrquery._container_exists("podman", "mycontainer") is False

    def test_pod_exists_timeout_returns_false(self):
        """rc=124 => returncode != 0 => False."""
        result = _timeout_result()
        with patch("harnessed.ctrquery._bounded", return_value=result):
            assert ctrquery._pod_exists("podman", "mypod") is False

    def test_inspect_id_timeout_returns_empty_string(self):
        """rc=124 => takes the else branch => ""."""
        result = _timeout_result(text=True)
        with patch("harnessed.ctrquery._bounded", return_value=result):
            assert ctrquery._inspect_id("podman", "container", "mycontainer", "{{.Id}}") == ""

    def test_inspect_id_success_returns_stdout(self):
        """rc=0 => returns stdout.strip() — validates the branch is not inverted."""
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="sha256:abc123\n", stderr=""
        )
        with patch("harnessed.ctrquery._bounded", return_value=result):
            val = ctrquery._inspect_id("podman", "container", "mycontainer", "{{.Id}}")
        assert val == "sha256:abc123", f"expected stripped stdout, got {val!r}"


class TestTimeoutConstantPresent:
    """_PODMAN_QUERY_TIMEOUT must be defined in ctrquery and equal 30."""

    def test_constant_is_defined(self):
        assert hasattr(ctrquery, "_PODMAN_QUERY_TIMEOUT"), (
            "ctrquery._PODMAN_QUERY_TIMEOUT not found — Issue #295 requires this constant"
        )

    def test_constant_value_is_30(self):
        assert ctrquery._PODMAN_QUERY_TIMEOUT == 30

    def test_ctrquery_is_in_audit(self):
        """ctrquery.py must appear in _AUDITED so the audit catches future unbounded calls there.

        This test guards against silently dropping the audit coverage: removing 'ctrquery.py'
        from _AUDITED would let a future bare subprocess.run() in ctrquery go undetected.
        """
        from tests.test_subprocess_timeout_audit import _AUDITED  # type: ignore[import]

        assert "ctrquery.py" in _AUDITED, (
            "'ctrquery.py' was removed from _AUDITED in test_subprocess_timeout_audit.py — "
            "Issue #295 requires it to be audited for unbounded subprocess calls."
        )


class TestBoundedIsUsed:
    """subprocess.run must NOT be called directly; _bounded must be used instead.

    These tests verify that the call dispatches through _bounded (which carries a timeout),
    rather than bare subprocess.run.  We do this by verifying that _bounded is called with
    a timeout= keyword argument, while a direct subprocess.run would not be.
    """

    @pytest.mark.parametrize(
        "fn,args,kwargs",
        [
            ("_image_exists", ("podman", "myimage"), {}),
            ("_container_running", ("podman", "myname"), {}),
            ("_container_exists", ("podman", "myname"), {}),
            ("_pod_exists", ("podman", "mypod"), {}),
            ("_inspect_id", ("podman", "container", "myref", "{{.Id}}"), {}),
        ],
    )
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
