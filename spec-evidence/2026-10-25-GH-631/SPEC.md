# SPEC — Host launches stop wiping a profile another launch or session uses

## Summary
This change stops a host launch (`host-run`, `host-acp`) from deleting and rebuilding a stack's assembled profile while another launch builds it or a live session uses it. Today `_launch_host` calls `assemble` on every launch, and `assemble` calls `emit.reset_profile`, which runs `shutil.rmtree` on the profile with no lock. Two concurrent launches then race in `rmtree` and one dies with `FileNotFoundError` (exit 1), and a later launch deletes the files a running session reads.

What changes: a new helper in `src/harnessed/hosthome.py` claims the profile with two `fcntl.flock` locks that sit beside the profile directory. A build gate (`<harness>.build.lock`) serializes claims. A session lock (`<harness>.lock`) is held exclusive while one launch builds, then shared for the life of every session. `_launch_host` assembles only when it gets the session lock exclusive. Otherwise it reuses the profile and prints one line to stderr. The shared lock fd is inheritable, so it survives the `exec` into the harness and is released by the kernel when the session ends, crash included.

Acceptance criteria, in plain words:
1. Two launches of one stack and harness at the same time both succeed, and the profile is assembled once.
2. A launch while a session is open does not assemble or reset the profile. It reuses it and prints the in-use line.
3. When every session has ended, killed ones included, the next launch assembles again.
4. When the build fails, the locks are released, and the next launch assembles the profile itself.
5. The session lock is still held by the process after `exec`.
6. `host-run` and `host-acp` both claim the profile; `project-setup` does not.
7. The lock files sit beside the profile directory, so `reset_profile` cannot delete them.

What must not change: `assemble`, `emit.reset_profile`, `harnessed build`, the container path, `_host_home_lock`, the settings merge on a build, and every existing test.

How each is proven: pytest tests that use real `flock` and real subprocesses (criteria 1, 3, 4, 5) and in-process `_launch_host` tests with `assemble` stubbed (criteria 2, 4, 6, 7).

Open decisions: none.

## Orientation
- Change: claim the host profile with a build gate and a session lock before `_launch_host` assembles, and assemble only when no session or build holds it.
- Why: `_launch_host` runs `emit.reset_profile` (`shutil.rmtree`) on every launch with no lock, so concurrent ACP server starts crash with `ENOENT` and a later launch deletes a live session's profile.
- Touches: `src/harnessed/hosthome.py`, `src/harnessed/launcher.py`, `tests/test_profile_claim.py` (new), `tests/test_host_acp.py`, `ARCHITECTURE.md`.
- Decide: the lock design (ruled: build gate); whether a reused profile gets the settings merge (agent decision A1: no).
- Decided: Decide 1, A — a build gate lock serializes claims, and no completion marker is written; governs S1, S4 and the Touches line for `hosthome.py` (mcrowe, 2026-10-25).
- Lane: engineering, because this is an internal concurrency defect in the host launcher, reported by the engineer from a traceback, with no product author and no user-facing behavior beyond one stderr line.

- Tier: 2 — concurrency and process-lifetime behavior in the launch path.
- Issue: GH-631
- Isolation: worktree — `main` takes no commits.

## Scenarios
Terms: `P` is `paths.profile_dir(stack, harness)`. The session lock is `P.parent / f"{harness}.lock"`. The gate is `P.parent / f"{harness}.build.lock"`. The in-use line is `profile '<stack>' (<harness>) is in use by a running session; stack changes apply after every session of it closes`. Every test sets `XDG_DATA_HOME` to a `tmp_path`.

### S1. Concurrent launches build once
- S1.1 Given two subprocesses that each call `_claim_profile("s", "claude")` within 50 ms of each other, where the claim that gets `build=True` appends one line to a counter file, sleeps 0.5 s and calls `done()`, when both finish, then both exit 0 and the counter file holds exactly 1 line. Per Decide 1 (mcrowe, 2026-10-25) the second waits on the gate, not in a retry loop.
- S1.2 Given S1.1, when the second subprocess's stderr is read, then it holds the in-use line once.

### S2. A live session's profile is reused, not reset
The in-process launch in S2, S4.1 and S6 is the one `tests/test_host_acp.py` already runs: the `host` fixture (temporary `HOME` and XDG tree, overlay stack `acpspike`), harness `omp`, a project dir `tmp_path / "proj"`, and `CliRunner().invoke(launcher.app, ["host-run", "omp", str(project), "--stack", "acpspike"])`. Its stubs are those of `TestHostRunSharesTheSetup` (`tests/test_host_acp.py:568-571`): `launcher.os.execvpe` raises `SystemExit(0)`, `launcher.os.chdir` does nothing, `launcher.aoe._bin` returns `None`. Nothing else is stubbed. `launcher.assemble` and `launcher._merge_host_claude_settings` are wrapped in spies that record the call and then call the real function. Here `P` is `paths.profile_dir("acpspike", "omp")`.
- S2.1 Given one such launch has run, and a subprocess then holds the session lock with `LOCK_SH`, and a file `P/sentinel` exists, when the launch runs again, then it exits 0, the `assemble` spy records no call in the second launch, `P/sentinel` still exists, and the output holds the in-use line.
- S2.2 Given S2.1, when the second launch runs, then the `_merge_host_claude_settings` spy records no call in it (agent decision A1).

### S3. After every session ends, the next launch builds
- S3.1 Given a subprocess that holds the session lock with `LOCK_SH`, when it is killed with `SIGKILL` and reaped, then the next `_claim_profile("s", "claude")` returns `build=True`.
- S3.2 (boundary) Given no prior launch and no `P.parent` directory, when `_claim_profile("s", "claude")` runs, then it creates `P.parent`, both lock files, and returns `build=True`.

### S4. A failed build releases the locks
- S4.1 (negative) Given the S2 launch with `launcher.assemble` replaced by a function that raises `SchemaError("boom")`, when it runs, then it exits 1, and afterwards a new `_claim_profile("acpspike", "omp")` in the same process returns `build=True` within 5 s (it runs in a thread joined with a 5 s timeout).
- S4.2 Given a subprocess A whose claim gets `build=True` and then exits 1 without calling `done()` while subprocess B waits on the gate, when A ends, then B's claim returns `build=True`.

### S5. The session lock survives exec
- S5.1 Given a subprocess that calls `_claim_profile("s", "claude")`, calls `done()`, and then `os.execvp("sleep", ["sleep", "30"])`, when the test tries `flock(LOCK_EX | LOCK_NB)` on the session lock after the exec, then it raises `BlockingIOError`.
- S5.2 Given S5.1, when the `sleep` process is killed and reaped, then the same `flock(LOCK_EX | LOCK_NB)` succeeds.
- S5.3 (negative) Given S5.1, when the test tries `flock(LOCK_EX | LOCK_NB)` on the gate after the exec, then it succeeds: the gate fd is not inherited.

### S6. Both host verbs claim; project-setup does not
- S6.1 Given the S2 launch with `launcher._claim_profile` wrapped in a spy that calls the real function, when `launcher._launch_host("acpspike", "omp", str(project))` runs, and then `launcher._launch_host("acpspike", "omp", str(project), acp=True)` runs with `launcher.acprelay.run`, `launcher.acp_stdout` and `launcher.os._exit` stubbed as `tests/test_host_acp.py:937-939` stubs them, then the spy records exactly one call `("acpspike", "omp")` per launch.
- S6.2 (negative) Given the same spy and a fresh `host` fixture, when `launcher._launch_host("acpspike", "omp", str(project), project_only=True)` runs, then the spy records no call and no `*.lock` file exists under `paths.profiles_root()`.

### S7. The lock files outlive a reset
- S7.1 Given a claim with `build=True`, when `emit.reset_profile(P)` runs, then both lock files still exist as regular files in `P.parent`.

## Must NOT
- Change the signature or behavior of `assemble`, `emit.reset_profile` or `_build_stack`; `harnessed build` and `container-run` keep their current assembly.
- Change `_host_home_lock` or the host home's fingerprint gate.
- Change the settings merge when this launch builds: same call, same arguments.
- Use a counter file or a PID file to track sessions.
- Let the gate fd reach the harness (S5.3).
- Lower the test count: the full suite passes with at least the baseline count plus the new tests.

## Touches
- `src/harnessed/hosthome.py` — add `_claim_profile(stack, harness)`, beside `_host_home_lock`. Under Decide 1 (mcrowe, 2026-10-25) it takes the gate `LOCK_EX` (blocking), then tries the session lock `LOCK_EX | LOCK_NB`. Granted: it returns a claim with `build=True` and keeps both locks; the claim's `done()` converts the session lock to `LOCK_SH`, marks its fd inheritable, and releases the gate. Busy: it takes the session lock `LOCK_SH`, marks its fd inheritable, releases the gate, prints the in-use line, and returns `build=False`. The claim's `release()` closes the gate and the session lock, and `launcher.py` calls it only on an exception before `done()`. After `done()`, or on the busy path, `release()` does nothing at all: the shared session lock stays held until the process, or the harness it exec'd, exits. No completion marker is written.
- `src/harnessed/launcher.py` — in `_launch_host`, when not `project_only`: claim before `assemble`; call `assemble` and the settings merge only when `build=True`; call `done()` right after the settings merge; call `release()` if anything raises between the claim and `done()`. Keep the claim object alive until `os.execvpe`, `subprocess.run` or `_relay_acp`. Reword the "Assemble IN-PROCESS every launch" comment to say assembly is skipped while the profile is claimed.
- `tests/test_profile_claim.py` — new: S1, S3, S5, S7, which call `_claim_profile` and real subprocesses.
- `tests/test_host_acp.py` — add S2, S4.1 and S6, beside `TestHostRunSharesTheSetup`, because they use its `host` fixture. S4.2 goes in `tests/test_profile_claim.py`.
- `ARCHITECTURE.md` — lines 245 and 370: the host backend assembles on a launch only when no session of that stack and harness is open.

## Documentation
- `ARCHITECTURE.md`, lines 245 and 370. The wiki (`main/docs/`) is a separate delivery and is not changed by this PR.

## Known limits
- `harnessed build`, `container-run` and `harnessed clean` still reset or delete the profile without the lock, so they can still disturb a live host session. The brief scopes the fix to `_launch_host`.
- A stack edited while any session of it is open is not applied to new launches until every session closes; the in-use line says so.
- A child of the harness, such as an MCP server, that outlives the harness keeps the shared lock, and the profile stays in use until it exits.
- `--fresh` still wipes the host home under `_host_home_lock` even while a session uses it. That is a separate, existing path.
- `flock` is not reliable on some network file systems. `XDG_DATA_HOME` on NFS is not supported by this change.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1-S7.1 and every existing test | `tools/run-tests.sh` passes; count ≥ baseline + the new tests |
| coverage | branch coverage of `src` | ≥ 80% (`--cov-fail-under=80`) |
| types | pyright over the dev environment | 0 errors |
| lint | ruff over `src tests tools` | 0 findings |
| shellcheck | every tracked `*.sh` | 0 findings |
| secrets | gitleaks over the history | 0 leaks |
| live | `live` and `live-docker` on the PR, since `launcher.py` is a live trigger | both jobs pass |
