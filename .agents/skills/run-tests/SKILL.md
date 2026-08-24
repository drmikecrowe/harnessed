---
name: run-tests
description: Run the harnessed pytest suite, and the other three CI gates before you push. Use whenever you need to run, re-run, or verify tests in this repo — including from a fresh git worktree, after changing src/harnessed/ or catalog/, and always before pushing a branch or opening a PR. Also use when pytest reports "No module named 'harnessed'", when a CLI test fails comparing plain text against ANSI-escaped output, when pyright reports hundreds of missing imports, or when mise says a config file is not trusted.
---

# Running the harnessed test suite

```bash
tools/run-tests.sh                        # whole suite
tools/run-tests.sh tests/test_schema.py   # one file
tools/run-tests.sh -k install -x          # filter, stop on first failure
```

That is the whole workflow **for pytest**. The script handles worktree setup itself and is
idempotent, so run it directly rather than composing `mise`/`uv`/`pytest` by hand.

## Before you push: `tools/preflight.sh`, not `run-tests.sh`

`run-tests.sh` runs **pytest and nothing else**. CI runs **four** gates across three workflows, so
a green suite proves one of four:

| Workflow | Gate |
|---|---|
| `test.yml` | pytest (3.12 **and** 3.13) |
| `lint.yml` | `ruff check src tests tools` → `pyright` → `shellcheck $(git ls-files '*.sh')` |
| `pin-check.yml` | `harnessed update --check` |

```bash
tools/preflight.sh              # pytest + ruff + pyright + shellcheck
tools/preflight.sh --all        # also the catalog pin check (network, slow)
tools/preflight.sh --no-tests   # lint layers only, for a docs- or shell-only change
```

**Never report a branch as verified on the strength of `run-tests.sh` alone.** PR #431 went red on
two `RUF005` findings with pytest fully green, because nothing local had ever run ruff.

Two traps worth knowing even if you always use the script:

- **`lint.yml` has no `continue-on-error`, and ruff is its first step.** A ruff finding means
  pyright and shellcheck **never ran** — so a red lint job understates how much is unverified. Fix
  ruff, then run the other two before assuming they were fine. `preflight.sh` diverges here on
  purpose: it runs every gate even after one fails, and names the ones it skipped.
- **`pyright` needs `--pythonpath`.** `mise.toml` puts the venv outside the repo
  (`UV_PROJECT_ENVIRONMENT=~/.local/share/harnessed/venvs/<branch>/.venv`), so a bare `pyright`
  resolves none of the installed packages and reports hundreds of phantom `reportMissingImports` on
  a tree that is genuinely at zero. `preflight.sh` passes it for you.

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

## If a test passes locally and fails on CI comparing rendered text

Same family as the escape codes above, different axis: **line wrapping**.

`_err` is a `rich` Console that hard-wraps at 80 columns, and most harnessed messages embed a path.
When that path is a pytest `tmp_path` its length is machine-dependent —
`/tmp/pytest-of-<you>/pytest-<n>/…` locally versus `/tmp/pytest-of-runner/pytest-0/…` on the runner
— so the wrap points move and a multi-word substring lands across a line break on one machine and
not the other. PR #430 failed exactly this way on `could not be resolved`.

**Never assert on raw rendered output.** Normalise first:

```python
def _flat(text: str) -> str:
    return " ".join(text.split())
```

A test that renders under a deliberately long path (`tmp_path / ("d" * 60) / ("e" * 60)`) shifts
every wrap point and keeps the class of bug from returning.

## Related

Live behavior is **not** covered by this suite. It runs no `podman build` and no
`harnessed launch`, so container layering, image ENV, and host-launch behavior are asserted through
emitted text and monkeypatched executors only. Do not report a change as verified end-to-end on the
strength of a green run — and do not run `harnessed` yourself to close that gap (see AGENTS.md); ask
the user to.
