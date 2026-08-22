"""osv-scanner's "nothing to scan" exit is a SKIP, not a broken scanner (catalog/base/harnessed-scan).

`osv-scanner scan source` exits **128** with "No package sources found" when the directories exist
but ship no lockfile — the normal case for a profile whose skills are plain markdown. It writes
nothing to stdout, so the manifest line is never written.

Before the fix only exit 124 (timeout) was special-cased. Everything else fell through to the
coverage reconciler, which can only read a missing manifest line one way:

    ⚠ 1 scanner(s) ran but produced NO parseable output — not covered by this result:
        osv · recipe lockfiles

That is the reconciler working exactly as designed (bd harnessed-wx9) on a bad input — 128 means
"nothing to look at", not "the scanner is broken". Crying wolf on every clean build is how a
coverage warning stops being read, which defeats the warning.

These drive the real bash script with a stub osv-scanner, because the bug lived in the bash half:
the summary heredoc never saw the exit code at all.
"""

import json
import os
import shutil
import subprocess

import pytest

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "catalog" / "base" / "harnessed-scan"

# Verbatim from osv-scanner 2.5.1 on a tree with no lockfile.
NO_SOURCES = "No package sources found, --help for usage information."


@pytest.fixture
def scan_env(tmp_path):
    """A fake $HOME with a skills/ dir, and a stub-only PATH so no real scanner runs."""
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "plain-markdown").mkdir(parents=True)
    (home / ".claude" / "skills" / "plain-markdown" / "SKILL.md").write_text("# no lockfile here\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return home, bin_dir


def stub(bin_dir, name, exit_code, stdout="", stderr=""):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\nprintf '%s'\nprintf '%s' >&2\nexit %d\n"
                    % (stdout, stderr, exit_code))
    path.chmod(0o755)


def run_scan(home, bin_dir):
    """Run harnessed-scan with only the stubs plus coreutils on PATH; return (stdout, report)."""
    env = dict(os.environ)
    env.update({"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bin_dir})
    # Token-gated scanners must stay out of this: they would try to reach the network.
    for var in ("SNYK_TOKEN", "SOCKET_CLI_API_TOKEN", "SOCKET_SECURITY_API_KEY"):
        env.pop(var, None)
    proc = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    report = json.loads((home / ".harnessed" / "scan-report.json").read_text())
    return proc.stdout, report


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
class TestNoLockfilesIsNotABrokenScanner:
    def test_exit_128_does_not_claim_the_scanner_produced_no_parseable_output(self, scan_env):
        """The regression. 128 must never reach the no-output bucket."""
        home, bin_dir = scan_env
        stub(bin_dir, "osv-scanner", 128, stderr=NO_SOURCES)
        stdout, report = run_scan(home, bin_dir)
        assert "produced NO parseable output" not in stdout
        assert "osv" not in report["coverage"]["no_output"]

    def test_exit_128_is_recorded_as_a_skip_with_a_reason(self, scan_env):
        """Still in the report — an operator must be able to see that osv looked and found nothing
        to scan, which is different from osv never having been installed."""
        home, bin_dir = scan_env
        stub(bin_dir, "osv-scanner", 128, stderr=NO_SOURCES)
        _, report = run_scan(home, bin_dir)
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert row["status"] == "unrun"
        # "no package sources", not "no lockfiles": 128 also fires when a lockfile IS present but
        # yields zero packages, and the reason an operator reads must not claim more than osv did.
        assert "no package sources" in row["reason"]

    def test_a_timeout_is_still_reported_as_a_timeout(self, scan_env):
        """124 keeps its own wording — a scanner cut off mid-run is a different fact from one that
        had nothing to scan, and collapsing them was never the fix."""
        home, bin_dir = scan_env
        stub(bin_dir, "osv-scanner", 124)
        _, report = run_scan(home, bin_dir)
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert "timed out" in row["reason"]

    def test_an_unexpected_failure_still_reads_as_no_output(self, scan_env):
        """The narrowing must stay narrow. A genuine crash (exit 1, nothing on stdout) is exactly
        what the no-output bucket exists for and must keep landing there."""
        home, bin_dir = scan_env
        stub(bin_dir, "osv-scanner", 1, stderr="panic: runtime error")
        stdout, report = run_scan(home, bin_dir)
        assert "osv" in report["coverage"]["no_output"]
        assert "produced NO parseable output" in stdout

    def test_a_timeout_that_left_partial_output_is_not_also_reported_as_a_result(self, scan_env):
        """The osv block is INLINE, so unlike snyk_scan and socket_scan it cannot `return` after
        recording a skip. A timeout that had already written some JSON therefore used to produce
        an unrun line AND a manifest line: one scanner, two rows, contradicting each other — and
        the `ok` row's findings came from a file the scanner never finished writing.

        `timeout` exits 124 having killed the child, so partial output on disk is the normal shape
        of this case, not a contrived one."""
        home, bin_dir = scan_env
        partial = json.dumps({"results": [{"packages": [
            {"package": {"name": "tar-fs"}, "groups": [{"max_severity": "9.8"}]}]}]})
        stub(bin_dir, "osv-scanner", 124, stdout=partial)
        _, report = run_scan(home, bin_dir)
        osv_rows = [r for r in report["sources"] if r["tool"] == "osv"]
        assert len(osv_rows) == 1, osv_rows
        assert osv_rows[0]["status"] == "unrun"
        assert "timed out" in osv_rows[0]["reason"]
        # A partial file must never be counted as a finished scan's findings.
        assert report["totals"] == {"critical": 0, "high": 0}

    def test_real_findings_are_still_parsed(self, scan_env):
        """Guard against fixing the warning by disabling the scanner."""
        home, bin_dir = scan_env
        payload = json.dumps({"results": [{"packages": [{
            "package": {"name": "tar-fs"},
            "groups": [{"max_severity": "8.1"}],
        }]}]})
        stub(bin_dir, "osv-scanner", 0, stdout=payload)
        _, report = run_scan(home, bin_dir)
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert row["status"] == "ok"
        assert row["high"] == 1
        assert row["notable"] == ["tar-fs"]
