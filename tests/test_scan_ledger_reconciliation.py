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

    def test_a_pair_that_both_reported_and_skipped_yields_only_the_skip(self, block, tmp_path):
        """P1. A skip means the run did not complete, so whatever output it left is partial.
        Reporting partial findings as a finished result is the worse of the two errors, so the
        reasoned skip wins and the `ok` row is dropped.

        Reachable through osv before the fix: unlike snyk_scan and socket_scan, the osv block is
        inline and cannot `return`, so a timeout that still left partial JSON recorded an unrun
        line AND a manifest line — one scanner, reported twice, contradicting itself."""
        payload = tmp_path / "osv.json"
        payload.write_text(json.dumps({"results": [{"packages": [
            {"package": {"name": "tar-fs"}, "groups": [{"max_severity": "9.8"}]}]}]}))
        stdout, report = run(
            block, tmp_path,
            ["osv|recipe lockfiles", "osv|recipe lockfiles|unrun|timed out after 120s"],
            [("osv", "recipe lockfiles", str(payload))],
        )
        osv_rows = [r for r in report["sources"] if r["tool"] == "osv"]
        assert len(osv_rows) == 1, osv_rows
        assert osv_rows[0]["status"] == "unrun"
        # And the partial finding must not reach the totals as though the scan had finished.
        assert report["totals"] == {"critical": 0, "high": 0}
        assert "timed out" in stdout

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

    def run_scan(self, tmp_path, skill_dir_name, with_socket=False):
        """Run the real script against a fake $HOME holding a recipe whose directory name carries
        a separator, with stub scanners so the `recipe: <name>` label is actually reached.

        `with_socket` drives socket's SUCCESS path, which is the only way to reach socket's
        MANIFEST write. Without it socket is absent and goes through `record_skip` instead —
        which is how the socket manifest writer stayed unexercised while this file looked like it
        covered the separator class.
        """
        home = tmp_path / "home"
        nm = home / ".claude" / "skills" / skill_dir_name / "node_modules" / "left-pad"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "left-pad", "version": "1.0.0"}')
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        snyk = bin_dir / "snyk"
        snyk.write_text("#!/usr/bin/env bash\necho '{\"vulnerabilities\":[]}'\n")
        snyk.chmod(0o755)
        env_extra = "unset SOCKET_CLI_API_TOKEN SOCKET_SECURITY_API_KEY\n"
        if with_socket:
            # Dispatch on the subcommand: `organization list`, `scan create`, then `scan view`.
            socket = bin_dir / "socket"
            socket.write_text(
                "#!/usr/bin/env bash\n"
                'case "$1 $2" in\n'
                '  "organization list") echo \'{"ok":true,"data":{"organizations":'
                '[{"slug":"acme"}]}}\' ;;\n'
                '  "scan create")      echo \'{"ok":true,"data":{"id":"scan-1"}}\' ;;\n'
                '  "scan view")        echo \'{"ok":true,"data":[{"name":"left-pad",'
                '"version":"1.0.0","alerts":[]}]}\' ;;\n'
                "  *) exit 1 ;;\n"
                "esac\n"
            )
            socket.chmod(0o755)
            env_extra = "export SOCKET_CLI_API_TOKEN=stub\n"
        runner = tmp_path / "run.sh"
        runner.write_text(
            "#!/usr/bin/env bash\n"
            'export HOME="%s"\nexport SNYK_TOKEN=stub\nexport PATH="%s:/usr/bin:/bin"\n'
            "%s"
            'exec bash "%s"\n' % (home, bin_dir, env_extra, SCRIPT)
        )
        proc = subprocess.run(["bash", str(runner)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return json.loads((home / ".harnessed" / "scan-report.json").read_text())

    @pytest.mark.parametrize("name", ["has|pipe", "a|b|c"])
    def test_the_socket_manifest_write_sanitizes_its_label_too(self, tmp_path, name):
        """C1. snyk and socket write the manifest with the identical pattern; only snyk's was
        exercised. In a MANIFEST line the field a separator shifts is the third one — a FILE PATH —
        so the parser is handed a path that points nowhere and the scanner silently contributes
        nothing while having run perfectly."""
        report = self.run_scan(tmp_path, name, with_socket=True)
        recipe_rows = {r["tool"]: r for r in report["sources"]
                       if r["source"].startswith("recipe: ")}
        assert set(recipe_rows) == {"snyk", "socket"}, report["sources"]
        assert recipe_rows["socket"]["status"] == "ok", recipe_rows["socket"]
        assert "|" not in recipe_rows["socket"]["source"]
        assert report["coverage"]["no_output"] == [], report["sources"]

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


class TestEveryPathOutOfAnAttemptRecordsAResultOrAReason:
    """The invariant the whole reconciler rests on.

    Once a scanner writes its attempt line, every path out of it must write a MANIFEST line or
    call `record_skip`. A path that does neither leaves an attempt with no result and no reason,
    which the reconciler can only read as "ran and produced nothing" — a broken scanner.

    Four early returns violated it, all pre-existing: socket bailing with no org slug, socket
    bailing when `scan create` returns no id, and the manifest-synthesis step in BOTH functions.
    The visible symptom is the same contradiction this change exists to remove — the console
    printed "skipped" while scan-report.json said the scanner was broken.
    """

    def run_with_socket_stub(self, tmp_path, body):
        home = tmp_path / "home"
        nm = home / ".local" / "share" / "mise" / "installs" / "node" / "22" / "lib" \
            / "node_modules" / "npm"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "npm", "version": "11.18.0"}')
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        socket = bin_dir / "socket"
        socket.write_text("#!/usr/bin/env bash\n" + body)
        socket.chmod(0o755)
        runner = tmp_path / "run.sh"
        runner.write_text(
            "#!/usr/bin/env bash\n"
            'export HOME="%s"\nexport PATH="%s:/usr/bin:/bin"\n'
            "export SOCKET_CLI_API_TOKEN=stub\nunset SNYK_TOKEN SOCKET_CLI_ORG_SLUG\n"
            'exec bash "%s"\n' % (home, bin_dir, SCRIPT)
        )
        proc = subprocess.run(["bash", str(runner)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        report = json.loads((home / ".harnessed" / "scan-report.json").read_text())
        return proc.stdout, report

    def test_no_org_for_the_token_is_a_reasoned_skip_not_a_broken_scanner(self, tmp_path):
        """`socket organization list` returns no organizations — a token with no org attached."""
        stdout, report = self.run_with_socket_stub(
            tmp_path, 'echo \'{"ok":true,"data":{"organizations":[]}}\'\n')
        row = next(r for r in report["sources"] if r["tool"] == "socket")
        assert row["status"] == "unrun", row
        assert "organization" in row["reason"], row
        assert report["coverage"]["no_output"] == [], report["sources"]
        # The console already said "skipped"; the report must not contradict it.
        assert "skipped" in stdout

    def test_a_failed_scan_create_is_a_reasoned_skip_not_a_broken_scanner(self, tmp_path):
        """The org lookup succeeds, then `scan create` returns no id — a quota or API failure."""
        stdout, report = self.run_with_socket_stub(tmp_path, (
            'case "$1 $2" in\n'
            '  "organization list") echo \'{"ok":true,"data":{"organizations":'
            '[{"slug":"acme"}]}}\' ;;\n'
            '  "scan create")      echo \'{"ok":false,"message":"quota exceeded"}\' ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n"
        ))
        row = next(r for r in report["sources"] if r["tool"] == "socket")
        assert row["status"] == "unrun", row
        assert "scan id" in row["reason"], row
        assert report["coverage"]["no_output"] == [], report["sources"]
        assert "skipped" in stdout

    def test_no_scanner_is_ever_left_as_an_attempt_with_neither_result_nor_reason(self, tmp_path):
        """The property itself, stated once: whatever socket does, the report never describes it
        as having run and produced nothing when it in fact bailed with a reason."""
        bodies = ['echo \'{"ok":true,"data":{"organizations":[]}}\'\n',
                  'echo \'{"ok":false}\'\n',
                  "exit 1\n",
                  'echo "not json at all"\n']
        for i, body in enumerate(bodies):
            case = tmp_path / ("case%d" % i)
            case.mkdir()
            _, report = self.run_with_socket_stub(case, body)
            assert report["coverage"]["no_output"] == [], (body, report["sources"])


class TestAFailedManifestSynthesisIsAlsoAReasonedSkip:
    """The two paths the socket-stub tests above CANNOT reach.

    `synth_manifest_dir` returns non-zero only when `mktemp -d` fails, and every other test in this
    file arranges for it to succeed — the socket stubs divert later, at `scan create`, and snyk is
    disabled by unsetting its token. So both `synth_manifest_dir || record_skip` guards were
    reachable in production and unreachable in the suite: deleting either left every test green.

    Forcing the failure needs `mktemp -d` to fail for the scanner but NOT for the script's own
    WORK directory, which is created first. Hence a counting stub: the first call delegates to the
    real mktemp, every later one fails.
    """

    def run_with_failing_mktemp(self, tmp_path, tool):
        home = tmp_path / "home"
        nm = home / ".local" / "share" / "mise" / "installs" / "node" / "22" / "lib" \
            / "node_modules" / "npm"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "npm", "version": "11.18.0"}')
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        counter = tmp_path / "mktemp.count"
        mktemp = bin_dir / "mktemp"
        mktemp.write_text(
            "#!/usr/bin/env bash\n"
            'n=$(cat "%s" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "%s"\n'
            '# Call 1 is the scan script\'s own WORK dir and must succeed, or nothing runs at all.\n'
            'if [ "$n" -gt 1 ] && [ "$1" = "-d" ]; then exit 1; fi\n'
            'exec /usr/bin/mktemp "$@"\n' % (counter, counter)
        )
        mktemp.chmod(0o755)
        # A scanner binary that would succeed if it were ever reached.
        stub = bin_dir / tool
        stub.write_text("#!/usr/bin/env bash\necho '{\"ok\":true,\"data\":[]}'\n")
        stub.chmod(0o755)
        token = ("export SNYK_TOKEN=stub\nunset SOCKET_CLI_API_TOKEN SOCKET_SECURITY_API_KEY\n"
                 if tool == "snyk" else
                 "export SOCKET_CLI_API_TOKEN=stub\nexport SOCKET_CLI_ORG_SLUG=acme\n"
                 "unset SNYK_TOKEN\n")
        runner = tmp_path / "run.sh"
        runner.write_text(
            "#!/usr/bin/env bash\n"
            'export HOME="%s"\nexport PATH="%s:/usr/bin:/bin"\n%s'
            'exec bash "%s"\n' % (home, bin_dir, token, SCRIPT)
        )
        proc = subprocess.run(["bash", str(runner)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return json.loads((home / ".harnessed" / "scan-report.json").read_text())

    def test_snyk_records_a_reason_when_the_manifest_cannot_be_synthesized(self, tmp_path):
        report = self.run_with_failing_mktemp(tmp_path, "snyk")
        row = next(r for r in report["sources"] if r["tool"] == "snyk")
        assert row["status"] == "unrun", row
        assert "synthesize" in row["reason"], row
        assert report["coverage"]["no_output"] == [], report["sources"]

    def test_socket_records_a_reason_when_the_manifest_cannot_be_synthesized(self, tmp_path):
        report = self.run_with_failing_mktemp(tmp_path, "socket")
        row = next(r for r in report["sources"] if r["tool"] == "socket")
        assert row["status"] == "unrun", row
        assert "synthesize" in row["reason"], row
        assert report["coverage"]["no_output"] == [], report["sources"]


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
