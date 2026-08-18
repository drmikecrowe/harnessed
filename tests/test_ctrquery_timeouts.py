"""Timeout behaviour for ctrquery.py — Issue #295.

The five direct podman callers (_image_exists, _container_running, _container_exists, _pod_exists,
_inspect_id) must return a safe sentinel (False or "") when podman hangs (rc=124 from _bounded)
rather than blocking indefinitely.  _stopped_leftover and _container_stale carry no direct
subprocess.run calls; their composite timeout behaviour is pinned in TestCompositeTimeoutBehaviour.
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
    _container_stale are tested in TestCompositeTimeoutBehaviour below.
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
    """Each of the five direct callers invokes _bounded with a real timeout= value.

    These tests verify that _bounded is called (and receives a non-None, positive timeout).
    They do NOT assert that subprocess.run is never called — that guarantee is the audit test
    in test_subprocess_timeout_audit.py (test_no_unbounded_call_without_a_stated_reason).
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
        """_bounded is called with a positive timeout= value."""
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


class TestCompositeTimeoutBehaviour:
    """Pin the actual behaviour of _stopped_leftover and _container_stale under timeout.

    These are KNOWN LIMITS documented in EVIDENCE, not PASSED claims.  The tests exist to
    prevent silent regression — if the behaviour changes, these tests will catch it.
    """

    def test_stopped_leftover_returns_false_when_all_bounded_calls_timeout(self):
        """_stopped_leftover returns False (eventually) when every _bounded call returns rc=124.

        On a hung podman with rt='podman', up to three sequential _bounded calls each wait
        _PODMAN_QUERY_TIMEOUT seconds before returning rc=124; the worst-case wall-clock block is
        3 * _PODMAN_QUERY_TIMEOUT.  This test pins that _stopped_leftover returns False rather than
        raising or returning True.
        """
        timeout_rc = subprocess.CompletedProcess(
            args=[], returncode=124, stdout=b"", stderr=b""
        )
        timeout_text = subprocess.CompletedProcess(
            args=[], returncode=124, stdout="", stderr=""
        )
        calls: list[list[str]] = []

        def _fake_bounded(cmd, *, timeout, warn=True, **kw):
            calls.append(list(cmd))
            text = kw.get("text", False)
            return timeout_text if text else timeout_rc

        with patch("harnessed.ctrquery._bounded", side_effect=_fake_bounded):
            result = ctrquery._stopped_leftover("podman", "myinst", "mypod")

        assert result is False
        # All three queries must have run (none short-circuits when rc=124).
        assert len(calls) == 3, f"expected 3 _bounded calls, got {len(calls)}: {calls}"

    def test_container_stale_returns_false_when_inspect_times_out(self):
        """_container_stale returns False (not stale) when _inspect_id returns '' on timeout.

        Known limit (F4, Issue #295): a hung podman causes _inspect_id to return '' (rc=124 =>
        else branch).  _img_differs sees two empty strings and returns False ('can't tell ->
        not stale').  The container is treated as current and re-attached, potentially running
        an old build.  This is fail-open on staleness detection; the alternative (hang forever)
        was the pre-#295 behaviour.
        """
        empty = subprocess.CompletedProcess(args=[], returncode=124, stdout="", stderr="")
        with patch("harnessed.ctrquery._bounded", return_value=empty):
            result = ctrquery._container_stale("podman", "mycontainer", "myimage")
        assert result is False, (
            "_container_stale must return False (fail-open) when inspect times out"
        )
