# SPEC — Drop gortex's Stop and SubagentStop hooks

## Summary
This change stops every gortex stack from running `gortex hook` when a turn ends (`Stop`) and when a subagent ends (`SubagentStop`). Those two hooks add nothing for the user, and on a host where `gortex` is missing from the hook's PATH they print errors at the end of every turn. Deleting them from `install.sh` would not help: the recipe's `hooks:` block is what puts them in `settings.json`, and the assembler rewrites that file after `install.sh` runs.

What changes: the two entries leave the `hooks:` block of `catalog/recipes/gortex/recipe.yaml`, the recipe's comments and README stop describing 8 events and post-task diagnostics, and one regression test pins the new hook set.

Acceptance criteria, in plain words:
1. A gortex stack's settings get exactly six gortex hook events: PreToolUse, PostToolUse, SessionStart, UserPromptSubmit, PreCompact and SubagentStart.
2. No harness gets a `Stop` or `SubagentStop` hook from the gortex recipe.
3. The six that stay are unchanged: the same `gortex hook` command and the same matchers.
4. The recipe still loads under strict validation, and its own capability test still finds a `gortex hook` entry in `settings.json`.
5. The recipe's comments and README no longer say 8 events or describe Stop.

What must not change: the six remaining hooks, the assembler, `install.sh`, the recipe's MCP server, `init`, `expect` and `persist` blocks, and the test count.

How each is proven: criteria 1-4 by one new pytest test against the real catalog recipe, plus the existing strict-load test; criterion 5 by an `rg` over the two files, shown in the evidence report.

Open decisions: none.

## Orientation
- Change: remove the `Stop` and `SubagentStop` entries from the gortex recipe's `hooks:` block, and update the comments and README that describe them.
- Why: the two hooks add no value to the user and run `gortex hook` at the end of every turn and subagent; `install.sh --no-hooks` cannot remove them because the assembler writes the recipe's `hooks:` into `settings.json` after `install.sh`.
- Touches: `catalog/recipes/gortex/recipe.yaml`, `catalog/recipes/gortex/README.md`, `tests/test_recipes_integration.py`.
- Decide: whether an opt-in path is needed (ruled: none).
- Decided: Decide 1, A — remove both hooks outright, with no opt-in path in the catalog; governs S1 and Known limits (mcrowe, 2026-10-17).
- Lane: engineering, because the change is internal recipe configuration — a catalog recipe's hook wiring, raised by the engineer who runs it — with no product author and no user-facing behavior to specify beyond the hook set.

- Tier: 1 — a configuration value in one recipe. One regression test is still added, because nothing in the suite asserts the gortex hook set today.
- Issue: GH-610
- Isolation: worktree — `main` takes no commits.

## Scenarios
### S1. The gortex recipe contributes six hook events, without Stop or SubagentStop
- S1.1 Given the catalog recipe `catalog/recipes/gortex` loaded with `load_recipe(..., strict=True)`, when `required_settings([], [recipe], harness="claude")` runs, then the keys of its `"hooks"` mapping are exactly `{"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "PreCompact", "SubagentStart"}`. Per Decide 1 (mcrowe, 2026-10-17), no key is added back under another name or behind an option.
- S1.2 (negative) Given the same recipe, when `required_settings([], [recipe], harness=h)` runs for each `h` in `claude`, `omp`, `opencode`, `codex` and `antigravity`, then neither `"Stop"` nor `"SubagentStop"` is a key of the result's `"hooks"` mapping (or the mapping is absent).
- S1.3 (boundary) Given the same recipe, when its `hooks` are read, then each of the six events holds exactly one entry whose command is `gortex hook`, the PreToolUse matcher is `*`, and the PostToolUse matcher is byte-identical to the one at `recipe.yaml:221` before this change.

### S2. The recipe still loads and its capability check still holds
- S2.1 Given every catalog recipe, when the existing strict-load test loads them, then `catalog/recipes/gortex` loads with no error.
- S2.2 Given the hooks `required_settings([], [recipe], harness="claude")` returns for the gortex recipe, when they are serialized with `json.dumps(..., indent=2)`, then the text matches the regex `"command"[[:space:]]*:[[:space:]]*"gortex hook"` that `catalog/recipes/gortex/tests/gortex-runs.sh` applies to `settings.json` (as the Python regex `"command"\s*:\s*"gortex hook"`).

### S3. The recipe's prose matches its hooks
- S3.1 Given `catalog/recipes/gortex/recipe.yaml` and `catalog/recipes/gortex/README.md` after the change, when `rg -n 'Stop\b|8 events'` runs over the two files, then it prints no line.
- S3.2 (boundary) Given `catalog/recipes/gortex/README.md` after the change, when its hooks row is read, then it says `6 events`.

## Must NOT
- Change the PreToolUse, PostToolUse, SessionStart, UserPromptSubmit, PreCompact or SubagentStart entries: same command, same matcher (S1.3).
- Change anything under `src/harnessed/`: the assembler stays as it is.
- Change `catalog/recipes/gortex/install.sh`, `catalog/recipes/gortex/tests/gortex-runs.sh`, or the recipe's `tools`, `mcp`, `init`, `persist`, `env`, `install` or `expect` blocks.
- Change `catalog/recipes/gortex/PLAN.md`: its "8 events" describes upstream's installer, which this change does not alter.
- Lower the test count: the full suite passes with at least the baseline count plus one.

## Touches
- `catalog/recipes/gortex/recipe.yaml` — delete the `Stop:` and `SubagentStop:` entries (lines 228-229 and 232-233); reword the hooks comment at lines 189-194 (8 events → 6; say that upstream's two end-of-turn events are dropped and why, without the words `Stop` or `SubagentStop`, so S3.1 holds; no "post-task diagnostics" sentence), and the event list at lines 213-214 (drop "Stop" and "Subagent*", name SubagentStart). No comment line in either file may match `Stop\b` (mcrowe, 2026-10-17).
- `catalog/recipes/gortex/README.md` — line 23: `8 events` → `6 events`.
- `tests/test_recipes_integration.py` — add one test against the real gortex recipe for S1.1, S1.2, S1.3 and S2.2.

## Documentation
- `catalog/recipes/gortex/README.md` (S3.2). The wiki (`main/docs/`) does not describe the gortex hook set — checked with `rg -n -i 'gortex hook|8 events|SubagentStop'`, no hit — so no wiki page changes.

## Known limits
- A profile built before this change keeps both hooks until its stack is rebuilt (`harnessed build <stack> <harness>`), because the assembled `settings.json` is generated state.
- The user-scope `~/.claude/settings.local.json` keeps its own Stop and SubagentStop entries from the original upstream install; the assembler does not write that file, so this change cannot reach it.
- Per Decide 1 (mcrowe, 2026-10-17) the catalog offers no way to turn the two hooks back on. A user who wants gortex's post-task diagnostics declares them in a recipe in the user overlay, `~/.config/harnessed/catalog`.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1-S1.3, S2.1, S2.2, and every existing test | `tools/run-tests.sh` passes; count ≥ baseline + 1 |
| coverage | branch coverage of `src` | ≥ 80% (`--cov-fail-under=80`) |
| types | pyright over the dev environment | 0 errors |
| lint | ruff over `src tests tools` | 0 findings |
| shellcheck | every tracked `*.sh` | 0 findings |
| secrets | gitleaks over the history | 0 leaks |
| doc check | S3.1, S3.2 | `rg` prints no line for S3.1; README row reads `6 events` |
