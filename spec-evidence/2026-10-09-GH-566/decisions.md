# Decisions — container-acp: take the project from session/new cwd

## Setup plan
- Isolation: worktree — `3-2-gh-566-acp-session-cwd` on branch `GH-566`. CLAUDE.md forbids commits to `main`.
- Git: one commit per RED/GREEN slice; signed; the PR closes GH-566.
- New dependencies: none. The proxy uses `json`, `threading`, `subprocess` and `os`.
- New files: `src/harnessed/acpproxy.py`, `tests/test_acp_proxy.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck, secrets; all run. Live layer: `tools/acp-smoke.py` by hand, and `.github/workflows/live.yml`, which runs on the PR because `src/harnessed/launcher.py` is on its list. Mutation testing (`mutmut`) is not in the layer manifest; it runs only if Decide 3 picks Tier 3. No layer is UNAVAILABLE.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml`, `pin-check.yml` — the layers above cover them.

## Facts this SPEC rests on
1. `container_run` resolves the project from the path argument, else `Path.cwd()` — `src/harnessed/launcher.py`, `anchor_path = Path(path).resolve() if path else Path.cwd()`.
2. The container path of a project equals its host path — `src/harnessed/paths.py:960`, `container_project_path` returns `Path(project_path)`.
3. In ACP mode, `_attach` exec's `podman exec -i … bash -l -c <shell>` with the real stdout restored, or runs it as a child under `--rm` — `src/harnessed/launcher.py`, `_attach`.
4. `set_acp_mode` swaps fd 1 to stderr and saves the real fd; `acp_stdout()` returns it — `src/harnessed/console.py`.
5. `_ACP_HARNESSES = ("omp", "claude")` — `src/harnessed/attachcmd.py:60`.
6. `tools/acp-smoke.py` waits `--launch-timeout` 900 s for `initialize` today, because the reply waits for the pod; it sends `session/new` with `cwd` = the project — `tools/acp-smoke.py`.
7. Two tests in `tests/test_acp_verb.py` encode the ACP exec handoff: `test_stdout_is_restored_before_the_exec` and `test_the_rm_child_gets_the_clients_channel`. The story's proxy replaces that handoff in ACP mode, so they change with it; this is the story's decision, not a loosening.
8. No Markdown file in the repository names `container-acp`.

## Decide calls

### Decide 1. Where does the canned `initialize` reply come from?
The proxy must answer before the agent runs (story, "Hard part"). AC-5 requires the reply to match the harness's own.

- A. A table in `acpproxy.py`, one entry per harness, filled from each harness's own reply at its pinned version. Cost: a version bump that changes capabilities needs a table edit; S5's drift line and the smoke run catch it.
- B. A cache file written from the child's real reply on each run, with the table as the first-run fallback. Cost: a cache file under the data dir, invalidation by version, and still a table for the first run.

Default: A. Ruling: A, a table in code (mcrowe, 2026-10-09).
Changes: Orientation `Decided:` line; S1.2 and S5 read the table.

### Decide 2. What does a second session for a different project get?
The story puts one process serving more than one project out of scope.

- A. A JSON-RPC error -32602, `one project per process: <P>`. A second session for the same project is forwarded. Cost: an editor that reuses one process across projects must start a new one.
- B. Forward it to the running agent unchanged. Cost: the agent runs in project P while the editor believes it is in another; files go to the wrong tree.

Default: A. Ruling: A, a JSON-RPC error (mcrowe, 2026-10-09).
Changes: Orientation `Decided:` line; S9.1 states the error.

### Decide 3. Tier 2 or Tier 3?
The proxy adds a two-thread pump (concurrency) and a stdin reader shared between the handshake and the pump.

- A. Tier 2: the full loop and the adversary. Cost: no mutation or property run on the pump.
- B. Tier 3: add a failure model, property tests on line forwarding, and mutation testing on `acpproxy.py`. Cost: about one more hour; `mutmut` is not in the layer manifest and must be run by hand.

Default: A. Ruling: A, Tier 2 (mcrowe, 2026-10-09).
Changes: Orientation `Tier:` line.

## Intent review
- Gap 1 (path argument and a third working directory): accepted. S3.1 now names a process working directory C different from both.
- Gap 2 (S9.1 points at an open Decide 2): accepted. S9.1 takes the ruling's behavior once Decide 2 is ruled.
- Gap 3 (no rule that the proxy never builds): declined. The launch keeps its existing build behavior, for example `--recipe` builds a minted stack. The story puts a cold build out of scope for its criteria, not out of the product; forbidding a build would change working behavior. Known limits names it.

## Intent review, round 2
- Gap 1 (S2.1 host path or container path): accepted. S2.1 now says the child gets P's container path, equal to P under path mirroring (Fact 2).
- Gap 2 (S2.4 is extra behavior): declined. A missing or relative `cwd` names no project, and the proxy must answer the request somehow. The alternative is to fall back to the process's own working directory, which is the very behavior the story removes. An error is the smallest answer that launches nothing.

## Revisions
### Revision 1. Gate 1a round 1, PR-REFERENT
S3.2 and Touches now say `--agent-start-folder` is an existing `container_run` option, resolved by `_resolve_start_dir`. Citation only; no scenario's meaning changed.
