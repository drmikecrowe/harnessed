---
phase: 02-isolated-tracer-bullet-stack
plan: 02
subsystem: infra
tags: [podman, pod, hatago, mcp, claude, isolated-mode, auth, jq, bash]

# Dependency graph
requires:
  - phase: 02-01
    provides: emit-only assembler, base/Dockerfile.hatago (harnessed-hatago:latest), committed profiles/tracer-time/.claude + hatago.config.json, build_stack/extended build_images/ensure_images, harnessed build dispatch
provides:
  - "lib/harnessed-isolated-config.sh — harnessed_isolated_auth_mounts: ro ~/.claude/.credentials.json mount + generated token-free .claude.json stub"
  - "lib/harnessed-isolated.sh — harnessed_isolated: §4a mounts + isolated §4b + podman pod (harness + hatago) on harnessed-net + headless path"
  - "harnessed — isolated dispatch arm (non-transparent stacks → harnessed_isolated) + --fresh flag + stack-aware positional parsing"
  - "lib/harnessed-common.sh — ensure_images covers hatago; pod-aware stop_instance/remove_instance + pod_exists helper"
affects: [02-03, capability-test, phase-03, phase-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Isolated launcher mirrors the transparent launcher shape; reuses §4a mounts verbatim (D-16)"
    - "Pod = instance name (harnessed-<stack>-<projhash>); harness member == instance, hatago member == <instance>-hatago"
    - "HARNESSED_HEADLESS env opts out of the interactive attach for capability-test introspection"
    - "Isolated auth = ro credential + jq-generated token-free stub (analog of copy-on-start, D-09)"

key-files:
  created:
    - lib/harnessed-isolated-config.sh
    - lib/harnessed-isolated.sh
  modified:
    - harnessed
    - lib/harnessed-common.sh

key-decisions:
  - "Pod name == instance name; default pod (no shared userns) so §4a --userns=keep-id stays per-container; netns shared → harness reaches hatago at localhost:3535"
  - "Headless mode via HARNESSED_HEADLESS=true: compose + start the pod, skip interactive `claude` attach, leave members up (sleep infinity) for podman-exec introspection (02-03 contract)"
  - "Stack-aware positional parsing: stacks/<name>/stack.yaml OR a non-existent stack-like token → STACK (dispatch validates); an existing dir → project path for default transparent"
  - "Stub copies oauthAccount + userID from host ~/.claude.json (read-only, NEVER mounted); zero token keys"

patterns-established:
  - "Isolated §4b: ro .credentials.json + generated stub; profile is the sole config source (no host ~/.claude mount)"
  - "Pod lifecycle: stop_instance/remove_instance branch on pod_exists (isolated pod) vs single container (transparent)"

requirements-completed: [MODE-03, AUTH-02, MCP-01, MCP-02]

# Metrics
duration: ~25min
completed: 2026-06-15
---

# Phase 02 (plan 02): Isolated Mode — Auth Seeding + Runtime Pod Composition

**Isolated launch: ro-credential + token-free generated .claude.json stub, plus a podman pod (claude harness + hatago) on harnessed-net wired to a single Streamable-HTTP MCP endpoint.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-15
- **Tasks:** 3 auto + 1 operator checkpoint (pending)
- **Files modified:** 4 (2 created, 2 edited)

## Accomplishments
- `lib/harnessed-isolated-config.sh` — `harnessed_isolated_auth_mounts`: read-only `~/.claude/.credentials.json` mount + a `jq -n` generated minimal `.claude.json` stub (onboarding/identity fields, ZERO token keys) at the per-instance state dir.
- `lib/harnessed-isolated.sh` — `harnessed_isolated`: reuses §4a `harnessed_host_integration_mounts` (D-16) + isolated §4b + a rw profile mount (`profiles/<stack>/.claude` → `/home/harnessed/.claude`); ensures `harnessed-net`, `podman pod create`, runs the hatago member (`--config <mounted hatago.config.json>`) and the harness member, applies the egress firewall; `--fresh` teardown; `HARNESSED_HEADLESS` path for 02-03.
- `harnessed` — `--fresh` flag, stack-aware positional parsing, and the isolated dispatch arm replacing the old `*) Unknown stack` error (clear `no stacks/<name>/stack.yaml` error for unknown stacks); transparent + build dispatch unchanged.
- `lib/harnessed-common.sh` — `ensure_images` now also ensures `HARNESSED_HATAGO_IMAGE`; `stop_instance`/`remove_instance` tear down the pod for isolated stacks via a new `pod_exists` helper.

## Task Commits

1. **Task 1: isolated auth (ro credential + generated stub)** - `ae66887` (feat)
2. **Task 2: isolated launcher with pod composition** - `27eddca` (feat)
3. **Task 3: harnessed dispatch — isolated arm + --fresh flag** - `9a1eef9` (feat)

**Plan metadata:** this SUMMARY (docs)

## Files Created/Modified
- `lib/harnessed-isolated-config.sh` (created) - isolated §4b auth: ro credential + token-free `.claude.json` stub generator.
- `lib/harnessed-isolated.sh` (created) - isolated launcher: §4a + §4b + profile mount + podman pod (harness + hatago) on harnessed-net + headless path.
- `harnessed` (modified) - `--fresh` flag, stack-aware positional parse, isolated dispatch arm, updated usage/header.
- `lib/harnessed-common.sh` (modified) - hatago-aware `ensure_images`; pod-aware `stop_instance`/`remove_instance` + `pod_exists`.

## Acceptance Criteria Log (all PASS)

**Task 1**
- `bash -n lib/harnessed-isolated-config.sh` → PASS (parses).
- File contains `hasCompletedOnboarding` and mounts `.claude/.credentials.json` with `:ro` → PASS.
- Generated stub (runtime, `harnessed_isolated_auth_mounts test-x`) deep-scanned for `accessToken|refreshToken|oauthToken` → `[]` (none) → PASS.
- Host `$HOME/.claude.json` never added to MOUNT_ARGS (only the per-instance generated stub `<state>/claude.json:/home/harnessed/.claude.json:rw`) → PASS.

**Task 2**
- `bash -n lib/harnessed-isolated.sh` → PASS.
- Calls both `harnessed_host_integration_mounts` AND `harnessed_isolated_auth_mounts` → PASS.
- Mounts `profiles/<stack>/.claude` at `$CONTAINER_HOME/.claude`; no `$HOME/.claude:` rw mount anywhere → PASS.
- `podman pod create` on `harnessed-net` + two `--pod` `run` members (hatago + harness) → PASS (confirmed by a mocked-runtime dry-run showing the exact `pod create`/`run -d --pod`/`run -d --pod` sequence).
- `--fresh` tears down existing pod/instance (`pod rm -f` / `rm -f`) before recreate → PASS.

**Task 3**
- `bash -n harnessed lib/harnessed-common.sh` → PASS.
- `harnessed` parses `--fresh` and sets FRESH (dry-run: `--fresh` teardown ran) → PASS.
- Non-transparent stack path sources `lib/harnessed-isolated.sh` and calls `harnessed_isolated` with FRESH (dry-run: pod composed) → PASS.
- Missing `stacks/<name>/stack.yaml` yields a clear error (`Unknown stack: nonexistent-stack (no stacks/nonexistent-stack/stack.yaml)`, exit 1) → PASS.
- `ensure_images` ensures hatago (stub test: builds when hatago missing, skips when both present) → PASS; transparent dispatch unchanged (dry-run: single container, no pod) → PASS.

## Plan-level Verification
- `bash -n harnessed lib/harnessed-isolated.sh lib/harnessed-isolated-config.sh lib/harnessed-common.sh` → PASS (ALL PARSE OK).
- Generated stub has onboarding/identity fields, NO token; host `~/.claude.json` never mounted → PASS.
- Isolated launcher mounts the profile (not host `~/.claude`) and composes a pod (harness + hatago) on `harnessed-net` → PASS (mocked-runtime dry-run).
- `--fresh` headless run reaches claude with zero onboarding/login prompts → DEFERRED to operator checkpoint (needs real podman + credentials).
- The `time` MCP server connected via hatago's single endpoint → DEFERRED to operator checkpoint.

## Candidate `.claude.json` stub field set (generated)
```json
{
  "hasCompletedOnboarding": true,
  "firstStartTime": "<ISO-8601 UTC, generated at launch>",
  "numStartups": 1,
  "oauthAccount": { /* copied read-only from host ~/.claude.json (.oauthAccount // {}); identity metadata, NO token */ },
  "userID": "<copied read-only from host ~/.claude.json (.userID // \"\")>"
}
```
This is the [INFERENCE] candidate set (RESEARCH Pitfall A). The operator must confirm it boots headlessly with zero prompts; if the working set differs, pin the exact fields and snapshot the working stub as a committed fixture.

## Decisions Made
See `key-decisions` frontmatter. Notably: pod name == instance name; default pod userns (so §4a `--userns=keep-id` stays per-container while netns is shared); `HARNESSED_HEADLESS` for the 02-03 introspection path; stack-aware positional parsing that preserves `harnessed [path]` for transparent while giving a clear error for unknown stack names.

## Deviations from Plan

None - plan executed exactly as written. (Implementation choices within Claude's discretion per D-15/02-CONTEXT: `HARNESSED_HEADLESS` env as the headless toggle, hatago member named `<instance>-hatago`, and stack-aware positional parsing in the arg loop so `harnessed tracer-time` selects the stack and `harnessed nonexistent-stack` reaches the clear dispatch error.)

## Issues Encountered
None blocking. Two runtime concerns are inherently operator-verifiable and are covered by the blocking checkpoint below: (1) the exact onboarding stub field set (Pitfall A), and (2) rootless `--userns=keep-id` per-container within a shared-netns pod (Pitfall E / podman behavior). Both are validated by the real `--fresh` headless boot.

## Operator Verification (PENDING)

**Blocking checkpoint (RESEARCH Pitfall A — highest risk).** Requires a host with rootless podman + real Claude credentials (`~/.claude/.credentials.json`). NOT runnable by the executor (no credentials; no real pod launch performed).

Run, in the repo root:
```bash
./harnessed build tracer-time
./harnessed tracer-time --fresh
```
Confirm the launcher drops into `claude` with **NO onboarding / login / theme prompt** and the project mounted. Then probe headlessly (instance name: `harnessed-tracer-time-<projhash>`):
```bash
podman exec harnessed-tracer-time-<projhash> bash -lc 'claude -p "list your connected MCP servers" --output-format json'
```
Confirm it returns **JSON (not an onboarding/login prompt)**, and that the `time` MCP server is **connected**:
```bash
podman exec harnessed-tracer-time-<projhash> bash -lc 'claude mcp list'
# or inspect hatago's hatago://servers resource via the harness
```
**Resume signal:** type "approved" once the `--fresh` isolated pod boots headlessly with zero prompts and `time` is connected. If the working stub differs from the candidate field set above, note the exact fields so the snapshot fixture can be pinned. If anything prompts/errors, describe it (and the working stub fields).

## Next Phase Readiness
- 02-03 capability test can launch the live oracle via `HARNESSED_HEADLESS=true ./harnessed tracer-time --fresh` and `podman exec` into `harnessed-tracer-time-<projhash>` for introspection.
- Blocker: the operator checkpoint above must confirm the headless no-prompt boot + `time` connectivity before the slice is proven green.

## Self-Check: PASSED
- `bash -n harnessed lib/harnessed-isolated.sh lib/harnessed-isolated-config.sh lib/harnessed-common.sh` → ALL PARSE OK.
- `key-files.created` exist on disk: `lib/harnessed-isolated-config.sh`, `lib/harnessed-isolated.sh` → confirmed.
- `git log --oneline --grep=02-02` → 3 task commits (`ae66887`, `27eddca`, `9a1eef9`) + this SUMMARY.
- All three tasks' `<acceptance_criteria>` re-run and passing (logged above). Operator checkpoint recorded PENDING (cannot run podman/credentials in executor).

---
*Phase: 02-isolated-tracer-bullet-stack*
*Completed: 2026-06-15*
