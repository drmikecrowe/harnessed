# SPEC — Name the ACP adapter install command of the tool that owns the adapter

## Summary

**What it achieves.** `harnessed build <stack> claude` and `harnessed host-acp claude` tell the user an install command that really replaces the `claude-agent-acp` on PATH. Today both name `npm i -g …`, which writes to npm's prefix and leaves a mise or pnpm copy in front of it, so the offer and the warning repeat forever.

**Why.** `_installed_acp_adapter` asks the first `claude-agent-acp` on PATH for its version. A command that installs somewhere else cannot change that answer. Raw `npm` also breaks the repo rule "pnpm, never raw npm/npx" (CLAUDE.md).

**What changes.** `_acp_adapter_install_cmd` looks at where the adapter on PATH lives. Under mise's data dir (installs or shims) it returns `mise use -g npm:@agentclientprotocol/claude-agent-acp@<pin>`. In every other case (pnpm's dir, no adapter, a location it does not recognise) it returns `pnpm add -g @agentclientprotocol/claude-agent-acp@<pin>`. After an install that exits 0, `build` asks the adapter on PATH for its version again, and when it is still not the pin, it prints that binary's path and version. The mise command skips this check (Decide 2).

**Acceptance criteria in plain words.**
1. A mise-installed adapter (installs dir or shim) at the wrong version: both messages name the `mise use -g` command, never `npm i -g` (S1).
2. No adapter on PATH: both messages name `pnpm add -g …@<pin>`; no command either message names starts with `npm` (S2).
3. A pnpm-installed adapter at the wrong version: both messages name `pnpm add -g …@<pin>`, and neither names `npm` or `mise` (S3).
4. After the suggested command exits 0, the next `build` asks nothing. When an unrecognised copy still answers first with another version, `build` prints its path and version right after the install (S4, S5).

**What must not change.** A failed install never fails the build. `host-acp` never prompts and writes nothing to stdout. omp never checks the adapter. The pin is read from `catalog/agents/claude/agent.yaml`, never a literal. The `c` option stays. The version is still asked with `--version`, never read from a file.

**How it is proven.** Unit tests in `tests/test_launcher_build_adapter.py` and `tests/test_host_acp.py` run a real stub `claude-agent-acp` placed under a temp `MISE_DATA_DIR`, a temp dir a stub `pnpm bin -g` prints, or another dir, and record the install argv. `live.yml` runs because `src/harnessed/launcher.py` changes.

**Open decisions.** None. mcrowe ruled on 2026-10-14: pnpm's dir is the one `pnpm bin -g` prints (Decide 1 B), and every exit-0 install except the mise command is re-checked (Decide 2 A).

## Orientation
- Change: choose the adapter install command from the location of the `claude-agent-acp` on PATH, default to pnpm, and re-check the version after a successful install.
- Why: `npm i -g` installs where PATH does not look when mise or pnpm owns the adapter, so the offer and the warning never stop.
- Touches: `src/harnessed/launcher.py` (`_acp_adapter_install_cmd`, `_offer_acp_adapter`, `_require_acp_adapter`); `tests/test_launcher_build_adapter.py`; `tests/test_host_acp.py`.
- Decide: (1) how pnpm's global dir is recognised; (2) which installs get the post-install re-check.
- Decided: Decide 1 B, pnpm's dir is what `pnpm bin -g` prints (governs the *pnpm dir* term and S3); Decide 2 A, re-check every exit-0 install except the mise command, `c` included (governs S5). Ruled by mcrowe, 2026-10-14.

- Tier: 2
- Issue: GH-604
- Isolation: worktree — `worktrees/GH-604` on branch `GH-604`.

## Scenarios

Terms. *Pin*: `(package, version)` from `_acp_adapter_pin()`, today `@agentclientprotocol/claude-agent-acp` `0.89.1`; tests read it from the code, never a literal. *Spec*: the build-arg spec `npm:@agentclientprotocol/claude-agent-acp` from the same manifest. *Mise data dir*: `$MISE_DATA_DIR`, else `<paths.xdg_data_home()>/mise`. *Mise location*: a path under `<mise data dir>/installs/` or `<mise data dir>/shims/`. *pnpm dir*: the directory `pnpm bin -g` prints, asked only when the adapter is on PATH and not in a mise location; when `pnpm` is not on PATH, exits nonzero, or times out, no path is in the pnpm dir (Decide 1 B, mcrowe, 2026-10-14). *Stub*: an executable `claude-agent-acp` script that prints a given version for `--version`. *Mise command*: `mise use -g <spec>@<pin version>`. *pnpm command*: `pnpm add -g <package>@<pin version>`. *Offer*: `build`'s `(y/n/c)` question, or its INFO line without a terminal. *Warning*: `host-acp claude`'s off-pin stderr line. *Refusal*: `host-acp claude`'s not-installed stderr error. The adapter found is the first `claude-agent-acp` on PATH, as `shutil.which` finds it; its path is not resolved through symlinks.

### S1. A mise-installed adapter gets the mise command
- S1.1 Given a stub reporting 0.85.1 at `<mise data dir>/installs/npm-agentclientprotocol-claude-agent-acp/0.85.1/bin/claude-agent-acp`, first on PATH, when `build <stack> claude` runs with a terminal, then the offer names the mise command and does not contain `npm i -g`; answering `y` runs exactly `["mise", "use", "-g", "<spec>@<pin version>"]`.
- S1.2 Given the same stub, when `host-acp claude --stack <s>` runs, then the warning on stderr names the mise command and does not contain `npm i -g`, and stdout is empty.
- S1.3 (boundary) Given a stub reporting 0.85.1 at `<mise data dir>/shims/claude-agent-acp`, when `build` and `host-acp claude` run, then the offer and the warning each name the mise command.
- S1.4 (boundary) Given `MISE_DATA_DIR` unset and `XDG_DATA_HOME=<tmp>/data`, and a stub at `<tmp>/data/mise/installs/npm-agentclientprotocol-claude-agent-acp/0.85.1/bin/claude-agent-acp`, when `build` runs, then the offer names the mise command.

### S2. No adapter gets the pnpm command
- S2.1 Given no `claude-agent-acp` on PATH, when `build <stack> claude` runs with a terminal, then the offer names the pnpm command; answering `y` runs exactly `["pnpm", "add", "-g", "<package>@<pin version>"]`.
- S2.2 Given no `claude-agent-acp` on PATH, when `host-acp claude --stack <s>` runs, then it exits 1 and the refusal on stderr names the pnpm command.
- S2.3 (negative) Given each setup of S1 to S4, when `build` (with a terminal and without one) and `host-acp claude` run, then the offer, the INFO line, the warning and the refusal contain the text `npm` or `npx` nowhere except as the `npm:` prefix of the spec inside the mise command, and no argv `build` runs has `npm` or `npx` as its first element.

### S3. A pnpm-installed adapter gets the pnpm command
- S3.1 Given a stub `pnpm` on PATH whose `pnpm bin -g` prints `<tmp>/pnpm/bin`, and a stub adapter reporting 0.85.1 at `<tmp>/pnpm/bin/claude-agent-acp` first on PATH, when `build` and `host-acp claude` run, then the offer and the warning each name the pnpm command and contain neither `npm i -g` nor `mise`, and the adapter is classified as pnpm (Decide 1 B, mcrowe, 2026-10-14).
- S3.2 (boundary) Given no `pnpm` on PATH and the adapter at `<tmp>/pnpm/bin/claude-agent-acp`, when `build` runs, then it does not fail, classifies the adapter as unrecognised, and the offer names the pnpm command.
- S3.3 (negative) Given a stub `pnpm` whose `pnpm bin -g` exits 1, when `build` and `host-acp claude` run, then neither fails, and both name the pnpm command.
- S3.4 (boundary) Given the S1.1 or S2 setup, when `build` runs, then `pnpm bin -g` is not run.

### S4. An unrecognised location falls back to the pnpm command
- S4.1 Given a stub reporting 0.85.1 at `<tmp>/npm/bin/claude-agent-acp`, outside the mise data dir and the pnpm dir, when `build` and `host-acp claude` run, then the offer and the warning each name the pnpm command.

### S5. After an install, the version is checked again
- S5.1 Given the S2, S3 or S4 setup, when the user answers `y`, the install exits 0, and the stub on PATH now reports the pin version, then `build` prints no shadow warning and exits 0; a second `build` makes no offer.
- S5.2 (negative) Given the S4 setup with the stub reporting 0.80.0, when the user answers `y`, the install exits 0, and the stub still reports 0.80.0, then `build` prints one yellow warning on stderr naming `<tmp>/npm/bin/claude-agent-acp` and `0.80.0` and exits 0.
- S5.3 (boundary) Given the S1.1 setup, when the user answers `y` and the mise command exits 0, then `build` runs no `--version` check after the install and prints no shadow warning (Decide 2 A, mcrowe, 2026-10-14). A second `build`, with a stub reporting the pin version first on PATH, makes no offer.
- S5.4 (boundary) Given the S4 setup, when the user answers `c`, types a command, and it exits 0 while the stub still reports 0.85.1, then `build` prints the same shadow warning as S5.2.
- S5.5 (negative) Given any setup, when the install exits nonzero, then `build` prints the existing failed-install warning, prints no shadow warning, and exits 0.
- S5.6 (negative) Given the S4 setup, when the install exits 0 and no `claude-agent-acp` is on PATH afterward, then `build` prints one warning that says the adapter is not on PATH, and exits 0.

## Must NOT
- A failed or shadowed install never fails `build`: it exits 0 (existing `test_s6_6_a_failed_install_warns_and_builds_on`; S5.2, S5.5, S5.6).
- `host-acp` never prompts and writes nothing to stdout (`_require_acp_adapter` docstring: "Never asks"; S1.2).
- omp never checks the adapter (existing `test_s6_9_omp_never_checks_the_adapter`).
- The pin is read from `catalog/agents/claude/agent.yaml` through `_acp_adapter_pin`, never a literal (comment at `tests/test_launcher_build_adapter.py:21`).
- The `c` option keeps running the typed command through `bash -c` (existing `test_s6_3_c_runs_the_typed_command_through_bash`).
- The installed version is asked with `--version`, never read from a file (`_installed_acp_adapter` docstring, SPEC revision 5 of GH-571).
- No answer, no terminal: the offer still only names the command and runs nothing (existing `test_s6_7_no_terminal_asks_nothing_and_names_the_command`).

## Touches
- `src/harnessed/launcher.py` — `_acp_adapter_install_cmd` takes the adapter path and picks the mise or pnpm command; `_acp_adapter_pin` (or a sibling) exposes the spec; `_offer_acp_adapter` re-checks after an exit-0 install; `_require_acp_adapter` passes the adapter path.
- `tests/test_launcher_build_adapter.py` — `_NPM`/`_INSTALL` and `test_s6_2_yes_runs_the_npm_install` move to the pnpm command (they encode GH-571's npm decision, which this story replaces); new S1 to S5 tests.
- `tests/test_host_acp.py` — `_install_cmd` moves to the chosen command; new S1.2, S1.3, S2.2, S3.1, S4.1 cases.

## Documentation
- None, because no guide names the install command; `docs/` (the wiki) was not searched for it, and a wiki hit would be a separate delivery.

## Known limits
- A project `mise.toml` that pins another adapter version wins over `mise use -g` inside that project, so `build` there still offers. The skipped re-check (Decide 2) does not report it.
- An install layout that is neither mise nor pnpm gets the pnpm command, which can be shadowed; S5.2 reports it but does not fix it.
- A symlink from another dir into the mise or pnpm dir is classified by the link's own path, not its target.
- Classifying a pnpm install costs one `pnpm bin -g` subprocess (timeout 10 s) on each `build <stack> claude` and `host-acp claude` start when the adapter is on PATH, off-pin, and outside a mise location. `build` never runs it when the adapter is the pin.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1–S5 unit scenarios, no regression | all pass; the count does not drop below the baseline |
| coverage | branch coverage of `src` | at least 80% (`--cov-fail-under=80`) |
| types | pyright | 0 errors in changed files |
| lint | ruff on src, tests, tools | 0 findings |
| shellcheck | shell scripts | 0 findings (no shell change expected) |
| secrets | gitleaks | 0 leaks |
| live.yml (CI) | container path: `launcher.py` | `live` and `live-docker` green |
