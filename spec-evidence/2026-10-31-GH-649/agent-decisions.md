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

### A7. S3.8 warns on the stack's `permissions:` field and on every key of its `settings:`
- Other option: warn only when `settings:` holds one of `permissions`, `env`, `defaultMode` or `statusLine`.
- Why: the stack schema refuses `settings.permissions` (`schema.py:2178`), so permissions can only come from the `permissions:` field, and a plugin carries no stack `settings:` key at all.
- Command: build

### A8. S2.4 compares the plugin's hooks with the user settings file only
- Other option: also read the project's `.claude/settings.json` and `.claude/settings.local.json`.
- Why: S2.4 names the user's `~/.claude/settings.json`, and a project hook file belongs to the project, not to the user.
- Command: build

### A9. A stdio MCP command not found in a stack tool bin dir is left as the recipe declares it
- Other option: refuse to emit the plugin.
- Why: `host-run` warns and continues for the same case (`hostrun._host_native_mcp`), so the two paths agree.
- Command: build

### A10. The marketplace counts as registered only when its name is `harnessed` and its `path` is `<mkt>`
- Other option: match on the name alone.
- Why: a `harnessed` marketplace registered at another path would point Claude at the wrong plugins.
- Command: build

### A11. The fixture recipe lives at `tests/fixtures/recipes/plugin-recipe/`
- Other option: write the recipe inline in each test, as `tests/test_host_acp.py` does.
- Why: skills, commands and rules resolve against the recipe root, so they need files on disk, and both test files share them.
- Command: build

### A12. A rebuild moves the previous plugin to `<mkt>/.prev/<stack>` and restores it when the emit or an install fails
- Other option: rebuild in place, and on failure remove the plugin and drop it from `marketplace.json`.
- Why: the plugin may be enabled, and the previous working plugin is better than a missing one or one whose hooks name files no install wrote.
- Command: build

### A13. Local-scope enablement is read at `git rev-parse --show-toplevel` of the path, else at the path
- Other option: read the settings file at the path and at every parent directory.
- Why: claude 2.1.314 wrote `<git root>/.claude/settings.local.json` when run from a subdirectory (measured), and the git root is the one place it writes.
- Command: build

### A14. Each `claude plugin` call has a 120-second timeout and fails `use` with a message when it expires
- Other option: mark the call `# unbounded:` with a reason, as the subprocess audit allows.
- Why: each call only edits a settings file, so a call that runs for two minutes is hung, and `use` must not wait forever.
- Command: build
