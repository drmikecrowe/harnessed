# Decisions — Global launchers, local launcher only for aoe

## Setup plan
- Isolation: worktree — `3-1-gh-565-global-launchers` on branch `GH-565`, cut from `main` at `d7bca3f`.
- Git: commit per scenario group (S1 to S6), signed, on `GH-565`. The spec-evidence setup is commit `9f87e0c`, and the queued label is `314d0a1`.
- New dependencies: none. `hypothesis` is already in the dev extra.
- New files: none in `src/`. New test functions go in the existing test files listed under Touches.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage (80%), types, lint, shellcheck and secrets. Mutation is not a declared layer, so it runs by hand: `HARNESSED_DIR=$PWD mise exec -- uv run --extra dev mutmut run "harnessed.launchscript.x_*"`, and the same for `harnessed.aoe.x__replays_stack*`. mutmut gives typer commands zero mutants, so `install` and `uninstall` take manual mutants.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml` — 4 checks transcribed (pytest, ruff, pyright, shellcheck). `live.yml` triggers on `src/harnessed/launcher.py`.

## Facts this SPEC rests on
1. `launchscript.write(verb, stack, harness, project_path, *, group, title, no_strict_mcp, argv)` writes shebang, sentinel, optional `# as typed:`, the `cd` line, and `exec <command_for minus "--"> "$@"`. It refuses an existing file that is not regular, lacks the sentinel, or is git-tracked, and returns None on any failure. — `launchscript.py:234-317`, read by a research agent.
2. `_VERB_SUFFIX = {"host-run": "host", "container-run": "container"}`, and `_BACKENDS` derives from it. No `acp` backend exists. — `launchscript.py:71-75`.
3. `_persist_this_launch` returns True for any aoe flag, else `not dynstack.is_adhoc(stack)`. So today every non-ad-hoc launch writes the local script and calls `_aoe_register`, which is a silent no-op without aoe. — `launcher.py:2658`, callers at `:3064` (host-run) and `:4234` (container-run).
4. `aoe._bin()` returns None when `HARNESSED_NO_AOE` is set, when `aoe` is not on PATH, or when aoe's config directory is absent. — `aoe.py:170-183`, read directly.
5. `aoe._replays_stack` reads the script's first `exec` line and matches a `--stack <stack>` pair. A new-format local script has no `--stack`, so it needs a second rule. — `aoe.py:1145`.
6. `aoe.command_for("container-run", "default", "claude", Path("."))` returns `harnessed container-run claude . --stack default --`. — `aoe.py:295`.
7. `container-run` calls `_build_stack` only for a just-minted stack (`:4153`) or a stale stamp the user agrees to rebuild (`:4221`). — read directly.
8. `_launch_host` assembles the profile on every launch and never calls `build`. — `launcher.py:3032-3043`, read directly.
9. `install_stack` writes `exec <abs harnessed> container-run --stack <stack> "$@"` to `~/.local/bin/<stack>`; `uninstall_stack` unlinks that path when `is_file()`, with no content check. — `launcher.py:5231-5285`, read directly.
10. `container-acp` refuses any harness outside `attachcmd._ACP_HARNESSES = ("omp", "claude")`. — `launcher.py:4133`, `attachcmd.py:60`.
11. The tests that encode today's behavior and must be rewritten: `tests/test_launcher_install.py::TestInstallShim` (4 tests, `:36-97`); `tests/test_adhoc_launch_is_not_persisted.py::test_an_ordinary_stack_still_persists` (`:215`); the body tests in `tests/test_launchscript.py` (`TestParityWithCommandFor :351`, `TestProvenanceComment :382`, `TestPassthrough :424`); the `_replays_stack`/`forget_stack` fixtures in `tests/test_aoe.py` (`:720`, `:807-896`, `:1725`). Each rewrite keeps the decision the test encodes unless this SPEC changes it, and EVIDENCE names each one.

## Decide calls

### Decide 1. How does a global launcher find `harnessed`?
`install_stack` bakes `shutil.which("harnessed")`, falling back to `sys.argv[0]` (`launcher.py:5247`). CLAUDE.md says the global `harnessed` is an editable install of `main/`, while a worktree runs a branch venv.

- A. Bake the absolute path, as the shim does. Cost: every launch rewrites the launcher, so a launch from a worktree venv repoints every global launcher at that branch, and the bytes flip between checkouts.
- B. Exec bare `harnessed`, resolved from `PATH` at run time. Cost: a launcher fails when `harnessed` is not on `PATH` (a dev venv that was never activated).

Default: B. Ruling: B, bare `harnessed` from PATH (mcrowe, 2026-10-09).
Changes: S1.1 exec lines, S2.1; Known limits line on option A removed.

### Decide 2. Do ad-hoc stacks get global launchers?
`dynstack.is_adhoc(stack)` stacks are minted per launch from `--recipe`/`--extends`, and are already exempt from the local script (`launcher.py:2658`, `tests/test_adhoc_launch_is_not_persisted.py`).

- A. Skip them. Cost: an ad-hoc launch has no global command until the stack is saved as a named stack.
- B. Write them. Cost: every ad-hoc launch adds three files to `~/.local/bin` that nothing removes.

Default: A. Ruling: A, skip ad-hoc stacks (mcrowe, 2026-10-09).
Changes: S1.9.

### Decide 3. What does "aoe is in use" mean for the local launcher?
Today the local script and the aoe row are written together whenever `_persist_this_launch` is true (`launcher.py:2658`, `:3064`, `:4234`). AC-2 needs a launch with no aoe row to write nothing.

- A. `_persist_this_launch(...)` and `aoe._bin() is not None`. Cost: someone with aoe installed who launches from a terminal still gets the local file and a row, as today.
- B. Only an explicit `--aoe-group`, `--aoe-title` or `--create-aoe-only`. Cost: a plain launch stops registering aoe rows at all, a behavior change the story did not ask for.

Default: A. Ruling: A, aoe is usable (mcrowe, 2026-10-09).
Changes: S2.3, S3.1.

## Intent review
- Accepted: the deferred aoe-cwd question. Added S3.4, which proves the local launcher's `cd` makes the project its own folder whatever folder aoe starts it in.
- Accepted: S1.5 was ambiguous about `<D>`. Reworded so a global launcher never carries a path.
- Declined: S3.2 as an addition. The Story's Design says per-launch flags "(`--no-strict-mcp-config`, and anything else typed) stay in the local file"; `--aoe-group` and `--aoe-title` are per-launch flags that `aoe.command_for` puts in today's exec line, so S3.2 tests a Story rule, not a new one.

## Intent review, round 2
- Accepted: per-launch flags were not enumerated. S3.1 now names them: the flags `aoe.command_for` adds after `--stack`.
- Accepted: no scenario proved row recognition. Added S3.5.
- Accepted: no scenario for zero referencing rows. Added S5.4.

## Revisions
### Revision 1. Decide 1-3 ruled
All three took the default (mcrowe, 2026-10-09); SPEC.md Orientation, S1.1, S1.9, S2.3, Summary and Known limits updated.
### Revision 2. Gate 1a round 1 PR-REFERENT
The Must NOT test-count line and the Touches tests line pointed at decisions.md; both now name the rewritable tests in SPEC.md itself.
### Revision 3. Intent review round 2
S3.1 enumerates per-launch flags; S3.5 and S5.4 added.
### Revision 4. Tests the build had to change beyond the Must NOT list
Found during GREEN; SPEC.md's Must NOT line now names each. Every one keeps the decision it encodes:
- `tests/test_launchscript.py` `run_script` fixture: writes the real global launcher beside the stub `harnessed`, so local launcher -> global launcher -> harnessed runs end to end. Fixture only.
- `TestTwoStacksDoNotCollide::test_each_file_launches_its_own_stack`: each file still launches its own stack; the stack is now read from the exec'd global name instead of `--stack`.
- `TestHostileInput::test_a_path_with_a_space_and_a_quote_survives`: the path still reaches the launch through the `cd` line, never argv; argv now carries no path token at all, so the `.` assertion became the full argv.
- `tests/test_aoe_real.py::test_an_aoe_rename_leaves_the_row_launchable_and_unduplicated`: the row still runs from aoe's moved folder; the fake bin gains the real global launcher, and the `.` argv token assertion became the full argv.
- `tests/test_adhoc_launch_is_not_persisted.py` `TestThePersistGate._gate` and `TestHostRunLeavesNothingBehind._launch`: gain an `aoe._bin` stub (Decide 3); assertions unchanged.

### Revision 5. Judgment calls made during the build
- `--create-aoe-only` bypasses the Decide 3 aoe check, so `_aoe_register` still reports a missing aoe and exits nonzero rather than the command becoming a plain launch.
- `install` exits 1 when a launcher could not be written (an explicit command fails loudly); launches only warn (S1.8, S1.11).
- `build --root <dir>` writes no global launchers: the launcher names no root, so it would launch a different stack.
- A symlink in `~/.local/bin` at a launcher's name is treated as foreign: never written through, never deleted.
