---
name: run-tests
description: Run the harnessed pytest suite. Use whenever you need to run, re-run, or verify tests in this repo — including from a fresh git worktree, after changing src/harnessed/ or catalog/, or before proposing a merge. Also use when pytest reports "No module named 'harnessed'", when a CLI test fails comparing plain text against ANSI-escaped output, or when mise says a config file is not trusted.
---

# Running the harnessed test suite

```bash
tools/run-tests.sh                        # whole suite
tools/run-tests.sh tests/test_schema.py   # one file
tools/run-tests.sh -k install -x          # filter, stop on first failure
```

That is the whole workflow. The script handles worktree setup itself and is idempotent, so run it
directly rather than composing `mise`/`uv`/`pytest` by hand.

The current baseline is on the branch you are working from — record the number before your change
and compare after. A drop is a regression even if your own new tests pass.

## Why not just run pytest

Three things make this suite fail **locally while CI stays green**. Each looks like a different bug
than it is, and each costs a round trip to rediscover.

**Per-branch venvs.** `mise.toml` sets `UV_PROJECT_ENVIRONMENT` to
`~/.local/share/harnessed/venvs/<branch>/.venv` — one venv per branch, outside the repo so a
container bind-mount cannot corrupt it. A fresh worktree starts with **no venv** and does not
inherit `main/`'s.

**pytest is an optional extra.** It lives in `[project.optional-dependencies].dev`. A plain
`uv sync` installs the project without it, and `uv run pytest` then falls through to a *system*
pytest on a different Python — where every test errors with `ModuleNotFoundError: No module named
'harnessed'`. That reads like a broken checkout; it is a missing `--extra dev`.

**mise refuses untrusted configs** in a new worktree.

## If a test fails on ANSI escape codes

```
assert "no such stack 'x'" in "\x1b[1;31merror:\x1b[0m no such stack \x1b[32m'x'\x1b[0m"
```

**Do not fix this by changing the assertion.** The test is correct — CI proves it. The environment
is wrong.

`rich` renders plain text when stdout is not a TTY, which is the case under typer's `CliRunner`.
`FORCE_COLOR` overrides that check, so escapes land inside the captured output. Terminal shell
integration sets it without asking (Ghostty exports `FORCE_COLOR=3`), so you hit this having never
opted in, while CI — a bare environment — is green the whole time.

`tests/conftest.py` pops `FORCE_COLOR` at **module import**. That is the only place early enough:
`rich` reads the variable when a `Console` is *constructed*, and `launcher.py` builds `_out`/`_err`
at import, before any fixture runs. An autouse fixture was tried and does not work. Preserve that if
you touch conftest.

## Related

Live behavior is **not** covered by this suite. It runs no `podman build` and no
`harnessed launch`, so container layering, image ENV, and host-launch behavior are asserted through
emitted text and monkeypatched executors only. Do not report a change as verified end-to-end on the
strength of a green run — and do not run `harnessed` yourself to close that gap (see AGENTS.md); ask
the user to.
