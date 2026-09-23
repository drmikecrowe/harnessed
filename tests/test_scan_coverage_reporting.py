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
    """Drive the summary block over a manifest + attempts ledger; return (stdout, report).

    An attempts entry is `(tool, source)` for a scanner that actually ran, or
    `(tool, source, "unrun", reason)` for one skipped before it started (bd harnessed-wx9).
    """
    manifest = tmp_path / "manifest"
    manifest.write_text("".join("%s|%s|%s\n" % r for r in manifest_rows))
    ledger = tmp_path / "attempts"
    ledger.write_text("".join("|".join(a) + "\n" for a in attempts))
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
            # All six were ATTEMPTED here — none was skipped for a missing token or binary, which
            # is the separate `unrun` case (bd harnessed-wx9, owner decision 2026-07-22).
            "unrun": [],
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


class TestSkippedScannersAreDeclared:
    """bd harnessed-wx9, owner decision 2026-07-22.

    A scanner skipped for an absent token or binary announces itself on stdout but contributes
    NOTHING to scan-report.json, so a consumer reading that file cannot tell a skipped scanner from
    one that never existed. Both are uncovered — but only `no-output` means a scanner is BROKEN,
    while `unrun` means it was never given what it needed. Conflating them would either hide a
    broken scanner or cry wolf about a deliberately unconfigured one.
    """

    SKIPPED = ("snyk", "node globals", "unrun", "no SNYK_TOKEN")

    def test_a_skipped_scanner_appears_in_sources(self, report_block, tmp_path, clean_source):
        _, report = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), self.SKIPPED],
        )
        unrun = [s for s in report["sources"] if s["status"] == "unrun"]
        assert len(unrun) == 1, "a skipped scanner must not be invisible in the report"
        assert unrun[0]["tool"] == "snyk"
        assert unrun[0]["source"] == "node globals"

    def test_the_reason_is_carried_into_the_report(self, report_block, tmp_path, clean_source):
        """Without the reason, `unrun` is unactionable — 'set SNYK_TOKEN' is the whole point."""
        _, report = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), self.SKIPPED],
        )
        unrun = next(s for s in report["sources"] if s["status"] == "unrun")
        assert unrun["reason"] == "no SNYK_TOKEN"

    def test_unrun_is_distinct_from_no_output(self, report_block, tmp_path, clean_source):
        """The distinction IS the requirement: one scanner is broken, the other unconfigured."""
        _, report = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), ("osv", "recipe lockfiles"), self.SKIPPED],
        )
        by_status = {s["status"] for s in report["sources"]}
        assert by_status == {"ok", "no-output", "unrun"}
        assert report["coverage"]["no_output"] == ["osv"], "a skip is not a broken scanner"
        assert report["coverage"]["unrun"] == ["snyk"]

    def test_unrun_counts_as_attempted_but_uncovered(self, report_block, tmp_path, clean_source):
        """`attempted` is what we COMMITTED to; `reported` is what actually covered us."""
        _, report = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), self.SKIPPED],
        )
        assert report["coverage"]["attempted"] == 2
        assert report["coverage"]["reported"] == 1

    def test_the_operator_is_told_by_name_and_reason(self, report_block, tmp_path, clean_source):
        stdout, _ = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), self.SKIPPED],
        )
        assert "1 scanner(s) did not run" in stdout
        assert "snyk · node globals" in stdout
        assert "no SNYK_TOKEN" in stdout

    def test_a_skip_alone_does_not_read_as_a_broken_scanner(
        self, report_block, tmp_path, clean_source
    ):
        stdout, _ = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), self.SKIPPED],
        )
        assert "produced NO parseable output" not in stdout

    def test_everything_skipped_is_not_coverage(self, report_block, tmp_path):
        """No scanner ran at all. This must read exactly as loudly as the no-output case."""
        stdout, report = run_report(
            report_block, tmp_path, [],
            [("snyk", "node globals", "unrun", "no SNYK_TOKEN"),
             ("socket", "node globals", "unrun", "no SOCKET_CLI_API_TOKEN")],
        )
        assert report["covered"] is False
        assert "NO COVERAGE" in stdout
        assert "no high/critical advisories" not in stdout


class TestTheGuardsActuallyRecordTheSkip:
    """End-to-end through bash, not just the report block.

    The reporting half can be perfect and the bug still live: the ledger entry has to be WRITTEN at
    each early return, and every one of those guards sat before the ledger write. Driving the real
    script with no scanners on PATH is the only way to prove the guards, not the parser.
    """

    @pytest.fixture(scope="class")
    def bare_run(self, tmp_path_factory):
        home = tmp_path_factory.mktemp("scanhome")
        # Give the scan something to look AT, or snyk_scan/socket_scan return at their
        # "nothing to scan" guard and never reach the token/binary guards under test. A real build
        # image always has both of these.
        (home / ".local/share/mise/installs/node/22.0.0/lib/node_modules/pkg").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        # /usr/bin:/bin has the shell and python3 the script needs, but none of the four scanners —
        # exactly the credential-free build case the report used to render as clean.
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            capture_output=True, text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        )
        report = home / ".harnessed" / "scan-report.json"
        assert report.is_file(), f"no report written.\nstdout:\n{proc.stdout}\n{proc.stderr}"
        return proc, json.loads(report.read_text())

    def test_the_scan_always_exits_zero(self, bare_run):
        """Advisory, never gating — including when nothing could run."""
        proc, _ = bare_run
        assert proc.returncode == 0

    def test_every_absent_scanner_is_recorded_as_unrun(self, bare_run):
        """The bug: none of these wrote a ledger line, so all four vanished from the report while
        the console still listed them — 'a build can run 6 scanners, report on 1, and print a green
        all-clear'."""
        _, report = bare_run
        unrun = {s["tool"] for s in report["sources"] if s["status"] == "unrun"}
        assert {"snyk", "socket", "osv", "pip-audit"} == unrun, (
            f"every skipped scanner must be declared unrun, got sources: {report['sources']}"
        )

    def test_the_console_skip_notice_now_has_a_report_counterpart(self, bare_run):
        """The bead's precise complaint: snyk/socket announce their skip on stdout but contributed
        nothing to scan-report.json, so a consumer of that file could not tell a skipped scanner
        from one that never existed."""
        proc, report = bare_run
        assert "snyk: skipped" in proc.stdout
        assert any(s["tool"] == "snyk" and s["status"] == "unrun" for s in report["sources"])

    def test_every_unrun_entry_states_why(self, bare_run):
        _, report = bare_run
        for s in report["sources"]:
            if s["status"] == "unrun":
                assert s.get("reason"), f"unrun entry without a reason: {s}"

    def test_a_scan_with_nothing_running_is_not_reported_as_covered(self, bare_run):
        """The headline false-clean: no scanner ran, so this is not a clean result."""
        _, report = bare_run
        assert report["covered"] is False
        assert "NO COVERAGE" in bare_run[0].stdout
        assert "no high/critical advisories" not in bare_run[0].stdout


class TestTheAllClearIsQualifiedWhenCoverageIsPartial:
    """The bead's headline: the build must NOT print a green all-clear on the strength of the
    scanners that happened to report, while others were silent or never ran."""

    def test_a_partial_scan_says_so_next_to_the_all_clear(
        self, report_block, tmp_path, clean_source
    ):
        stdout, _ = run_report(
            report_block, tmp_path, [clean_source],
            [("pip-audit", "python env"), ("osv", "recipe lockfiles"),
             ("snyk", "node globals", "unrun", "no SNYK_TOKEN")],
        )
        assert "no high/critical advisories" in stdout
        assert "NOT a full all-clear" in stdout, (
            "2 of 3 scanners contributed nothing — reporting that as a plain all-clear is the "
            "false clean this bead exists to remove"
        )

    def test_full_coverage_still_gets_an_unqualified_all_clear(
        self, report_block, tmp_path, clean_source
    ):
        """The qualifier must not become noise that everyone learns to ignore."""
        stdout, _ = run_report(
            report_block, tmp_path, [clean_source], [("pip-audit", "python env")]
        )
        assert "no high/critical advisories" in stdout
        assert "NOT a full all-clear" not in stdout

    def test_findings_present_means_no_all_clear_wording_at_all(self, report_block, tmp_path):
        """Uses snyk, not pip-audit: pip-audit's JSON carries no severity field, so its findings
        are all recorded `unknown` and can never be critical/high. A pip-audit payload therefore
        cannot exercise the flagged branch at all — the first draft of this test 'failed' for
        exactly that reason."""
        payload = tmp_path / "snyk.json"
        payload.write_text(json.dumps({
            "vulnerabilities": [
                {"id": "SNYK-1", "severity": "critical", "packageName": "evil"},
            ],
        }))
        stdout, _ = run_report(
            report_block, tmp_path, [("snyk", "node globals", str(payload))],
            [("snyk", "node globals"), ("osv", "recipe lockfiles", "unrun", "osv-scanner absent")],
        )
        assert "no high/critical advisories" not in stdout
        assert "evil" in stdout, "the finding itself must still be reported"


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
