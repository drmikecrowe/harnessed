# SPEC — keep the host Claude login refreshed when the refresher starts from an isolated tree

## Summary
This change keeps the one Claude login refresher refreshing the real host login, even when a launch from an isolated test tree starts it. Today such a refresher treats a stack home as the user's store, so the real login in `~/.claude` expires (observed 2026-10-25, 21:47) and it holds the only refresher lock, so no correct refresher can start.

Two things change. First, harnessed recognizes a stack home by its own markers, not only by its location under the current data root. Second, the refresher lock and its log move to the data root the refresher syncs, so a refresher for an isolated tree cannot block the real one.

The acceptance criteria, in plain words:
- A `CLAUDE_CONFIG_DIR` that points at a stack home is ignored, even when that home is outside the current data root. The refresher then refreshes `~/.claude`.
- A `CLAUDE_CONFIG_DIR` the user set themselves, which is not a stack home, is still honored.
- A refresher for one data root never takes the lock of another data root, and only one refresher runs per data root.
- The refresher always starts in this case. It never refuses.
- One refresher pass turns every stack file into a view with no refresh token.

What must not change: the location check stays (a stack home can lose its stamp), an unreadable path is never treated as a stack home, the child refresher still inherits the locked file, and pod views and the views lock stay under `XDG_STATE_HOME`.

Each criterion is proven by a pytest test in `tests/test_claudeauth.py` that builds the 2026-10-25 layout under a temp dir, plus mutation testing of the two changed functions.

Open decisions: none. Decide 1 put the lock and log under the data root.

## Orientation
- Change: `_is_harnessed_owned` also accepts a path that carries the stack markers, and the refresher's lock and log live under the data root.
- Why: a refresher started under an isolated `XDG_DATA_HOME` with an inherited stack `CLAUDE_CONFIG_DIR` refreshed the stack's file, not `~/.claude`, and held the only lock under the real `XDG_STATE_HOME`.
- Touches: `src/harnessed/hosthome.py`, `src/harnessed/claudeauth.py`, `tests/test_claudeauth.py`.
- Decide: where the lock lives (Decide 1, ruled); whether the sibling `<harness>.lock` alone is enough proof of a stack home; whether two refreshers for one host store are safe during an upgrade.
- Decided: Decide 1, A, lock and log under the data root, governs S2.1 (mcrowe, 2026-10-27).
- Lane: engineering, because this is a production defect found and diagnosed by the engineer from the refresher's own log and process environment, and it has no product-facing behavior to specify.

- Tier: 3 (auth: a wrong answer logs every stack out or writes a login into the wrong file)
- Issue: GH-637
- Isolation: worktree — `worktrees/GH-637-token-refresh`, the repo's rule for every change.

## Scenarios
### S1. A stack home is recognized by its markers
- S1.1 Given `XDG_DATA_HOME=<tmp>/iso`, `HOME=<tmp>/home` and `CLAUDE_CONFIG_DIR=<tmp>/real/harnessed/home/s/claude`, a directory that holds a `.harnessed-stack` file, when `claudeauth.host_store()` is called, then it returns `<tmp>/home/.claude/.credentials.json`.
- S1.2 (boundary) Given S1.1, but the directory has no `.harnessed-stack` file and the sibling file `<tmp>/real/harnessed/home/s/claude.lock` exists (the state `_invalidate_host_home` leaves), when `host_store()` is called, then it returns `<tmp>/home/.claude/.credentials.json`.
- S1.3 (negative) Given `XDG_DATA_HOME=<tmp>/iso` and `CLAUDE_CONFIG_DIR=<tmp>/mine`, a directory with neither marker and no sibling `mine.lock`, when `host_store()` is called, then it returns `<tmp>/mine/.credentials.json`.
- S1.4 (negative) Given `CLAUDE_CONFIG_DIR=<tmp>/absent`, a path that does not exist, outside the data root, when `host_store()` is called, then it returns `<tmp>/absent/.credentials.json`.
- S1.5 Given the S1.1 environment, when `refresh_host` runs with `claude` stubbed, then the environment passed to `claude` has no `CLAUDE_CONFIG_DIR` key.

### S2. The refresher lock is keyed to the data root it syncs
- S2.1 Given `XDG_DATA_HOME=<tmp>/data` and `XDG_STATE_HOME=<tmp>/state`, when `_lock_path()` and `_log_path()` are called, then they return `<tmp>/data/harnessed/claude-auth-refresher.lock` and `<tmp>/data/harnessed/claude-auth-refresher.log`. (Decide 1, A, mcrowe, 2026-10-27.)
- S2.2 Given a held `LOCK_EX` on `<tmp>/real/harnessed/claude-auth-refresher.lock`, the S1.1 environment with `XDG_STATE_HOME` unchanged, and `subprocess.Popen` stubbed, when `start_refresher()` runs, then it spawns one refresher, and the spawned fd is a lock on `<tmp>/iso/harnessed/claude-auth-refresher.lock`.
- S2.3 Given the S1.1 environment and `Popen` stubbed, when `start_refresher()` runs, then afterwards `LOCK_EX | LOCK_NB` on `<tmp>/real/harnessed/claude-auth-refresher.lock` succeeds.
- S2.4 (negative) Given another process holds `LOCK_EX` on `<tmp>/iso/harnessed/claude-auth-refresher.lock`, when `start_refresher()` runs under `XDG_DATA_HOME=<tmp>/iso`, then `Popen` is not called.
- S2.5 (boundary) Given the S1.1 environment and a usable login in `<tmp>/home/.claude/.credentials.json`, when `start_refresher()` runs, then it calls `Popen` (it never refuses to start because `CLAUDE_CONFIG_DIR` names a stack home).

### S3. One pass converts every stack file to a view
- S3.1 Given a usable host store at `<tmp>/home/.claude/.credentials.json` and a stack file `<data>/harnessed/home/s/claude/.credentials.json` holding an older login with `refreshToken`, when `tick()` runs with no refresh due, then the stack file's `claudeAiOauth` equals the host login with `refreshToken` and `refreshTokenExpiresAt` removed.
- S3.2 (boundary) Given the S1.1 environment, a stack file under `<tmp>/iso/harnessed/home/` and a usable host store, when `tick()` runs, then the host store still holds its `refreshToken` and the stack file holds none.

## Must NOT
- `_is_harnessed_owned` must not drop the containment check: a home whose `.harnessed-stack` was deleted by `_invalidate_host_home` must still read as owned when it sits under `host_homes_root()` (docstring of `_host_claude_source`).
- An unresolvable path must not read as owned (docstring of `_is_harnessed_owned`).
- A user override with no marker must still be honored: `test_a_user_override_outside_the_homes_root_is_still_honored` and `test_the_env_override_wins` in `tests/test_launch_host.py` pass unchanged.
- `start_refresher` must not refuse to start because `CLAUDE_CONFIG_DIR` names a stack home.
- The child must keep inheriting the locked fd: `test_the_child_inherits_the_held_lock` passes unchanged.
- `pod_view_path`, `_pod_views` and `_views_lock` must stay under `XDG_STATE_HOME`: pods bind-mount those paths.
- No signature of `host_store`, `start_refresher`, `sync`, `tick`, `refresh_host` or `_is_harnessed_owned` changes.
- No existing test in `tests/` is edited, skipped or loosened. The suite's pass count must not drop below the baseline.

## Touches
- `src/harnessed/hosthome.py` — `_is_harnessed_owned` also returns True when the resolved path holds `.harnessed-stack` or has a sibling `<name>.lock` file; its docstring and `_host_claude_source`'s "Containment, not the stamp" paragraph say so.
- `src/harnessed/claudeauth.py` — `_lock_path` and `_log_path` return paths under `paths.host_homes_root().parent`.
- `tests/test_claudeauth.py` — tests for S1 to S3.

## Documentation
none, because no repo doc or wiki page names the refresher lock or the ownership rule (`rg` over the worktree and `main/docs` found the lock name only in `claudeauth.py`). The two docstrings in `hosthome.py` are updated in place.

## Known limits
- A user's own config dir with a sibling file named `<dir>.lock` reads as a stack home, and its override is ignored. The brief names that marker; no such layout is known.
- During the upgrade, a refresher from the old release still holds the old lock under `XDG_STATE_HOME`, so a new one can start beside it. Both refresh the same `~/.claude`, and claude's own refresh lock serializes them (docstring of `refresh_host`). The old one ends at the next reboot or `kill`.
- An isolated refresher still writes pod views under the real `XDG_STATE_HOME`. Those views get the real host login, which is correct, so this stays.
- This does not move or rewrite the stale credential files left on disk by the 2026-10-25 incident. The next refresher pass does that through the existing `sync()`.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1 to S3 and every existing test | all pass, count >= baseline + new tests |
| coverage | untested branches in the changed code | `--cov-fail-under=80` passes |
| types | wrong types at the changed signatures | 0 new pyright errors |
| lint | style and unused code | `ruff check src tests tools` clean |
| mutation | tests that do not pin `_is_harnessed_owned`, `_lock_path`, `_log_path` | every mutant of those three killed, or each survivor named with a reason |
| property | `_is_harnessed_owned` over generated layouts (marker, sibling lock, containment, none) | hypothesis test passes: owned exactly when one of the three holds |
| secrets | a credential committed in a fixture | gitleaks clean |
| adversary | a defect the author did not see | no unresolved finding |
