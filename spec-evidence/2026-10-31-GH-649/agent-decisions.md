# Agent decisions: Deliver a stack as a Claude Code plugin with `harnessed use` (phases 2-4)

### A1. Plugin hooks come from the recipes through `emit._recipe_hooks_settings`
- Other option: copy the `hooks` block of the profile's `settings.json`.
- Why: a host launch merges the user's `~/.claude/settings.json` into that file (`launcher.py:3377`), so it can hold the user's own hooks and permissions.
- Command: hotfix

### A2. Stack tools reach hooks through a `PATH` prefix and reach MCP servers through an absolute command path
- Other option: parse each hook command and replace the binary name with its absolute path.
- Why: hook commands are free shell strings, often `sh -c '...'`, so a parse is unreliable; an MCP `command` is one field and can be resolved exactly.
- Command: hotfix

### A3. Rules and instructions are joined into one `context.md` at build time
- Other option: the hook command globs the rules directory at session start.
- Why: rule files sit at mixed depths (`a/RULE.md`, `b.md`), and a build-time join gives a fixed order and bytes a test can compare.
- Command: hotfix

### A4. `use` enables the target plugin before it disables the others
- Other option: disable the others first, then enable the target, as the brief's "Switching" line orders it.
- Why: when the enable fails, the previous stack stays on instead of leaving no stack enabled.
- Command: hotfix

### A5. The settings round-trip test compares parsed JSON with `enabledPlugins` and `extraKnownMarketplaces` removed
- Other option: compare bytes apart from `enabledPlugins`, as the brief's phase 3 says.
- Why: the `claude` CLI may rewrite the file's formatting, and `marketplace add` may record the marketplace in `extraKnownMarketplaces`; neither is a harnessed write.
- Command: hotfix

### A6. `marketplace_dir()` lives in `plugin.py`, built on `paths.xdg_data_home()`
- Other option: add it to `paths.py` beside `profile_dir`.
- Why: `plugin.py` is its only user, and the path is still anchored on the XDG data dir, never the cwd.
- Command: hotfix
