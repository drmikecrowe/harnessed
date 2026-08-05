# Test intent audit — results, 2026-08-05

Audit of all 86 test files using `.agents/prompts/test-intent-audit.md`, run by 23 agents.
Per-file reports are in `.old-coder/audit/` (gitignored, local to the audit worktree).

**Coverage: 86 of 86 files, 76 findings, 27 reports.** Complete.

## Why this was run

`src/harnessed/aoe.py` shipped a repair that could not work, while 139 tests, full changed-line
coverage and a complete mutation score stayed green. Every one of those tests mocked the external
CLI and asserted the argv we send. The belief "`aoe remove` deletes the row" lived in the mock;
nothing tested the belief; the real binary moves the row to the trash where it still holds the key
the tool deduplicates on. Four tests that ran the real binary found it in seconds.

The question this audit asks of the whole suite: **where else is a belief doing the work of a
test?**

## The headline finding is not in the counts

**The live-verification layer already exists and runs nowhere.** Filed as **harnessed-3x1** (P1).

Every run reports `2120 passed, 22 skipped`. Those 22 *are* the live layer — 12 in
`test_recipes_integration.py`, plus `test_persist_mounts.py`, `test_live_verification_debt.py`
and a dolt-gated test, all behind `HARNESSED_PODMAN=1`. Nothing opens the gate:
`tools/run-tests.sh` does not set it, and `.github/workflows/test.yml` deliberately does not
("Hermetic: no podman on the runner").

Someone built the right mechanism. It emits a reassuring "22 skipped" on every run and verifies
nothing. The cheapest remediation available is therefore not writing tests — it is **running the
ones that already exist**.

Self-inflicted instance, for honesty: `tests/test_aoe_real.py`, added on
`worktree-harnessed-cn9-aoe-drift`, is gated on `shutil.which("aoe")` and CI has no `aoe`. It will
skip in CI forever, exactly like the other 22.

## Findings by class

| Class | What it is | Count |
|---|---|---|
| 4 | asserts on source TEXT — passes when code is present but disabled | **37** |
| 2 | argv assertion with no pinning test behind it | 14 |
| 1 | mock encoding an unverified belief about an external system | 11 |
| 3 | vacuous — passes if the feature were deleted | 7 |
| 6 | asserts existence/naming rather than behaviour | 6 |
| 7 | over-mocking — bypasses the unit under test | 1 |
| | **total** | **76** |

Class 4 alone is half of everything found.

Tier A (16 mock-dense files) averaged **2.1 findings/file**; Tier C (29 files with no mocking at
all) **0.76**. Mock density predicted finding density — but not the *kind*. Files with mocks
encode beliefs about binaries; files without mocks assert on text and structure. Neither tests
intent.

## Unpinned external contracts

Eight binaries whose behaviour the suite describes but never exercises. Every failure mode is
silent — no crash, no error; the parse returns empty, the caller reads that as "nothing found",
the suite stays green.

| Dependency | Belief encoded | If wrong |
|---|---|---|
| varlock `load --format json` | output shape, null-key semantics | **every secret silently fails to arrive** |
| podman `inspect` | Go template + exit-code contract | everything rebuilds, or staleness never detected |
| podman `port` | separator, no header line | clients dial a stale port |
| podman `images` | one name per line | reconciler misclassifies stacks |
| podman `top <inst> tty` | column layout, no-tty markers | idle vs attached misclassified |
| lsusb | positional bus/device fields | YubiKey passthrough stops |
| mise `trust` | command syntax | trust silently not applied |
| claude `--strict-mcp-config` | that the flag suppresses global MCP | wrong MCP surface |
| omp | mount + session-dir argv | (class 2, same shape) |
| rtk | argv contract | (class 1) |
| pnpm | stubbed behaviour | (class 2) |

Tracked in **harnessed-rwt**, which also carries the four aoe contracts (remove permanence,
`--tool` retry protocol, create-idempotency exit codes, add-flag compatibility).

## The class-4 cluster is smaller than it looks

27 findings, two mechanisms:

- **`_code()` helper, ~9.** It strips comment lines before asserting on file text — already a
  mitigation someone wrote for this exact weakness ("a rule about what a file DOES must not be
  satisfied by prose describing it"). The finding is that it is not applied uniformly. Mechanical
  fix; it is also copy-pasted into two files and wants to be shared.
- **`inspect.getsource` and raw `read_text()`, ~7 plus the remainder.** These need real fixes where
  the assertion is load-bearing — `test_launch_host`'s ordering invariants, `test_module_boundaries`'
  import rules.

`_code()` closes the *comment* loophole only. A text assertion still passes when the call site is
wrapped in `if False:`, which is how the capmatrix tests failed here before. For anything
load-bearing the assertion must observe behaviour.

`test_module_boundaries.py` deserves its own note: it enforces architecture by scanning **static**
imports, and can be bypassed by dynamic imports and a ledger proxy — unguarded in exactly the case
someone would use to violate it.

## Recommended order

1. **Give the live layer a home** (harnessed-3x1). Highest value, lowest effort: the tests exist.
2. **Make skips loud in aggregate.** "22 skipped" reads as fine; "nothing verified podman or
   varlock this run" reads as what it is.
3. **Pin the contracts the gated tests do not reach** (harnessed-rwt), varlock first.
4. **Apply `_code()` uniformly**, and promote it to a shared helper.
5. **Replace load-bearing text assertions with behavioural ones** — ordering invariants and module
   boundaries only; the rest are low stakes.

## Notes for the next run of this audit

- **Sonnet is the right model.** On the calibration file it found 4/4 belief-encoding mocks plus
  two findings the others missed. **Haiku** got 3/4 at a fraction of the cost and produced zero
  false positives — fine for bulk tiers. **Opus was the worst**: 1/4, and it undercounted
  mechanic-asserting assertions by 4× (12 vs an actual 50). This is rubric-driven classification,
  where following a checklist beats free-form reasoning.
- **Two models on one file found non-overlapping findings.** A single pass over a high-density file
  is not complete.
- **The prompt resisted leading briefs.** Agents told to expect class-1 findings in the self-update
  files reported them clean. Priming did not manufacture findings.
- **Have agents write reports to files and return one line.** 23 verbatim reports would not fit in
  a working context, and agents that never reported back still left their report on disk.
