#!/usr/bin/env python3
"""Mutation check for the supply-chain scan noise fixes.

Run: tools/mutants_scan_noise.py

WHY THIS FILE EXISTS AT ALL. The project declares mutmut, and mutmut is the right tool — but it
generates mutants from the Python AST of `source_paths = ["src/"]`. The logic under test here is a
Python program embedded in a bash heredoc inside `catalog/base/harnessed-scan`, plus the bash
around it. mutmut cannot see either. So mutmut is not "unavailable"; it is unable to address this
surface, and this hand-written set is the declared SUBSTITUTE. Its blind spot is stated in
EVIDENCE: these are the bugs I thought of, where mutmut would have enumerated every AST-reachable
one.

Each mutant is a real bug a future edit could plausibly introduce. The suite must FAIL on every
one; a survivor means the tests covering it assert nothing.

This also serves as the RED evidence for a retrofit. These tests were written after the
implementation, so none was ever observed failing against absent code. A mutant that the suite
kills is the same proof arriving late: the test can fail, and it fails for the right reason.

Restores every file it touches and verifies the tree came back clean with `git diff`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = "catalog/base/harnessed-scan"
DOCKERFILE = "catalog/base/Dockerfile.harnessed-base"

TESTS = [
    "tests/test_scan_acknowledged.py",
    "tests/test_scan_osv_no_lockfiles.py",
    "tests/test_scan_ledger_reconciliation.py",
    "tests/test_scan_corepack_removed.py",
    "tests/test_scan_coverage_reporting.py",
    "tests/test_scan_socket_parser.py",
]

# (label, file, find, replace) — `find` must occur EXACTLY ONCE in the file.
MUTANTS = [
    # --- osv exit-code dispatch (SPEC group O, failure mode F4) ---
    ("osv exit 128 no longer treated as a skip", SCAN,
     '        elif [[ $osv_rc -eq 128 ]]; then\n            record_skip osv "recipe lockfiles" '
     '"no package sources found under skills/ or commands/"\n',
     "        elif false; then\n            :\n"),
    ("osv skip branch broadened to a catch-all, swallowing real crashes", SCAN,
     "elif [[ $osv_rc -eq 128 ]]; then", "elif true; then"),
    ("osv skip branch keyed on the wrong exit code", SCAN,
     "elif [[ $osv_rc -eq 128 ]]; then", "elif [[ $osv_rc -eq 129 ]]; then"),
    ("osv timeout branch collapsed into the nothing-to-scan branch", SCAN,
     'if [[ $osv_rc -eq 124 ]]; then\n            record_skip osv "recipe lockfiles" '
     '"timed out after ${SCAN_TIMEOUT}s"\n        elif',
     "if false; then\n            :\n        elif"),

    # --- ledger reconciliation (SPEC group L, failure mode F3) ---
    ("attempt/skip collapse removed — a skipped scanner reads as broken again", SCAN,
     'elif (tool, source) not in reported and (tool, source) not in skipped:',
     "elif (tool, source) not in reported:"),
    ("collapse keyed on tool alone — a skip on one source silences another", SCAN,
     '        skipped.add((parts[0], parts[1] if len(parts) > 1 else ""))',
     "        skipped.add((parts[0], parts[1] if len(parts) > 1 else \"\"))\n"
     "        skipped.update({(parts[0], s) for s in "
     "[l.split('|')[1] for l in ledger if '|' in l]})"),
    ("reason truncated at the first separator (maxsplit dropped)", SCAN,
     "    parts = line.split(\"|\", 3)\n    tool, source = parts[0], (parts[1] if len(parts) > 1 "
     "else \"\")",
     "    parts = line.split(\"|\", 2)\n    tool, source = parts[0], (parts[1] if len(parts) > 1 "
     "else \"\")"),
    ("blank ledger lines no longer filtered", SCAN,
     'ledger = [line.rstrip("\\n") for line in f if line.strip()]',
     'ledger = [line.rstrip("\\n") for line in f]'),

    # --- ledger writer sanitation (the bug hypothesis found) ---
    ("nosep becomes the identity — separators reach the ledger again", SCAN,
     'nosep() { printf \'%s\' "${1//|/ }"; }',
     "nosep() { printf '%s' \"$1\"; }"),
    ("record_skip stops sanitizing the label (the original defect)", SCAN,
     '    printf \'%s|%s|unrun|%s\\n\' "$(nosep "$tool")" "$(nosep "$label")" '
     '"$(nosep "$reason")" \\',
     '    printf \'%s|%s|unrun|%s\\n\' "$(nosep "$tool")" "$label" "$(nosep "$reason")" \\'),
    ("manifest writer stops sanitizing the label — the path field shifts", SCAN,
     '    [[ -s "$out" ]] && printf \'snyk|%s|%s\\n\' "$(nosep "$label")" "$out" >>"$MANIFEST"',
     '    [[ -s "$out" ]] && printf \'snyk|%s|%s\\n\' "$label" "$out" >>"$MANIFEST"'),

    # --- acknowledged advisories (SPEC group A, failure modes F1/F2) ---
    ("acknowledgment disabled — the two brace-expansion highs return", SCAN,
     "            known = {i for i in advisory_ids(v) & set(ACKNOWLEDGED)\n"
     "                     if ACKNOWLEDGED[i][0] == pkg}",
     "            known = set()"),
    ("acknowledgment keyed by PACKAGE NAME — silences every future brace-expansion CVE", SCAN,
     "            known = {i for i in advisory_ids(v) & set(ACKNOWLEDGED)\n"
     "                     if ACKNOWLEDGED[i][0] == pkg}",
     '            known = {"CVE-2026-14257"} if pkg == "brace-expansion" else set()'),
    ("identifiers ignored — only snyk's own id can match", SCAN,
     "        for values in identifiers.values():",
     "        for values in []:"),
    ("acknowledged hits silently dropped instead of recorded", SCAN,
     "                acknowledged_hits[sorted(known)[0]] = pkg",
     "                pass"),
    ("acknowledged findings omitted from the report json", SCAN,
     '          "acknowledged": [{"id": vid, "package": pkg, "reason": ACKNOWLEDGED[vid][1]}\n'
     '                           for vid, pkg in sorted(acknowledged_hits.items())],',
     '          "acknowledged": [],'),
    ("acknowledged findings no longer printed to the summary", SCAN,
     "if acknowledged_hits:", "if False:"),

    # --- the advisory contract (SPEC N1) ---
    ("scan starts gating on findings", SCAN,
     'report = {"advisory": True, "gating": 0,', 'report = {"advisory": True, "gating": 1,'),

    # --- hostile scanner JSON (security review F1) ---
    # The worst finding of the review: a TypeError here has no handler, and the surrounding bash
    # is `set -uo pipefail` WITHOUT -e, so the python dies, no report is written, and the scan
    # still exits 0. The build prints no summary and looks like it had nothing to say.
    ("identifiers assumed to be a list again — crashes the whole summary block", SCAN,
     "            if isinstance(values, str):     # a bare string would otherwise iterate "
     "CHARACTERS,\n                values = [values]           # silently matching nothing rather "
     "than crashing\n            elif not isinstance(values, (list, tuple, set)):\n"
     "                continue\n            for value in values:\n"
     "                if isinstance(value, str) and value:",
     "            for value in values or []:\n                if value:"),
    ("bare-string identifier iterates characters instead of matching", SCAN,
     "            if isinstance(values, str):     # a bare string would otherwise iterate "
     "CHARACTERS,\n                values = [values]           # silently matching nothing rather "
     "than crashing\n            elif",
     "            if False:\n                values = [values]\n            elif"),

    # --- third-party strings reaching an output surface (security review F2 / correctness C3) ---
    ("package names no longer sanitized before printing", SCAN,
     '    text = "".join(ch for ch in str(value) if ch.isprintable())',
     '    text = str(value)'),
    ("package names no longer bounded in length", SCAN,
     '    return (text[:limit] + "…") if len(text) > limit else text',
     "    return text"),
    ("the pre-existing notable path left unsanitized", SCAN,
     "seen.add(pkg); notable.append(safe_text(pkg, _PKG_MAX))",
     "seen.add(pkg); notable.append(pkg)"),

    # --- acknowledgment must also match the package (security review F4) ---
    ("acknowledgment stops requiring the package to match", SCAN,
     "            known = {i for i in advisory_ids(v) & set(ACKNOWLEDGED)\n"
     "                     if ACKNOWLEDGED[i][0] == pkg}",
     "            known = advisory_ids(v) & set(ACKNOWLEDGED)"),

    # --- a pair that both reported and skipped (correctness P1) ---
    ("parser-side defence removed: a skipped scanner can also report a result", SCAN,
     'skipped_pairs = {(r["tool"], r["source"]) for r in unrun}\n'
     'rows = [r for r in rows if (r["tool"], r["source"]) not in skipped_pairs]\n',
     ""),
    # "osv writes a manifest line even after recording a skip" lives in COMPOUND_MUTANTS, not here.
    # As a single mutant it SURVIVES, and correctly so: the parser-side defence catches the same
    # contradiction, so removing the bash guard alone changes nothing observable. Leaving it here
    # would report a redundancy as a hollow test, which is the opposite of what a survivor means.

    # --- the socket sibling of the snyk manifest writer (correctness C1) ---
    ("socket manifest writer stops sanitizing the label", SCAN,
     '    [[ -s "$out" ]] && printf \'socket|%s|%s\\n\' "$(nosep "$label")" "$out" >>"$MANIFEST"',
     '    [[ -s "$out" ]] && printf \'socket|%s|%s\\n\' "$label" "$out" >>"$MANIFEST"'),

    # --- every path out of an attempt records a result or a reason (round-2 review) ---
    # Four pre-existing early returns left an attempt with neither, so the console said "skipped"
    # while the report said the scanner was broken — the exact contradiction this change removes.
    ("socket bails on a missing org without recording a skip", SCAN,
     '    [[ -n "$org" ]] || { echo "    (socket: no org for this token — skipped)"\n'
     '        record_skip socket "$label" "no organization for this token"; return 0; }',
     '    [[ -n "$org" ]] || { echo "    (socket: no org for this token — skipped)"; return 0; }'),
    ("socket bails on a failed scan create without recording a skip", SCAN,
     '    [[ -n "$id" ]] || { echo "    (socket scan create failed — skipped)"\n'
     '        record_skip socket "$label" "socket scan create returned no scan id"; return 0; }',
     '    [[ -n "$id" ]] || { echo "    (socket scan create failed — skipped)"; return 0; }'),

    # --- corepack removal (SPEC group D, failure mode F6) ---
    # The Dockerfile is the other half of the change and no other layer touches it: ruff, pyright
    # and the heredoc mutants above all stop at the scan script.
    ("corepack removal layer deleted entirely", DOCKERFILE,
     '    rm -rf "$NODE_DIR/lib/node_modules/corepack" \\',
     '    true "$NODE_DIR/lib/node_modules/corepack" \\'),
    ("removal widened from corepack to the whole node_modules tree", DOCKERFILE,
     '"$NODE_DIR/lib/node_modules/corepack" \\',
     '"$NODE_DIR/lib/node_modules" \\'),
    ("mise reshim dropped, leaving a dangling corepack shim on PATH", DOCKERFILE,
     '    mise reshim && \\\n    ! command -v corepack',
     "    true"),
    ("empty-node guard removed — rm -rf silently targets an absolute system path", DOCKERFILE,
     '    [ -n "$NODE_DIR" ] && [ -d "$NODE_DIR" ] && \\\n', "    "),
    ("removal no longer verifies corepack is actually gone", DOCKERFILE,
     '    mise reshim && \\\n    ! command -v corepack', "    mise reshim"),
    ("node resolved inline again instead of once, reintroducing the fail-open", DOCKERFILE,
     'RUN NODE_DIR="$(mise where node@22)" && \\',
     'RUN NODE_DIR="" && \\'),
    ("pnpm pin removed — nothing would provide pnpm once corepack is gone", DOCKERFILE,
     "        pnpm@11 \\\n", ""),
    ("something starts invoking corepack again", DOCKERFILE,
     "RUN npm install -g npm@11.18.0",
     "RUN npm install -g npm@11.18.0\nRUN corepack enable"),
]


# Mutants that must be applied TOGETHER, each a list of (file, find, replace).
#
# Why this list exists. Some invariants here are guarded twice on purpose, and a one-at-a-time
# runner reports both guards as survivors: remove either and the other still holds the line, so
# nothing observable changes. That is a true statement about redundancy, and it is indistinguishable
# in a report from "these tests assert nothing" — which is the failure mutation testing exists to
# catch. Applying both edits at once tells the two apart. A compound that is KILLED proves the pair
# genuinely guards something; one that survives means neither guard was ever load-bearing.
COMPOUND_MUTANTS = [
    ("BOTH guards removed: osv writes a manifest line after a skip AND the parser stops "
     "dropping the contradiction", [
         (SCAN,
          '        elif [[ -s "$WORK/osv.json" ]]; then\n'
          "            printf 'osv|recipe lockfiles|%s\\n' \"$WORK/osv.json\" >>\"$MANIFEST\"\n"
          "        fi",
          "        fi\n        [[ -s \"$WORK/osv.json\" ]] && printf 'osv|recipe lockfiles|%s\\n' "
          '"$WORK/osv.json" >>"$MANIFEST"'),
         (SCAN,
          'skipped_pairs = {(r["tool"], r["source"]) for r in unrun}\n'
          'rows = [r for r in rows if (r["tool"], r["source"]) not in skipped_pairs]\n',
          ""),
     ]),
]


def run_suite() -> bool:
    """True when the suite passes."""
    proc = subprocess.run(
        ["tools/run-tests.sh", *TESTS, "-q", "-p", "no:randomly"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0


class GuardFailed(RuntimeError):
    """A safety check could not be evaluated, so it must not be treated as having passed."""


def _git(*args: str) -> str:
    """Run a read-only git command, FAILING CLOSED.

    A guard that reports "looks fine" when git itself failed is worse than no guard: a failing
    `git status` writes nothing to stdout, so an empty result would read as "clean" and the run
    would proceed to rewrite a tracked file with no verified way back.
    """
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GuardFailed(
            f"`git {' '.join(args)}` exited {proc.returncode}: "
            f"{proc.stderr.strip() or '(no stderr)'}"
        )
    return proc.stdout


def dirty() -> bool:
    """True when any TRACKED file differs from HEAD, staged or not."""
    return bool(_git("status", "--porcelain", "-uno").strip())


def restore(rel: str) -> None:
    subprocess.run(["git", "checkout", "--", rel], cwd=ROOT, check=True)


def main() -> int:
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if branch in ("main", "master"):
            print(f"refusing to run on '{branch}': this rewrites tracked files in place. "
                  "Run it in a worktree.")
            return 2
        if dirty():
            print("refusing to run: tracked files differ from HEAD, so restores would be "
                  "unverifiable. Commit or set them aside first.")
            return 2
    except GuardFailed as exc:
        print(f"refusing to run: cannot verify the tree is safe to mutate — {exc}")
        return 2

    print("baseline: running the suite unmutated ...")
    if not run_suite():
        print("BASELINE RED — the suite must be green before mutation means anything.")
        return 2
    print("baseline GREEN\n")

    survivors: list[str] = []
    for i, (label, rel, find, repl) in enumerate(MUTANTS, 1):
        path = ROOT / rel
        original = path.read_text()
        count = original.count(find)
        if count != 1:
            # FAIL CLOSED. A mutant that did not apply must never be scored as a kill — that is
            # exactly how a hand-rolled runner inflates its own score.
            print(f"[{i}/{len(MUTANTS)}] ABORT: anchor occurs {count}x (expected 1) for: {label}")
            restore(rel)
            return 2
        try:
            path.write_text(original.replace(find, repl))
            killed = not run_suite()
        finally:
            restore(rel)
        status = "killed " if killed else "SURVIVED"
        print(f"[{i}/{len(MUTANTS)}] {status} — {label}")
        if not killed:
            survivors.append(label)

    compound_survivors: list[str] = []
    for j, (label, edits) in enumerate(COMPOUND_MUTANTS, 1):
        originals = {}
        try:
            for rel, find, repl in edits:
                path = ROOT / rel
                if rel not in originals:
                    originals[rel] = path.read_text()
                current = path.read_text()
                count = current.count(find)
                if count != 1:
                    print(f"[C{j}] ABORT: anchor occurs {count}x (expected 1) in {rel}")
                    for r in originals:
                        restore(r)
                    return 2
                path.write_text(current.replace(find, repl))
            killed = not run_suite()
        finally:
            for rel in originals:
                restore(rel)
        print(f"[C{j}/{len(COMPOUND_MUTANTS)}] {'killed ' if killed else 'SURVIVED'} — {label}")
        if not killed:
            compound_survivors.append(label)

    if dirty():
        print("\nFAILED: tree is dirty after restore — a mutant was not reverted.")
        return 2
    print("\ntree restored clean (git status -uno)")

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} single mutants killed")
    print(f"{len(COMPOUND_MUTANTS) - len(compound_survivors)}/{len(COMPOUND_MUTANTS)} "
          "compound mutants killed")
    if survivors:
        print("SINGLE SURVIVORS:")
        for s in survivors:
            print(f"  - {s}")
    if compound_survivors:
        print("COMPOUND SURVIVORS (neither guard was ever load-bearing):")
        for s in compound_survivors:
            print(f"  - {s}")
    return 1 if (survivors or compound_survivors) else 0


if __name__ == "__main__":
    sys.exit(main())
