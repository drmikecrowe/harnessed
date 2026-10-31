# SPEC — Deliver a stack as a Claude Code plugin with `harnessed use` (phases 2-4)

## Summary
What it achieves: plain `claude`, running against the real `~/.claude`, gets a harnessed stack's skills, commands, hooks, MCP servers, rules and instructions. The user runs `harnessed use claude [path] --stack X` once. Claude Code's plugin system then loads the stack, and `harnessed use claude [path] --off` turns it off again.

Why: today a stack reaches Claude only through `host-run` or `container-run`, which give Claude a separate config dir. Tools that read `~/.claude` do not work there, and a `claude` started by an editor or another tool gets no stack. Claude Code's plugin system can carry most of a stack while the user keeps the real `~/.claude`.

What changes: a new module `src/harnessed/plugin.py` turns a stack into a plugin directory inside a harnessed-owned local marketplace at `$XDG_DATA_HOME/harnessed/marketplace/`. A new verb `harnessed use` builds that plugin, runs the stack's install scripts into it, registers the marketplace with the `claude` CLI, and enables the plugin at project scope (default) or user scope (`--global`). The stack's rules and instructions reach Claude through a `SessionStart` hook that prints them. harnessed itself writes no file under `~/.claude`; every change there goes through `claude plugin`.

The criteria in plain words:
- S1: the emitter writes a plugin directory with the stack's skills, commands, hooks and MCP servers. Hook paths that point at the config dir are rewritten to point at the plugin. The user's own settings, hooks and permissions never enter the plugin. The marketplace file lists every emitted stack, and rebuilding one stack leaves the others alone.
- S2: the stack's instructions and rules are joined into one file that a `SessionStart` hook prints. A stack with none gets no such hook.
- S3: `use` registers the marketplace once, enables the target plugin, then disables every other harnessed plugin at the same scope. `--off` disables them all. `use` refuses a stack with services, a harness other than `claude`, and a missing `claude` binary. It warns about stack settings a plugin cannot carry. Install scripts write into the plugin directory, never into `~/.claude`. A full A, then B, then off cycle leaves `~/.claude/settings.json` as it was apart from the plugin keys.

What must not change: `assemble()`, `host-run`, `container-run` and the container-path duplicate-hook warning behave exactly as before. harnessed never writes into `~/.claude` directly, never calls `_materialize_host_home` from this path, never disables a plugin that is not `@harnessed`, and never copies a credential into the plugin.

How each criterion is proven: pytest tests against a temporary `HOME` and `XDG_DATA_HOME` and a fake `claude` binary that records its arguments; one integration test with the real `claude` binary when it is present (skipped with a reason when not); `claude plugin validate --strict` on each emitted fixture plugin when `claude` is present; property tests for the hook-path rewrite; mutation testing on `plugin.py`. The live CI jobs run because `launcher.py` is a live trigger. The engineer confirms `/plugin` and `/context` in a real session by hand, since no test drives the interactive UI.

Open decisions: none. Ruled by mcrowe on 2026-10-31: the `claude` CLI writes project-scope enablement; one plugin per stack; rules and instructions arrive through a SessionStart hook.

## Orientation
- Change: a plugin emitter, a local harnessed marketplace, and a `harnessed use` verb that enables one stack as a Claude Code plugin at project or user scope.
- Why: a stack reaches Claude only through a separate config dir, which breaks tools that read `~/.claude` and gives nothing to a `claude` that harnessed did not start.
- Lane: engineering, because it changes how harnessed delivers a stack to Claude Code (the plugin system instead of a separate config dir), a design change with no product author.
- Touches: new `src/harnessed/plugin.py`, `src/harnessed/launcher.py`, new tests and one fixture stack.
- Decide: who writes project-scope enablement (S3.1); plugin per stack or per recipe (S1, S3); rules through a hook (S2).
- Decided: Decide 1 A, the `claude` CLI writes project-scope enablement with `--scope local`, governs S3.1, S3.3, S3.5 and S3.14; Decide 2 A, one plugin per stack, governs S1 and S3; Decide 3 A, a SessionStart hook, governs S2 (mcrowe, 2026-10-31).

- Tier: 3 — `use` changes the user's real Claude settings, so a defect can lose user config.
- Issue: GH-649
- Isolation: worktree — `worktrees/plugin-mode`, branch `plugin-mode`, per AGENTS.md §Git workflow.

Precondition for `/spec-evidence:build`: phase 1 of the brief, the manual spike, has passed. It shows that a local-path marketplace added with `claude plugin marketplace add` lets `claude plugin enable <stack>@harnessed --scope local|user` succeed with no `claude plugin install`, and that `claude plugin validate --strict` accepts the layout in S1. If the spike fails, the SPEC is revised before RED.

Terms used below:
- `<mkt>` is `$XDG_DATA_HOME/harnessed/marketplace` (default `~/.local/share/harnessed/marketplace`).
- `<plugin>` is `<mkt>/plugins/<stack>`.
- The profile is `paths.profile_dir(<stack>, "claude")`, as `assemble()` writes it.
- A harnessed plugin is a plugin whose id ends in `@harnessed`.

## Failure model (Tier 3)
- Writes into `~/.claude` outside the `claude` CLI: caught by S3.12, S3.13 and the Must NOT test that snapshots temp `HOME/.claude`.
- Disables a user's own plugin: caught by S3.3 and S3.5.
- Leaves no stack enabled after a failed switch: caught by S3.10.
- Leaks user hooks, permissions or credentials into the plugin: caught by S1.3 and S1.10.
- A rewritten hook path points at a file that is not there: caught by S1.2 and the property test.
- One stack's rebuild damages another's plugin: caught by S1.7.

## Scenarios
### S1. The plugin emitter
Ruled by mcrowe, 2026-10-31 (Decide 2 A): one plugin per stack, built from that stack's assembled profile.
- S1.1 Given the fixture stack `plugin-stack` whose profile holds `.claude/skills/foo/SKILL.md` and `.claude/commands/bar.md`, when `emit_plugin("plugin-stack")` runs, then `<plugin>/skills/foo/SKILL.md` and `<plugin>/commands/bar.md` exist with the profile's bytes, and `<plugin>/.claude-plugin/plugin.json` parses to an object whose `name` is `"plugin-stack"`.
- S1.2 Given a recipe hook command `sh -c 'exec node "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/x/hooks/a.js"'`, when the plugin is emitted, then the matching command in `<plugin>/hooks/hooks.json` reads `sh -c 'exec node "${CLAUDE_PLUGIN_ROOT}/x/hooks/a.js"'`, and no command in that file contains the text `CLAUDE_CONFIG_DIR`.
- S1.3 Given a temp `HOME` whose `.claude/settings.json` holds a hook `echo user-hook` and a `permissions.allow` list, when the plugin is emitted, then no file under `<plugin>` contains `user-hook` or a `permissions` key. Hooks come from the stack's recipes through `emit._recipe_hooks_settings(recipes, "claude")`, never from the profile's `settings.json`.
- S1.4 (boundary) Given a recipe hook entry whose `skip_harnesses` names `claude`, when the plugin is emitted, then that command is absent from `hooks.json`.
- S1.5 Given a stdio MCP server whose `command` is `srv` and a stack tool bin dir that holds an executable `srv`, when the plugin is emitted, then `<plugin>/.mcp.json` has `mcpServers.<name>.command` equal to that executable's absolute path. A url server keeps its `url` and `headers` unchanged, `${VAR}` text included. A service-backed server is absent. The server set is `hostrun._host_native_mcp(<stack>)`.
- S1.6 Given a stack whose `tools:` gives bin dirs `D1` and `D2`, when the plugin is emitted, then each hook command in `hooks.json` begins with `PATH="D1:D2:$PATH" `, followed by the recipe's command after the S1.2 rewrite. Given a stack with no `tools:`, no command gains a prefix.
- S1.7 Given stacks `A` and `B` both emitted, when `A` is emitted again after a file is removed from its profile, then `<mkt>/.claude-plugin/marketplace.json` has `name` `"harnessed"` and one plugin entry per stack with `source` `"./plugins/A"` and `"./plugins/B"`, every file under `<mkt>/plugins/B` is byte-equal to before, and the removed file is absent from `<mkt>/plugins/A`.
- S1.8 (boundary) Given a stack with no hooks, no MCP servers, no rules and no instructions, when the plugin is emitted, then `<plugin>/hooks/hooks.json` and `<plugin>/.mcp.json` do not exist and `plugin.json` does.
- S1.9 Given the `claude` binary on `PATH`, when `claude plugin validate --strict <plugin>` runs on each fixture stack's emitted plugin, then it exits 0. Without the binary, the test is skipped with the reason `claude not on PATH`.
- S1.10 (negative) Given a temp `HOME` holding `.claude/.credentials.json` and `.claude.json`, when the plugin is emitted, then no file under `<mkt>` has the bytes of either file and no file under `<mkt>` is a symlink to either.

### S2. Rules and instructions through a SessionStart hook
Ruled by mcrowe, 2026-10-31 (Decide 3 A): rules and instructions reach Claude only through this hook, never through a write into `~/.claude/rules/`.
- S2.1 Given a profile whose `.claude/CLAUDE.md` holds `I` and whose `.claude/rules/` holds `b.md` (`B`) and `a/RULE.md` (`A`), when the plugin is emitted, then `<plugin>/context.md` is `I`, a blank line, `A`, a blank line, `B`: instructions first, then each rule file in sorted relative-path order. The last `SessionStart` group in `hooks.json` is `{"hooks": [{"type": "command", "command": "cat \"${CLAUDE_PLUGIN_ROOT}/context.md\""}]}`.
- S2.2 (boundary) Given a profile with no `CLAUDE.md` and an empty or missing `.claude/rules/`, when the plugin is emitted, then `<plugin>/context.md` does not exist and no hook command names `context.md`.
- S2.3 Given an emitted plugin with a `context.md`, when the S2.1 command runs under `sh -c` with `CLAUDE_PLUGIN_ROOT=<plugin>`, then its stdout is byte-equal to `context.md` and it exits 0.
- S2.4 Given a recipe hook whose emitted command equals a hook command in the temp `HOME`'s `.claude/settings.json` for the same event and matcher, when `use` runs, then `emit.warn_duplicate_hooks` is called on the user's hooks plus the plugin's hooks, and stderr names that event and command. Given no overlap, nothing is printed. The container-path call in `_merge_baked_settings` is unchanged.

### S3. The `use` verb
Ruled by mcrowe, 2026-10-31 (Decide 1 A, Decide 2 A): one plugin per stack, and both scopes change enablement only through `claude plugin enable|disable --scope local|user`.
Each S3 scenario runs with a temp `HOME`, a temp `XDG_DATA_HOME`, and a fake `claude` on `PATH` that records every argv and its cwd, and answers `plugin marketplace list --json` and `plugin list --json` from a fixture. S3.11 alone uses the real binary.
- S3.1 Given the marketplace not registered and no harnessed plugin enabled, when `harnessed use claude <proj> --stack plugin-stack` runs, then the fake records, in order: `plugin marketplace add <mkt>`, then `plugin enable plugin-stack@harnessed --scope local` with cwd `<proj>`, and `use` exits 0.
- S3.2 (boundary) Given `plugin marketplace list --json` already lists `harnessed` with source `<mkt>`, when S3.1's command runs, then no `plugin marketplace add` is recorded.
- S3.3 Given `plugin list --json` reports `B@harnessed` and `other@vendor` enabled at local scope, when `use claude <proj> --stack A` runs, then the fake records `plugin enable A@harnessed --scope local` before `plugin disable B@harnessed --scope local`, and records no `disable` for `other@vendor`.
- S3.4 Given `--global`, when `use claude --global --stack A` runs, then every `enable` and `disable` carries `--scope user` and none carries `--scope local`.
- S3.5 Given `A@harnessed` and `other@vendor` enabled at local scope, when `use claude <proj> --off` runs, then the fake records `plugin disable A@harnessed --scope local`, no `enable`, no `marketplace add`, no `disable` for `other@vendor`, and `<mkt>` is unchanged.
- S3.6 (negative) Given a stack for which `svcstate._service_refs` is non-empty, when `use` runs, then it exits nonzero, stderr names each service and says `use` does not support services, the fake records no call, and `<plugin>` is not written.
- S3.7 (negative) Given `harnessed use codex --stack A`, then it exits nonzero, stderr says `use` supports only `claude`, and the fake records no call.
- S3.8 Given a stack whose `settings:` sets `permissions`, `env`, `defaultMode` or `statusLine`, when `use` runs, then stderr has one warning per key present naming it as not delivered by a plugin, and `use` exits 0.
- S3.9 (negative) Given no `claude` on `PATH`, when `use` runs, then it exits nonzero with a message naming the missing binary, and `<mkt>` is not created.
- S3.10 (negative) Given `B@harnessed` enabled and a fake whose `plugin enable` exits 1 with stderr `boom`, when `use --stack A` runs, then `use` exits nonzero, stderr includes `boom`, and no `disable` is recorded, so `B@harnessed` stays enabled.
- S3.11 Given the real `claude` binary and a temp `CLAUDE_CONFIG_DIR` holding a `settings.json` with unrelated keys, when `use --stack A`, then `use --stack B`, then `use --off` run, then the final `settings.json` parses equal to the first with the keys `enabledPlugins` and `extraKnownMarketplaces` removed from both. Without the binary, the test is skipped with the reason `claude not on PATH`.
- S3.12 Given a fixture recipe whose `install.sh` writes `$CLAUDE_CONFIG_DIR/x/marker`, when `use` runs, then `<plugin>/x/marker` exists and the temp `HOME/.claude` tree is unchanged. Installs run through `hostrun._host_run_installs(<stack>, <proj>, harness="claude", home=<plugin>)` after the plugin is emitted.
- S3.13 Given any S3 run, when it ends, then every file under the temp `HOME/.claude` has the same bytes and mtime as before the run. Changes there come only from the `claude` CLI, which the fake does not make.
- S3.14 (boundary) Given no `path` argument, when `use claude --stack A` runs from cwd `<proj>`, then local-scope calls carry cwd `<proj>`.
- S3.15 Given `--stack`, `--recipe`, `--extends` and `--no-extends`, when `use` runs, then it resolves the stack through `launcher._resolve_stack` exactly as `host-run` does, and `harnessed use --help` shows the line "Enable a stack as a Claude Code plugin for a project or globally."

## Must NOT
- harnessed writes no file under `~/.claude` or `$CLAUDE_CONFIG_DIR`; every change there goes through `claude plugin`. (S3.12, S3.13)
- This path never calls `hosthome._materialize_host_home`. (a test that patches it to raise)
- `assemble()`, `host-run` and `container-run` behave as before: the existing suite passes with the baseline count.
- `use` never disables a plugin whose id does not end in `@harnessed`. (S3.3, S3.5)
- The container-path `warn_duplicate_hooks` call in `_merge_baked_settings` is unchanged. (existing tests)
- No credential file or credential value is copied or linked into `<mkt>`. (S1.10)
- Nothing is written into the repo or `catalog/`; the marketplace is anchored on `paths.xdg_data_home()`, never on the cwd.
- No new dependency.

## Touches
- `src/harnessed/plugin.py` (new): `marketplace_dir()`, `emit_plugin(stack)`, `write_marketplace()`, the hook-path rewrite, the `PATH` prefix, the MCP command resolution, and `context.md`.
- `src/harnessed/launcher.py`: the `use` command, its stack flags shared with `host-run`, the enable and disable calls, and the duplicate-hook and unsupported-setting warnings.
- `tests/test_plugin.py` (new): S1 and S2.
- `tests/test_use.py` (new): S3 and the Must NOT checks.
- `tests/fixtures/stacks/plugin-stack/` (new): a stack with a skill, a command, a hook, an MCP server, a rule, instructions and an install script.

## Documentation
None in repo Markdown, because phase 6 of the brief rewrites the README promise as a follow-up issue. The verb's `--help` line is its documentation for this change.

## Known limits
- Agents: the profile holds no agents today (`synclinks.LinkSyncer.fan` fans out only skills, commands and rules), so the plugin ships none.
- Permissions, `env`, `defaultMode` and `statusLine` do not reach Claude; a plugin cannot carry them. `use` warns (S3.8).
- Rules lose `paths:` scoping and arrive as hook output, not memory.
- Skills and commands are namespaced: `/commit` becomes `/<stack>:commit`.
- Services and secrets are out of scope; `use` refuses services (S3.6), and secret values must come from the user's shell environment.
- `setup:` and `init:` scripts run as `host-run` runs them, against the host-run home, not the plugin.
- Tools that scan `~/.claude/skills` directly do not see plugin skills.
- omp, codex and opencode get nothing from this change.
- Session mode (`CLAUDE_CODE_PLUGIN_DIRS` for `host-run`, phase 5) and the README rewrite (phase 6) are follow-up issues.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | behavior regressions and S1-S3 | `tools/run-tests.sh` passes; count is the baseline plus the new tests |
| coverage | untested branches | `--cov-fail-under=80` passes |
| types | type errors | pyright reports no new error in `plugin.py` or `launcher.py` |
| lint | style and bug patterns | `ruff check src tests tools` exits 0 |
| shellcheck | shell defects in new fixture scripts | exits 0 |
| secrets | committed credentials | `gitleaks detect` finds nothing |
| property | the hook-path rewrite | a hypothesis test: any command without `CLAUDE_CONFIG_DIR` is unchanged by the rewrite, and no rewritten command contains it |
| mutation | weak tests on `plugin.py` | every surviving mutant of `plugin.py` is killed or named in EVIDENCE with a reason |
| live CI | the container path, since `launcher.py` is a live trigger | `live` and `live-docker` green on the PR |
| adversary | defects a self-review misses | every finding fixed or answered |
| manual | `/plugin` and `/context` in a real session | the engineer confirms the stack shows, a hook fires and an MCP server connects |
