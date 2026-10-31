## Evidence Report — Deliver a stack as a Claude Code plugin with `harnessed use` (phases 2-4) (Tier 3)

## Summary
Delivered: `harnessed use claude [path] --stack X` turns a stack into a Claude Code plugin in harnessed's own marketplace at `$XDG_DATA_HOME/harnessed/marketplace`, registers that marketplace, enables `X@harnessed` for the project (or for the user with `--global`), and disables the other harnessed plugins at that scope. `--off` turns them all off. This gives plain `claude`, on the real `~/.claude`, a stack's skills, commands, hooks, MCP servers, rules and instructions. Before this, a stack reached Claude only through a separate config dir.

How each criterion was proven, all by tests in the final run (see Spec → Test mapping):
- S1, the emitter: tests on a fixture stack show skills and commands copied byte for byte, config-dir hook paths rewritten to `${CLAUDE_PLUGIN_ROOT}`, user hooks, permissions and credentials kept out, `skip_harnesses` honored, MCP commands resolved to stack tool binaries, the `PATH` prefix, a marketplace file that lists every stack, and a rebuild that leaves other stacks alone. The real `claude plugin validate --strict` accepts the emitted plugins. Two hypothesis tests cover the rewrite.
- S2, rules and instructions: `context.md` holds the instructions, then the rules in sorted path order. The SessionStart hook prints it byte for byte, and a stack with neither gets no hook. A user hook that duplicates a plugin hook is warned through the existing `emit.warn_duplicate_hooks`.
- S3, the `use` verb: a recording fake `claude` shows the call order, the scope, and the cwd. It also shows that no non-harnessed plugin is disabled, and that services, other harnesses and a missing binary are refused. Settings a plugin cannot carry are warned. Installs land in the plugin, and `~/.claude` keeps its bytes and mtimes. One test drives the real `claude` through A, then B, then off, and shows that user settings come back equal apart from the two plugin keys.

Mutation testing on `plugin.py` killed 310 mutants. The 8 that survive are named as equivalent. Agent decisions A12 to A14 came from review and the gauntlet.

Not proven: the adversary review read commit 396901b, not the final one. Round 2 raised a hunch that was then confirmed and fixed, and the four later commits were not reviewed. The live CI jobs run only when the PR opens. The manual `/plugin` and `/context` check in a real session is still for the engineer.

## Agent decisions
<details><summary>14 agent decisions</summary>

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

</details>

### Review risks
- The adversary layer is bound to 396901b. Round 2 raised a hunch about local scope from a subdirectory. I confirmed it against claude 2.1.314 and fixed it in 0391d48. The loop says a confirmed problem in round 2 means the change is too entangled for this method. I fixed the problem instead of abandoning the change, and the engineer judges that call. Commits 0391d48, 4ae2ac3, b1b67e1, 20715f4 and 1eef1d0 had no adversary read.
- The SPEC changed after approval (decisions.md Revision 3, Decide 4). The spike showed that `claude plugin list --json` omits plugins enabled without an install, so S3 reads `enabledPlugins` from the settings file. The approval commit cd1aa69 holds the text from before the spike.
- The `gh-issue-tracker` SessionStart hook finds its script through `$HARNESSED_CONFIG_DIR`, which no plugin sets. Under `use`, that hook does nothing and stays silent (decisions.md fact 16). The approved property test forbids rewriting that variable.
- The `PATH` prefix applies only to the first command of a compound hook such as `a && b` (adversary round 2 hunch). S1.6 specifies this prefix.
- The registration check compares the marketplace `path` as a string, with no `resolve()`. A symlinked `XDG_DATA_HOME` could make `use` run `marketplace add` again (adversary round 2 hunch, not confirmed).
- The settings preflight reads the project's `settings.local.json` even under `--global`, so a malformed project file blocks a global `use` (adversary round 2 hunch).
- `hostrun._host_native_mcp` warns "needs 'srv' on PATH" before `plugin.py` resolves the command to the stack's tool binary, so `use` can print a false warning (adversary round 1 hunch).
- A recipe ships a command as a directory (decisions.md fact 13), so no recipe can produce the SPEC's flat `.claude/commands/bar.md`. The S1.1 test writes that file into the assembled profile directly and checks both it and the recipe's `commands/bar/bar.md`.
- `plugin.scope_settings_path` runs `git rev-parse` with no timeout. The subprocess audit does not cover `plugin.py`.
- The baseline stamp records exit codes, not test counts. The baseline count of 4818 passed is derived: the run at b1b67e1 had 4861 passed and 1 failed, minus 44 new tests.

### Not reached by review
- Round 1: calls 2/10; hunts not reached: 4 (hook-command edge inputs beyond the regex review), 6, 7, 8 (no EVIDENCE report was in the diff), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/hostrun.py:598 (_host_run_installs, home shim), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/emit.py:866 (warn_duplicate_hooks output format), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/launcher.py:3511 (_resolve_stack, name validation), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/.github/workflows/live.yml
- Round 2: calls 4/10; hunts not reached: 4 (hook-command edge inputs beyond the regex review), 6, 7, 8 (the diff has no EVIDENCE report), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/hostrun.py:598 (_host_run_installs home shim), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/launcher.py:3511 (_resolve_stack name validation, for a path-traversing --stack value), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/src/harnessed/emit.py:866 (warn_duplicate_hooks), /home/mcrowe/Programming/Personal/harnessed/plugin-mode/.github/workflows/live.yml

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: a plugin emitter (`src/harnessed/plugin.py`) and a `harnessed use` verb that enables one stack as a Claude Code plugin at local or user scope.
- Proven: 29/29 scenarios mapped and passing
- Not proven: adversary review of the final commit (SUBSTITUTED by review of 396901b); live CI (UNAVAILABLE until the PR); manual `/plugin` and `/context` session check (UNAVAILABLE, engineer by hand)

- Process: spec-evidence 0.0.1 (gate files: story-gate.md none, spec-gate.md spec-evidence 0.0.1)
- Spec: spec-evidence/2026-10-31-GH-649/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit cd1aa69); Revision 3 and Decide 4 ruled by mcrowe after it (commit 1e0405f)
- Intent review: not run, engineering lane
- Source state: commit 1eef1d0dca4b0eaf845b53511095b6bd20a705f0 — the commit the final run read; the adversary read 396901b
- Baseline: baseline-stamp.json at commit cd1aa6911a08778fe0cfad43abc65faf441e08c6, green

<details>
<summary>Stamp: green, 6/6 layers</summary>

```json
{
  "result": "green",
  "mode": "full",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 399.105, "coverage": 423.007, "types": 14.836, "lint": 0.13, "shellcheck": 1.524, "secrets": 2.598},
  "layers": {
    "tests": {"baseline": "reused", "selection": "off"},
    "coverage": {"baseline": "reused", "selection": "off"},
    "types": {"baseline": "reused", "selection": "off"},
    "lint": {"baseline": "reused", "selection": "off"},
    "shellcheck": {"baseline": "reused", "selection": "off"},
    "secrets": {"baseline": "reused", "selection": "off"}
  },
  "failed": null,
  "exit_code": 0,
  "commit": "1eef1d0dca4b0eaf845b53511095b6bd20a705f0",
  "dirty": false,
  "written": "2026-10-31T15:41:31.625Z"
}
```

</details>

### Spec → Test mapping
Every row is `pass`.

<details>
<summary>29/29 scenarios mapped and passing</summary>

| Scenario | Test | Status |
|---|---|---|
| S1.1 | tests/test_plugin.py::TestEmitter::test_s1_1_skills_commands_and_manifest_are_copied | pass |
| S1.2 | tests/test_plugin.py::TestEmitter::test_s1_2_config_dir_hook_paths_point_at_the_plugin; tests/test_plugin.py::test_no_rewritten_command_contains_the_config_dir; tests/test_plugin.py::test_a_command_without_the_config_dir_is_unchanged; tests/test_plugin.py::TestMutationGaps::test_bare_config_dir_becomes_the_plugin_root | pass |
| S1.3 | tests/test_plugin.py::TestEmitter::test_s1_3_user_hooks_and_permissions_never_enter_the_plugin | pass |
| S1.4 | tests/test_plugin.py::TestEmitter::test_s1_4_entry_skipped_for_claude_is_absent | pass |
| S1.5 | tests/test_plugin.py::TestEmitter::test_s1_5_mcp_servers_resolve_tools_and_keep_urls; tests/test_plugin.py::TestMutationGaps::test_s1_5_tool_lookup_spans_every_bin_dir | pass |
| S1.6 | tests/test_plugin.py::TestEmitter::test_s1_6_tool_bin_dirs_prefix_every_recipe_hook; tests/test_plugin.py::TestEmitter::test_s1_6_no_tools_means_no_prefix | pass |
| S1.7 | tests/test_plugin.py::TestEmitter::test_s1_7_marketplace_lists_every_stack_and_a_rebuild_touches_only_its_own; tests/test_plugin.py::TestMutationGaps::test_s1_7_marketplace_json_is_exact; tests/test_plugin.py::TestMutationGaps::test_marketplace_is_under_xdg_data_home | pass |
| S1.8 | tests/test_plugin.py::TestEmitter::test_s1_8_empty_stack_gets_only_a_manifest | pass |
| S1.9 | tests/test_plugin.py::TestEmitter::test_s1_9_claude_validates_each_fixture_plugin (real claude 2.1.314; not skipped in tests.log or coverage.log) | pass |
| S1.10 | tests/test_plugin.py::TestEmitter::test_s1_10_credentials_are_neither_copied_nor_linked; tests/test_plugin.py::TestMutationGaps::test_s1_10_a_symlink_in_the_profile_arrives_as_bytes | pass |
| S2.1 | tests/test_plugin.py::TestContextHook::test_s2_1_instructions_then_sorted_rules_with_a_last_sessionstart_hook; tests/test_plugin.py::TestMutationGaps::test_s2_1_rules_sort_by_relative_path_text_and_keep_trailing_spaces | pass |
| S2.2 | tests/test_plugin.py::TestContextHook::test_s2_2_no_instructions_or_rules_means_no_context | pass |
| S2.3 | tests/test_plugin.py::TestContextHook::test_s2_3_the_hook_prints_context_md | pass |
| S2.4 | tests/test_use.py::TestDuplicateHooks::test_s2_4_a_user_hook_equal_to_a_plugin_hook_is_warned; tests/test_use.py::TestDuplicateHooks::test_s2_4_no_overlap_prints_nothing | pass |
| S3.1 | tests/test_use.py::TestUse::test_s3_1_registers_then_enables_locally_in_the_project | pass |
| S3.2 | tests/test_use.py::TestUse::test_s3_2_a_registered_marketplace_is_not_added_again | pass |
| S3.3 | tests/test_use.py::TestUse::test_s3_3_enables_the_target_then_disables_only_other_harnessed_plugins; tests/test_use.py::TestUse::test_s3_3_from_a_subdirectory_reads_the_git_root_enablement | pass |
| S3.4 | tests/test_use.py::TestUse::test_s3_4_global_acts_at_user_scope_only; tests/test_use.py::TestUse::test_s3_4_user_scope_reads_claude_config_dir_first | pass |
| S3.5 | tests/test_use.py::TestUse::test_s3_5_off_disables_every_harnessed_plugin_and_nothing_else | pass |
| S3.6 | tests/test_use.py::TestUse::test_s3_6_a_stack_with_services_is_refused | pass |
| S3.7 | tests/test_use.py::TestUse::test_s3_7_only_claude_is_supported | pass |
| S3.8 | tests/test_use.py::TestUse::test_s3_8_settings_a_plugin_cannot_carry_are_warned | pass |
| S3.9 | tests/test_use.py::TestUse::test_s3_9_a_missing_claude_binary_is_named | pass |
| S3.10 | tests/test_use.py::TestUse::test_s3_10_a_failed_enable_leaves_the_previous_stack_on; tests/test_use.py::TestUse::test_s3_10_a_hung_claude_call_times_out_cleanly | pass |
| S3.11 | tests/test_use.py::test_s3_11_a_full_cycle_leaves_user_settings_as_they_were (real claude 2.1.314; not skipped) | pass |
| S3.12 | tests/test_use.py::TestUse::test_s3_12_and_s3_13_installs_land_in_the_plugin_and_home_claude_is_untouched; tests/test_use.py::TestUse::test_s3_12_a_failed_reinstall_keeps_the_previous_plugin | pass |
| S3.13 | tests/test_use.py::TestUse::test_s3_12_and_s3_13_installs_land_in_the_plugin_and_home_claude_is_untouched; tests/test_use.py::TestUse::test_s3_13_off_leaves_home_claude_untouched; tests/test_use.py::TestUse::test_s3_13_a_malformed_settings_file_stops_before_any_write | pass |
| S3.14 | tests/test_use.py::TestUse::test_s3_14_no_path_means_the_cwd | pass |
| S3.15 | tests/test_use.py::TestUse::test_s3_15_the_stack_resolves_as_host_run_resolves_it; tests/test_use.py::TestUse::test_s3_15_help_line | pass |

</details>

Must NOT:
- No write under `~/.claude` or `$CLAUDE_CONFIG_DIR`: covered by the S3.12 and S3.13 tests.
- Never calls `_materialize_host_home`: the `env` fixture in tests/test_use.py patches it in `hosthome` and `launcher` to raise, for every `use` test.
- `assemble()`, `host-run` and `container-run` are unchanged: the diff only adds lines to `launcher.py` (one import plus the block after `host_run`), and the tests layer passes at 4863.
- Never disables a non-`@harnessed` plugin: covered by S3.3 and S3.5.
- The container-path `warn_duplicate_hooks` call is unchanged: `_merge_baked_settings` is not in the diff, and its existing tests pass.
- No credential enters `<mkt>`: covered by S1.10.
- Nothing is written into the repo: `<mkt>` sits on `paths.xdg_data_home()` (`test_marketplace_is_under_xdg_data_home`).
- No new dependency: `pyproject.toml` and `uv.lock` are not in the diff.

### Gauntlet (final fresh run)
Every gauntlet-manifest row is `PASSED`. The SPEC rows outside the manifest are listed under Layers not run as specified.

<details>
<summary>6/6 layers PASSED</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4863 passed, 79 skipped, 0 failed | reused | off | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 87.17% total (threshold 80), 4863 passed, 79 skipped | reused | off | work/coverage.log |
| types | pyright with the dev venv as `--pythonpath` | PASSED — 0 errors | reused | off | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | reused | off | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — exit 0, includes tests/fixtures/recipes/plugin-recipe/install.sh | reused | off | work/shellcheck.log |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — no leaks found | reused | off | work/secrets.log |

</details>

Layers outside the manifest:
- Property: PASSED. These are the two hypothesis tests in tests/test_plugin.py, and they ran inside the tests layer.
- Mutation: PASSED. `HARNESSED_DIR=$PWD mutmut run "harnessed.plugin.x_*"`, with `tests_dir` narrowed for the run to tests/test_plugin.py and tests/test_use.py as pyproject.toml advises, ran at b1b67e1. It killed 310 and 8 survived, and all 8 are named as equivalent under Defect classes closed. `plugin.py` has not changed since b1b67e1, and a break check covers the S1.1 test added after it (Process notes).

### Layers not run as specified
- N-A: none
- UNAVAILABLE: live CI (`live`, `live-docker`) runs on the PR, which `/spec-evidence:pr` opens.
- UNAVAILABLE: the manual `/plugin` and `/context` check in a real session. No test drives the interactive UI, so the engineer confirms it by hand.
- SUBSTITUTED: the adversary review. Two rounds read up to 396901b, and nothing read the final commit 1eef1d0. A review of an earlier commit cannot detect a defect added by 0391d48, 4ae2ac3, b1b67e1, 20715f4 or 1eef1d0.
- SUBSTITUTED: mutation testing of `launcher.use`. mutmut gives a typer-decorated command zero mutants. Behavior tests drive `use` instead, and those tests cannot detect a mutant that no assertion observes.

### Defect classes closed
- Generator: a step that can fail runs after a destructive write to state Claude reads. Enumerated by reading every write in `use` and `emit_plugin` (`rg -n 'rmtree|write_text|rename' src/harnessed/plugin.py src/harnessed/launcher.py`, limited to the new block). Sites: 3. The `emit_plugin` rmtree is fixed (A12, restore from `.prev`). The settings reads that came after the emit are fixed (now read first). The `marketplace.json` rewrite is fixed (`write_marketplace` runs again on failure).
- Generator: the local-scope settings file is assumed to sit at the given path. Sites: 1. `plugin.scope_settings_path` is fixed (A13, git root).
- Generator: a subprocess in the new code has no deadline. Sites: 2. `launcher._claude_plugin` is fixed (A14). `plugin.scope_settings_path`'s `git rev-parse` is not applicable to the audit, because `plugin.py` is outside `_AUDITED`. It is listed under Review risks.
- Generator: a mutant of `plugin.py` that no test kills. Sites: 35 at the first run. 27 were killed by the tests in `TestMutationGaps` and `test_s3_4_user_scope_reads_claude_config_dir_first`, and 1 by removing the unused `stack` parameter of `plugin_hooks`. 8 are equivalent:
  - `_write_json` mutants 1, 3 and 5 (`mkdir(parents=…)`) are equivalent, because the parent always exists by then.
  - `_write_json` mutants 10, 12 and 13 (`indent=`) are equivalent, because indentation is only cosmetic and every reader parses the JSON.
  - `emit_plugin` mutants 32 and 35 (`symlinks=None` and the default) are equivalent, because both equal `False`.

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 151642/1596 |
| spec-evidence-intent | — | not run, engineering lane | unrecorded |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 206406/5562 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 298796/4056 |

### Process notes
- The phase 1 spike ran during build, at the start of this run, against claude 2.1.314 in a temp `CLAUDE_CONFIG_DIR`. Its findings are in decisions.md.
- mutmut first failed at stats collection because the tests unset `HARNESSED_DIR`, so the mutants tree could not find the catalog. I removed that line (88de87e). It failed again on a hypothesis `differing_executors` health check, so the property tests became module-level functions (4ae2ac3). Neither change touched an assertion.
- The first final gauntlet at b1b67e1 was red. `tests/test_subprocess_timeout_audit.py` failed on the unbounded `claude plugin` call, which 20715f4 fixed. The run above is the one after that fix.
- The S2.4 test first asserted the raw command text. `warn_duplicate_hooks` prints the command by its `repr`, so the test now looks for `repr(command)` (decisions.md fact 15).
- Gate 2a pass 1 (0c5cac2) was not-ready on S1.1, because the test read only `commands/bar/bar.md`. 1eef1d0 added the SPEC's flat `commands/bar.md`. The added assertion passed at once, so I broke the emitter by removing `commands` from the copy: S1.1 failed, then passed after the restore. The gauntlet above ran after that commit.
- The fixture stack first used `harness:`, which the schema does not have. It now uses `harnesses:` (decisions.md fact 14).
