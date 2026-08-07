"""The guard that stops a skipped live layer from reading as a clean run (bd harnessed-3x1).

This suite's live-verification tests sat behind `HARNESSED_PODMAN=1` and ran nowhere for months:
`tools/run-tests.sh` never set the gate, CI deliberately did not, and every run printed
`N passed, 22 skipped` — a number that looks like health and was in fact the whole live layer
going unexercised.

The accounting in `conftest.py` is now load-bearing, so it needs its own tests. Each one runs a
throwaway pytest session via the `pytester` fixture with the real conftest copied in, because the
behaviour under test IS the exit status of a session — asserting on the helper functions alone
would pin the arithmetic and miss the thing that matters.
"""
from __future__ import annotations

from pathlib import Path

import pytest


pytest_plugins = ["pytester"]

# The SHIPPED conftest, not a paraphrase of it. A copy of the hooks written inline here would drift
# from the real ones and these tests would keep passing against a version nobody runs.
CONFTEST_SOURCE = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")


@pytest.fixture
def live_session(pytester, monkeypatch):
    """Run a throwaway pytest session using the real hooks, with the gate under our control."""

    def run(*, gate_open: bool, test_body: str):
        # Set before the subprocess starts: the hooks read the gate at import time.
        monkeypatch.setenv("HARNESSED_PODMAN", "1" if gate_open else "0")
        pytester.makeconftest(CONFTEST_SOURCE)
        pytester.makepyfile(test_body)
        return pytester.runpytest_subprocess("-q")

    return run


# Mirrors `support.podman`: the gate marks what it governs, so the guard can count markers rather
# than read wording.
_GATED = '''
import pytest
def podman(func):
    return pytest.mark.live_podman(
        pytest.mark.skipif(True, reason="set HARNESSED_PODMAN=1 for live podman tests")(func)
    )
'''

PODMAN_SKIP = _GATED + '''
@podman
def test_needs_podman():
    assert False, "must not run"

def test_ordinary():
    assert True
'''

DOLT_SKIP = '''
import pytest
@pytest.mark.skipif(True, reason="needs the dolt binary")
def test_needs_dolt():
    assert False, "must not run"

def test_ordinary():
    assert True
'''

NO_SKIPS = '''
def test_ordinary():
    assert True
'''

# The shape that slipped past the first version of this guard: a precondition skip that only fires
# WHEN the gate is open, whose reason mentions neither the gate nor any known pattern. Real example
# from tests/test_live_verification_debt.py.
IMAGE_PRECONDITION_SKIP = _GATED + '''
@podman
@pytest.mark.skipif(True, reason="harnessed-base:local not built — run `harnessed build` first")
def test_needs_an_image():
    assert False, "must not run"

def test_ordinary():
    assert True
'''

# A skip that has nothing to do with podman. The allowlist design would have failed the run on
# this; the marker design must not even notice it.
UNRELATED_SKIP = '''
import pytest
@pytest.mark.skipif(True, reason="only meaningful on macOS")
def test_platform_specific():
    assert False, "must not run"

def test_ordinary():
    assert True
'''


class TestGateClosed:
    """Deferring the live layer is legitimate — say so loudly, do not fail."""

    def test_run_is_green_but_says_what_did_not_happen(self, live_session):
        result = live_session(gate_open=False, test_body=PODMAN_SKIP)
        assert result.ret == 0, "a deliberately closed gate must not fail the suite"
        result.stdout.fnmatch_lines(["*live test(s) did NOT run*"])

    def test_it_names_the_way_to_open_the_gate(self, live_session):
        result = live_session(gate_open=False, test_body=PODMAN_SKIP)
        result.stdout.fnmatch_lines(["*HARNESSED_PODMAN=1*"])


class TestGateOpen:
    """Asking for live verification and getting none is a failure, not a pass."""

    def test_podman_gated_skip_fails_the_run(self, live_session):
        # The scenario this exists for: CI sets the gate, podman is absent or broken, the tests
        # skip, and without this the job reports success having verified nothing.
        result = live_session(gate_open=True, test_body=PODMAN_SKIP)
        assert result.ret != 0, "gate open + podman tests skipped must NOT exit clean"

    def test_an_unrelated_gate_does_not_fail_the_run(self, live_session):
        # dolt is a different gate. Failing a podman run because dolt is missing would train
        # people to ignore this guard, which is worse than not having it.
        result = live_session(gate_open=True, test_body=DOLT_SKIP)
        assert result.ret == 0, "a non-podman gate must not fail a podman run"

    def test_nothing_skipped_is_clean_and_quiet(self, live_session):
        result = live_session(gate_open=True, test_body=NO_SKIPS)
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*gate open, no live tests skipped*"])

    def test_a_gated_test_skipped_for_another_reason_still_fails(self, live_session):
        """The hole the first version of this guard had, found in review of PR #212.

        `test_live_verification_debt.py` stacks a second skipif on a gated test — "<image> not
        built" — which fires ONLY when the gate is open, and whose wording mentions no gate. The
        guard read reasons, so it missed them, and the run exited green having verified nothing.

        The marker travels with the test regardless of which decorator does the skipping, so the
        wording is no longer load-bearing.
        """
        result = live_session(gate_open=True, test_body=IMAGE_PRECONDITION_SKIP)
        assert result.ret != 0, "a governed test that skipped for ANY reason must fail the run"

    def test_a_skip_the_gate_does_not_govern_is_ignored(self, live_session):
        """The failure mode of the fix I nearly shipped instead.

        Inverting to "anything not on an allowlist fails" would catch the case above and also fail
        this run — a platform skip has nothing to do with podman. Every such false failure gets
        answered by widening the allowlist, which decays it back into reason-matching.
        """
        result = live_session(gate_open=True, test_body=UNRELATED_SKIP)
        assert result.ret == 0, "an unrelated skip must not fail a podman run"

    def test_the_reason_that_failed_the_run_is_printed(self, live_session):
        """bd harnessed-ln7. The guard failed the run correctly and then described it wrongly.

        The failure line says the podman-gated tests "above" were expected to run, but the listing
        above it is built by pattern-matching skip REASONS. An image-precondition reason matches no
        pattern, so the one skip that actually failed the run was the one reason not shown. A reader
        saw the unrelated gates that were listed (aoe, dolt) and blamed those — which is exactly
        what happened on run 31205617563, to the author of this test.

        Whatever fails the run must appear in the list the failure message points at.
        """
        result = live_session(gate_open=True, test_body=IMAGE_PRECONDITION_SKIP)
        assert result.ret != 0
        result.stdout.fnmatch_lines(["*not built*"])

    def test_an_unrelated_skip_is_still_not_listed_as_a_failure_cause(self, live_session):
        """The other half: widening the listing must not widen the FAILURE. A platform skip is
        reported when it looks live, but it never fails a podman run."""
        result = live_session(gate_open=True, test_body=UNRELATED_SKIP)
        assert result.ret == 0
