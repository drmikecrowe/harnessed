# SPEC — Global launchers, local launcher only for aoe

## Summary
**What it achieves.** Every stack you install, build or launch gets one stable command per backend in `~/.local/bin`, such as `harnessed-claude-default-container`. Run it from any folder and it launches that stack there. A launch outside aoe no longer leaves a file in your project.

**Why.** Today every launch writes a launcher script into the project folder, and `harnessed install` writes a different, container-only shim named after the bare stack. Editors and aoe have no single command per stack to point at.

**What changes.** A new writer puts `harnessed-<harness>-<stack>-<backend>` files in `~/.local/bin`. `install`, `build`, `host-run` and every `container-run` call it. `install` and `uninstall` take `<stack> <harness>`. The old `~/.local/bin/<stack>` shim stops being written, and `uninstall` removes one it finds. The in-project launcher is written only when aoe is in use, and it now calls the global launcher. `harnessed rm` learns to read the stack from the global name.

**Each criterion in plain words.**
- AC-1: install, build, host-run and container-run each leave the host and container launchers, plus the container ACP one, `harnessed-acp-<harness>-<stack>-container`, for `omp` and `claude` (S1).
- AC-2: a global launcher started from a folder launches there and passes every argument on; a launch without aoe writes nothing into the folder (S2).
- AC-3: with aoe, the project gets a small launcher that keeps your one-off flags and calls the global one; never for ACP (S3).
- AC-4: `harnessed rm <stack>` still removes the right aoe rows, old and new, and never another stack's rows or any global launcher (S4).
- AC-5: `harnessed uninstall <stack> <harness>` deletes exactly that pair's launchers and lists aoe rows that still point at them (S5).
- AC-6: the old shim is never written again, and `uninstall` removes one only when it is really the old shim (S6).

**What must not change.** Old aoe rows stay removable. A file in `~/.local/bin` that harnessed did not write is never overwritten or deleted. A failure to write a launcher never stops a launch. The `host-run` and `container-run` arguments stay the same.

**How each criterion is proven.** Each scenario below is a pytest test against a temporary `HOME` and a stub `harnessed` or `aoe` on `PATH`. Then the gauntlet runs (tests, coverage at 80%, pyright, ruff, shellcheck, gitleaks), plus scoped mutation testing and the adversarial review for Tier 3. `live.yml` runs on the PR because `launcher.py` changes.

**Open decisions.** None. Ruled (mcrowe, 2026-10-09): global launchers call `harnessed` from PATH; ad-hoc stacks get no global launchers; the local launcher and aoe row are written when aoe is usable, as today.

## Orientation
- Change: write per-(harness, stack, backend) launchers into `~/.local/bin`, and write the in-project launcher only for aoe.
- Why: editors and aoe need one stable command per stack, and non-aoe launches should leave nothing in the repo.
- Touches: `launchscript.py` (name grammar, both script bodies), `launcher.py` (install, uninstall, build, host-run, container-run, `_persist_this_launch`), `aoe.py` (`_replays_stack`, a reverse lookup for uninstall), `paths.py` (one `~/.local/bin` helper), tests, README, one catalog skill page.
- Decide: Decide 1 (how a global launcher finds `harnessed`), Decide 2 (ad-hoc stacks), Decide 3 (the aoe predicate).
- Decided: Decide 1 B, bare `harnessed` from PATH, governs S1.1 and S2.1; Decide 2 A, skip ad-hoc stacks, governs S1.9; Decide 3 A, aoe is usable, governs S2.3 and S3 (mcrowe, 2026-10-09).

- Tier: 3 — it changes a hand-rolled name parser, and `uninstall` deletes files in the user's home.
- Issue: GH-565
- Isolation: worktree — `3-1-gh-565-global-launchers`, branch `GH-565`.

Failure model (Tier 3):
- The parser reads `default.x` as `default`, so `rm` or `uninstall` hits another stack. Caught by S4.3, S5.1 and a property test over generated stack names.
- `uninstall` deletes a user file in `~/.local/bin`. Caught by S5.3 and S6.4.
- Every launch rewrites `~/.local/bin`, and a write error kills the launch. Caught by S1.8 and S1.11.
- New-format local launchers lose `rm` attribution. Caught by S4.1.
- Old rows become unremovable. Caught by S4.2.

## Scenarios
### S1. Global launchers are written (AC-1)
- S1.1 Given stack `default` exists and `HOME` is a temp dir, when `harnessed install default claude` runs, then `~/.local/bin` holds `harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-acp-claude-default-container`, each mode 0755, line 2 `# harnessed:launcher v1`, with exec lines `exec harnessed host-run claude --stack default "$@"`, `exec harnessed container-run claude --stack default "$@"` and `exec harnessed container-acp claude --stack default "$@"`.
- S1.2 (negative) Given stack `default`, when `harnessed install default codex` runs, then `harnessed-codex-default-host` and `harnessed-codex-default-container` exist and `harnessed-acp-codex-default-container` does not.
- S1.3 (boundary) Given stack `default.codebase-memory-mcp.gh-issue-tracker`, when `harnessed install default.codebase-memory-mcp.gh-issue-tracker claude` runs, then `harnessed-claude-default.codebase-memory-mcp.gh-issue-tracker-container` exists and its exec line names `--stack default.codebase-memory-mcp.gh-issue-tracker`.
- S1.4 Given stack `default`, when `harnessed build default claude` succeeds, then the same three files as S1.1 exist.
- S1.5 Given stack `default`, when `harnessed host-run claude <D> --stack default` runs with the harness exec stubbed, then the three files of S1.1 exist before the harness starts, byte-identical to S1.1's, and none names `<D>`: a global launcher never carries a path, and the project comes from the folder it runs in.
- S1.6 Given stack `default` with a current build stamp, when `harnessed container-run claude <D> --stack default` runs and `_build_stack` is not called, then the three files of S1.1 exist.
- S1.7 (boundary) Given `harnessed-claude-default-container` already holds the exact bytes the writer would produce, when any S1 command runs, then its inode and mtime are unchanged.
- S1.8 (negative) Given `~/.local/bin/harnessed-claude-default-container` exists without the sentinel on line 2, when `harnessed container-run claude <D> --stack default` runs, then that file's bytes are unchanged, one warning names its path, and the launch goes on.
- S1.9 (negative) Given an ad-hoc stack minted by `--recipe`, when `container-run` launches it, then `~/.local/bin` gains no file: ad-hoc stacks get no global launchers (mcrowe, 2026-10-09).
- S1.10 (negative) Given no stack `nosuch`, when `harnessed install nosuch claude` runs, then it exits nonzero and `~/.local/bin` gains no file.
- S1.11 (negative) Given `~/.local/bin` is not writable, when `harnessed host-run claude <D> --stack default` runs, then one warning prints and the launch goes on.
- S1.12 (negative) Given stack `default`, when `harnessed install default claude` runs, then `harnessed-acp-claude-default-host` does not exist: `-host` is reserved for `host-acp`, which this change does not build.

### S2. A global launcher launches where it is run (AC-2)
- S2.1 Given `harnessed-claude-default-container` and a stub `harnessed` on `PATH` that records its argv and cwd, when the launcher runs from folder D with `--fresh`, then the stub records argv `container-run claude --stack default --fresh` and cwd D.
- S2.2 (boundary) Given the same, when the launcher runs with `-x -- --resume abc`, then the stub records `container-run claude --stack default -x -- --resume abc`, in that order.
- S2.3 (negative) Given aoe is not usable (`aoe._bin()` returns None, for example `HARNESSED_NO_AOE=1`) (mcrowe, 2026-10-09), when `harnessed host-run claude <D> --stack default` runs, then D gains no file and no aoe row is registered.

### S3. The local launcher exists only for aoe (AC-3)
- S3.1 Given aoe is usable (`aoe._bin()` is not None) and the stack is not ad-hoc, when `harnessed container-run claude <D> --stack default --no-strict-mcp-config` runs, then D holds `claude-default-container` with, in order: `#!/bin/sh`, `# harnessed:launcher v1`, a `# as typed:` line, `CDPATH= cd -- "$(dirname -- "$0")" || exit 1`, and `exec harnessed-claude-default-container --no-strict-mcp-config "$@"`. The aoe row command is `<D>/claude-default-container --`. The per-launch flags are exactly those `aoe.command_for` adds after `--stack` today: `--no-strict-mcp-config`, `--aoe-group <g>` and `--aoe-title <t>`, in that order. `--stack`, the verb, the harness and the path are never in the local exec line; the global name carries them.
- S3.2 (boundary) Given aoe is usable, when the launch adds `--aoe-group g --aoe-title t`, then those flags are in the local exec line after the global name and are absent from `~/.local/bin/harnessed-claude-default-container`.
- S3.3 (negative) Given aoe is usable, when `harnessed container-acp claude <D> --stack default` runs, then D gains no file.
- S3.4 (boundary) Given D holds the S3.1 `claude-default-container` and a stub `harnessed-claude-default-container` on `PATH` records its cwd, when the local launcher runs as `<D>/claude-default-container --` from a different folder E, then the stub records cwd D. This settles the Story's deferred question: the local launcher's `cd` line makes the project D whatever folder aoe starts it in.
- S3.5 Given the S3.1 row command `<D>/claude-default-container --`, when `aoe._is_ours` and `aoe._is_launcher_script` read it, then both return True, unchanged from today's row shape.

### S4. `harnessed rm` attribution (AC-4)
- S4.1 Given an aoe row `<D>/claude-default-container --` whose script execs `harnessed-claude-default-container`, when `harnessed rm default` runs, then that row is removed.
- S4.2 Given an aoe row whose older script execs `harnessed container-run claude . --stack default "$@"`, when `harnessed rm default` runs, then that row is removed.
- S4.3 (boundary) Given a row `<D>/claude-default.x-container --` whose script execs `harnessed-claude-default.x-container`, when `harnessed rm default` runs, then that row stays.
- S4.4 (negative) Given launchers from S1.1, when `harnessed rm default` runs, then every file in `~/.local/bin` is unchanged.

### S5. `harnessed uninstall <stack> <harness>` (AC-5)
- S5.1 Given launchers for (`default`, `claude`), (`default.x`, `claude`) and (`default`, `codex`), when `harnessed uninstall default claude` runs, then `harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-acp-claude-default-container` are gone, and `harnessed-claude-default.x-container`, `harnessed-acp-claude-default.x-container` and `harnessed-codex-default-host` remain.
- S5.2 Given an aoe row whose script execs `harnessed-claude-default-container`, when `harnessed uninstall default claude` runs, then the output names that row's script path.
- S5.3 (negative) Given `~/.local/bin/harnessed-claude-default-host` without the sentinel, when `harnessed uninstall default claude` runs, then that file remains and one line names it as not removed.
- S5.4 (boundary) Given no aoe row references any `harnessed-claude-default-*` launcher, when `harnessed uninstall default claude` runs, then it prints no row path and exits 0.
- S5.5 (boundary) Given `~/.local/bin/harnessed-acp-claude-default-host` exists with the sentinel, as `host-acp` will write it, when `harnessed uninstall default claude` runs, then that file is gone too.

### S6. The old shim (AC-6)
- S6.1 Given stack `default`, when `harnessed install default claude` runs, then `~/.local/bin/default` does not exist.
- S6.2 Given `~/.local/bin/default` whose exec line runs `container-run --stack default`, when `harnessed uninstall default claude` runs, then that file is gone.
- S6.3 (boundary) Given S6.2 has run, when `harnessed uninstall default claude` runs again, then the output says no shim was found and the exit is 0.
- S6.4 (negative) Given `~/.local/bin/default` whose exec line is `exec /usr/bin/true`, when `harnessed uninstall default claude` runs, then its bytes are unchanged.

## Must NOT
- Break legacy recognition: `parse_legacy_script_name` names and `--stack` exec lines stay readable by `aoe._is_launcher_script` and `aoe._replays_stack` (the bug its docstring records).
- Accept `acp` as a backend in any launcher name. `parse_script_name("claude-default-acp")` and `parse_global_name("harnessed-claude-default-acp")` return None; ACP is the `harnessed-acp-` prefix, and its backend is `host` or `container`.
- Overwrite or delete a `~/.local/bin` file without the sentinel on line 2. This is the rule `launchscript.write` already applies.
- Let a launcher write failure end a launch. This is `launchscript`'s "never fatal" contract.
- Quote twice. Exec lines are built with `shlex.join`, the way `aoe.command_for` already builds them.
- Put `"$@"` before `--stack` in a global launcher. The ordering comment in `install_stack` records why.
- Change the arguments of `host-run`, `container-run` or `container-acp`.
- Let `harnessed rm` touch host rows or any file in `~/.local/bin`.
- Drop the test count below the baseline. Only these existing tests may be rewritten, each keeping the decision it encodes unless a scenario above changes it: `tests/test_launcher_install.py::TestInstallShim` (4 tests, lines 36-97; replaced by S1.1, S1.10 and S6.1); `tests/test_adhoc_launch_is_not_persisted.py::test_an_ordinary_stack_still_persists` (line 215; now needs aoe usable, per S2.3 and S3.1); `tests/test_launchscript.py` classes `TestParityWithCommandFor` (line 351), `TestProvenanceComment` (line 382) and `TestPassthrough` (line 424), whose expected exec line becomes S3.1's; and the `_replays_stack`/`forget_stack` fixtures in `tests/test_aoe.py` (lines 720, 807-896 and 1725), which gain new-format cases beside the `--stack` ones S4.2 keeps. Revision 4 adds, found during the build: the `run_script` fixture, `TestTwoStacksDoNotCollide::test_each_file_launches_its_own_stack` and `TestHostileInput::test_a_path_with_a_space_and_a_quote_survives` in `tests/test_launchscript.py`; `test_an_aoe_rename_leaves_the_row_launchable_and_unduplicated` in `tests/test_aoe_real.py`; and the `_gate`/`_launch` fixtures in `tests/test_adhoc_launch_is_not_persisted.py`, which gain an `aoe._bin` stub with assertions unchanged.

## Touches
- `src/harnessed/launchscript.py` — accept the `harnessed-` and `harnessed-acp-` prefixes for global names, with the backend `host` or `container`; add the global launcher body and writer; change the local body to exec the global name.
- `src/harnessed/launcher.py` — `install` and `uninstall` take `<stack> <harness>`; they write, remove and report launchers and remove the old shim; `build`, `host-run` and `container-run` call the writer; `_persist_this_launch` uses the Decide 3 predicate.
- `src/harnessed/aoe.py` — `_replays_stack` reads the stack from an exec'd global name; add a lookup of rows that reference a given global launcher, for `uninstall`.
- `src/harnessed/paths.py` — one `user_bin_dir()` helper, replacing the two inline `Path.home() / ".local" / "bin"`.
- `tests/test_launchscript.py`, `tests/test_aoe.py`, `tests/test_launcher_install.py`, `tests/test_launcher_build.py`, `tests/test_adhoc_launch_is_not_persisted.py` — the scenarios above, and the rewrites the Must NOT list names by test.
- `README.md` — lines 117, 123 and 140 describe the shim.
- `catalog/recipes/default/skills/harnessed-catalog/stack-fields.md` — line 134 describes the shim.

## Documentation
- `README.md` — the quick start and the command table describe `install`/`uninstall` and the `~/.local/bin/<stack>` shim.
- `catalog/recipes/default/skills/harnessed-catalog/stack-fields.md` — its command list names the shim.
- The wiki (`docs/`) is a separate delivery with no PR. Its guides get a follow-up edit after merge, with its own confirmation to push.

## Known limits
- A renamed or deleted stack keeps its global launchers until someone runs `uninstall` for it. No command sweeps orphans.
- A launcher deleted by hand breaks the aoe rows that point at it until the next launch or `install` rewrites it.
- A global launcher fails when `harnessed` is not on `PATH`, for example in a dev venv that was never activated.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1 to S6 and every existing test | all pass; count at or above baseline plus new |
| coverage | untested branches | 80% whole project |
| types | pyright on src | 0 errors |
| lint | ruff on src, tests, tools | 0 findings |
| shellcheck | tracked `.sh` files | 0 findings |
| secrets | gitleaks over history | 0 unignored findings |
| mutation | parser and writer logic in `launchscript.py`, and `_replays_stack` | 0 surviving mutants, or each survivor named in EVIDENCE |
| property | `parse_script_name` round trip over generated stack names with `.` and `-` | holds for every generated case |
| live | `live.yml` `live` and `live-docker` jobs on the PR | both green |
