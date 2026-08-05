# Test intent audit — hunting tests that verify the code instead of the intent

A reusable prompt for auditing a test suite. Give one agent one test file (or a small group),
collect the structured findings, aggregate.

## Why this exists

A real case from this repo, 2026-08-05. `src/harnessed/aoe.py` registers sessions with an external
CLI. It had 139 passing tests, 100% coverage on the changed lines, and a full mutation score. The
implementation could not work: it repaired a stale row with `aoe remove` followed by `aoe add`, and
against the real binary `remove` only moves a row to the trash, where it *still* answers
`aoe list --json` and *still* holds the key the tool deduplicates on — so the replacement `add` was
refused and the row was lost.

Every test passed throughout, because every test mocked the seam and asserted **the argv we emit**.
They were faithful to the code and blind to the outcome. The belief "remove deletes the row" lived
in the mock, and nothing anywhere tested the belief. Four tests that ran the real binary found it
in seconds.

**The thesis of this audit: a mock encodes a belief about something outside the test, and a belief
needs its own test.** Where that pinning test does not exist, the suite's green is decorative for
that behavior.

## What you are looking for

Seven classes. Each needs `file:line`, a one-line statement of what breaks, and — for classes 1–3 —
**the test that would pin the belief**, named concretely.

1. **Belief-encoding mock** *(highest severity)*
   A stub of something external — subprocess, CLI, HTTP, container runtime, clock, filesystem
   semantics — where the test asserts what we *send*, and correctness depends on how the real thing
   *responds*, and nothing in the repo verifies that response.
   Recognizer: a patched `run`/`Popen`/client/transport seam, plus assertions on the arguments
   passed to it. Ask: *if the external tool changed this behavior tomorrow, which test goes red?*
   If the answer is "none", it is a finding.

2. **Argv / call-shape assertion**
   Asserts the exact command, flag set, or call order rather than the resulting state.
   **Calibration:** for a module whose entire job is emitting a command, asserting the command is
   legitimate — *provided* a real-system test pins what that command does. Report it only when no
   such test exists. Do not report every argv assertion; that would drown the signal.

3. **Vacuous / absence-only assertion**
   Would still pass if the feature under test were deleted. Recognizers: the only assertions are
   `== []`, `is None`, "not called", "did not raise", or a count of zero.
   Ask literally: *delete the feature — does this test still pass?*

4. **Source-text assertion**
   `inspect.getsource`, reading the module file, regex over source. These pass when the code is
   present but disabled — wrapping the call site in `if False:` leaves them green. This repo has
   already been bitten by exactly this.

5. **Patch-by-location fragility**
   `monkeypatch.setattr("mod.symbol", …)` where the symbol is imported into another module by
   value. The patch silently stops applying when code moves, and the test keeps passing while
   asserting nothing.

6. **Asserts the refactor happened**
   Checks that a function/file/constant exists, is named a certain way, or lives somewhere —
   rather than checking behavior.

7. **Over-mocking**
   The unit under test is itself mocked, or so much is stubbed that the test exercises only the
   stubs.

## What is NOT a finding

Say so explicitly rather than padding the list:

- Mocking a boundary for **speed or determinism** where a real-system test pins the behavior.
- Asserting argv where the argv **is** the contract and a pinning test exists.
- Tests that are simple because the behavior is simple.
- Style, naming, duplication, parametrization opportunities. **Not this audit.**

## Method

1. Read the whole file. Read the module under test too — you cannot judge whether an assertion
   tracks intent without knowing what the intent is.
2. Search the repo for a pinning test before reporting classes 1–2: does anything execute the real
   dependency? Use `rg` for the tool/binary name, `skipif`, `integration`, or marker names.
3. Classify each test. Most will be fine. Resist inflating the count — a precise list of 5 real
   findings is worth more than 40 speculative ones.
4. For each finding, state what a human would observe if the code were wrong and the test still
   passed. If you cannot state that, it is not a finding.

## Output — exactly this shape, so results aggregate

```
FILE: tests/<name>.py
MODULE UNDER TEST: src/<...>
TESTS: <n>   ASSERTS: <n>   INTENT-ASSERTING: <n>   MECHANIC-ASSERTING: <n>
PINNING TEST EXISTS FOR THE EXTERNAL DEPENDENCY: yes / no / n-a (no external dependency)

FINDINGS (worst first, or "none"):
- [class <1-7>] test_<name> :: <file>:<line>
  breaks: <one line — what can be wrong while this test stays green>
  pin: <the test that would catch it, named concretely — or "n/a" for classes 4-7>

HIGHEST-RISK TEST IN THIS FILE: test_<name> — <one line>
VERDICT: <one line: is this file's green trustworthy, and about what>
```

## Rules

- **Read-only.** Change no files. Do not run the test suite unless a specific question needs it.
- Use `rg`, never `grep`. Use `fd`, never `find`.
- Do not report style, coverage gaps, or missing tests for unimplemented features.
- If a file is fine, say so in one line. That is a useful result, not a wasted one.
