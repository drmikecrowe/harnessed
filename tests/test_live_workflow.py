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
CLAUDE_MD = ROOT / "CLAUDE.md"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return YAML(typ="safe").load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def job(workflow) -> dict:
    return workflow["jobs"]["live"]


def _triggers(workflow) -> dict:
    """The `on:` block, whichever key the loader produced.

    YAML 1.1 reads a bare `on` as the boolean True; 1.2 reads it as the string. ruamel's safe loader
    is 1.2 here, but a loader change must not silently turn every trigger assertion into a KeyError
    that reads like a missing trigger.
    """
    return workflow.get("on", workflow.get(True))


def _as_list(value) -> list:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _claude_md_live_paths() -> list[str]:
    """The first column of CLAUDE.md's "Why the suite cannot see it" table."""
    marker = "| Trigger | Why the suite cannot see it |"
    text = CLAUDE_MD.read_text()
    assert marker in text, f"{CLAUDE_MD} no longer carries the live-trigger table"
    paths: list[str] = []
    for line in text.split(marker, 1)[1].splitlines():
        if not line.startswith("|"):
            if paths:
                break
            continue
        cell = re.fullmatch(r"`([^`]+)`", line.split("|")[1].strip())
        if cell:
            paths.append(cell.group(1))
    assert paths, "the live-trigger table has no backticked paths in its first column"
    return paths


def _steps(job) -> list[dict]:
    return job["steps"]


def _commands(step: dict) -> str:
    """A step's run body with comment lines stripped.

    Matching steps by a bare substring is too loose: a COMMENT mentioning `tools/run-tests.sh`
    inside the diagnostics step made `_suite_step` select the wrong step and broke two tests that
    were otherwise correct. What identifies a step is what it EXECUTES, not what it mentions.
    """
    return "\n".join(
        line for line in step.get("run", "").splitlines() if not line.strip().startswith("#")
    )


def _run_bodies(job) -> str:
    """Every step's EXECUTED commands, joined — comments excluded.

    Including comments made these assertions satisfiable by prose: this workflow's comments mention
    `id -u`, `IDMappings` and `mise` by name, so deleting the commands while leaving the comments
    that explain them would have kept every diagnostics test green (CodeRabbit).
    """
    return "\n".join(_commands(step) for step in _steps(job))


def _suite_step(job) -> dict:
    """The step that actually invokes the project's test script."""
    return next(s for s in _steps(job) if "tools/run-tests.sh" in _commands(s))


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
        steps = _steps(job)
        identity = next(i for i, s in enumerate(steps) if "id -u" in _commands(s))
        suite = steps.index(_suite_step(job))
        assert identity < suite

    def test_the_identity_step_is_unconditional(self, job):
        """An adversarial reviewer's finding: the two assertions above read a FLAT JOIN of every
        step's `run` body, so an `if: failure()`-guarded step containing the same three commands
        would satisfy both while diagnosing nothing — and the failure modes that most need a uid
        (a timeout kill, a setup failure before the suite) are exactly the ones where a conditional
        step would not have run yet."""
        step = next(s for s in _steps(job) if "id -u" in _commands(s))
        assert "if" not in step, (
            f"the runner-identity step is conditional ({step.get('if')!r}); it must run on every "
            "job, or the log it exists to produce is missing precisely when it is needed"
        )


class TestItRunsWhatDevelopersRun:
    def test_the_suite_goes_through_the_project_script(self, job):
        assert "tools/run-tests.sh" in _commands(_suite_step(job)), (
            "CI is bypassing the sanctioned entry point, so a local green and a CI green are not "
            "evidence about the same thing"
        )

    def test_it_does_not_hand_compose_pytest(self, job):
        assert not re.search(r"uv run .*pytest", "\n".join(_commands(s) for s in _steps(job))), (
            "a hand-composed pytest line is exactly what tools/run-tests.sh exists to replace"
        )

    def test_the_suite_step_still_sets_the_live_gate(self, job):
        """Without HARNESSED_PODMAN=1 every live test skips and the job goes green having run
        nothing — the defect this whole workflow was created to fix."""
        assert _suite_step(job).get("env", {}).get("HARNESSED_PODMAN") in ("1", 1)


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


class TestItProvisionsTheLiveGates:
    """bd harnessed-ln7. The job is named "live verification", so a gate it can satisfy and does
    not is a gap between the name and the work.

    `aoe` is deliberately NOT provisioned. ARCHITECTURE.md and `src/harnessed/aoe.py` both state
    that harnessed "neither requires nor installs" it, and `test_aoe_real.py` says it is "free in CI
    and real on a developer machine". Its tests carry no `live_podman` marker, so they are reported
    and never fail the run. That skip is a declared choice, not an oversight.
    """


    def test_the_base_image_is_built_before_the_suite(self, job):
        """The actual cause of the red run on 31205617563.

        `test_live_verification_debt.py` skips two `@podman` tests unless
        `localhost/harnessed-base:latest` exists, and evaluates that at COLLECTION time. A later
        test building the image does not help — the skip decision is already made. So the image must
        exist before pytest starts.

        The command must be BARE `harnessed build`, and the anchored pattern is what enforces that.
        `harnessed build <stack> <harness>` also builds the agent and derived images, runs the
        credentialed supply-chain rescan, and creates the stack's podman volumes — including volumes
        for the very tests that exercise volume creation. This test therefore pins the narrow form
        rather than merely "a build happens".
        """
        steps = _steps(job)
        build = next(
            (i for i, st in enumerate(steps)
             if re.search(r"harnessed build[ \t]*$", _commands(st), re.M)),
            None,
        )
        assert build is not None, (
            "no step runs a bare `harnessed build`; either nothing builds the base image, or it "
            "was widened to `build <stack> <harness>`, which does far more than this step needs"
        )
        assert build < steps.index(_suite_step(job)), (
            "the image must exist before pytest collects, not merely before the tests run"
        )


class TestItGatesPullRequests:
    """#467. The live layer is the only thing in CI that starts a container, and until this change
    it ran on no PR at all — so the container path had no merge gate, only a manual dispatch step
    documented in CLAUDE.md that PR #461 demonstrates nobody runs.

    The shape matters as much as the trigger. A `paths:`-filtered workflow does not run on a PR that
    misses the filter, so it reports NO status — and a required check that never reports deadlocks
    the PR forever (`test.yml` records that trap for `pytest`). A job skipped by an `if:` reports a
    `skipped` conclusion instead, which satisfies the requirement and costs nothing. These tests pin
    the working shape so a well-meaning simplification back to `on: pull_request: paths:` cannot
    land quietly.
    """

    def test_it_runs_on_pull_request(self, workflow):
        assert "pull_request" in _triggers(workflow), (
            "live.yml does not run on pull_request, so nothing gates the container path"
        )

    def test_the_trigger_carries_no_paths_filter(self, workflow):
        pr = _triggers(workflow)["pull_request"] or {}
        assert "paths" not in pr and "paths-ignore" not in pr, (
            "a paths filter on the trigger stops the workflow reporting at all on a PR that misses "
            "it; a required `live` check would then wait forever. Filter in the `changes` job."
        )

    @pytest.mark.parametrize("name", ["live", "live-docker"])
    def test_the_container_jobs_hang_off_the_changes_job(self, workflow, name):
        job = workflow["jobs"][name]
        assert "changes" in _as_list(job.get("needs")), f"{name} does not depend on `changes`"
        assert "needs.changes.outputs.live" in str(job.get("if", "")), (
            f"{name} is not conditioned on the filter, so every PR pays for a container launch"
        )

    def test_the_changes_job_is_unconditional_and_publishes_the_decision(self, workflow):
        """It is the only job that always runs, so it must not itself be filtered — and its output
        is the whole interface the other two read."""
        changes = workflow["jobs"]["changes"]
        assert "if" not in changes and "needs" not in changes
        assert "live" in changes.get("outputs", {})

    def test_non_pull_request_events_still_run_the_layer(self, workflow):
        """Push to main, the nightly, and a manual dispatch have no diff to filter on and all mean
        "run the layer". A filter that answered `false` for them would silently delete the coverage
        this workflow existed for before #467."""
        body = _run_bodies(workflow["jobs"]["changes"])
        assert re.search(r'!=\s*"?pull_request"?', body), (
            "the filter has no non-PR escape hatch; the nightly and post-merge runs would be gated "
            "on a diff that does not exist"
        )

    def test_the_filter_covers_every_path_claude_md_names(self, workflow):
        """CLAUDE.md's table and this job are one filter written twice. The table is what a
        contributor reads; the job is what actually runs. Drift between them is how a file lands on
        the documented list and gets no live evidence anyway."""
        body = _run_bodies(workflow["jobs"]["changes"])
        missing = [p for p in _claude_md_live_paths() if p not in body]
        assert not missing, (
            f"CLAUDE.md names {missing} as needing live evidence, but the `changes` job does not "
            "match them, so a PR touching only those files skips both container jobs"
        )

    def test_the_filter_fails_closed(self, workflow):
        """The one failure mode that silently opens the gate.

        A dependent job whose `needs` FAILED reports a `skipped` conclusion, and GitHub accepts a
        skipped required check as satisfied. So if this step dies on an api.github.com hiccup, the
        PR merges with no container evidence and a green tick. The API call must therefore be
        handled rather than left to `set -e`, and the handler must answer `true`.
        """
        body = _run_bodies(workflow["jobs"]["changes"])
        guarded = re.search(r"if !\s*files=.*gh api", body)
        assert guarded, (
            "the PR file-list call is unguarded; a transient API failure would fail the `changes` "
            "job, skip both container jobs, and satisfy a required check having proved nothing"
        )
        assert body.count('live=true" >> "$GITHUB_OUTPUT"') >= 2, (
            "the API-failure branch does not fall back to running the live layer"
        )

    def test_the_workflow_gates_changes_to_itself(self, workflow):
        """A change to the gate must run the gate. Without this, a PR can weaken, break, or skip
        this workflow and the first evidence arrives post-merge on `main`, where no author looks."""
        assert ".github/workflows/live.yml" in _run_bodies(workflow["jobs"]["changes"])
