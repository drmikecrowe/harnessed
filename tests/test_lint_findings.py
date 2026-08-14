"""The fail-closed contract of `tools/lint-findings.py`, the gate's finding-level differ (#369).

That script decides whether the lint/type gate passes, so its own failure modes matter more than
most code here: every one of them is silent. A malformed record that slips through does not crash —
it produces an identity like "\\t\\t" that every other malformed record also matches, collapses them
into one entry, and makes real findings vanish from BOTH sides of the diff. The gate then reports a
clean comparison it never actually made.

The script's docstring promises "any missing file, malformed JSON, or unrecognised invocation exits
2". These tests are what make that a property rather than an intention. They were originally run as
a scratch probe while answering a review, which proved the behaviour once and then evaporated —
evidence that cannot be re-run from the repo is not evidence, so they live here now.

Exit status is the assertion, and 1 vs 2 is the distinction that matters: 1 means "findings were
ADDED" (an ordinary gate failure), so a schema error surfacing as 1 — which is what an uncaught
AttributeError would do — reads as a normal red build and gets triaged as a lint problem forever.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


# The SHIPPED script, loaded by path because its filename contains a dash and is not importable as a
# module. A paraphrase inlined here would drift from the real one and keep passing against a version
# nobody runs (same reasoning as test_live_gate_accounting.py's use of the real conftest).
_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "lint-findings.py"


def _load():
    spec = importlib.util.spec_from_file_location("lint_findings", _SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_findings = _load()


def _write(tmp_path: Path, payload: object) -> str:
    p = tmp_path / "findings.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def _exit_code(func, path: str) -> int:
    """Run a normalizer and return the process exit status it would produce (0 when it returns)."""
    try:
        func(path)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


class TestRuffSchemaIsRejectedNotAbsorbed:
    def test_a_non_mapping_record_exits_2(self, tmp_path):
        """Without this the `.get` call raises an uncaught AttributeError, which exits 1 — the
        gate's own "findings were added" status. A crash would be read as a normal red build."""
        path = _write(tmp_path, [["not", "a", "mapping"]])
        assert _exit_code(lint_findings.normalize_ruff, path) == 2

    def test_a_null_filename_exits_2(self, tmp_path):
        """Ruff 0.16 explicitly allows `filename` to be null rather than defaulting it, so this is
        reachable input. `or ""` would build an identity with an empty path."""
        path = _write(tmp_path, [{"filename": None, "code": "F401", "message": "x"}])
        assert _exit_code(lint_findings.normalize_ruff, path) == 2

    def test_a_blank_message_exits_2(self, tmp_path):
        path = _write(tmp_path, [{"filename": "a.py", "code": "F401", "message": "   "}])
        assert _exit_code(lint_findings.normalize_ruff, path) == 2

    def test_a_non_string_code_exits_2(self, tmp_path):
        """`code` is optional, which means absent-or-null — not any type. A truthy non-string would
        otherwise interpolate into the identity and differ between runs."""
        path = _write(tmp_path, [{"filename": "a.py", "code": {"a": 1}, "message": "m"}])
        assert _exit_code(lint_findings.normalize_ruff, path) == 2

    def test_a_json_object_instead_of_an_array_exits_2(self, tmp_path):
        path = _write(tmp_path, {"not": "an array"})
        assert _exit_code(lint_findings.normalize_ruff, path) == 2


class TestPyrightSchemaIsRejectedNotAbsorbed:
    def test_general_diagnostics_must_be_a_list(self, tmp_path):
        path = _write(tmp_path, {"generalDiagnostics": {"not": "a list"}})
        assert _exit_code(lint_findings.normalize_pyright, path) == 2

    def test_a_malformed_NON_error_record_still_exits_2(self, tmp_path):
        """Validation runs BEFORE the severity filter on purpose. Filtering first lets a malformed
        record through unexamined whenever its severity happens not to be `error`, so the schema
        problem surfaces only on the run where it also happens to be one — the worst possible
        moment to discover the parser cannot read its own input."""
        path = _write(
            tmp_path,
            {"generalDiagnostics": [{"severity": "warning", "file": None, "message": "m"}]},
        )
        assert _exit_code(lint_findings.normalize_pyright, path) == 2

    def test_a_non_string_rule_exits_2(self, tmp_path):
        path = _write(
            tmp_path,
            {"generalDiagnostics": [{"severity": "error", "file": "a.py", "message": "m",
                                     "rule": 17}]},
        )
        assert _exit_code(lint_findings.normalize_pyright, path) == 2


class TestLegitimateInputIsStillAccepted:
    """The other half of the contract. Tightening a validator until it rejects real tool output
    would take the whole gate down, and every check above would still pass."""

    def test_ruff_null_code_is_accepted(self, tmp_path):
        """Ruff emits a null code for findings with no rule id — syntax errors among them, which is
        the E9 class this project selects. Requiring it would crash the gate on the very finding it
        exists to report."""
        path = _write(tmp_path, [{"filename": "a.py", "code": None, "message": "syntax error"}])
        assert lint_findings.normalize_ruff(path) == ["a.py\t\tsyntax error"]

    def test_pyright_missing_rule_is_accepted(self, tmp_path):
        """`rule` is documented as present only when a rule is associated with the diagnostic."""
        path = _write(
            tmp_path, {"generalDiagnostics": [{"severity": "error", "file": "a.py",
                                               "message": "m"}]},
        )
        assert lint_findings.normalize_pyright(path) == ["a.py\t\tm"]

    def test_pyright_warnings_are_filtered_out(self, tmp_path):
        path = _write(
            tmp_path,
            {"generalDiagnostics": [{"severity": "warning", "file": "a.py", "message": "m"}]},
        )
        assert lint_findings.normalize_pyright(path) == []


class TestOneFindingIsOneLine:
    def test_a_multi_line_pyright_message_collapses(self, tmp_path):
        """The normalized format is one finding per line and `diff` compares line SETS, but pyright
        routinely appends an indented explanation under the summary. Written verbatim, one finding
        becomes several lines and the printed counts describe lines rather than findings — a single
        new error with a three-line message reported "+3 added"."""
        path = _write(
            tmp_path,
            {"generalDiagnostics": [{"severity": "error", "file": "a.py", "rule": "reportX",
                                     "message": 'Type "int" not assignable\n  to "str"'}]},
        )
        identities = lint_findings.normalize_pyright(path)
        assert len(identities) == 1
        assert "\n" not in identities[0]


class TestBadInputIsNeverAQuietZero:
    def test_missing_file_exits_2(self, tmp_path):
        assert _exit_code(lint_findings.normalize_ruff, str(tmp_path / "nope.json")) == 2

    def test_empty_file_exits_2(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert _exit_code(lint_findings.normalize_ruff, str(p)) == 2

    def test_malformed_json_exits_2(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("[{oh no", encoding="utf-8")
        assert _exit_code(lint_findings.normalize_ruff, str(p)) == 2


class TestTheDiffReportsAddedFindings:
    def _norm(self, tmp_path: Path, name: str, lines: list[str]) -> str:
        p = tmp_path / name
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)

    def test_an_added_finding_fails_the_gate(self, tmp_path):
        """Exit 1 is what makes this a gate rather than a report."""
        base = self._norm(tmp_path, "base.txt", ["a.py\tF401\tunused"])
        head = self._norm(tmp_path, "head.txt", ["a.py\tF401\tunused", "b.py\tF811\tredefined"])
        assert lint_findings.diff_findings(base, head) == 1

    def test_a_removed_finding_passes(self, tmp_path):
        """Removals are wins, not failures — burning the baseline down must not go red."""
        base = self._norm(tmp_path, "base.txt", ["a.py\tF401\tunused", "b.py\tF811\tredefined"])
        head = self._norm(tmp_path, "head.txt", ["a.py\tF401\tunused"])
        assert lint_findings.diff_findings(base, head) == 0

    def test_a_swap_that_leaves_the_total_unchanged_still_fails(self, tmp_path):
        """The #325 case, and the reason this script exists: one finding removed and one added reads
        as "no change" to any total-based comparison (#327)."""
        base = self._norm(tmp_path, "base.txt", ["a.py\tF401\tunused"])
        head = self._norm(tmp_path, "head.txt", ["b.py\tF811\tredefined"])
        assert lint_findings.diff_findings(base, head) == 1

    def test_a_missing_normalized_file_exits_2(self, tmp_path):
        base = self._norm(tmp_path, "base.txt", ["a.py\tF401\tunused"])
        with pytest.raises(SystemExit) as exc:
            lint_findings.diff_findings(base, str(tmp_path / "absent.txt"))
        assert exc.value.code == 2
