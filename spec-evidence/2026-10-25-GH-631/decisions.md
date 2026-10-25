# Decisions — Host launches stop wiping a profile another launch or session uses

## Setup plan
- Isolation: worktree `GH-631-acp-live-sessions` (branch `GH-631-acp-live-sessions`) — `main` takes no commits (AGENTS.md, Git workflow).
- Git: one signed commit per step of the process; the change itself in one commit; PR to `main`.
- New dependencies: none. `fcntl` is the standard library, and `hosthome.py` already imports it.
- New files: `tests/test_profile_claim.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares six layers — tests (`tools/run-tests.sh`), coverage (pytest-cov, 80% floor), types (pyright), lint (ruff on src, tests, tools), shellcheck (all tracked `*.sh`), secrets (gitleaks). All six are declared and run; none is missing.
- Merge gate: `.github/workflows/test.yml`, `.github/workflows/lint.yml` and `live.yml` — pytest → tests; ruff → lint; pyright → types; shellcheck → shellcheck; `live` and `live-docker` run because `src/harnessed/launcher.py` is in the live trigger list (AGENTS.md, Tests).

## Facts this SPEC rests on
1. `_launch_host` calls `assemble(None, stack, paths.profiles_root().parent, harness, strict=True, shared_identity=False)` on every launch where `project_only` is false, with no lock around it — `src/harnessed/launcher.py:3124-3436`, read.
2. `emit.reset_profile` runs `shutil.rmtree(profile_dir)` when the dir exists, then `mkdir(parents=True)` — `src/harnessed/emit.py:47-51`, read.
3. `paths.profile_dir(stack, harness)` is `profiles_root() / stack / harness` — `src/harnessed/paths.py:569-571`, read. A sibling lock file is therefore `profiles_root() / stack / f"{harness}.lock"`.
4. `_host_home_lock` already uses this pattern for the host home: a sibling `<harness>.lock` file and `fcntl.flock(LOCK_EX)` — `src/harnessed/hosthome.py:88-111`, read. It is held only across materialize and installs, not the session.
5. `_launch_host` merges host settings into the profile with `_merge_host_claude_settings(profile_dir(stack, harness), ...)` after assembly, for claude, omp and opencode — `launcher.py`, inside `_launch_host`, read.
6. Under `acp`, `_launch_host` calls `_relay_acp`, which runs the agent as a child through `acprelay.run` and ends with `os._exit`; the harnessed process lives for the session. Without `acp` it calls `os.execvpe`, or `subprocess.run` under `--rm` — `launcher.py:3074-3116` and the end of `_launch_host`, read.
7. `project_only` (`project-setup`) skips assembly and never touches the host home; `host-acp` runs it per project folder while the agent runs — `_launch_host` docstring, read.
8. `harnessed clean` runs `shutil.rmtree(paths.profiles_root())`; `_build_stack` assembles to the same profile root — `launcher.py:5484-5493` and `launcher.py:818-820`, read.
9. Linux `flock(2)`: converting a lock between shared and exclusive is not atomic; the existing lock is removed, then the new one is taken. Python opens files with `O_CLOEXEC` by default, so an fd survives `exec` only after `os.set_inheritable(fd, True)`.
10. `ARCHITECTURE.md:245` and `ARCHITECTURE.md:370` say the host backend assembles in-process on every launch — `rg`, read.

## Decide calls

### Decide 1. One lock with EX-to-SH conversion, or a build gate plus a session lock?
The brief converts the session lock from `LOCK_EX` to `LOCK_SH` after the build. Fact 9: that conversion drops the lock first, so a third launch's `LOCK_EX | LOCK_NB` can win in the gap and `rmtree` the profile the builder is about to use.

- A. Add a build gate, `<harness>.build.lock`, taken `LOCK_EX` by every claim. Inside it the conversion cannot race, because every other claimant waits on the gate. Cost: one more lock file; claims serialize, sub-second, and longer while a build runs. No completion marker is needed: a busy session lock now means a build finished.
- B. The brief's design: one lock, EX-to-SH conversion, a completion marker and a retry loop. Cost: the race above stays open.

Default: A.
- Ruling: A (mcrowe, 2026-10-25)
Changes: SPEC.md Orientation `Decided:` line; S1.1 and S4.2 wait on the gate; the `hosthome.py` Touches line names both locks and no marker.

## Revisions
### Revision 1. release() and the S2 launch are stated exactly
Gate 1a round 1: PR-READINGS on `release()` after `done()`, and PR-REFERENT on S2.1's unnamed stubs and `...` arguments. Applied the smallest fixes: `release()` acts only before `done()` and the session lock is held until exit; S2, S4.1 and S6 name the `host` fixture of `tests/test_host_acp.py`, the stack `acpspike`, harness `omp`, the exact stubs and the argv. S2, S4.1 and S6 move to `tests/test_host_acp.py` to use that fixture. Changed: the `hosthome.py` and test Touches lines, the Orientation Touches line, S2, S4.1 and S6.
