# Decisions — Deliver a stack as a Claude Code plugin with `harnessed use` (phases 2-4)

## Setup plan
- Isolation: worktree — `worktrees/plugin-mode` on branch `plugin-mode`, as AGENTS.md §Git workflow requires.
- Git: signed commits on `plugin-mode`; one commit per RED/GREEN pair; PR to `main` at the end.
- New dependencies: none. `hypothesis` and `mutmut` are already dev extras (`pyproject.toml:32,36`).
- New files: `src/harnessed/plugin.py`, `tests/test_plugin.py`, `tests/test_use.py`, `tests/fixtures/stacks/plugin-stack/`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck and secrets, and all six run. Property tests (`hypothesis`) and mutation tests (`mutmut`) are declared in `pyproject.toml` and run by hand for Tier 3. Nothing is missing.
- Merge gate: `.github/workflows/test.yml` (pytest), `lint.yml` (ruff, pyright, shellcheck), `live.yml` (live and live-docker, triggered by `launcher.py`), `pr-title.yml` (conventional title) — 6 checks transcribed.
- Scope: phases 2-4 of the brief (emitter, `use` verb, rules hook). Phase 1 (manual spike) is a precondition for `/spec-evidence:build`. Phases 5 and 6 become follow-up issues. Ruled by mcrowe, 2026-10-31.

## Facts this SPEC rests on
1. `assemble(root, stack_name, build_dir, harness, ...)` writes the profile at `build_dir/profiles/<stack>/<harness>`; `paths.profile_dir(stack, harness)` returns it — `assemble.py:253`, `paths.py:570`, read.
2. The profile holds `.claude/skills`, `.claude/commands`, `.claude/rules` and `.claude/CLAUDE.md`, and no agents — `synclinks.py:99-113`, `emit.py:174-188`, read by the survey subagent and spot-checked.
3. `emit._recipe_hooks_settings(recipes, harness)` returns `{event: [{"matcher"?, "hooks": [{"type": "command", "command"}]}]}` and honors `skip_harnesses` per recipe and per entry — `emit.py:617-652`, read.
4. Recipe hooks reach their scripts through `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/...`; 7 recipe files use `CLAUDE_CONFIG_DIR` — `catalog/recipes/ponytail/recipe.yaml:47-60`, read; `rg` count.
5. `hostrun._host_run_installs(stack, project_path, *, harness, home)` runs install scripts with `CLAUDE_CONFIG_DIR` set to `home` and a `$HOME` shim whose `.claude` links to `home` — `hostrun.py:598-630`, `paths.py:604`, read.
6. `hostrun._host_native_mcp(stack)` builds native `mcpServers` and skips service-backed servers — `hostrun.py:851-887`, survey.
7. `hostrun._host_tool_bin_dirs(stack)` returns the stack tools' real bin dirs from `mise bin-paths` — `hostrun.py:54`, read.
8. `launcher._resolve_stack(stack, recipe, extends, no_extends, service)` is the shared stack resolver — `launcher.py:3511`, read.
9. `emit.warn_duplicate_hooks(settings, harness, *, warn)` has one caller, `_merge_baked_settings` on the container path — `emit.py:866`, `launcher.py:1283`, read and survey.
10. `svcstate._service_refs(stack)` unions a stack's services with recipe MCP `service:` refs — `svcstate.py:282`, survey.
11. Claude Code 2.1.314 has `claude plugin enable|disable -s user|project|local`, `claude plugin marketplace add|list|remove`, and `claude plugin validate --strict` — `claude plugin <cmd> --help`, run.
12. No source file uses `CLAUDE_CODE_PLUGIN_DIRS`, `marketplace` or `enabledPlugins` today — survey `rg`.

## Decide calls

### Decide 1. Who writes project-scope enablement?
Brief line 65 says `use` writes `<stack>@harnessed` into `<path>/.claude/settings.local.json`; brief line 72 says every change to `~/.claude` goes through the `claude plugin` CLI. `claude plugin enable` takes `--scope local` (fact 11).

- A. Run `claude plugin enable|disable <id> --scope local` with cwd `<path>`. Cost: depends on the CLI resolving local scope from the cwd and enabling with no install record, which the phase 1 spike must confirm.
- B. harnessed edits `<path>/.claude/settings.local.json` itself with `jsonmerge`. Cost: harnessed owns a settings format Claude Code may change, and two code paths for two scopes.

Default: A.
- Ruling: A, the claude CLI with `--scope local` and cwd `<path>` (mcrowe, 2026-10-31)
Changes: S3.1, S3.3, S3.5, S3.14 use `claude plugin enable|disable --scope local`.

### Decide 2. One plugin per stack, or one plugin per recipe?
Brief open question 1.

- A. One plugin per stack, built from the assembled profile. Cost: two stacks that share a recipe ship two copies of it, and switching is one plugin at a time.
- B. One plugin per recipe; a stack is a set of enabled plugins. Cost: stack `instructions:` and `extends:` have no plugin home, and `use` must enable and disable sets.

Default: A.
- Ruling: A, one plugin per stack (mcrowe, 2026-10-31)
Changes: S1 and S3 build and switch one plugin per stack.

### Decide 3. How do rules and instructions reach Claude?
Brief open question 2. Plugins have no rules or CLAUDE.md component (brief, verified platform facts).

- A. A `SessionStart` hook prints them. Cost: rules lose `paths:` scoping and arrive as hook output, not memory.
- B. harnessed writes them into `~/.claude/rules/harnessed/`. Cost: harnessed writes into `~/.claude`, which breaks the ownership rule, and the rules apply globally whatever the enable scope.

Default: A.
- Ruling: A, a SessionStart hook (mcrowe, 2026-10-31)
Changes: S2 delivers rules and instructions through `context.md` and a SessionStart hook.

## Revisions
### Revision 1. Decide 1-3 ruled A
The engineer ruled all three Decide calls in the hotfix Decide round; SPEC.md Orientation records them.
### Revision 2. Gate 1a round 1 findings fixed
Defined the brief and its six phases, and described the spike with no phase number (PR-REFERENT 1). Defined a stack tool bin dir, an install script and a scope in Terms (PR-REFERENT 2 and both gaps).

## Spike (phase 1), run 2026-10-31 by the doer during build, Claude Code 2.1.314, temp `CLAUDE_CONFIG_DIR`
- `claude plugin marketplace add <dir>` registers a local-path marketplace and records it in user `extraKnownMarketplaces`.
- `claude plugin enable s1@harnessed --scope local` with cwd `<proj>` writes `<proj>/.claude/settings.local.json`; `--scope user` writes `$CLAUDE_CONFIG_DIR/settings.json`. Neither needs `claude plugin install`.
- `claude plugin validate --strict` passes only with `version`, `description` and `author` in `plugin.json` and `metadata.description` in `marketplace.json`.
- `claude plugin details s1@harnessed` lists the plugin's skills, commands and SessionStart hook.
- `claude plugin list --json` returns `[]` for an enabled plugin that was never installed, so it cannot tell `use` what is enabled. `disable` on an already-disabled plugin exits 1.
- `claude plugin marketplace list --json` reports each marketplace's directory as `path`, not `source`.

### Decide 4. How does `use` learn which harnessed plugins are enabled at a scope?
Spike: `plugin list --json` omits enabled plugins with no install record.

- A. Read `enabledPlugins` from the scope's settings file (local `<proj>/.claude/settings.local.json`, user `$CLAUDE_CONFIG_DIR/settings.json`). Cost: harnessed depends on that layout for reads.
- B. Disable every plugin in harnessed's `marketplace.json` except the target and ignore the "already disabled" exit. Cost: one call per stack, and an error string decides failure.

Default: A.
- Ruling: A, read `enabledPlugins` (mcrowe, 2026-10-31)
Changes: S3 preamble, S3.2, S3.3, S3.5, S3.10.

### Revision 3. Spike findings folded in after approval
The spike ran after the approval commit and showed `plugin list --json` cannot report enablement. Decide 4 replaced it with a read of `enabledPlugins`. S3.2 names the `path` field the CLI really prints. No scenario was added or removed.

## Facts found during build
13. A recipe command is a directory, never a file (`synclinks.py:53` registers commands with no `allow_file`), so the fixture's command is `commands/bar/bar.md` and S1.1 reads that path. Rules may be files (`synclinks.py:56`).
14. The stack schema has `harnesses:`, not `harness:` (`schema.py` `_validate_stack_fields`).
15. `emit.warn_duplicate_hooks` prints the command by its `repr`, so S2.4's test reads `repr(command)`.
16. `gh-issue-tracker`'s SessionStart hook reaches its script through `$HARNESSED_CONFIG_DIR`, which no plugin sets. Its `test -x` guard makes the hook a silent no-op under `use`. The approved property test forbids a rewrite of any command without `CLAUDE_CONFIG_DIR`, so the rewrite leaves it alone.
