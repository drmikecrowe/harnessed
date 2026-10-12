"""The pin-upgrade workflow (GH-582), which replaced pin-check.yml.

Its TRIGGERS carry the decision pin-check's tests guarded (bd harnessed-4xu): `harnessed update`
resolves LIVE registries, so its result depends on what upstream published today rather than on a
diff. Wired to `pull_request` it would fail or rewrite an unrelated contributor's branch. These
tests keep that a test failure rather than a contributor's red PR.

Scenario ids (S4.3, S7.2, S7.3, S8.x) are the ones in spec-evidence/2026-10-12-GH-582/SPEC.md.
"""

import json
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "pin-upgrade.yml"
SCRIPT = ROOT / "tools" / "pin-upgrade.sh"


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return YAML(typ="safe").load(WORKFLOW.read_text())


def _triggers(workflow) -> set:
    # PyYAML/ruamel parse a bare `on:` key as the boolean True (YAML 1.1 truthiness).
    raw = workflow.get(True, workflow.get("on"))
    return set(raw) if not isinstance(raw, str) else {raw}


def _steps(workflow):
    (job,) = workflow["jobs"].values()
    return job, job["steps"]


class TestTriggers:
    def test_s8_1_only_schedule_and_dispatch(self, workflow):
        assert _triggers(workflow) == {"schedule", "workflow_dispatch"}

    def test_s8_2_every_other_day(self, workflow):
        on = workflow.get(True, workflow.get("on"))
        assert on["schedule"] == [{"cron": "0 6 */2 * *"}]


class TestTheJob:
    def test_s8_3_actions_are_pinned_to_a_sha(self, workflow):
        _, steps = _steps(workflow)
        uses = [s["uses"] for s in steps if "uses" in s]
        assert uses, "no action steps"
        for u in uses:
            assert re.search(r"@[0-9a-f]{40}$", u), f"{u} is not pinned to a commit SHA"

    def test_s8_3_bounded_runtime(self, workflow):
        job, _ = _steps(workflow)
        assert 0 < job["timeout-minutes"] <= 30

    def test_s8_3_permissions_are_exactly_these(self, workflow):
        assert workflow["permissions"] == {
            "contents": "write", "pull-requests": "write", "actions": "write",
        }

    def test_s8_3_mise_is_installed_so_registered_tools_resolve(self, workflow):
        """A bare `tools:` entry (currently `pulumi`) finds its GitHub repo via `mise registry`.
        Without mise those pins degrade to 'unresolved' and are never bumped."""
        _, steps = _steps(workflow)
        assert any("mise" in s.get("uses", "") for s in steps)

    def test_runs_queue_instead_of_overlapping(self, workflow):
        """PR #593 review: two overlapping runs race on one upgrade-<date> ref. Queue, never
        cancel: a cancelled run can stop between creating the ref and making the commit."""
        assert workflow["concurrency"] == {"group": "pin-upgrade", "cancel-in-progress": False}

    def test_only_main_is_upgraded(self, workflow):
        """PR #593 review: a dispatch from another ref would base the day's PR on that ref."""
        job, _ = _steps(workflow)
        assert job["if"] == "github.ref == 'refs/heads/main'"

    def test_s8_4_the_script_runs_with_the_workflow_token(self, workflow):
        _, steps = _steps(workflow)
        (step,) = [s for s in steps if "tools/pin-upgrade.sh" in s.get("run", "")]
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105 — an expression, not a secret

    def test_s8_5_pin_check_is_gone_and_tests_still_gate_prs(self):
        assert not (WORKFLOWS / "pin-check.yml").exists()
        tests_wf = YAML(typ="safe").load((WORKFLOWS / "test.yml").read_text())
        assert "pull_request" in _triggers(tests_wf)


def _live_yml_patterns() -> set:
    """The patterns in the `case` of live.yml job `changes` — the filter that actually runs."""
    run = YAML(typ="safe").load((WORKFLOWS / "live.yml").read_text())
    (step,) = [s for s in run["jobs"]["changes"]["steps"] if "run" in s]
    block = step["run"].split('case "$f" in', 1)[1]
    pats = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        last = line.endswith(")")
        pats += [p.strip() for p in line.rstrip("\\").rstrip(")").split("|") if p.strip()]
        if last:
            break
    return set(pats)


def _script_patterns() -> set:
    body = SCRIPT.read_text().split("LIVE_TRIGGERS=(", 1)[1].split(")", 1)[0]
    return set(re.findall(r"'([^']+)'", body))


class TestOneLiveList:
    def test_s4_3_the_script_matches_live_yml(self):
        live = _live_yml_patterns()
        assert "src/harnessed/launcher.py" in live, f"parsed nothing useful from live.yml: {live}"
        assert _script_patterns() == live


class TestFeatRelease:
    def test_s7_2_the_title_passes_pr_title_yml(self):
        text = (WORKFLOWS / "pr-title.yml").read_text()
        found = re.search(r"pattern='([^']+)'", text)
        assert found, "no pattern= line in pr-title.yml"
        assert re.match(found.group(1),"feat(catalog): upgrade pins 2026-10-13")
        assert "chore(" not in SCRIPT.read_text()

    def test_s7_3_a_feat_is_a_minor_bump_before_1_0(self):
        cfg = json.loads((ROOT / "release-please-config.json").read_text())
        manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
        pkg = cfg["packages"]["."]
        assert pkg["bump-minor-pre-major"] is True
        # The setting that would turn a pre-1.0 feat into a PATCH bump; absent means minor.
        assert not pkg.get("bump-patch-for-minor-pre-major", False)
        assert int(manifest["."].split(".")[0]) == 0
