# Decisions — Name the ACP adapter install command of the tool that owns the adapter

## Setup plan
- Isolation: worktree — `worktrees/GH-604` on branch `GH-604`, cut from `main` at `42981bd`.
- Git: commit per scenario group, signed, on `GH-604`. The queued label is its own commit.
- New dependencies: none.
- New files: none in `src/`; tests extend `tests/test_launcher_build_adapter.py` and `tests/test_host_acp.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests (`tools/run-tests.sh`), coverage (80%, branch), types (pyright), lint (ruff on src, tests, tools), shellcheck and secrets (gitleaks). Mutation is not a declared layer. Tier 2 does not require it, so it does not run.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml`, the same set GH-600 transcribed (pytest, ruff, pyright, shellcheck). `live.yml` triggers on `src/harnessed/launcher.py`, which this change touches.

## Facts this SPEC rests on
1. `_acp_adapter_install_cmd` (`src/harnessed/launcher.py:4913`) returns `["npm", "i", "-g", f"{package}@{version}"]`. Its two callers are `_require_acp_adapter` (`:4941`, the refusal and the warning) and `_offer_acp_adapter` (`:4963`). Read 2026-10-14.
2. `_acp_adapter_pin` (`launcher.py:4905`) reads package and version from the claude agent manifest; the spec `npm:@agentclientprotocol/claude-agent-acp` is in `agent.build_arg_specs`. `catalog/agents/claude/agent.yaml:10` pins 0.89.1.
3. `_installed_acp_adapter` asks `shutil.which("claude-agent-acp")` for `--version`. `host_acp` calls `_require_acp_adapter` for claude only (`launcher.py:3698`).
4. On this host, `pnpm bin -g` prints `/home/mcrowe/.local/share/pnpm/bin` while `PNPM_HOME=/home/mcrowe/.local/share/pnpm`. So pnpm 11's global bin is a subdirectory of `PNPM_HOME`, not `PNPM_HOME` itself. Run 2026-10-14.
5. On this host, `~/.local/share/mise/installs/npm-agentclientprotocol-claude-agent-acp/` still holds `0.85.1` after `mise use -g …@0.89.1` installed `0.89.1`. mise keeps old versions. In activate mode the running process's PATH still names the old dir until the shell hook runs again. `which -a claude-agent-acp` lists the installs dir first, then `~/.local/share/mise/shims/`. Run 2026-10-14, mise 2026.10.3.
6. `paths.xdg_data_home()` (`src/harnessed/paths.py:308`) returns `$XDG_DATA_HOME` or `~/.local/share`. Reusing it does not touch `paths.py`.
7. The existing tests `tests/test_launcher_build_adapter.py:24` (`_NPM`) and `tests/test_host_acp.py:338` (`_install_cmd`) encode GH-571's `npm i -g` choice. GH-604's approved story replaces that decision, so these change by this story's authority. They are not loosened.
8. The test stubs put the adapter under `<tmp>/npm/bin`, which is neither a mise nor a pnpm location, so they exercise the fallback.

## Decide calls

### Decide 1. How is pnpm's global dir recognised?
Fact 4: the bin dir is `$PNPM_HOME/bin` on pnpm 11, so equality with `PNPM_HOME` would miss it.

- A. The adapter path is under `$PNPM_HOME`, defaulting to `<xdg_data_home>/pnpm` when unset. Cost: a pnpm configured with a custom `global-bin-dir` outside `PNPM_HOME` is not recognised; it then gets the pnpm command anyway, through the fallback.
- B. Ask `pnpm bin -g` and compare. Cost: one more subprocess on every build and host-acp start, and it needs pnpm on PATH; it fails closed to the fallback.

Default: A. Ruling: B (mcrowe, 2026-10-14).
Changes: the *pnpm dir* term in SPEC.md; S3.1 uses a stub `pnpm bin -g`; new S3.2, S3.3, S3.4; a Known limits line on the subprocess cost.

### Decide 2. Which installs get the post-install re-check?
Fact 5: after `mise use -g` the build's own PATH still finds the old installs dir, so a re-check there reports a false shadow.

- A. Re-check after every exit-0 install except the mise command, including `c`. Cost: a project `mise.toml` that pins another version goes unreported until the next build offers again.
- B. Re-check only when the location was unrecognised. Cost: a pnpm install hidden behind a non-PATH `PNPM_HOME` (S5.6) goes unreported.
- C. Re-check every install, mise too. Cost: in mise activate mode every successful mise install prints a false warning.

Default: A. Ruling: A (mcrowe, 2026-10-14).
Changes: S5.3 cites the ruling; no scenario changed.

## Intent review
- Accepted: S2.3 now forbids `npm`/`npx` anywhere in the four messages, except the `npm:` spec prefix inside the mise command.
- Declined: "AC-4 requires the re-check for the mise case." AC-4's negative names only "a `claude-agent-acp` in an unrecognised location"; its positive clause asks only that the next build make no offer, which S5.3 proves. Whether mise is re-checked stays Decide 2.
- Declined in part: "S3.1 passes for the wrong reason." S3 and S4 produce the same command by design (the story's fallback is pnpm). Decide 1 A already states the unset case: `<xdg_data_home>/pnpm`. The ruling settles the SR-DEFER at this plan review.
- Declined: "S5.6 and S5.4 extend AC-4." Both are the same single re-check reporting what PATH now finds; dropping them would leave a reachable branch of that check untested.

## Revisions
### Revision 1. Decide 1 B and Decide 2 A ruled
mcrowe ruled both on 2026-10-14; SPEC.md updated in place as listed under each Decide call.
