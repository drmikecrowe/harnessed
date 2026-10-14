# SPEC — Copy ~/.claude/CLAUDE.md @-imports into stack rules for ACP sessions

## Summary

**What it achieves.** A `host-acp` or `container-acp` session gets the same instructions as an interactive session. Today, files that `~/.claude/CLAUDE.md` pulls in with `@`-imports (for example the Gortex `active.md`) never reach an ACP session, and nothing says so.

**Why.** The ACP adapter loads CLAUDE.md files but expands no `@`-imports, and it does not load a symlinked rule. It does load a regular file in the stack's `rules/`. This was verified on 2026-10-13 with random markers.

**What changes.** harnessed reads the whole-line `@<path>` imports in `~/.claude/CLAUDE.md`. If the user agrees, it writes a real copy of each imported file into a directory that harnessed owns: `rules/harnessed-imports/` in the stack's Claude config. The copy is rewritten on every launch. The answer (`y`, `n` or `i`) is stored per stack. `build`, `install`, `host-run` and `container-run` ask when no answer is stored. ACP launches never ask. `harnessed build --reask-imports` clears the answer and asks again.

**Acceptance criteria in plain words.**
1. The question is asked by the four terminal commands, and only for imports in `~/.claude/CLAUDE.md` (S1).
2. After `y`, both ACP modes see the imported text (S2).
3. When the imported file changes, the next launch sees the new text (S3).
4. `host-acp` with no answer, or with `n`, warns on stderr and writes nothing to stdout. With `y` or `i` it is silent (S4).
5. The answer is stored per stack and not asked again (S5).
6. A removed import, or an answer changed to `n` or `i` through `--reask-imports`, deletes harnessed's copy and never deletes a user's rule (S6).
7. A missing import target gives a warning and is skipped. Nested imports are not followed (S7).

**What must not change.** `~/.claude/CLAUDE.md` and the imported files are never written. Rules outside `rules/harnessed-imports/` are never deleted. ACP stdout carries protocol only. The stack fingerprint ignores imports. A launch never fails because of an import.

**How it is proven.** Unit tests in `tests/test_claude_imports.py` and `tests/test_launch_host.py` cover S1, S3.1, S4, S5, S6, S7 and the mount argument in S2.2. Live runs of `tools/acp-smoke.py --prompt` on a throwaway stack prove S2.3, S2.4 and S3.2. `live.yml` runs because `launcher.py` and `paths.py` change.

**Open decisions.** None. mcrowe ruled on 2026-10-14: the copies go in one owned subdirectory, only whole-line imports count, and only the claude harness gets copies.

## Orientation
- Change: copy whole-line `@`-imports from `~/.claude/CLAUDE.md` into a harnessed-owned `rules/harnessed-imports/` directory in each consenting stack, refreshed on every launch.
- Why: headless ACP sessions expand no `@`-imports and load no symlinked rule, so imported instructions are silently missing.
- Touches: new `src/harnessed/claude_imports.py`; `src/harnessed/paths.py`; `src/harnessed/launcher.py` (build, install, host-run, host-acp, container-run, the host launch plan, the container mount args); new `tests/test_claude_imports.py`; `tests/test_launch_host.py`.
- Decide: (1) where the copies live; (2) what counts as an import; (3) which harnesses.
- Decided: Decide 1 A, one owned `rules/harnessed-imports/` dir (governs S2, S3, S6); Decide 2 A, whole-line imports only (governs the Scenarios terms and S1.4); Decide 3 A, claude harness only (governs Known limits). Ruled by mcrowe, 2026-10-14.

- Tier: 2
- Issue: GH-600
- Isolation: worktree — `6-3-gh-600-claude-md-imports-to-rules` on branch `GH-600`.

## Scenarios

Terms. *Import file*: `~/.claude/CLAUDE.md`, resolved from `$HOME` at call time. *Import*: a line of that file whose stripped text is `@<path>`, where `<path>` begins with `/`, `~/` or neither (relative to `~/.claude/`). *Answer file*: `$XDG_STATE_HOME/harnessed/claude-imports/<stack>`, one byte `y`, `n` or `i`. *Copies dir*: `$XDG_DATA_HOME/harnessed/claude-imports/<stack>/`. *Copy name*: `<target stem>-<first 8 hex of sha256 of the resolved target path>.md`. *Owned dir*: `rules/harnessed-imports/` in the stack's Claude config (`paths.host_home(stack, "claude")` on the host, `/home/harnessed/.claude` in the container).

### S1. Who asks, and when
- S1.1 Given an import file holding the line `@~/.local/share/gortex/instructions/active.md`, no answer file for stack `s`, and a terminal that can prompt (`console._can_prompt()` true), when `harnessed build s claude` runs, then it prints `Your ~/.claude/CLAUDE.md uses @import syntax that ACP sessions do not expand. Copy the imported files into this stack's rules? [y/n/i]`. The same holds for `harnessed install s claude`, `harnessed host-run claude --stack s` and `harnessed container-run claude --stack s`.
- S1.2 (boundary) Given the import line only in a project `CLAUDE.md` or a parent directory's `CLAUDE.md`, and none in the import file, when `build` runs, then no prompt is printed and no answer file is written.
- S1.3 (negative) Given an import file with no import line, when any of the four commands runs, then no prompt is printed and no answer file is written.
- S1.4 (negative) Given an import file whose only `@` is mid-line, for example `mail me at a@b.com` or `` see `@foo` ``, when `build` runs, then no prompt is printed.
- S1.5 (negative) Given `container-acp`, `host-exec` or `container-exec`, or a launch where `_can_prompt()` is false, with no answer file, when the launch runs, then no prompt is printed and the launch does not block on stdin.

### S2. A `y` answer delivers the text to both ACP modes
- S2.1 Given the answer `y` for stack `s` and an import whose target holds `MARKER-a1`, when a host launch of `s` runs `_host_launch_plan`, then `<host home>/rules/harnessed-imports/active-<hash8>.md` is a regular file, not a symlink, and its bytes equal the target's bytes.
- S2.2 Given the answer `y` for stack `s`, when the container mount args for `s` are composed, then they hold `-v <copies dir>:/home/harnessed/.claude/rules/harnessed-imports:ro`, placed after the config-volume mount. With the answer `n`, `i` or none, no such mount is composed.
- S2.3 (live) Given the throwaway stack built with the answer `y` and a random marker line in the import target, when `tools/acp-smoke.py <project> --stack <s> --verb host-acp --harness claude --prompt "<ask for the marker>"` runs, then the reply holds the marker.
- S2.4 (live) Given the same stack and marker, when the same probe runs with `--verb container-acp`, then the reply holds the marker.
- S2.5 (negative) Given no answer file, when S2.1's launch runs, then no owned dir is created, and the S2.3 probe does not return the marker.

### S3. The copy is refreshed on every launch
- S3.1 Given the answer `y`, a launch that wrote a copy holding `MARKER-old`, and an unchanged stack fingerprint (no rebuild), when the import target changes to `MARKER-new` and the stack launches again, then the copy holds `MARKER-new` and not `MARKER-old`.
- S3.2 (live) Given S2.3's stack, when `gortex instructions switch` changes the target's content to a new marker and a new `host-acp` session starts, then the probe returns the new marker and not the old one.
- S3.3 (boundary) Given a refresh, when it rewrites the copies dir, then it replaces the directory's contents and keeps the directory itself, so a running container's bind mount sees the new files.
- S3.4 Given the answer `y` and a copies dir that holds a copy of `MARKER-old` plus a copy whose import was removed, when `ContainerBackend.materialize_config` runs for any container verb (`container-run`, `container-exec`, `container-acp`), then before the mount args are composed the copies dir holds the current target bytes (`MARKER-new`) and no copy for the removed import.

### S4. host-acp warns, on stderr only
- S4.1 Given an import in the import file and no answer file, when `host-acp` starts, then stderr holds `warning: ~/.claude/CLAUDE.md has @-imports this ACP session will not load. Run: harnessed build <stack> claude --reask-imports`, no owned dir is created, and stdout receives no byte from this step.
- S4.2 Given the answer `n`, when `host-acp` starts, then the same warning is printed and nothing is copied.
- S4.3 (negative) Given the answer `y` or `i`, when `host-acp` starts, then no import warning is printed.
- S4.4 (negative) Given no import in the import file, when `host-acp` starts, then no import warning is printed, whatever the answer.

### S5. The answer is stored per stack
- S5.1 Given stack `s` with no answer file, when the user answers `y` (then, in separate runs, `n` and `i`), then the answer file for `s` holds that letter, and the next `build s claude` asks nothing.
- S5.2 (boundary) Given an answer file for `s` and none for `t`, when `build t claude` runs on a terminal, then it asks.
- S5.3 (negative) Given the answer `n` or `i`, when a launch runs, then the copies dir and the owned dir hold no file.
- S5.4 (negative) Given an answer file holding anything other than `y`, `n` or `i`, when the answer is read, then it counts as no answer.

### S6. harnessed deletes its own stale copies, and only those
- S6.1 Given the answer `y` and a copy made for an import, when that import line is removed from the import file and the stack launches, then the copy is gone from the copies dir and from the owned dir.
- S6.2 Given the answer `y` and a copy, when `harnessed build s claude --reask-imports` runs and the user answers `n` (in a second run, `i`), then the answer file holds the new letter, and after the next launch the copies dir and the owned dir hold no file.
- S6.3 (negative) Given the answer `y` and a copy, when `build --reask-imports` is answered `y`, then no copy is deleted.
- S6.4 (negative) Given a user file `rules/mine.md` in the stack's Claude config beside the owned dir, when any S6 deletion runs, then `rules/mine.md` is unchanged.
- S6.5 (boundary) Given `build --reask-imports` where `_can_prompt()` is false, when it runs, then the answer file is removed and the S4.1 warning names the next step.

### S7. Missing and nested imports
- S7.1 Given the answer `y` and an import whose target does not exist, when `build` or a launch runs, then stderr holds `warning: @-import target not found, skipped: <path>`, the command exits 0, and every other import is still copied.
- S7.2 (boundary) Given an imported file that itself holds the line `@other.md`, when it is copied, then the copy holds `@other.md` as literal text and `other.md` is not copied.
- S7.3 (boundary) Given two imports with the same file name in different directories, or the same import listed twice, when they are copied, then the two distinct targets get two distinct copy names, and the duplicate line gets one copy.

## Must NOT
- Write to `~/.claude/CLAUDE.md` or to any import target.
- Delete or change any file under the stack's `rules/` outside `rules/harnessed-imports/`.
- Write any byte to stdout in `host-acp` or `container-acp` from this feature.
- Prompt, or read stdin, where `console._can_prompt()` is false or the verb is `container-acp`, `host-acp`, `host-exec` or `container-exec`.
- Fail `build`, `install` or any launch because of an import: a missing or unreadable target is a warning.
- Create a symlink anywhere in the copy path.
- Add the import file or its targets to `_host_stack_fingerprint` or `_container_stack_fingerprint`; a `gortex instructions switch` must not rebuild the stack.
- Convert imports from a project or parent `CLAUDE.md`.
- Break any existing test in `tests/test_launch_host.py`, the settings re-propagation in `_host_launch_plan`, or the mount order that `materialize_config` documents.

## Touches
- `src/harnessed/claude_imports.py` (new): parse imports, read and write the answer file, ask the question, refresh the copies dir, sync the owned dir, and print the warnings.
- `src/harnessed/paths.py`: `claude_imports_answer_file(stack)` and `claude_imports_dir(stack)`.
- `src/harnessed/launcher.py`: `build` gains `--reask-imports` and the ask; `install_stack`, `host_run` and `container_run` (non-ACP verbs) ask; `_host_launch_plan` syncs the owned dir after the settings propagation; `host_acp` warns; `ContainerBackend.materialize_config` refreshes the copies dir, then adds the ro directory mount.
- `tests/test_claude_imports.py` (new): S1, S3.1, S3.3, S3.4, S4, S5, S6, S7, S2.1, S2.2, S2.5.
- `tests/test_launch_host.py`: S2.1 and S3.1 through `_host_launch_plan`.

## Documentation
- `--reask-imports` help text in `build`. The `harnessed-catalog` skill and the wiki guides need no change in this PR. A wiki note in `docs/guides/troubleshooting.md` is a separate delivery, and it is named in the PR body.

## Known limits
- Only whole-line imports count (ruled by mcrowe, 2026-10-14). An inline `@path` in prose is not copied.
- Nested imports are not followed (story AC-7). Their text arrives literally.
- `claude` harness only (ruled by mcrowe, 2026-10-14). The omp stack's nested Claude config dir gets no copies.
- A container started before an import was added, and still running, sees the new file because the mount is a directory (ruled by mcrowe, 2026-10-14). A brand-new mount needs a new container.
- An interactive session loads the content twice, by the import and as the rule. The story accepts this.
- Whether claude-agent-acp 0.89.1 (the catalog pin; the issue observed 0.85.1) now expands imports is checked live first. If it does, the build stops and reports to the engineer.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1–S7 unit scenarios, no regression | all pass; the count does not drop below the baseline |
| coverage | branch coverage of `src` | at least 80% (`--cov-fail-under=80`) |
| types | pyright | 0 errors in changed files |
| lint | ruff on src, tests, tools | 0 findings |
| shellcheck | shell scripts | 0 findings (no shell change expected) |
| secrets | gitleaks | 0 leaks |
| live (manual) | S2.3, S2.4, S3.2 on a throwaway stack | each probe returns the expected marker |
| live.yml (CI) | container path: `launcher.py`, `paths.py` | `live` and `live-docker` green |
