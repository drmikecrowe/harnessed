# SPEC — Merge ~/.claude.json so trust, import and in-stack answers persist

## Summary
**What it achieves.** A stack's `.claude.json` stops being thrown away on every launch. Answers given inside a stack persist. Folder trust and external-import approval are seeded for the launch's project, so a fresh API-key-only machine (8451) is not asked them at all.

**Why.** Both launch paths overwrite the file each time. The container path writes a fresh five-key stub (`_claude_config_seed_mount`). The host path copies the host file over the stack copy (`_share_host_claude_state`). A host stack rebuild also deletes the file. So trust, import, API key and MCP answers never survive.

**What changes.** One pure merge function in `jsonmerge.py` builds the file: the stack's live file is the base, and only the keys harnessed owns are laid over it. Both paths call it. The host path stops copying the host file wholesale, and a host rebuild keeps `.claude.json`. Under `host-acp`, `project-setup` seeds trust for each new session folder.

**Criteria in plain words.**
- AC-1: the first launch shows no trust and no import question, on both paths (S1.1, S2.1, S3.1, S3.7, S4.1).
- AC-2: once answered, the API key question does not come back, and a "no" stays a "no" (S1.2, S2.2, S3.2).
- AC-3: any other answer given in the stack survives a relaunch, and harnessed still forces its own onboarding flag (S1.2, S1.3, S2.2, S3.2, S3.5).
- AC-4: under `isolated_auth`, the host's `oauthAccount`/`userID` never reach the stack; without it, the host path still copies them (S1.6 to S1.9, S3.4).
- AC-5: the host's global `mcpServers` never reach the stack file, even one left by an older launch, and the stack's own servers still load (S1.5, S3.1, S3.8, S3.10).
- AC-6: an ACP session loads the external import, under `container-acp` and under `host-acp` in a new folder (S3.9, S4.2).

**What must not change.** The host's own `~/.claude.json` is never written. No API key fragment is written by harnessed. `--strict-mcp-config` stays. omp still gets no stub. Credential symlinking is unchanged.

**How it is proven.** Unit tests on the pure merge (with a hypothesis property), unit tests on both call sites, the full suite, `live.yml` because `launcher.py` changes, and manual runs on this machine: a relaunch on `container-run` and on `host-run` (S4.1), and `tools/acp-smoke.py` on `container-acp` and `host-acp` (S4.2).

**Open decisions.** None. The engineer ruled on 2026-10-12: the host path honours `isolated_auth` (Decide 1), and `host-acp` seeds each new session folder through `project-setup` (Decide 2).

## Orientation
- Change: build the stack's `.claude.json` by merging harnessed-owned keys over the live file, on both launch paths.
- Why: both paths overwrite the file on every launch, so no answer persists.
- Touches: `src/harnessed/jsonmerge.py`, `src/harnessed/mounts.py`, `src/harnessed/hosthome.py`, `src/harnessed/launcher.py`, tests, `ARCHITECTURE.md`.
- Decide: Decide 1, host path and `isolated_auth`. Decide 2, `host-acp` trust seeding.
- Decided: Decide 1 = A, the host path honours `isolated_auth` (S3.4). Decide 2 = A, `project-setup` seeds each new `host-acp` session folder (S3.6, S3.9, S4.2).

- Tier: 2 — a bug fix. It touches identity metadata (`oauthAccount`/`userID`) but no credential, so the pure merge also gets a property test and a hand-run mutation pass.
- Issue: GH-594
- Isolation: worktree — `gh-594-merge-claude-json` on branch `GH-594`.

## Scenarios

`P` below is `/work/proj`. "The three project keys" are `hasTrustDialogAccepted`, `hasClaudeMdExternalIncludesApproved` and `hasClaudeMdExternalIncludesWarningShown`. "Owned keys" are `hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID` and the three project keys under `projects[P]`.

### S1. The merge function `merge_claude_json(live, host, project, *, isolated_auth, now)`
- S1.1 Given live `{}`, host `{}`, project `P`, when merged, then the result is `{"hasCompletedOnboarding": true, "firstStartTime": now, "numStartups": 1, "oauthAccount": {}, "userID": "", "projects": {P: {the three project keys: true}}}` and nothing else.
- S1.2 Given live holding `customApiKeyResponses: {"approved": ["abc"], "rejected": ["def"]}`, `projects[P].enabledMcpjsonServers: ["srv"]` and `projects["/other"]: {"hasTrustDialogAccepted": false}`, when merged, then all three are in the result unchanged, and `projects[P]` also holds the three project keys as true.
- S1.3 (negative) Given live `hasCompletedOnboarding: false`, when merged, then it is `true`: the profile wins on an owned key.
- S1.4 (boundary) Given live `firstStartTime: "2026-01-01T00:00:00.000Z"` and `numStartups: 7`, when merged, then both keep the live values; they are seeded only when absent.
- S1.5 (negative) Given host holding `projects: {"/secret": {}}`, `mcpServers: {"leak": {}}`, `customApiKeyResponses: {"approved": ["zzz"]}` and `tipsHistory: {}`, and live `{}`, when merged, then none of those four keys is in the result.
- S1.6 Given `isolated_auth` false, host `oauthAccount: {"emailAddress": "me@example.com"}`, `userID: "host-id"`, and live holding other values, when merged, then the result holds the host's values (host wins, as today).
- S1.7 Given `isolated_auth` true, host identity as in S1.6, and live without identity keys, when merged, then `oauthAccount` is `{}` and `userID` is `""`. The story allows dropping the keys or emptying them; empty placeholders are chosen because `TestIsolatedAuthDoesNotLeakHostAccountMetadata` already pins `{}` and `""`.
- S1.8 Given `isolated_auth` true and live `oauthAccount: {"emailAddress": "client@example.com"}`, `userID: "client-id"`, when merged, then the live values are kept: the client's own login.
- S1.9 (negative) Given `isolated_auth` true and live holding exactly the host's `oauthAccount` and `userID`, when merged, then they are replaced with `{}` and `""`. This is a stack switched to `isolated_auth` after a shared launch.
- S1.10 (boundary) Given project `None`, when merged, then `projects` is left exactly as live had it, or absent when live had none.
- S1.11 (boundary) Given live or host that is not a dict (a list, `null`), when merged, then it counts as `{}`, and no exception is raised.
- S1.12 (property) For any live dict (hypothesis, 200 examples), every top-level key outside the owned keys, and every `projects` entry other than `P`, equals the live value; and the host contributes no key outside `oauthAccount`/`userID`.

### S2. Container path: `_claude_config_seed_mount`
- S2.1 Given no stub under `$XDG_STATE_HOME/harnessed/<inst>/claude.json` and project `P`, when it runs, then the stub holds the S1.1 shape for `P`, and the mount argument is `<stub>:<container home>/.claude.json:rw` as today.
- S2.2 Given a stub already holding `customApiKeyResponses` and `projects[P].enabledMcpjsonServers: ["srv"]`, when it runs again, then both are still in the stub.
- S2.3 (boundary) Given a stub that holds invalid JSON, when it runs, then the stub is rewritten from `{}` and no exception is raised.
- S2.4 `ContainerBackend.materialize_config` passes `spec.project_path` as the project. The container mirrors the project at the same path, so the key is the host path string.

### S3. Host path
- S3.1 Given the user's `~/.claude.json` holding `oauthAccount`, `userID`, `projects: {"/secret": {}}` and `mcpServers: {"leak": {}}`, and a stack home with no `.claude.json`, when a claude host launch for `P` seeds the home, then the stack file holds the user's identity and `projects[P]` with the three project keys, and has no `/secret` and no `mcpServers`.
- S3.2 Given a stack `.claude.json` holding `customApiKeyResponses: {"approved": [], "rejected": ["def"]}` and `projects[P].enabledMcpjsonServers: ["srv"]`, when the home is seeded again, then both survive unchanged, so a declined key stays declined.
- S3.3 Given a nested launch (`CLAUDE_CONFIG_DIR` set inside another stack's home), when the home is seeded, then the identity comes from the user's own `~/.claude.json`, never the parent stack's, and src equal to dst raises nothing. This keeps the intent of the existing nested-launch tests.
- S3.4 Given a stack with `isolated_auth: true` and the user file of S3.1, when the home is seeded, then the stack file holds no host `oauthAccount` and no host `userID`. Per Decide 1 = A (mcrowe, 2026-10-12): `HostBackend` receives the stack's `isolated_auth` and passes it to the merge.
- S3.5 Given a host home stamped `fp-1` that holds `.claude.json`, when `_materialize_host_home` rebuilds for `fp-2`, then `.claude.json` is still there with the same content, and a leftover recipe file is still removed. Story AC-2 and AC-3 need this: without it, any stack change on the host path deletes every answer.
- S3.6 Given a `host-acp` launch (`acp=True`), when the home is seeded, then onboarding and identity are merged and no `projects` entry is added for the launch folder, which is the editor's, not a project.
- S3.9 Given a stack home whose `.claude.json` holds `customApiKeyResponses` and `projects["/other"]`, when `project-setup` runs for session folder `P` (`project_only=True`), then `projects[P]` holds the three project keys as true, every other key is unchanged, and the write goes through a temp file and `os.replace`. Given no `.claude.json` in the home, it writes none. Per Decide 2 = A (mcrowe, 2026-10-12): this is the only home write `project-setup` makes.
- S3.7 (boundary) Given no user `~/.claude.json` at all, when the home is seeded, then the stack file still holds `hasCompletedOnboarding: true` and the three project keys for `P`. Today this case copied nothing.
- S3.10 (negative) Given a stack `.claude.json` left by a launch before this change, holding the user's `mcpServers: {"leak": {}}` and `projects: {"/secret": {}}`, when the home is seeded, then the stack file has no top-level `mcpServers`. The host path always drops that key: the stack's servers come from `<home>/.mcp.json`. Added by Revision 3 (mcrowe, 2026-10-12).
- S3.8 (negative) Given a stack with one MCP server `srv` and a user file holding `mcpServers: {"leak": {}}`, when the host launch plans its argv, then `<home>/.mcp.json` holds `srv` and not `leak`, and the argv still ends with `--mcp-config <home>/.mcp.json --strict-mcp-config`. The stack's own servers still load.

### S4. Manual runs on this machine
- S4.1 The engineer runs `harnessed container-run claude <throwaway project> --stack <throwaway stack>` twice, and then `harnessed host-run claude` on the same project and stack twice. On every launch, neither the trust question nor the import question appears. The API key question may appear on the first launch of each path and is expected there; it must not appear on the second. An agent never runs `container-run` or `host-run` (AGENTS.md); the engineer records the result in the evidence.
- S4.2 `tools/acp-smoke.py`, against `container-acp` and again against `host-acp` with a session folder this stack has never seen, on a stack whose CLAUDE.md imports `~/.local/share/gortex/instructions/active.md`, with a prompt asking for that file's first heading, returns `MANDATORY: Use Gortex MCP tools instead of Read/Grep/Glob`.

## Must NOT
- Write the host's own `~/.claude.json`, on either path.
- Write `customApiKeyResponses`, or any part of an API key, from harnessed code.
- Drop `--strict-mcp-config` from the host argv (`tests/test_launch_host.py` around line 720).
- Give omp or any non-claude harness a stub (`tests/test_claude_config_seed.py::TestSeedStub::test_omp_gets_no_stub`, `test_non_claude_harness_gets_no_stub`).
- Change credential symlinking or the token-gated credential removal in `_share_host_claude_state`.
- Break `TestIsolatedAuthDoesNotLeakHostAccountMetadata` or `TestSeedStub` in their current form. `project_path` defaults to `None` so their calls stand.
- Rebuild, wipe or write anything in the host home under `project-setup` (`project_only`), where an agent may be running on it, except the S3.9 key merge into `.claude.json`.
- Change the signature of `HostHarness.share_state`.
- Keep any runtime entry other than `.claude.json` across a host rebuild: `test_changed_fingerprint_rebuilds_wholesale` stands.

## Touches
- `src/harnessed/jsonmerge.py` — new `merge_claude_json` and its owned-key constants.
- `src/harnessed/mounts.py` — `_claude_config_seed_mount` gains `project_path=None`, reads the stub, merges, writes.
- `src/harnessed/hosthome.py` — `_share_host_claude_state` stops copying `.claude.json`; new `_seed_host_claude_json(home, project, *, isolated_auth)` merges instead; new `_seed_host_claude_project(home, project)` does the S3.9 key-only atomic write; the claude `_materialize_host_home` passes `keep=(".claude.json",)`.
- `src/harnessed/launcher.py` — `ContainerBackend.materialize_config` passes the project; `HostBackend` takes `isolated_auth` and `acp`, and `seed_auth` calls `_seed_host_claude_json` for claude; the `project_only` branch of `_launch_host` calls a project-keys-only seed for claude (S3.9).
- `tests/test_claude_json_merge.py` — new: S1.
- `tests/test_claude_config_seed.py` — S2 added.
- `tests/test_launch_host.py` — S3 added. The nested-launch and decoy tests (around lines 314 to 349 and 460 to 471) compare the whole file to the user's file. They change to compare `oauthAccount`, the allowlisted key, with the same fixtures and intent.
- `ARCHITECTURE.md` — the "token-free `~/.claude.json` onboarding stub" sentence (line 536) says the file is now merged, not overwritten.

## Documentation
- `ARCHITECTURE.md`, line 536, as above.
- The docstrings of `_claude_config_seed_mount`, `_share_host_claude_state` and `_materialize_host_home`, which today describe a stub, a snapshot copy and a wholesale wipe.

## Known limits
- The API key question still appears once per stack on the first launch. Story AC-1 allows this. `apiKeyHelper` is not built, because nobody has shown it skips the question.
- Trust is seeded for the launch's project path only. A session that later changes into another folder is asked as before.
- Under `host-acp`, a different live session that rewrites `.claude.json` from a stale copy can drop the S3.9 seed for a new folder. That session then behaves as today. The atomic write keeps the window small but cannot close it.
- S3.9 assumes claude-agent-acp starts a fresh claude CLI per session, so the new session reads the seed. The build confirms this first, with the `host-acp` run of S4.2.
- A host stack launched before this change keeps the old copy's other `projects` entries (for example `/secret`) after S3.10. They name the user's own folders on the user's own machine, and nothing reads them unless a session starts there. Revision 3.
- On the host path, a server added in the stack with `claude mcp add -s user` is dropped at each launch (S3.10). It was already inert under `--strict-mcp-config`. Revision 3.
- Two launches of one stack in different projects share one host home, and the agent writes `.claude.json` without harnessed's lock, so a concurrent answer can be lost. The old whole-file copy lost it always. The container stub is still written in place, because a bind mount needs the same inode.
- Key names are confirmed on Claude Code 2.1.289 only. A later rename would quietly bring the questions back. No test can catch that; S4.1 is the check.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1 to S3.9 and the existing suite | all pass; count not below the baseline plus the new tests |
| coverage | untested branches in the merge and both call sites | 80% overall, branch coverage on |
| types | type errors | pyright 0 errors in changed files |
| lint | style and bug patterns | ruff 0 findings |
| shellcheck | shell scripts | 0 findings |
| secrets | leaked credentials | gitleaks 0 findings |
| property | S1.12 | hypothesis, 200 examples |
| mutation | weak assertions in `merge_claude_json` | no surviving mutant without a stated reason |
| live | container path (`launcher.py` touched) | `live.yml` both jobs green on the PR |
| manual | S4.1, S4.2 | transcripts in the evidence |
