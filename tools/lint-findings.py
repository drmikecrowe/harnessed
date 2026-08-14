#!/usr/bin/env python3
"""
Normalize lint/type tool JSON output to stable finding identities and compare two runs.

A "finding identity" is  file TAB rule TAB message  with line numbers dropped.
This means a finding that merely shifted because lines were inserted above it is NOT
reported as a new finding.  Only a genuinely new file+rule+message triple is ADDED.

Usage:
    lint-findings.py normalize ruff    <json-file>   # print sorted identities to stdout
    lint-findings.py normalize pyright <json-file>   # print sorted identities to stdout
    lint-findings.py diff <baseline-normalized> <head-normalized>
        # compare two files produced by "normalize"; exit 1 if any finding was ADDED

Fail-closed contract:
    Any missing file, malformed JSON, or unrecognised invocation exits 2 (hard error).
    Never silently fall through to a zero exit on bad input.
"""

import json
import os
import sys


def _repo_root() -> str:
    """Return the git repo root (used to relativise the tools' absolute paths)."""
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    # Fail closed, like every other error path here. Falling back to getcwd() would still
    # produce output, but the identities would be relative to whatever directory the caller
    # happened to be in — so a baseline and a head normalized from different cwds would
    # disagree on every single finding and the gate would report the whole set as churn.
    # A gate that can silently emit garbage identities is worse than one that stops.
    if result.returncode != 0:
        print(
            f"ERROR: not a git repository (git rev-parse failed): {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    return result.stdout.strip()


def _rel(path: str, root: str) -> str:
    """Return path relative to root; fall back to the original string."""
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _load_json(path: str) -> object:
    if not os.path.exists(path):
        print(f"ERROR: JSON file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path) as fh:
            content = fh.read()
        if not content.strip():
            print(f"ERROR: JSON file is empty: {path}", file=sys.stderr)
            sys.exit(2)
        return json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"ERROR: malformed JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _one_line(text: str) -> str:
    """Collapse a message to a single line.

    The normalized format is one finding per line and `diff` compares line sets, but pyright
    messages are routinely MULTI-line — it appends an indented explanation under the summary
    ('Type "int" is not assignable to return type "str"' then '  "int" is not assignable to "str"').
    Written verbatim, one finding becomes several lines and the counts the gate prints then describe
    lines rather than findings: a single new error with a three-line message reports "+3 added".
    The set arithmetic still detects it (both sides split identically, so this was never a false
    pass), but a gate that misreports how much it found trains people to distrust it.
    """
    return " ".join(text.split())


def _require_record(item: object, tool: str, index: int) -> dict:
    """Reject a non-mapping record rather than letting `.get` raise an uncaught AttributeError.

    An uncaught traceback exits 1, which is this script's "findings were added" code — a crash
    would be read as an ordinary gate failure. Schema problems must stay distinguishable, hence 2.
    """
    if not isinstance(item, dict):
        print(
            f"ERROR: {tool} record #{index} is {type(item).__name__}, expected an object",
            file=sys.stderr,
        )
        sys.exit(2)
    return item


def _require_str(item: dict, key: str, tool: str, index: int) -> str:
    """Return a required non-empty string field, or exit 2.

    A finding's identity is built from these, so a missing or null one does not degrade the
    comparison gracefully — it manufactures an identity like "\\t\\t" that every other malformed
    record also matches, collapsing them into one entry and making real findings vanish from both
    sides of the diff. Ruff 0.16 explicitly allows `filename` to be null rather than defaulting it,
    so this is reachable input rather than a hypothetical.
    """
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        print(
            f"ERROR: {tool} record #{index} has a missing or non-string '{key}': {value!r}",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def normalize_ruff(json_path: str) -> list[str]:
    root = _repo_root()
    data = _load_json(json_path)
    if not isinstance(data, list):
        print(
            f"ERROR: expected a JSON array from ruff, got {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)
    findings: list[str] = []
    for index, raw in enumerate(data):
        item = _require_record(raw, "ruff", index)
        # Relativised for the same reason pyright's paths are: ruff reports ABSOLUTE
        # filenames, so an identity built from them is only comparable against a baseline
        # normalized from the identical directory. That holds while the gauntlet reverts
        # in place, and stops holding the moment a baseline is generated in a temp
        # worktree — at which point every finding reads as both added and removed.
        filename = _rel(_require_str(item, "filename", "ruff", index), root)
        message = _one_line(_require_str(item, "message", "ruff", index))
        # `code` stays OPTIONAL on purpose. Ruff emits a null code for findings with no rule id —
        # syntax errors (the E9 class this project selects) among them. Demanding it here would
        # turn a genuine syntax error into a crash of the gate that is supposed to report it.
        code = item.get("code") or ""
        findings.append(f"{filename}\t{code}\t{message}")
    return sorted(set(findings))


def normalize_pyright(json_path: str) -> list[str]:
    root = _repo_root()
    data = _load_json(json_path)
    if not isinstance(data, dict):
        print(
            f"ERROR: expected a JSON object from pyright, got {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)
    diags = data.get("generalDiagnostics")
    if diags is None:
        print(
            "ERROR: pyright JSON missing 'generalDiagnostics' key",
            file=sys.stderr,
        )
        sys.exit(2)
    if not isinstance(diags, list):
        print(
            f"ERROR: pyright 'generalDiagnostics' is {type(diags).__name__}, expected a list",
            file=sys.stderr,
        )
        sys.exit(2)
    findings: list[str] = []
    for index, raw in enumerate(diags):
        # Validate EVERY record BEFORE filtering on severity. Filtering first lets a malformed
        # record through unexamined whenever its severity happens not to be "error", so the schema
        # problem would surface only on the run where it also happened to be an error — the worst
        # possible moment to discover the parser cannot read its own input.
        item = _require_record(raw, "pyright", index)
        severity = _require_str(item, "severity", "pyright", index)
        filepath = _rel(_require_str(item, "file", "pyright", index), root)
        message = _one_line(_require_str(item, "message", "pyright", index))
        if severity != "error":
            continue
        # `rule` is documented as present only when a rule is associated with the diagnostic, so it
        # is genuinely optional and must not be required.
        rule = item.get("rule") or ""
        findings.append(f"{filepath}\t{rule}\t{message}")
    return sorted(set(findings))


def diff_findings(baseline_path: str, head_path: str) -> int:
    """
    Compare two normalized finding files.  Print +added / -removed / =unchanged.
    Return 1 if any findings were ADDED (gate fail), 0 if not.
    """
    for path in (baseline_path, head_path):
        if not os.path.exists(path):
            print(f"ERROR: normalized file not found: {path}", file=sys.stderr)
            sys.exit(2)

    with open(baseline_path) as fh:
        baseline_lines = fh.read().splitlines()
    with open(head_path) as fh:
        head_lines = fh.read().splitlines()

    # Filter out blank lines (e.g. empty findings set)
    baseline = set(line for line in baseline_lines if line.strip())
    head = set(line for line in head_lines if line.strip())

    added = sorted(head - baseline)
    removed = sorted(baseline - head)
    unchanged = len(head & baseline)

    print(f"  +{len(added)} added   -{len(removed)} removed   ={unchanged} unchanged")
    for finding in added:
        print(f"  + {finding}")
    for finding in removed:
        print(f"  - {finding}")

    return 1 if added else 0


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    action = sys.argv[1]

    if action == "normalize":
        if len(sys.argv) < 4:
            print("Usage: normalize ruff|pyright <json-file>", file=sys.stderr)
            sys.exit(2)
        tool = sys.argv[2]
        json_path = sys.argv[3]
        if tool == "ruff":
            findings = normalize_ruff(json_path)
        elif tool == "pyright":
            findings = normalize_pyright(json_path)
        else:
            print(f"ERROR: unknown tool '{tool}' (expected ruff or pyright)", file=sys.stderr)
            sys.exit(2)
        print("\n".join(findings))

    elif action == "diff":
        if len(sys.argv) < 4:
            print("Usage: diff <baseline-normalized> <head-normalized>", file=sys.stderr)
            sys.exit(2)
        sys.exit(diff_findings(sys.argv[2], sys.argv[3]))

    else:
        print(f"ERROR: unknown action '{action}' (expected normalize or diff)", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
