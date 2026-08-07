"""`live.yml` must be diagnosable and must run what developers run — bd harnessed-rv2.3.

The workflow failed six times in a row and every log was insufficient to decide WHY:

  * it never printed the runner's uid, so rv2.1's central claim (host uid != 1000) could not be
    confirmed from any existing log — the fix was proposed against a number nobody had measured;
  * it invoked `uv run --extra dev pytest` directly rather than `tools/run-tests.sh`, which CLAUDE.md
    describes as absorbing "three traps that fail locally while CI stays green" — so local and CI
    were not running the same thing by construction;
  * `timeout-minutes: 30` against observed runtimes of 15:03, 14:41 and 23:47 left six minutes of
    headroom, and a timeout kill presents as an unrelated failure.

A one-line edit could undo any of these. These tests are the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "live.yml"


@pytest.fixture(scope="module")
def job() -> dict:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return YAML(typ="safe").load(WORKFLOW.read_text())["jobs"]["live"]


def _steps(job) -> list[dict]:
    return job["steps"]


def _run_bodies(job) -> str:
    return "\n".join(s.get("run", "") for s in _steps(job))


class TestItPrintsEnoughToDiagnoseAFailure:
    def test_the_runner_identity_is_printed(self, job):
        """rv2.1 is a claim about a NUMBER — the runner's uid — that no log has ever carried."""
        bodies = _run_bodies(job)
        assert re.search(r"\bid -u\b", bodies), "the runner's uid is never printed"
        assert re.search(r"\bid -g\b", bodies), "the runner's gid is never printed"
        assert "IDMappings" in bodies, (
            "podman's idmappings are never printed; without them a keep-id failure cannot be "
            "distinguished from an ownership one"
        )

    def test_the_identity_is_printed_before_the_suite_runs(self, job):
        """A diagnostic that only runs after a passing suite diagnoses nothing."""
        bodies = [s.get("run", "") for s in _steps(job)]
        identity = next(i for i, b in enumerate(bodies) if "id -u" in b)
        suite = next(i for i, b in enumerate(bodies) if "run-tests.sh" in b)
        assert identity < suite

    def test_the_identity_step_is_unconditional(self, job):
        """An adversarial reviewer's finding: the two assertions above read a FLAT JOIN of every
        step's `run` body, so an `if: failure()`-guarded step containing the same three commands
        would satisfy both while diagnosing nothing — and the failure modes that most need a uid
        (a timeout kill, a setup failure before the suite) are exactly the ones where a conditional
        step would not have run yet."""
        step = next(s for s in _steps(job) if "id -u" in s.get("run", ""))
        assert "if" not in step, (
            f"the runner-identity step is conditional ({step.get('if')!r}); it must run on every "
            "job, or the log it exists to produce is missing precisely when it is needed"
        )


class TestItRunsWhatDevelopersRun:
    def test_the_suite_goes_through_the_project_script(self, job):
        assert "tools/run-tests.sh" in _run_bodies(job), (
            "CI is bypassing the sanctioned entry point, so a local green and a CI green are not "
            "evidence about the same thing"
        )

    def test_it_does_not_hand_compose_pytest(self, job):
        assert not re.search(r"uv run .*pytest", _run_bodies(job)), (
            "a hand-composed pytest line is exactly what tools/run-tests.sh exists to replace"
        )

    def test_the_suite_step_still_sets_the_live_gate(self, job):
        """Without HARNESSED_PODMAN=1 every live test skips and the job goes green having run
        nothing — the defect this whole workflow was created to fix."""
        step = next(s for s in _steps(job) if "run-tests.sh" in s.get("run", ""))
        assert step.get("env", {}).get("HARNESSED_PODMAN") in ("1", 1)


class TestItProvisionsWhatTheScriptNeeds:
    def test_mise_is_available(self, job):
        """`tools/run-tests.sh` shells out to `mise` on its first line; without it the job fails
        with 'is mise installed and on PATH?' instead of running anything."""
        text = "\n".join(
            [_run_bodies(job)] + [s.get("uses", "") for s in _steps(job)]
        )
        assert "mise" in text

    @pytest.mark.parametrize(
        "step_uses",
        [s.get("uses", "") for s in YAML(typ="safe").load(WORKFLOW.read_text())["jobs"]["live"]["steps"]
         if s.get("uses")],
    )
    def test_every_action_is_pinned_to_a_commit_sha(self, step_uses):
        """CLAUDE.md: pin every download. An action is a download that executes, and a git tag is
        mutable — whoever controls the action can repoint `v2` at different code."""
        ref = step_uses.split("@", 1)[1]
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{step_uses} is pinned to a mutable ref, not a commit SHA"
        )


class TestTheTimeoutHasHeadroom:
    def test_it_clears_the_observed_worst_case(self, job):
        """Observed runtimes: 15:03, 14:41, 23:47. Run 31133464515 came within 6 minutes of being
        killed, and a timeout kill presents as an unrelated failure. `mise` now also provisions
        shellcheck and pyright on a cold runner, which widens the gap further."""
        assert job["timeout-minutes"] >= 45, (
            f"timeout-minutes={job['timeout-minutes']} is thin against a 23:47 worst case"
        )
