---
phase: 02-isolated-tracer-bullet-stack
verified: 2026-06-15T11:20:00Z
status: passed
score: 12/12 plan must-have truths verified (0 failed); all 4 ROADMAP success criteria confirmed live
---

# Phase 2: Isolated Tracer-Bullet Stack Verification Report

**Phase Goal:** Prove the core value on the smallest end-to-end isolated slice — one harness + one MCP server + one skill — via recipe/stack schema, the build-time assembler, isolated auth seeding, runtime pod composition with hatago, and the capability test/report.
**Verified:** 2026-06-15
**Status:** passed

## Verification stance

Initial static verification was `human_needed` (3 blocking `checkpoint:human-verify` gates need host rootless podman + real Claude credentials). The operator then ran the gates; three real bugs surfaced and were fixed, after which **all three gates were executed green on a host with rootless podman + real Claude credentials**:

- **Gate 1 (build)** — `./harnessed build tracer-time`: failed at `pnpm add -g` because pnpm 11's global bin dir is `$PNPM_HOME/bin`, not `$PNPM_HOME`. Fixed in `base/Dockerfile.hatago` (commit `4c9b665`). Re-run: containerized emit + host `podman build` both exit 0; profile byte-unchanged.
- **Gate 2 (isolated headless boot)** — `./harnessed tracer-time --fresh`: failed at pod start with `netavark: create bridge: Operation not supported` (rootless can't create the custom bridge) and then `cannot set user namespace mode when joining pod with infra container`. Fixed in `lib/harnessed-isolated.sh` (commit `1c2efea`): default pod network (pasta; `HARNESSED_NET` now opt-in), pod-level `--userns=keep-id` with the flag stripped from member args, and copy-on-start of the profile into a per-instance dir (committed profile no longer mutated). Re-run: headless `claude -p` returns `{"subtype":"success","result":"READY"}` — **no onboarding/login prompt**; the stub + ro credential authenticate.
- **Gate 3 (capability test)** — `./harnessed test tracer-time`: initially false-RED. Fixed in `tools/harnessed/capability.py` + `harnessed` (commit `94793f5`): wait for hatago readiness before introspecting, keep the project mount for the pod's lifetime (deleting it broke `podman exec`), and resolve host deps via `uv`. Re-run: `time ✓ connected`, `time-helper ✓ present`, exit 0; negative run (skill hidden) → `✗` + exit 1; `--json` clean.

## Goal Achievement

### Observable Truths (plan `must_haves.truths`)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1-1 | `harnessed build <stack>` runs harnessed-tools (emit-only) then host `podman build`, producing the committed profile + `hatago.config.json` | ✓ VERIFIED | Executed (gate 1): containerized `harnessed-tools assemble` → exit 0, profile byte-unchanged; host `podman build -f base/Dockerfile.hatago` → exit 0; hatago 0.0.16 + `mcp-server-time` baked. Fix: `base/Dockerfile.hatago` pnpm bin PATH (`4c9b665`). |
| 1-2 | The assembler fans the standalone skill into the profile AND fails the build (non-zero, both names) on a name collision | ✓ VERIFIED | `synclinks.py` copytree; crafted dup recipe → `assemble` exit 1, stderr names BOTH source paths. |
| 1-3 | harnessed-tools never invokes podman/docker — only reads/writes the mounted build dir | ✓ VERIFIED | Shellout audit: `subprocess`/`Popen`/`import docker` only in `capability.py` (host test driver), not the assembler modules. `harnessed` has no `CONTAINER_HOST`/`DOCKER_HOST`/`.sock`. |
| 1-4 | `base/Dockerfile.hatago` bakes hatago hub + light stdio server (`uvx mcp-server-time`) | ✓ VERIFIED | Built image runs `hatago serve --http --port 3535` (flags confirmed against `serve --help`); `mcp-server-time` resolvable; hatago connects the `time` child on start (logs: "Connected to server: time"). |
| 2-1 | `harnessed <stack> --fresh` launches an isolated pod (harness + hatago) that boots claude headlessly with NO onboarding/login prompt | ✓ VERIFIED | Gate 2: pod composes (default network) + both members start; headless `claude -p "...READY"` → `{"subtype":"success","is_error":false,"result":"READY"}` with no prompt. |
| 2-2 | Auth = ro mount of `~/.claude/.credentials.json` + generated `.claude.json` stub with identity/onboarding fields but NO token; host `~/.claude.json` never mounted | ✓ VERIFIED | `lib/harnessed-isolated-config.sh`: `:ro` credential bind; `jq -n` stub (hasCompletedOnboarding/firstStartTime/numStartups/oauthAccount/userID), ZERO token keys (sandbox-proven even with a host token present); host `~/.claude.json` only READ for identity, never mounted. Stub proven sufficient by gate 2's no-prompt boot. |
| 2-3 | The harness config comes ONLY from the mounted profile tree — no host config layer | ✓ VERIFIED | Launcher mounts a per-instance copy of `profiles/<stack>/.claude` (copy-on-start) at `$CONTAINER_HOME/.claude`; no `$HOME/.claude` rw mount. Committed profile stays clean after runs (git status clean). |
| 2-4 | The harness reaches hatago at `http://localhost:3535/mcp` (shared pod netns) and the declared `time` MCP server is connected | ✓ VERIFIED | Gate 2/3: harness TCP-connects `127.0.0.1:3535`; `_mcp_from_hatago` → `{'time':'connected'}`; hatago logs the `time` child connected. |
| 3-1 | `harnessed test <stack>` builds + launches `--fresh` headless and asserts declared capabilities present, exiting non-zero if any is missing/disconnected | ✓ VERIFIED | Gate 3: `./harnessed test tracer-time` → table green, exit 0; negative (skill hidden) → `✗` + exit 1 (exit propagated, not swallowed). |
| 3-2 | Assertion prefers machine-readable introspection (hatago://servers / `claude mcp list`) with an LLM-prompt backstop | ✓ VERIFIED | `introspect_mcp` orders hatago resource → `claude mcp list` → LLM backstop; green run resolved via the hatago primary (no LLM needed). |
| 3-3 | The stack manifest is the test oracle — expected derived from it, not hardcoded | ✓ VERIFIED | `expected_capabilities` reuses `schema.load_stack_with_recipes`; derives `mcp=['time'] skills=['time-helper']`. |
| 3-4 | The same check renders a rich markdown report (capability\|kind\|status); CI consumes the same structured result | ✓ VERIFIED | `report.emit` returns `report.exit_code` from the same `CapabilityReport`; live `--json` emitted `{"ok":true,...}`. |

**Score:** 12/12 plan truths VERIFIED · 0 NEEDS HUMAN · 0 FAILED

### Phase Success Criteria (ROADMAP) — all confirmed live

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| SC1 | `harnessed build <stack>` assembles into a committed `profiles/<stack>/` tree + baked images, failing fast on a name collision | ✓ VERIFIED | Gate 1 green; collision → exit 1 naming both paths. |
| SC2 | `harnessed <stack> --fresh` launches an isolated pod that boots headlessly with no onboarding/login prompt | ✓ VERIFIED | Gate 2: headless `claude -p` returns success, no prompt. |
| SC3 | The instance exposes exactly the declared MCP server and skill, reached through hatago's single Streamable-HTTP endpoint | ✓ VERIFIED | Gate 3: `time ✓ connected` via `http://localhost:3535/mcp`, `time-helper ✓ present`. |
| SC4 | The per-stack capability test passes and renders a markdown report showing the declared capabilities present | ✓ VERIFIED | Gate 3: green table, exit 0; negative flips to ✗/exit 1; `--json` clean. |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `recipes/time/recipe.yaml` + `skills/time-helper/SKILL.md` | ✓ EXISTS + SUBSTANTIVE | 1 stdio MCP server + 1 standalone skill; parses. |
| `stacks/tracer-time/stack.yaml` | ✓ EXISTS + SUBSTANTIVE | isolated, claude, recipes:[time]. |
| `tools/` assembler (cli/schema/assemble/synclinks/emit) + Dockerfile + pyproject | ✓ EXISTS + SUBSTANTIVE | 7 modules import; emit-only; no stubs. |
| `base/Dockerfile.hatago` | ✓ EXISTS + SUBSTANTIVE | builds; pinned pnpm/uv; serves :3535. |
| `profiles/tracer-time/` | ✓ EXISTS + SUBSTANTIVE | reproducible; immutable across runs (copy-on-start). |
| `tools/harnessed/capability.py` + `report.py` | ✓ EXISTS + SUBSTANTIVE | oracle → readiness-gated live introspect → single-result report/exit. |
| `harnessed` + `lib/harnessed-isolated*.sh` + `lib/harnessed-common.sh` | ✓ EXISTS + SUBSTANTIVE | `bash -n` clean; build/test/isolated arms; pod-aware lifecycle. |

**Artifacts:** 11/11 verified (no stubs/placeholders).

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| RCP-01: recipe declares an MCP and/or file-extension layer | ✓ SATISFIED |
| RCP-02: stack manifest composes a harness + recipes | ✓ SATISFIED |
| RCP-03: `harnessed build` runs the assembler → committed profile; host runs podman build | ✓ SATISFIED (gate 1 green) |
| RCP-04: assembler fans skills/commands, fails fast on name collisions | ✓ SATISFIED |
| MCP-03: light stdio MCP servers run as hatago children, baked into the hatago image | ✓ SATISFIED (hatago connects `time` child) |
| MODE-03: isolated mounts only the assembled profile — no host config layer | ✓ SATISFIED (gate 2) |
| AUTH-02: ro `.credentials.json` + generated stub that boots headlessly with no prompt | ✓ SATISFIED (gate 2 no-prompt boot) |
| MCP-01: a running isolated stack is a podman pod (harness + hatago) | ✓ SATISFIED (gate 2; default pod network) |
| MCP-02: hatago aggregates the MCP servers behind one Streamable-HTTP endpoint | ✓ SATISFIED (gate 3) |
| TST-01: per-stack capability test asserts a live `--fresh` headless instance exposes the declared servers/skills | ✓ SATISFIED (gate 3) |
| TST-02: the check renders a markdown capability report | ✓ SATISFIED |

**Coverage:** 11/11 SATISFIED · 0 NEEDS HUMAN · 0 BLOCKED

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `lib/harnessed-isolated-config.sh` | candidate `.claude.json` stub field set (was `[INFERENCE]`) | ℹ️ Info | Resolved: the field set (hasCompletedOnboarding/firstStartTime/numStartups/oauthAccount/userID) is proven sufficient by gate 2's no-prompt boot. No token keys. |

**Anti-patterns:** 0 blockers, 0 warnings, 1 informational (now resolved).

## Human Verification — completed

All three blocking gates were executed green on a host with rootless podman + real Claude credentials:

1. **Build** — `./harnessed build tracer-time` → builds harnessed-tools + harnessed-hatago, emits the profile idempotently. ✓
2. **Isolated headless boot** — `./harnessed tracer-time --fresh` → pod up; headless `claude -p` returns success with no onboarding/login prompt; `time` MCP connected via hatago. ✓
3. **Capability test** — `./harnessed test tracer-time` → `time ✓ connected`, `time-helper ✓ present`, exit 0; negative run → ✗ + exit 1. ✓

## Gaps Summary

**No gaps.** Phase goal achieved end-to-end. Three real bugs found during live verification (pnpm global bin PATH; rootless pod networking/userns + profile pollution; capability-test readiness/mount/deps) were fixed and re-verified green. Commits: `4c9b665`, `1c2efea`, `94793f5` (+ tracking).

## Verification Metadata

**Verification approach:** Goal-backward (ROADMAP goal + 4 success criteria) cross-referenced with the 12 plan truths and all 11 Phase-2 requirement IDs; finalized with live operator-gate execution.
**Automated checks:** `bash -n` (8 shell files), full `tools` package import + `py_compile`, reproducible emit diff, collision fail-fast, oracle dry-run, report exit-code samples — all green.
**Live checks:** all 3 gates executed green (host podman + real credentials).
**podman/docker/launch:** executed during finalization (gates 1–3).

---
*Verified: 2026-06-15 (static) + live gate execution*
*Verifier: Claude (subagent VerifyP2) + orchestrator live finalization*
