## Evidence Report — Drop gortex's Stop and SubagentStop hooks (Tier 1)

## Summary
Delivered: the gortex recipe no longer declares `gortex hook` on `Stop` or `SubagentStop`, so a gortex stack stops running the hook at the end of every turn and every subagent. The fix lives in the recipe's `hooks:` block because the assembler rewrites `settings.json` from that block after `install.sh` runs; `install.sh --no-hooks` could not remove them.

How each criterion was proven:
- Six events, exactly (S1.1): the new test `test_gortex_hooks_stop_at_six_events` asserts the claude hook keys equal the six named events. It failed on the approval commit's recipe with `Stop` and `SubagentStop` as extra items, and passes after the fix.
- No end-of-turn hook on any harness (S1.2): the same test checks claude, omp, opencode, codex and antigravity.
- The six that stay are unchanged (S1.3): the test pins one `gortex hook` entry per event and both matchers; a separate comparison against the approval commit found all six entries equal.
- The recipe still loads, and its own check still holds (S2.1, S2.2): `test_all_catalog_recipes_pass_strict` passes, and the new test applies `gortex-runs.sh`'s regex to the serialized hooks.
- The prose matches (S3.1, S3.2): `rg -n 'Stop\b|8 events'` over `recipe.yaml` and `README.md` prints no line (it found 5 and 1 lines on the approval commit), and the README row reads `6 events`.

The final gauntlet ran green on commit 3685edd with a clean tree: all six layers passed, 4491 tests passed and 80 skipped (4571 collected against a baseline of 4570), coverage 86.59% against an 80% floor.

Not proven: nothing.

Judgment calls: `PLAN.md` keeps its "8 events", because it describes upstream's installer, which this change does not alter. The adversary raised one low hunch and no finding; it was checked against the approval commit and needed no code change, so no second review round ran. The final gauntlet's per-layer numbers come from rerunning the same layer commands on the same clean commit, because the gauntlet keeps only pass/fail and timings.

## Orientation
- Verdict: PASSED
- Delivered: the gortex recipe declares six hook events, dropping `Stop` and `SubagentStop`, with matching comments, README and a regression test.
- Proven: 7/7 scenarios mapped and passing
- Not proven: nothing

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-16-GH-610/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit a8776ea, "GH-610: spec approved")
- Intent review: not run, engineering lane
- Source state: commit 3685edd4f4bfc0f5010e055b96cc9b79e681a53b — the commit the final run and the review read
- Stamp:
```json
{
  "result": "green",
  "expected_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "completed_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "layer_seconds": {
    "tests": 303.859,
    "coverage": 337.32,
    "types": 13.98,
    "lint": 0.145,
    "shellcheck": 1.451,
    "secrets": 2.646
  },
  "failed": null,
  "exit_code": 0,
  "commit": "3685edd4f4bfc0f5010e055b96cc9b79e681a53b",
  "dirty": false,
  "written": "2026-10-18T10:29:06.460Z"
}
```
- Baseline: baseline-stamp.json at commit a8776ea2307e6b605595f6a856ed52e08611f5d8, green

### Spec → Test mapping
| Scenario | Test | Status |
|---|---|---|
| S1.1 | `tests/test_recipes_integration.py::test_gortex_hooks_stop_at_six_events` (line 304; `assert set(hooks) == six`). Break check: at commit 85a0627, before the fix, it failed with "Extra items in the left set: 'SubagentStop', 'Stop'" | pass |
| S1.2 | `tests/test_recipes_integration.py::test_gortex_hooks_stop_at_six_events` (loop over claude, omp, opencode, codex, antigravity asserting neither key) | pass |
| S1.3 | `tests/test_recipes_integration.py::test_gortex_hooks_stop_at_six_events` (one `gortex hook` entry per event; PreToolUse matcher `*`; PostToolUse matcher equals `_GORTEX_POST_TOOL_MATCHER`). The constant was compared with the approval commit's `recipe.yaml` matcher and found equal, and all six entries were found equal to the approval commit's | pass |
| S2.1 | `tests/test_recipes_integration.py::test_all_catalog_recipes_pass_strict` (line 117) | pass |
| S2.2 | `tests/test_recipes_integration.py::test_gortex_hooks_stop_at_six_events` (`re.search(r'"command"\s*:\s*"gortex hook"', json.dumps(hooks, indent=2))`) | pass |
| S3.1 | `catalog/recipes/gortex/recipe.yaml:189-199` and `catalog/recipes/gortex/recipe.yaml:218-219` (the reworded comments), checked by `rg -n 'Stop\b|8 events' catalog/recipes/gortex/recipe.yaml catalog/recipes/gortex/README.md`: no output, exit 1. The same pattern counts 5 lines in `recipe.yaml` and 1 in `README.md` on commit a8776ea, so the check can fail | pass |
| S3.2 | `catalog/recipes/gortex/README.md:23` reads `hooks (\`gortex hook\`, 6 events)` | pass |

### Gauntlet (final fresh run)
The gauntlet run (`node <skill>/scripts/gauntlet.mjs`, stamp above) exited 0 on commit 3685edd with every layer completed. The gauntlet records pass/fail per layer, not counts, so each layer's command from `tools/gauntlet-layers.json` was run again on the same commit, tree clean, to read its numbers.

| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — exit 0 in the gauntlet (303.9 s); 4571 tests collected against a baseline of 4570 | gauntlet stdout, `layer tests: ok` |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 4491 passed, 80 skipped; total coverage 86.59% (floor 80%) | job scratch `cov.log` |
| types | `mise exec -- pyright --pythonpath <dev venv python>` | PASSED — 0 errors, 0 warnings, 0 informations | terminal |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — "All checks passed!" | terminal |
| shellcheck | `mise exec -- sh -c 'shellcheck $(git ls-files "*.sh")'` | PASSED — exit 0 in the gauntlet over 34 tracked `*.sh` files; the diff touches none | gauntlet stdout, `layer shellcheck: ok` |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — 1506 commits scanned, no leaks found | terminal |
| merge gate parity | `.github/workflows/test.yml` (pytest, 2 Python versions) → tests/coverage; `.github/workflows/lint.yml` (ruff `src tests tools`, pyright, shellcheck over `git ls-files '*.sh'`) → lint, types, shellcheck | PASSED — every merge-gate check maps to a layer above with the same arguments; `live.yml` is not triggered by `catalog/recipes/` | — |
| adversarial review | spec-evidence-adversary, round 1, on a8776ea...3685edd | PASSED — 0 findings, 1 hunch (triaged below) | `findings-code.md` |

### Layers not run as specified
- N-A: egress (new data paths) — the change adds no field, log line or output; it removes two hook entries.
- N-A: mutation testing — the diff changes no Python or shell source; the one code-like change is YAML data, and the regression test's break check (S1.1, commit 85a0627) shows the test fails when the data is wrong.
- N-A: property-based tests — no parser, math or serialization changes.
- N-A: real execution — the suite runs no `harnessed build`; a rebuilt profile is not part of this change's surface, and `live.yml` is not triggered. Known limit in the SPEC: a profile built before this change keeps the hooks until it is rebuilt.
- SUBSTITUTED: per-layer numbers for tests, types, lint and secrets — the gauntlet stamp records pass/fail only, so the numbers come from rerunning each layer's own command on the same commit with a clean tree. A rerun cannot detect a result that differs between the two runs on the same commit (a flaky test).

### Defect classes closed
- Generator: a catalog recipe declares `gortex hook` on an end-of-turn event (`Stop` or `SubagentStop`), so the assembler writes it into every stack that uses the recipe.
- Enumerated by: `rg -n --glob '*.yaml' '^\s+(Stop|SubagentStop):' catalog` (no output, exit 1) and `rg -n --glob '*.yaml' -F 'gortex hook' catalog` (6 `command:` lines, all in `catalog/recipes/gortex/recipe.yaml`, on the six kept events); the user overlay `~/.config/harnessed/catalog` was checked with the same first pattern (no output) and holds no gortex recipe.
- Sites: 2 — `catalog/recipes/gortex/recipe.yaml` `Stop:` entry — fixed; `catalog/recipes/gortex/recipe.yaml` `SubagentStop:` entry — fixed.

### Not reached by review
- Round 1: calls 3/10; hunts not reached: 1 (merge-gate argument comparison: test.yml, lint.yml and the layer manifest were not read); 2 (call sites: the diff changes no functions); 8 (no EVIDENCE report in the diff); 9 (not checked that required_settings(..., harness=...) accepts omp, opencode, codex and antigravity; the test would fail loudly if it didn't); sites not opened: /home/mcrowe/Programming/Personal/harnessed/.bare/.claude/worktrees/gh-610-gortex-stop-hooks/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/.bare/.claude/worktrees/gh-610-gortex-stop-hooks/.github/workflows/lint.yml, /home/mcrowe/Programming/Personal/harnessed/.bare/.claude/worktrees/gh-610-gortex-stop-hooks/tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/.bare/.claude/worktrees/gh-610-gortex-stop-hooks/catalog/recipes/gortex/tests/gortex-runs.sh, /home/mcrowe/Programming/Personal/harnessed/.bare/.claude/worktrees/gh-610-gortex-stop-hooks/catalog/recipes/gortex/install.sh

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 88965/495 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 108605/523 |

### Honest notes
- The adversary's one hunch (the test's PostToolUse matcher is a hand copy) was triaged by loading the approval commit's `recipe.yaml` and comparing: the constant, the current matcher and all six kept entries are equal to the approval commit's. No code changed, so no second round ran.
- Hunt 9 (does `required_settings` accept every harness name) was not reached by the reviewer; the test calls it for all five harnesses and passes, so an unknown name would have raised.
- The editor showed pyright "Import could not be resolved" diagnostics on the test file; those come from the editor's environment. The types layer, run with the dev venv's Python, reports 0 errors.
- During the build, the gortex MCP server reported "daemon restarted" once; the systemd daemon had not restarted (`NRestarts=0`), so this was a reset of the session's MCP state and did not touch the build.
