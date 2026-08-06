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


PODMAN_SKIP = '''
import pytest
@pytest.mark.skipif(True, reason="set HARNESSED_PODMAN=1 for live podman tests")
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
IMAGE_PRECONDITION_SKIP = '''
import pytest
@pytest.mark.skipif(True, reason="harnessed-base:local not built — run `harnessed build` first")
def test_needs_an_image():
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

    def test_an_unrecognised_skip_reason_still_fails(self, live_session):
        """The hole the first version of this guard had, found in review of PR #212.

        `test_live_verification_debt.py` skips with "<image> not built — run `harnessed build`
        first", a reason that fires ONLY when the gate is open and matches no known pattern. The
        guard asked "does the reason mention HARNESSED_PODMAN?", so it did not, and the run exited
        green having verified nothing — the exact fail-open the guard exists to prevent.

        The rule is now an allowlist: with the gate open, a reason this file has never seen fails
        the run rather than passing it.
        """
        result = live_session(gate_open=True, test_body=IMAGE_PRECONDITION_SKIP)
        assert result.ret != 0, "an unknown skip with the gate open must fail, not pass"
