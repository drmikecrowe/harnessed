"""Coverage reconciliation in catalog/base/harnessed-scan (bd harnessed-wx9).

Every scanner writes its manifest line only when it produced parseable output
(`[[ -s "$out" ]] && printf ... >>"$MANIFEST"`). So a scanner that RAN and yielded nothing
never reached the report at all: a build could run six scanners, have five produce nothing
usable, report on one, and print a green all-clear. That is a FALSE CLEAN on a security
gate, and the failure mode points the wrong way.

The fix records every scanner we commit to running in an attempts ledger, then reconciles
that ledger against the manifest at report time. These tests pin the reconciliation down.

The reporting half runs after `with open(sys.argv[1])`, so unlike test_scan_socket_parser
it cannot be exec'd as bare function defs — it is driven end-to-end as a subprocess.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "catalog" / "base" / "harnessed-scan"


@pytest.fixture(scope="module")
def report_block(tmp_path_factory):
    """Extract the summary heredoc to a runnable .py file."""
    src = SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", src[src.index("HARNESSED_SCAN_REPORT"):], re.S)
    assert match, "summary heredoc not found in harnessed-scan"
    path = tmp_path_factory.mktemp("scan") / "report.py"
    path.write_text(match.group(1))
    return path


def run_report(report_block, tmp_path, manifest_rows, attempts):
    """Drive the summary block over a manifest + attempts ledger; return (stdout, report)."""
    manifest = tmp_path / "manifest"
    manifest.write_text("".join("%s|%s|%s\n" % r for r in manifest_rows))
    ledger = tmp_path / "attempts"
    ledger.write_text("".join("%s|%s\n" % a for a in attempts))
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(report_block), str(manifest)],
        capture_output=True,
        text=True,
        env={"HARNESSED_SCAN_REPORT": str(out), "HARNESSED_SCAN_ATTEMPTS": str(ledger),
             "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, json.loads(out.read_text())


@pytest.fixture
def clean_source(tmp_path):
    """One scanner that genuinely ran and genuinely found nothing."""
    payload = tmp_path / "pip.json"
    payload.write_text("[]")
    return ("pip-audit", "python env", str(payload))


class TestSilentScannersAreSurfaced:
    def test_the_six_scanner_false_clean_names_every_silent_source(
        self, report_block, tmp_path, clean_source
    ):
        """The bead's exact scenario: 6 run, 5 produce nothing, 1 reports."""
        attempts = [
            ("snyk", "node globals"),
            ("snyk", "recipe: foo"),
            ("socket", "node globals"),
            ("socket", "recipe: foo"),
            ("osv", "recipe lockfiles"),
            ("pip-audit", "python env"),
        ]
        stdout, report = run_report(report_block, tmp_path, [clean_source], attempts)

        # The silent five must not vanish — they stay in sources[] with an explicit status.
        assert len(report["sources"]) == 6
        no_output = [s for s in report["sources"] if s["status"] == "no-output"]
        assert len(no_output) == 5
        assert report["coverage"] == {
            "attempted": 6,
            "reported": 1,
            "no_output": ["snyk", "snyk", "socket", "socket", "osv"],
        }
        # ...and the operator is told, by name.
        assert "5 scanner(s) ran but produced NO parseable output" in stdout
        for tool, label in attempts[:5]:
            assert "%s · %s" % (tool, label) in stdout

    def test_the_all_clear_counts_only_reporting_sources(
        self, report_block, tmp_path, clean_source
    ):
        """The old wording claimed coverage it did not have."""
        attempts = [("snyk", "node globals"), ("pip-audit", "python env")]
        stdout, _ = run_report(report_block, tmp_path, [clean_source], attempts)
        assert "no high/critical advisories across 1 reporting source(s)." in stdout


class TestNoCoverageIsNotClean:
    def test_zero_reporting_scanners_is_flagged_loudly(self, report_block, tmp_path):
        attempts = [("snyk", "node globals"), ("socket", "node globals"), ("osv", "recipe lockfiles")]
        stdout, report = run_report(report_block, tmp_path, [], attempts)

        assert report["covered"] is False
        assert "NO COVERAGE" in stdout
        assert "This is NOT a clean result." in stdout
        # It must never render as a reassuring zero.
        assert "no high/critical advisories" not in stdout
        # The attempts still appear, so the report says WHAT was not covered.
        assert len(report["sources"]) == 3

    def test_a_genuinely_covered_scan_is_marked_covered(
        self, report_block, tmp_path, clean_source
    ):
        stdout, report = run_report(
            report_block, tmp_path, [clean_source], [("pip-audit", "python env")]
        )
        assert report["covered"] is True
        assert report["coverage"]["no_output"] == []
        assert "NO COVERAGE" not in stdout
        assert "produced NO parseable output" not in stdout


def test_a_missing_attempts_ledger_does_not_break_the_report(report_block, tmp_path, clean_source):
    """Report generation must survive a ledger that was never written."""
    manifest = tmp_path / "manifest"
    manifest.write_text("%s|%s|%s\n" % clean_source)
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(report_block), str(manifest)],
        capture_output=True,
        text=True,
        env={"HARNESSED_SCAN_REPORT": str(out), "HARNESSED_SCAN_ATTEMPTS": str(tmp_path / "nope"),
             "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text())["covered"] is True
