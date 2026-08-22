"""Known-unfixable advisories in catalog/base/harnessed-scan (ACKNOWLEDGED).

Some advisories have no patched release anywhere upstream, so no pin, bump, or removal clears
them. brace-expansion is the standing case: npm 11.18.0 (the base image pin), 11.19.0, and 12.0.2
all bundle 5.0.7, and the fix landed in 5.0.9. Reporting those two HIGHs on every build is noise
that trains people to ignore the scan.

The trap these tests pin down: an acknowledgment list is a security control pointed at its own
scanner, so both failure directions are real.

  * Too broad  — keying by PACKAGE blinds the scan to the NEXT CVE in the same dependency.
  * Too silent — a finding that vanishes from the totals with no trace is indistinguishable from
                 a scanner that never looked.

So the list is keyed by advisory ID (self-expiring: a fixed release stops emitting the id, a new
advisory carries a different one) and every hit is printed and written to scan-report.json.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "catalog" / "base" / "harnessed-scan"

# Both brace-expansion advisories bundled by every published npm, with their CVE aliases.
BRACE_GHSA = "GHSA-mh99-v99m-4gvg"
BRACE_CVE = "CVE-2026-14257"


def _heredoc() -> str:
    src = SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", src[src.index("HARNESSED_SCAN_REPORT"):], re.S)
    assert match, "summary heredoc not found in harnessed-scan"
    return match.group(1)


@pytest.fixture
def parsers():
    """Exec the heredoc's function defs. Function-scoped, NOT module-scoped: `acknowledged_hits`
    is module-level accumulator state in that block, so a shared namespace would leak hits from
    one test into the next."""
    ns: dict = {}
    exec(_heredoc().split("with open(sys.argv[1])")[0], ns)  # noqa: S102 — exec is the mechanism: the parser lives in a bash heredoc and has no import surface
    return ns


def snyk_vuln(vid, pkg="brace-expansion", severity="high", identifiers=None):
    return {"id": vid, "packageName": pkg, "severity": severity,
            "identifiers": identifiers or {}}


class TestAcknowledgedAdvisoriesAreExcluded:
    def test_matched_by_snyk_native_id(self, parsers):
        """The ACKNOWLEDGED map is keyed by upstream ids, but snyk reports its own `SNYK-JS-*` id
        first. `advisory_ids` unions both, so an entry lands whichever one snyk leads with."""
        doc = {"vulnerabilities": [snyk_vuln(BRACE_GHSA)]}
        assert parsers["parse_snyk"](doc) == []
        assert parsers["acknowledged_hits"] == {BRACE_GHSA: "brace-expansion"}

    def test_matched_by_cve_identifier(self, parsers):
        """Snyk's `identifiers` key set is not guaranteed — CVE is present where GHSA is absent."""
        doc = {"vulnerabilities": [
            snyk_vuln("SNYK-JS-BRACEEXPANSION-13579", identifiers={"CVE": [BRACE_CVE]})
        ]}
        assert parsers["parse_snyk"](doc) == []
        assert parsers["acknowledged_hits"] == {BRACE_CVE: "brace-expansion"}

    def test_matched_by_ghsa_identifier(self, parsers):
        doc = {"vulnerabilities": [
            snyk_vuln("SNYK-JS-BRACEEXPANSION-13579", identifiers={"GHSA": [BRACE_GHSA]})
        ]}
        assert parsers["parse_snyk"](doc) == []
        assert parsers["acknowledged_hits"] == {BRACE_GHSA: "brace-expansion"}


class TestTheListDoesNotOverreach:
    def test_a_new_advisory_against_the_same_package_is_still_reported(self, parsers):
        """THE test. Keying by package name would silence brace-expansion forever, including the
        next real CVE in it. Keying by advisory id means an unknown id reports at full severity."""
        doc = {"vulnerabilities": [snyk_vuln("GHSA-future-brace-rce", severity="critical")]}
        assert parsers["parse_snyk"](doc) == [("critical", "brace-expansion")]
        assert parsers["acknowledged_hits"] == {}

    def test_an_unrelated_package_is_untouched(self, parsers):
        doc = {"vulnerabilities": [snyk_vuln("SNYK-JS-LODASH-1", pkg="lodash")]}
        assert parsers["parse_snyk"](doc) == [("high", "lodash")]

    def test_a_mixed_project_keeps_the_unacknowledged_finding(self, parsers):
        doc = {"vulnerabilities": [
            snyk_vuln(BRACE_GHSA),
            snyk_vuln("SNYK-JS-LODASH-1", pkg="lodash", severity="critical"),
        ]}
        assert parsers["parse_snyk"](doc) == [("critical", "lodash")]
        assert list(parsers["acknowledged_hits"]) == [BRACE_GHSA]

    def test_every_entry_is_an_advisory_id_never_a_package_name(self, parsers):
        """A bare package name in the map would be an unbounded silence. Reject it structurally."""
        for key in parsers["ACKNOWLEDGED"]:
            assert re.match(r"^(GHSA-|CVE-|SNYK-)", key), key

    def test_a_repeated_hit_across_projects_is_counted_once(self, parsers):
        """snyk --json is a LIST when it detects multiple projects, and reports the same
        vulnerability once per project — mirroring the by_id dedup on the reported path."""
        doc = [{"vulnerabilities": [snyk_vuln(BRACE_GHSA)]},
               {"vulnerabilities": [snyk_vuln(BRACE_GHSA)]}]
        assert parsers["parse_snyk"](doc) == []
        assert parsers["acknowledged_hits"] == {BRACE_GHSA: "brace-expansion"}


class TestTheSameAdvisoryAgainstAnotherPackageIsStillReported:
    """A CVE can affect more than one package. Matching on the advisory ID ALONE would silence a
    finding against some other package that shares the advisory — and that one may well have a fix
    available, which is the entire justification for these entries. The package is a second
    necessary condition, never a key: it can only ever narrow what is acknowledged."""

    def test_a_known_id_against_a_different_package_is_reported(self, parsers):
        doc = {"vulnerabilities": [snyk_vuln(BRACE_GHSA, pkg="some-other-fork")]}
        assert parsers["parse_snyk"](doc) == [("high", "some-other-fork")]
        assert parsers["acknowledged_hits"] == {}

    def test_every_entry_names_the_package_it_applies_to(self, parsers):
        for key, value in parsers["ACKNOWLEDGED"].items():
            assert isinstance(value, tuple) and len(value) == 2, key
            assert value[0] == "brace-expansion", key


class TestScannerJsonIsNotTrustedToHaveAShape:
    """`identifiers` is JSON from another program. The obvious `for value in values or []` raises
    TypeError on two shapes that are perfectly valid JSON, and there is no handler anywhere above
    it — the summary block dies, the report is never written, and because the surrounding bash is
    `set -uo pipefail` WITHOUT -e, the scan still exits 0. A build would print no summary at all
    and read as though it had nothing to say."""

    @pytest.mark.parametrize("identifiers", [
        {"CVE": 12345},               # a number — TypeError: not iterable
        {"CVE": [["nested"]]},        # a nested list — TypeError: unhashable
        {"CVE": None},
        {"CVE": {}},
        {"CVE": [None, 1, "CVE-X"]},  # mixed
        [],                           # not a dict at all
        "CVE-2026-14257",             # a bare string where a dict is expected
        None,
    ])
    def test_a_hostile_identifiers_shape_does_not_raise(self, parsers, identifiers):
        doc = {"vulnerabilities": [snyk_vuln("SNYK-JS-X-1", identifiers=identifiers)]}
        assert parsers["parse_snyk"](doc) == [("high", "brace-expansion")]

    def test_a_bare_string_identifier_matches_instead_of_iterating_characters(self, parsers):
        """The quiet one. `for value in "CVE-2026-14257"` does not crash — it walks CHARACTERS, so
        the advisory silently never matches and the entry looks broken rather than absent."""
        doc = {"vulnerabilities": [
            snyk_vuln("SNYK-JS-X-1", identifiers={"CVE": BRACE_CVE})
        ]}
        assert parsers["parse_snyk"](doc) == []
        assert parsers["acknowledged_hits"] == {BRACE_CVE: "brace-expansion"}

    def test_a_non_string_id_can_never_be_acknowledged_but_is_still_reported(self, parsers):
        """Fails toward REPORTING, which is the only safe direction for a suppression mechanism:
        a junk id cannot collide with an ACKNOWLEDGED key, so the finding survives to the totals."""
        doc = {"vulnerabilities": [{"id": 99, "packageName": "brace-expansion",
                                    "severity": "high"}]}
        assert parsers["parse_snyk"](doc) == [("high", "brace-expansion")]
        assert parsers["acknowledged_hits"] == {}


class TestThirdPartyPackageNamesAreBoundedBeforeTheyArePrinted:
    """Package names arrive from scanner output — ultimately from whoever published the package —
    and reach a build console (a CI log, public for a public repo) and scan-report.json. Nothing
    upstream bounds or escapes them."""

    def test_control_characters_are_stripped(self, parsers):
        doc = {"vulnerabilities": [snyk_vuln("SNYK-X", pkg="evil\x1b[2Jname\n")]}
        (_, pkg), = parsers["parse_snyk"](doc)
        assert "\x1b" not in pkg and "\n" not in pkg
        assert pkg == "evil[2Jname"

    def test_an_absurdly_long_name_is_truncated(self, parsers):
        doc = {"vulnerabilities": [snyk_vuln("SNYK-X", pkg="a" * 5000)]}
        (_, pkg), = parsers["parse_snyk"](doc)
        assert len(pkg) <= 70, len(pkg)
        assert pkg.endswith("…")

    def test_the_pre_existing_notable_path_is_bounded_too(self, tmp_path):
        """`notable[:4]` bounds how MANY names print, never how long each is. Guarding only the new
        acknowledged line would leave the identical hole one row higher.

        Driven through **osv**, deliberately. The first version of this test used a snyk payload
        and the mutation run reported the notable guard as a SURVIVOR — because `parse_snyk`
        already sanitizes `pkg` upstream for the acknowledgment check, so on that one path the
        guard is redundant and removing it changes nothing. It is load-bearing for the three
        parsers that do NOT pre-sanitize: osv, socket and pip-audit. Testing the path where a
        guard happens to be redundant proves nothing about the paths where it is not.
        """
        block = tmp_path / "report.py"
        block.write_text(_heredoc())
        payload = tmp_path / "osv.json"
        payload.write_text(json.dumps({"results": [{"packages": [
            {"package": {"name": "b" * 5000 + "\x1b[2J"},
             "groups": [{"max_severity": "9.8"}]}
        ]}]}))
        manifest = tmp_path / "manifest"
        manifest.write_text("osv|recipe lockfiles|%s\n" % payload)
        ledger = tmp_path / "attempts"
        ledger.write_text("osv|recipe lockfiles\n")
        out = tmp_path / "report.json"
        proc = subprocess.run(
            [sys.executable, str(block), str(manifest)],
            capture_output=True, text=True,
            env={"HARNESSED_SCAN_REPORT": str(out), "HARNESSED_SCAN_ATTEMPTS": str(ledger),
                 "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 0, proc.stderr
        notable = json.loads(out.read_text())["sources"][0]["notable"]
        assert len(notable) == 1
        assert len(notable[0]) <= 70, len(notable[0])
        assert "\x1b" not in notable[0]
        assert "\x1b" not in proc.stdout


class TestAcknowledgedIsNeverSilent:
    """Excluded from the totals, but always named. The printed list is the audit trail that lets a
    reader check the claim instead of trusting a number that quietly got smaller."""

    def _run(self, tmp_path, vulns):
        block = tmp_path / "report.py"
        block.write_text(_heredoc())
        payload = tmp_path / "snyk.json"
        payload.write_text(json.dumps({"vulnerabilities": vulns}))
        manifest = tmp_path / "manifest"
        manifest.write_text("snyk|node globals|%s\n" % payload)
        ledger = tmp_path / "attempts"
        ledger.write_text("snyk|node globals\n")
        out = tmp_path / "report.json"
        proc = subprocess.run(
            [sys.executable, str(block), str(manifest)],
            capture_output=True, text=True,
            env={"HARNESSED_SCAN_REPORT": str(out), "HARNESSED_SCAN_ATTEMPTS": str(ledger),
                 "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout, json.loads(out.read_text())

    def test_the_summary_names_the_advisory_and_the_reason(self, tmp_path):
        stdout, _ = self._run(tmp_path, [snyk_vuln(BRACE_GHSA)])
        assert "acknowledged" in stdout
        assert BRACE_GHSA in stdout
        assert "brace-expansion" in stdout

    def test_the_report_records_id_package_and_reason(self, tmp_path):
        _, report = self._run(tmp_path, [snyk_vuln(BRACE_GHSA)])
        assert report["acknowledged"] == [
            {"id": BRACE_GHSA, "package": "brace-expansion",
             "reason": "brace-expansion <5.0.9 DoS; every npm release bundles 5.0.7"}
        ]

    def test_totals_exclude_the_acknowledged_high(self, tmp_path):
        _, report = self._run(tmp_path, [snyk_vuln(BRACE_GHSA)])
        assert report["totals"] == {"critical": 0, "high": 0}

    def test_a_scan_whose_only_findings_are_acknowledged_reads_clean(self, tmp_path):
        """The whole point of (c): with corepack gone and these two acknowledged, a normal build
        prints the all-clear line instead of a table nobody can act on."""
        stdout, _ = self._run(tmp_path, [snyk_vuln(BRACE_GHSA)])
        assert "no high/critical advisories" in stdout
        assert "NOT a full all-clear" not in stdout

    def test_a_clean_scan_prints_no_acknowledged_line_at_all(self, tmp_path):
        stdout, report = self._run(tmp_path, [])
        assert "acknowledged" not in stdout
        assert report["acknowledged"] == []
