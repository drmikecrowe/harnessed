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
    """Return the git repo root (used to relativise pyright's absolute paths)."""
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return os.getcwd()
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


def normalize_ruff(json_path: str) -> list[str]:
    data = _load_json(json_path)
    if not isinstance(data, list):
        print(
            f"ERROR: expected a JSON array from ruff, got {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)
    findings: list[str] = []
    for item in data:
        filename = item.get("filename") or ""
        code = item.get("code") or ""
        message = (item.get("message") or "").strip()
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
    findings: list[str] = []
    for item in diags:
        if item.get("severity") != "error":
            continue
        filepath = _rel(item.get("file") or "", root)
        rule = item.get("rule") or ""
        message = (item.get("message") or "").strip()
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
