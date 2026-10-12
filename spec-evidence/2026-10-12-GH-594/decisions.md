# Decisions — Merge ~/.claude.json so trust, import and in-stack answers persist

## Setup plan
- Isolation: worktree — `gh-594-merge-claude-json` on branch `GH-594`, cut from `main` at `a649823`.
- Git: commit per scenario group (S1, S2, S3), signed, on `GH-594`. The queued label is `f668fc7`.
- New dependencies: none. `hypothesis` is already in the dev extra.
- New files: `tests/test_claude_json_merge.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage (80%, branch), types (pyright), lint (ruff on src, tests, tools), shellcheck and secrets (gitleaks). Mutation is not a declared layer, so it runs by hand: `HARNESSED_DIR=$PWD mise exec -- uv run --extra dev mutmut run "harnessed.jsonmerge.x_merge_claude_json*"`. Property tests run inside `tests`.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml` — 4 checks transcribed (pytest, ruff, pyright, shellcheck). `live.yml` triggers on `src/harnessed/launcher.py`, which this change touches.

## Facts this SPEC rests on
1. `_claude_config_seed_mount(harness, inst, isolated_auth=False)` (`mounts.py:149-197`) writes `{hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID}` to `$XDG_STATE_HOME/harnessed/<inst>/claude.json` with an unconditional `write_text`, and mounts it rw at the container home. — read directly.
2. Its only production caller is `ContainerBackend.materialize_config` (`launcher.py:3785`), which passes `isolated_auth=self.stk.isolated_auth and spec.harness == "claude"`. — graph callers plus source.
3. `inst` is `instance_name(stack, harness, project_path)` = `harnessed-<harness>-<stack>-<project_hash>` (`paths.py:634`), so the stub is already per project. — read directly.
4. The container mirrors the project at the same path: "The folder path-mirrored into the container" (`launcher.py:4386-4389`), and `project_path` is the resolved start dir. So `projects[str(project_path)]` is the key Claude uses inside the container. — read directly.
5. `_share_host_claude_state(home)` (`hosthome.py:435-479`) ends with `shutil.copy2(acct, home / ".claude.json")`, where `acct` is `(_host_claude_config_override() or Path.home()) / ".claude.json"`, and copies nothing when that file is absent. — read directly.
6. `HostHarness.share_state` is `Callable[[Path], None]` and `HostBackend.seed_auth` calls `share_state(self.home)` with no project and no stack (`launcher.py:2536-2549, 2911-2924`). `HostBackend.__init__` takes only `recipes`. — read directly.
7. `_launch_host` holds `host_stk` (`load_stack_with_recipes`) and the `acp` flag before it builds `HostBackend` (`launcher.py:3236-3243`). — read directly.
8. No `isolated_auth` reference exists in `hosthome.py`, so the host path copies host identity even for an `isolated_auth` stack today. — `rg '\bisolated_auth\b'` over `hosthome.py` and `launcher.py`.
9. `_materialize_host_home` calls `_clear_host_home_except_runtime(home)` on a fingerprint change, which deletes every entry except daemon state; the claude call passes no `keep`, so `.claude.json` is deleted on a rebuild. omp passes `keep=_OMP_RUNTIME_KEEP` (`hosthome.py:135-166, 168-205, 632`). — read directly.
10. The host argv always carries `--strict-mcp-config` unless `--no-strict-mcp-config`, "so the copied .claude.json's global mcpServers never leak" (`launcher.py:2989-3000`). That keeps them out of the agent but not out of the file. — read directly.
11. `project_only` (`project-setup`, GH-571) "never touches the host home — under `host-acp` an agent is already running on it" (`launcher.py:3130-3138`). — read directly.
12. Claude Code 2.1.289 on this machine stores `hasTrustDialogAccepted`, `hasClaudeMdExternalIncludesApproved` and `hasClaudeMdExternalIncludesWarningShown` under `projects[<path>]`, and `hasCompletedOnboarding`, `oauthAccount`, `userID`, `mcpServers` at the top level. — `jq` over `~/.claude.json`, key names only. `customApiKeyResponses` is absent there because that login is OAuth; its shape comes from the story.
13. Existing tests pin today's behavior: `tests/test_claude_config_seed.py::TestSeedStub` (no `projects`, no `mcpServers` from the host), `tests/test_claude_container_auth.py::TestIsolatedAuthDoesNotLeakHostAccountMetadata` (`oauthAccount == {}` under isolation), and `tests/test_launch_host.py` lines 314-349 and 460-471 (whole-file equality with the user's file). — read directly.
14. `ARCHITECTURE.md:536` describes "a token-free `~/.claude.json` onboarding stub". — read directly.

## Gate 1 deferred items
- AC-1, key names from recall: confirmed on 2.1.289, fact 12. Known limit names the version.
- AC-2, `apiKeyHelper`: not built. The API key answer persists through the merge instead (S1.2, S2.2, S3.2); see Known limits.
- AC-6, headless import: S4.2 is the proof, run on `container-acp`.

## Intent review
- Gap 1 (AC-6 on `host-acp`): accepted as a visible limit. Known limits now says AC-6 is proven on `container-acp` only under Decide 2's default; the choice itself stays with Decide 2.
- Gap 2 (AC-2 negative, host manual check): accepted. S3.2 now carries a `rejected` entry, and S4.1 runs `host-run` as well as `container-run`.
- Gap 3 (AC-4 host, AC-5 negative): AC-4 host is Decide 1. AC-5 negative accepted as S3.8.
- Gap 4 (S3.5 beyond the story): accepted; S3.5 now states that AC-2 and AC-3 need it.
- Gap 5 (host wins over live identity): declined. Story AC-4's negative says the host path copies `oauthAccount` and `userID` "as it does today", and today the host value wins. Identity is the login's, not an in-stack answer.
- Gap 6 (empty vs dropped identity): accepted; S1.7 now names the choice and the test that pins it.
- Gap 7 (API key prompt in S4.1): accepted; S4.1 now expects it on the first launch only.

## Decide calls

### Decide 1. Does the host path honour `isolated_auth`?
Story AC-4 says "both paths". Fact 8: the host path ignores `isolated_auth` today, and it symlinks the host's own credential into the stack (`hosthome.py:463-466`), so a host-path stack runs as the host account anyway.

- A. Honour it: `_seed_host_claude_json` drops host identity under `isolated_auth`, the same as the container. Cost: `HostBackend` takes one more argument; the identity in the file then disagrees with the shared credential until the next login.
- B. Leave the host path as it is, and narrow AC-4 to the container path. Cost: the story's boundary "both paths" is not met, and a client stack launched on the host still carries the host's email.

Default: A. Ruling: A (mcrowe, 2026-10-12).
Changes: S3.4 states the effect; Orientation `Decided:` line added.

### Decide 2. Does `host-acp` seed trust for each session folder?
Fact 11: under `host-acp` one running agent serves every folder, and the launch folder is not a project. The per-project half (`project-setup`) never writes the host home, because the agent is running on it.

- A. Seed in `project-setup`: merge the three project keys for the session folder at `session/new`. Cost: harnessed writes `.claude.json` while claude-agent-acp may write it too, so an answer can be lost in a race; it also breaks the "project-setup never touches the home" rule.
- B. Seed nothing per project under `host-acp`, and prove AC-6 on `container-acp` (S4.2). Cost: a `host-acp` session in a new folder can still hit the unapproved import, the risk the story names.

Default: B. Ruling: A (mcrowe, 2026-10-12), with limits: an atomic write (temp file plus `os.replace`), a re-read just before the write, and only the three project keys under `projects[<session folder>]`.
Discussion before the ruling: `_intercept` holds `session/new` until `project-setup` exits (`acprelay.py:155-197`), so the seed lands before the session starts. The race is only with a different live session that rewrites the file from a stale copy, and losing it costs the seed, which is today's behavior. A folder approved before already persists through the merge; A covers a folder this stack has never seen.
Changes: S3.6 rewritten, S3.9 added, S4.2 adds a `host-acp` run, the `project_only` Must NOT line narrowed, Touches and Known limits updated, Orientation `Decided:` line added.

## Revisions
### Revision 1. Decide 1 and Decide 2 ruled A
The engineer ruled both on 2026-10-12, before Gate 1a. Decide 2 went against its default after the discussion above.
### Revision 2. Touches missed one existing test, and S1 needed two helpers
Found during RED for S3, after approval. `tests/test_launch_host.py::TestShareClaudeState::test_symlinks_session_state_and_live_auth` (line 375) also asserts that `_share_host_claude_state` leaves a real `.claude.json`. That function no longer writes the file, so the test now calls `_seed_host_claude_json` after it, and its "not a symlink" assertion stands unchanged. The S3.3 tests changed their fixture key from `account` to `oauthAccount`, because only the identity pair crosses from the user's file now. `jsonmerge.py` also gained `seed_claude_project` (shared by S1 and S3.9) and `read_json_or_empty` (shared by both paths). No scenario, Must NOT line or criterion changed.
