"""The pin-check workflow's TRIGGERS are the design decision (bd harnessed-4xu).

`harnessed update --check` resolves LIVE registries, so its result depends on what npm/PyPI/GitHub
published today rather than on the diff under review. Wired to `pull_request` it would fail an
unrelated contributor's branch the moment a third party cut a release — red through nobody's fault
and unfixable by the author. A check that behaves that way is one everyone learns to ignore, which
is the same false-signal problem bd harnessed-wx9 was about, pointed the other way.

So the trigger set is load-bearing, and a one-line edit could silently undo it. These tests are the
guard: adding `pull_request:` to this workflow must break a test, not a contributor's PR.
"""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pin-check.yml"


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return YAML(typ="safe").load(WORKFLOW.read_text())


def _triggers(workflow) -> set:
    # PyYAML/ruamel parse a bare `on:` key as the boolean True (YAML 1.1 truthiness).
    raw = workflow.get(True, workflow.get("on"))
    return set(raw) if not isinstance(raw, str) else {raw}


class TestItIsNotAPullRequestGate:
    @pytest.mark.parametrize("trigger", ["pull_request", "pull_request_target", "push"])
    def test_diff_triggered_events_are_absent(self, workflow, trigger):
        assert trigger not in _triggers(workflow), (
            f"pin-check must not run on {trigger}: a third-party release would fail an unrelated "
            "PR that cannot fix it"
        )

    def test_it_runs_on_a_schedule(self, workflow):
        assert "schedule" in _triggers(workflow), (
            "with no schedule the check never runs at all, which is where this started"
        )

    def test_it_can_be_run_on_demand(self, workflow):
        assert "workflow_dispatch" in _triggers(workflow)


class TestItActuallyChecksPins:
    def test_the_check_command_is_invoked(self, workflow):
        runs = " ".join(
            s.get("run", "") for s in workflow["jobs"]["pins"]["steps"]
        )
        assert "harnessed update --check" in runs

    def test_mise_is_installed_so_registered_tools_resolve(self, workflow):
        """A bare `tools:` entry (currently `pulumi`) finds its GitHub repo via `mise registry`.
        Without mise those pins degrade to 'unresolved' — reported, never silently skipped, but
        unchecked, which quietly shrinks what the sweep covers."""
        uses = [s.get("uses", "") for s in workflow["jobs"]["pins"]["steps"]]
        assert any("mise" in u for u in uses), f"no mise setup step among {uses}"


class TestTheSuiteWorkflowIsUnchangedInThisRespect:
    def test_the_test_workflow_still_gates_pull_requests(self):
        """The contrast that makes the point: the hermetic pytest suite SHOULD block PRs, because
        its result depends only on the diff. Only the network-dependent check is scheduled."""
        tests_wf = WORKFLOW.parent / "test.yml"
        d = YAML(typ="safe").load(tests_wf.read_text())
        assert "pull_request" in _triggers(d)
