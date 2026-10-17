# Decisions — Drop gortex's Stop and SubagentStop hooks

## Setup plan
- Isolation: worktree `gh-610-gortex-stop-hooks` (branch `worktree-gh-610-gortex-stop-hooks`) — `main` takes no commits (CLAUDE.md, Git workflow).
- Git: one signed commit per step of the process; the change itself in one commit; PR to `main`.
- New dependencies: none.
- New files: none outside the story directory. The regression test goes in the existing `tests/test_recipes_integration.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares six layers — tests (`tools/run-tests.sh`), coverage (pytest-cov, 80% floor), types (pyright), lint (ruff on src, tests, tools), shellcheck (all tracked `*.sh`), secrets (gitleaks). All six are declared and run; none is missing.
- Merge gate: `.github/workflows/test.yml` and `.github/workflows/lint.yml` — 5 checks transcribed: pytest (two Python versions, `uv run --extra dev pytest`) → tests; ruff `check src tests tools` → lint; pyright → types; shellcheck over `git ls-files '*.sh'` → shellcheck. `live.yml` does not run: its trigger list (CLAUDE.md, Tests) holds no `catalog/recipes/` path.

## Facts this SPEC rests on
1. The gortex recipe declares 8 hook events, each `command: gortex hook`: PreToolUse (matcher `*`), PostToolUse (gortex MCP tool matcher), SessionStart, UserPromptSubmit, PreCompact, Stop, SubagentStart, SubagentStop — read at `catalog/recipes/gortex/recipe.yaml:215-233`.
2. The assembler writes the recipe `hooks:` block into the stack's `settings.json` after `install.sh` runs, so a script that strips hooks is undone on the next launch; `install.sh` already passes `--no-hooks` — `recipe.yaml:205-207` and `install.sh:36,59`, read.
3. The recipe comments name Stop in three places: the "8 events" count at `recipe.yaml:190`, "Stop runs post-task diagnostics" at `recipe.yaml:193-194`, and the name-independent event list "(PreToolUse on *, SessionStart, UserPromptSubmit, PreCompact, Stop, Subagent*)" at `recipe.yaml:213-214` — read.
4. `catalog/recipes/gortex/README.md:23` says "hooks (`gortex hook`, 8 events)" — read.
5. `catalog/recipes/gortex/PLAN.md:46` records upstream's own installer set ("8 events") as history of what `gortex install` writes. That stays true after this change, so it is left alone — read.
6. No test in `tests/` asserts the gortex hook set; the recipe test `catalog/recipes/gortex/tests/gortex-runs.sh` checks only that some `"command": "gortex hook"` entry exists in `settings.json`, which the six remaining events still satisfy — scanned `tests/**/*.py` for gortex lines naming Stop or hooks, and read `gortex-runs.sh`.
7. `required_settings([], [recipe], harness=...)` returns the hooks a recipe contributes per harness, and `test_codebase_memory_mcp_hooks_reach_settings` (`tests/test_recipes_integration.py:197`) already asserts a real catalog recipe's exact hook set with it — read.
8. The recipe schema has no per-recipe option field: `KNOWN_RECIPE_FIELDS` at `src/harnessed/schema.py:1526-1549` holds no `options`-like key — read.
9. The user-scope `~/.claude/settings.local.json` carries its own `gortex hook` entries for Stop and SubagentStop, from the original upstream install. The assembler does not write that file, so this change does not reach it — read its `hooks` keys with `jq`.

## Decide calls

### Decide 1. Remove the two hooks outright, or keep them available as opt-in?
The brief's trade-off section: users who want gortex's post-task diagnostics lose them; "if that matters, make these two events opt-in through a recipe option instead". The schema has no option field (fact 8).

- A. Remove `Stop` and `SubagentStop` from the recipe outright. Cost: no stack can get gortex's post-task diagnostics from the catalog; a user who wants them adds the hooks in a user-overlay recipe.
- B. Remove them, and add a companion recipe (for example `catalog/recipes/gortex-diagnostics/`) that declares only those two hooks, for stacks that list it. Cost: a new recipe directory, its README and a test; one more recipe to keep in step with gortex's pin.
- C. Add a recipe option field to the schema so a stack can turn the two events on. Cost: a schema and assembler change, new validation and tests, for one recipe's two hooks.

Default: A.
- Ruling: A (mcrowe, 2026-10-17)
Changes: SPEC.md Orientation `Decided:` line; scenario S1 removes both events with no opt-in path; Known limits names the overlay route.

## Revisions
