"""Attempt/skip reconciliation in catalog/base/harnessed-scan.

Every scanner announces its attempt to the ledger BEFORE it runs, then calls `record_skip` if it
bails. So a scanner that timed out, or had nothing to scan, writes two lines about itself:

    snyk|node globals                              <- the attempt
    snyk|node globals|unrun|timed out after 120s   <- the bail

Read literally that is two rows in `sources[]` making contradictory claims about one scanner: an
actionable skip carrying its reason, and a "ran but produced NO parseable output" row, which
means the scanner is probably broken. The reasoned line is strictly more informative, so it wins.

The second half of this file is the reason it is a separate file from the acknowledgment tests:
the ledger is a HAND-ROLLED `|`-separated format with no escaping, parsed by `str.split("|", 3)`.
That is the Tier-3 failure mode — input the parser accepts but no example-based test ever feeds
it. The properties below fuzz the field values instead of enumerating them.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

SCRIPT = Path(__file__).resolve().parents[1] / "catalog" / "base" / "harnessed-scan"


def heredoc() -> str:
    src = SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", src[src.index("HARNESSED_SCAN_REPORT"):], re.S)
    assert match, "summary heredoc not found in harnessed-scan"
    return match.group(1)


@pytest.fixture(scope="module")
def block(tmp_path_factory):
    path = tmp_path_factory.mktemp("ledger") / "report.py"
    path.write_text(heredoc())
    return path


def run(block, tmp_path, ledger_lines, manifest_rows=()):
    """Drive the summary block over a raw ledger; return (stdout, report)."""
    manifest = tmp_path / "manifest"
    manifest.write_text("".join("%s|%s|%s\n" % r for r in manifest_rows))
    ledger = tmp_path / "attempts"
    ledger.write_text("".join(line + "\n" for line in ledger_lines))
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(block), str(manifest)],
        capture_output=True, text=True,
        env={"HARNESSED_SCAN_REPORT": str(out), "HARNESSED_SCAN_ATTEMPTS": str(ledger),
             "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, json.loads(out.read_text())


class TestASkippedScannerAppearsOnceWithItsReason:
    def test_an_unrun_line_wins_over_the_bare_attempt_for_the_same_pair(self, block, tmp_path):
        """L1. Two ledger lines about one scanner must not become two rows about one scanner."""
        _, report = run(block, tmp_path, [
            "osv|recipe lockfiles",
            "osv|recipe lockfiles|unrun|no lockfiles under skills/ or commands/ to scan",
        ])
        osv_rows = [r for r in report["sources"] if r["tool"] == "osv"]
        assert len(osv_rows) == 1
        assert osv_rows[0]["status"] == "unrun"
        assert "no lockfiles" in osv_rows[0]["reason"]

    def test_the_same_collapse_applies_to_every_scanner_timeout_path(self, block, tmp_path):
        """L2. This was latent for snyk/socket/pip-audit long before the osv change — each one
        printfs its attempt and only then records a timeout skip."""
        _, report = run(block, tmp_path, [
            "snyk|node globals",
            "snyk|node globals|unrun|timed out after 120s",
        ])
        rows = [r for r in report["sources"] if r["tool"] == "snyk"]
        assert len(rows) == 1
        assert rows[0]["status"] == "unrun"

    def test_the_summary_does_not_report_a_skipped_scanner_as_broken(self, block, tmp_path):
        stdout, _ = run(block, tmp_path, [
            "osv|recipe lockfiles",
            "osv|recipe lockfiles|unrun|nothing to scan",
        ])
        assert "produced NO parseable output" not in stdout
        assert "did not run" in stdout

    def test_a_scanner_that_attempted_and_produced_nothing_still_reads_no_output(
        self, block, tmp_path
    ):
        """L3. The narrowing must stay narrow — this row is what the reconciler exists for."""
        _, report = run(block, tmp_path, ["socket|node globals"])
        assert report["coverage"]["no_output"] == ["socket"]

    def test_a_skip_for_one_source_does_not_suppress_another_source_of_the_same_tool(
        self, block, tmp_path
    ):
        """The collapse keys on (tool, source), not tool. snyk scans several trees per run, and a
        skip on one must not silence a genuinely-broken scan of a different one."""
        _, report = run(block, tmp_path, [
            "snyk|node globals",
            "snyk|node globals|unrun|no SNYK_TOKEN",
            "snyk|recipe: serena",
        ])
        by_source = {r["source"]: r["status"] for r in report["sources"] if r["tool"] == "snyk"}
        assert by_source == {"node globals": "unrun", "recipe: serena": "no-output"}

    def test_a_reported_scanner_is_never_duplicated_by_its_attempt_line(self, block, tmp_path):
        """The pre-existing guard: a scanner with a manifest line is already an `ok` row."""
        payload = tmp_path / "pip.json"
        payload.write_text("[]")
        _, report = run(block, tmp_path, ["pip-audit|python env"],
                        [("pip-audit", "python env", str(payload))])
        rows = [r for r in report["sources"] if r["tool"] == "pip-audit"]
        assert len(rows) == 1
        assert rows[0]["status"] == "ok"


class TestTheHandRolledLedgerFormatSurvivesItsOwnInputs:
    """F3. `split("|", 3)` with no escaping, over strings the scanners supply."""

    def test_a_reason_containing_the_field_separator_does_not_shift_fields(self, block, tmp_path):
        """L4. maxsplit=3 keeps the whole tail as the reason. The bash half strips `|` from
        reasons, but the parser must not DEPEND on that — it is one edit away from not being true,
        and a shifted field would silently mis-attribute a skip to another scanner."""
        _, report = run(block, tmp_path, [
            "osv|recipe lockfiles|unrun|osv said: a|b|c",
        ])
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert row["source"] == "recipe lockfiles"
        assert row["reason"] == "osv said: a|b|c"

    def test_a_malformed_short_line_does_not_crash_the_reconciler(self, block, tmp_path):
        """L5. A tool name with no source field at all."""
        stdout, report = run(block, tmp_path, ["osv"])
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert row["source"] == ""
        assert "full report" in stdout

    def test_blank_and_whitespace_only_lines_produce_no_rows(self, block, tmp_path):
        """L6. An empty-tool row would print as ' · ' in the summary and count as an attempt."""
        _, report = run(block, tmp_path, ["", "   ", "osv|recipe lockfiles", ""])
        assert [r["tool"] for r in report["sources"]] == ["osv"]

    def test_an_unrun_line_with_no_reason_still_parses(self, block, tmp_path):
        _, report = run(block, tmp_path, ["osv|recipe lockfiles|unrun"])
        row = next(r for r in report["sources"] if r["tool"] == "osv")
        assert row["status"] == "unrun"
        assert row["reason"] == ""
        assert "no reason recorded" in run(block, tmp_path, ["osv|recipe lockfiles|unrun"])[0]

    # Field values a scanner label or reason could realistically carry. `|` is deliberately IN the
    # alphabet: it is the one character that breaks a `|`-separated line format, and the contract
    # below differs between the leading fields and the trailing one.
    FIELD = st.text(alphabet=st.sampled_from(list("abz 019-:./|")), min_size=0, max_size=12)
    # Leading fields, as the WRITER guarantees them — `nosep` strips the separator before either
    # ledger is touched, so the parser is only ever handed separator-free tool and source values.
    # Fuzzing them with `|` here would test a contract the writer does not offer; the guarantee
    # itself is tested against the real bash in TestTheWriterNeverEmitsASeparator below.
    SAFE_FIELD = st.text(alphabet=st.sampled_from(list("abz 019-:./")), min_size=0, max_size=12)

    @settings(max_examples=200, deadline=None)
    @given(tool=FIELD, source=FIELD, reason=FIELD)
    def test_the_reconciler_never_crashes_and_always_writes_a_report(
        self, block, tmp_path_factory, tool, source, reason
    ):
        """The property that matters even on input the writer promises never to emit: whatever the
        three fields contain, the block exits 0 and produces a parseable report. A crash here means
        a build prints a python traceback instead of a supply-chain summary."""
        tmp = tmp_path_factory.mktemp("prop")
        line = "%s|%s|unrun|%s" % (tool, source, reason)
        _, report = run(block, tmp, [line])
        assert report["gating"] == 0
        assert isinstance(report["sources"], list)

    @settings(max_examples=200, deadline=None)
    @given(tool=SAFE_FIELD, source=SAFE_FIELD)
    def test_an_unrun_line_always_suppresses_the_matching_attempt(
        self, block, tmp_path_factory, tool, source
    ):
        """The collapse must hold for ALL field values, not just the ones I thought to type."""
        tmp = tmp_path_factory.mktemp("prop")
        _, report = run(block, tmp, ["%s|%s" % (tool, source),
                                     "%s|%s|unrun|why" % (tool, source)])
        assert report["coverage"]["no_output"] == []
        assert len(report["sources"]) == 1
        assert report["sources"][0]["status"] == "unrun"

    @settings(max_examples=100, deadline=None)
    @given(reason=FIELD)
    def test_a_reason_is_carried_through_verbatim_after_the_third_separator(
        self, block, tmp_path_factory, reason
    ):
        """maxsplit=3 is load-bearing. Drop it and any `|` in a reason truncates it silently."""
        tmp = tmp_path_factory.mktemp("prop")
        _, report = run(block, tmp, ["osv|recipe lockfiles|unrun|%s" % reason])
        assert report["sources"][0]["reason"] == reason


class TestTheWriterNeverEmitsASeparator:
    """The guarantee the parser rests on, tested against the real bash rather than assumed.

    Found by the property test above: `record_skip` used to strip `|` from the reason and NOT from
    the label, and one label is `recipe: $(basename …)` — a directory name a recipe controls. A `|`
    in it shifted every later field, so the unrun line stopped reading as unrun and the scanner
    reappeared in the summary as "probably broken". The manifest writer had the same defect one
    field further along, where the shifted field is a FILE PATH.
    """

    def run_scan(self, tmp_path, skill_dir_name):
        """Run the real script against a fake $HOME holding a recipe whose directory name carries
        a separator, with a stub snyk so the `recipe: <name>` label is actually reached."""
        home = tmp_path / "home"
        nm = home / ".claude" / "skills" / skill_dir_name / "node_modules" / "left-pad"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "left-pad", "version": "1.0.0"}')
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        snyk = bin_dir / "snyk"
        snyk.write_text("#!/usr/bin/env bash\necho '{\"vulnerabilities\":[]}'\n")
        snyk.chmod(0o755)
        runner = tmp_path / "run.sh"
        runner.write_text(
            "#!/usr/bin/env bash\n"
            'export HOME="%s"\nexport SNYK_TOKEN=stub\nexport PATH="%s:/usr/bin:/bin"\n'
            "unset SOCKET_CLI_API_TOKEN SOCKET_SECURITY_API_KEY\n"
            'exec bash "%s"\n' % (home, bin_dir, SCRIPT)
        )
        proc = subprocess.run(["bash", str(runner)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return json.loads((home / ".harnessed" / "scan-report.json").read_text())

    @pytest.mark.parametrize("name", ["has|pipe", "a|b|c", "|leading"])
    def test_a_separator_in_a_recipe_name_does_not_corrupt_the_report(self, tmp_path, name):
        """The PROPERTY, not the mechanics: in this fixture nothing is broken, so the report must
        say nothing is broken.

        The first version of this test asserted only that snyk's own row looked right. That
        checked the MANIFEST writer and left `record_skip` completely uncovered — snyk succeeds
        here, so the skip path is never taken through it — and the mutation run duly reported the
        original defect as a survivor. socket is absent in this fixture, so it goes through
        `record_skip` with the same pipe-bearing label; unsanitized, its `unrun` marker lands in
        the wrong field and it is reported as a scanner that ran and broke.
        """
        report = self.run_scan(tmp_path, name)
        assert report["coverage"]["no_output"] == [], report["sources"]
        for row in report["sources"]:
            assert "|" not in row["tool"], row
            assert "|" not in row["source"], row
            assert row["status"] in ("ok", "unrun"), row
        # Every scanner that looked at the recipe tree names it by its sanitized label.
        recipe_rows = [r for r in report["sources"] if r["source"].startswith("recipe: ")]
        assert {r["tool"] for r in recipe_rows} == {"snyk", "socket"}, recipe_rows
        assert next(r for r in recipe_rows if r["tool"] == "snyk")["status"] == "ok"
        assert next(r for r in recipe_rows if r["tool"] == "socket")["status"] == "unrun"

    def test_a_plain_recipe_name_is_unchanged(self, tmp_path):
        """Guard against fixing the corruption by mangling every label."""
        report = self.run_scan(tmp_path, "serena")
        snyk_rows = [r for r in report["sources"] if r["tool"] == "snyk"]
        assert [r["source"] for r in snyk_rows] == ["recipe: serena"]


class TestTheScanStaysAdvisory:
    """N1. Nothing in this change may start gating a build."""

    def test_gating_is_zero_even_with_findings(self, block, tmp_path):
        payload = tmp_path / "snyk.json"
        payload.write_text(json.dumps({"vulnerabilities": [
            {"id": "SNYK-JS-X-1", "packageName": "x", "severity": "critical"}
        ]}))
        stdout, report = run(block, tmp_path, ["snyk|node globals"],
                             [("snyk", "node globals", str(payload))])
        assert report["gating"] == 0
        assert report["advisory"] is True
        assert "0 gating" in stdout
