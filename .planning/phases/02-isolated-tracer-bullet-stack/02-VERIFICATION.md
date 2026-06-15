---
phase: 02-isolated-tracer-bullet-stack
verified: 2026-06-15T00:00:00Z
status: human_needed
score: 9/12 plan must-have truths verified (3 remain live-runtime → operator-gated; 0 failed). Gate 1 (build) executed + fixed post-verification.
---

# Phase 2: Isolated Tracer-Bullet Stack Verification Report

**Phase Goal:** Prove the core value on the smallest end-to-end isolated slice — one harness + one MCP server + one skill — via recipe/stack schema, the build-time assembler, isolated auth seeding, runtime pod composition with hatago, and the capability test/report.
**Verified:** 2026-06-15
**Status:** human_needed

## Verification stance & hard constraint

The three plans each close with a `checkpoint:human-verify gate="blocking"` that needs HOST rootless podman + REAL Claude OAuth credentials to build images and launch a pod (`./harnessed build tracer-time`, `./harnessed tracer-time --fresh`, `./harnessed test tracer-time`). Those are OPERATOR-only — no podman/docker, image build, or pod launch was run by the verifier. Everything was verified **statically**: file existence + substance, code wiring, schema parse, python import, `bash -n`, the no-podman assembler dry-runs, the reproducible emit diff, and the report exit-code logic. The four ROADMAP Success Criteria are all live-runtime truths and are therefore classified `? NEEDS HUMAN`. No implementation gap or stub was found, so the overall status is `human_needed` (not `gaps_found`).

## Goal Achievement

### Observable Truths (plan `must_haves.truths`)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1-1 | `harnessed build <stack>` runs harnessed-tools (emit-only) then host `podman build`, producing `profiles/.../​.claude/` + `hatago.config.json` + emitted Dockerfile/launcher — nothing assembled at container start | ✓ VERIFIED | Executed end-to-end with real podman (post-verification, operator gate 1). Containerized `harnessed-tools assemble tracer-time --build-dir <repo>` (the exact `build_stack` run flags) → exit 0, committed profile byte-unchanged (idempotent). Host `podman build -f base/Dockerfile.hatago` → exit 0; hatago 0.0.16 + `mcp-server-time` baked + resolvable. NOTE: original build failed at `pnpm add -g` — pnpm 11's global bin dir is `$PNPM_HOME/bin`, not `$PNPM_HOME`; fixed PATH + pre-create in `base/Dockerfile.hatago`. |
| 1-2 | The assembler fans the standalone skill into the profile AND fails the build (non-zero, both names) on a name collision | ✓ VERIFIED | Emit produced `profiles/tracer-time/.claude/skills/time-helper/SKILL.md` (byte-identical, copytree in `synclinks.py:66-75`). Crafted dup `time2` recipe shipping `time-helper`: `assemble dup` → exit 1, stderr names BOTH `recipes/time/skills/time-helper` and `recipes/time2/skills/time-helper` (`synclinks.py:56-63`, `assemble.py:_merge_servers` mirrors for MCP names). |
| 1-3 | harnessed-tools never invokes podman/docker — only reads/writes the mounted build dir | ✓ VERIFIED | Shellout audit of `tools/harnessed/*.py`: `subprocess`/`os.system`/`Popen`/`import docker`/`import podman` present ONLY in `capability.py` (the host-native test driver added in 02-03, not the assembler). `assemble.py`/`schema.py`/`synclinks.py`/`emit.py`/`cli.py` are shellout-free. `harnessed` itself has no `CONTAINER_HOST`/`DOCKER_HOST`/`.sock`. |
| 1-4 | `base/Dockerfile.hatago` bakes hatago hub + light stdio server (`uvx mcp-server-time`) so hatago runs it as a stdio→HTTP child | ✓ VERIFIED | `base/Dockerfile.hatago:11-34`: `FROM harnessed-base`, `pnpm add -g @himorishige/hatago-mcp-hub@0.0.16` (pinned, no npm/npx), `uv tool install mcp-server-time==2026.6.4` (pinned), `CMD ["hatago","serve","--http","--port","3535"]`. `hatago.config.json` declares `time` as a stdio child (`command:uvx`,`args:[mcp-server-time]`, no `url`). Live image build operator-gated. |
| 2-1 | `harnessed <stack> --fresh` launches an isolated pod (harness + hatago) on harnessed-net that boots claude headlessly with NO onboarding/login prompt | ? NEEDS HUMAN | Wiring verified: `lib/harnessed-isolated.sh:76-91` ensures `harnessed-net`, `pod create --network harnessed-net`, runs `${instance}-hatago` then `${instance}` as `--pod` members; `--fresh` teardown at :48-52. Headless no-prompt boot = RESEARCH Pitfall A → needs real podman + credentials. |
| 2-2 | Auth = ro mount of `~/.claude/.credentials.json` + generated `.claude.json` stub with identity/onboarding fields but NO token; host `~/.claude.json` never mounted | ✓ VERIFIED | `lib/harnessed-isolated-config.sh:31-69`: `:ro` bind of `.credentials.json` (:33); `jq -n` stub with `hasCompletedOnboarding/firstStartTime/numStartups/oauthAccount/userID` (:61-67) — ZERO token keys; host `~/.claude.json` is only READ (`jq -c` :52-53) to copy identity, never added to `MOUNT_ARGS`; only the generated stub is mounted (:69). MNT-03 carried forward. |
| 2-3 | The harness config comes ONLY from the mounted `profiles/.../.claude` tree — no host config layer | ✓ VERIFIED | `lib/harnessed-isolated.sh:73` mounts `$profile_dir/.claude:$CONTAINER_HOME/.claude:rw`; no `$HOME/.claude` rw mount anywhere in the launcher (isolated path; transparent-only mount absent). Profile is the sole config source. |
| 2-4 | The harness reaches hatago at `http://localhost:3535/mcp` (shared pod netns) and the declared `time` MCP server is connected | ? NEEDS HUMAN | Wiring verified: `.claude/.mcp.json` has exactly one entry `hatago → http://localhost:3535/mcp`; pod members share netns; hatago member served with `--config` of the mounted `hatago.config.json` declaring the `time` child. Live connection needs a running pod → operator-gated. |
| 3-1 | `harnessed test <stack>` builds + launches `--fresh` headless and asserts declared capabilities present, exiting non-zero if any is missing/disconnected | ? NEEDS HUMAN | Wiring verified: `harnessed:128-152` ensures built → host `python -m harnessed.cli test … --root` → `exit "$test_rc"` (propagated, not swallowed under `set -e`). The live launch + introspection need podman + credentials → operator-gated. |
| 3-2 | Assertion prefers machine-readable introspection (hatago://servers / `claude mcp list`) with an LLM-prompt backstop | ✓ VERIFIED | `capability.py:392-403` `introspect_mcp` orders `_mcp_from_hatago` (primary, `hatago://servers` over Streamable HTTP) → `_mcp_from_claude_list` → `_mcp_from_llm` backstop; skills via `_fileext_from_filesystem` → `_skills_from_llm` backstop. |
| 3-3 | The stack manifest (stack.yaml + recipes) is the test oracle — expected derived from it, not hardcoded | ✓ VERIFIED | `capability.py:111-117` `expected_capabilities` reuses `schema.load_stack_with_recipes` + `schema.expected_capabilities`. Dry-run on tracer-time → `mcp=['time'] skills=['time-helper'] commands=[]` (derived, no literal source of truth). |
| 3-4 | The same check renders a rich markdown per-capability report (capability\|kind\|status); CI consumes the same structured result | ✓ VERIFIED | `report.py:30-71`: `render_markdown` emits the `capability\|kind\|status` table; `emit` returns `report.exit_code` from the SAME `CapabilityReport` (`capability.py:84-87` `exit_code` 0/1). Sample run: all-green → `ok=True exit=0`; missing skill → `ok=False exit=1` + `✗ missing (...)` cell; `--json` path present. |

**Score:** 8/12 plan truths statically VERIFIED · 4 ? NEEDS HUMAN (live-runtime) · 0 ✗ FAILED

### Phase Success Criteria (ROADMAP — all live-runtime → operator-gated)

| # | Success Criterion | Status | Note |
|---|-------------------|--------|------|
| SC1 | `harnessed build <stack>` assembles a 1-harness/1-MCP/1-skill recipe into a committed `profiles/<stack>/` tree + baked images, failing fast on a name collision | ? NEEDS HUMAN | Collision fail-fast + reproducible emit are statically VERIFIED; the image build + host `podman build` leg needs podman. Operator runs checkpoint 1. |
| SC2 | `harnessed <stack> --fresh` launches an isolated pod (harness + hatago) that boots headlessly with no onboarding/login prompt | ? NEEDS HUMAN | Pod-compose + isolated-auth wiring statically VERIFIED; the no-prompt headless boot is RESEARCH Pitfall A. Operator runs checkpoint 2. |
| SC3 | The instance exposes exactly the declared MCP server and skill, reached through hatago's single Streamable-HTTP endpoint | ? NEEDS HUMAN | `.mcp.json` single-endpoint + `hatago.config.json` child + profile skill are statically VERIFIED; live exposure/connection needs a running pod. Operator runs checkpoint 2/3. |
| SC4 | The per-stack capability test passes and renders a markdown report showing the declared capabilities present | ? NEEDS HUMAN | Oracle + diff + report + exit-code logic statically VERIFIED on samples; the green pass requires a live `--fresh` instance. Operator runs checkpoint 3. |

All four implementing code paths are present and statically verified; only the live runtime confirmation is operator-gated.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `recipes/time/recipe.yaml` | 1 MCP server (time, uvx, stdio) + 1 standalone skill | ✓ EXISTS + SUBSTANTIVE | `mcp.servers:[{name:time,command:uvx,args:[mcp-server-time],transport:stdio}]` + `skills:[{path:skills/time-helper}]`; parses. |
| `recipes/time/skills/time-helper/SKILL.md` | minimal valid Claude skill | ✓ EXISTS + SUBSTANTIVE | Frontmatter `name: time-helper` + description + body; no stub markers. |
| `stacks/tracer-time/stack.yaml` | isolated, claude, recipes:[time] | ✓ EXISTS + SUBSTANTIVE | `config: isolated`, `harness: claude`, `recipes: [time]`; parses. |
| `tools/` assembler (cli/schema/assemble/synclinks/emit) | emit-only Python assembler | ✓ EXISTS + SUBSTANTIVE | All 7 modules import cleanly; emit-only confirmed; no placeholder bodies. |
| `tools/Dockerfile`, `tools/pyproject.toml` | harnessed-tools image | ✓ EXISTS + SUBSTANTIVE | `python:3.13-slim`, installs jq, `pip install .`, non-root user, `ENTRYPOINT ["harnessed-tools"]`; pyproject declares `ruamel.yaml`+`rich` deps and the console script. |
| `base/Dockerfile.hatago` | hatago hub + baked uvx mcp-server-time | ✓ EXISTS + SUBSTANTIVE | Pinned pnpm/uv installs + `CMD hatago serve --http --port 3535`. |
| `profiles/tracer-time/` | generated + committed | ✓ EXISTS + SUBSTANTIVE | `.claude/skills/time-helper/SKILL.md`, `.claude/.mcp.json` (single hatago entry), `hatago.config.json` (time stdio child), `baked-servers.json`; reproducible (byte-identical re-emit). |
| `tools/harnessed/capability.py` | manifest oracle → live introspect → result | ✓ EXISTS + SUBSTANTIVE | Pure oracle + pure diff + podman-guarded launch/introspect/teardown; 471 lines, no stubs. |
| `tools/harnessed/report.py` | rich markdown report + exit code | ✓ EXISTS + SUBSTANTIVE | render/print/json/emit; single result drives report + exit. |
| `harnessed`, `lib/harnessed-isolated.sh`, `lib/harnessed-isolated-config.sh`, `lib/harnessed-common.sh` | dispatch + isolated launcher + auth + lifecycle | ✓ EXISTS + SUBSTANTIVE | `bash -n` clean for all; `build`/`test`/isolated arms + `--fresh`; `HARNESSED_HATAGO_IMAGE`/`HARNESSED_TOOLS_IMAGE`; pod-aware `ensure_images`/`stop_instance`/`remove_instance`/`pod_exists`. |

**Artifacts:** 11/11 verified (exist + substantive; no stubs/placeholders)

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| recipe `transport: stdio` | `hatago.config.json` child entry | `emit._hatago_entry` | ✓ WIRED | `is_stdio_child` → `{command,args}` (no url); emitted `time` entry = `{command:uvx,args:[mcp-server-time]}`. |
| emitted `.claude/.mcp.json` | single `http://localhost:3535/mcp` | `emit.write_mcp_json` | ✓ WIRED | Exactly one `hatago` entry → endpoint; NOT the stdio server directly. |
| isolated launcher | `profiles/tracer-time/.claude` + `$HARNESSED_HATAGO_IMAGE` on `harnessed-net` | `harnessed_isolated` | ✓ WIRED | `isolated.sh:73` profile mount; :80 `pod create --network harnessed-net`; :84-91 hatago + harness members. |
| `capability.py` expected set | `schema.expected_capabilities` | reuse | ✓ WIRED | No hardcoded oracle; dry-run derives `time`/`time-helper`. |
| `harnessed test` | python test exit code | `exit "$test_rc"` | ✓ WIRED | `harnessed:148-151` captures `|| test_rc=$?` and re-exits; not swallowed. |
| `build_stack` | emit-only run → host `podman build` | `harnessed-common.sh:88-105` | ✓ WIRED (static) | Run leg is operator-gated but the code path is present and correct. |

**Wiring:** 6/6 connections statically verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| RCP-01: recipe declares an MCP and/or file-extension layer | ✓ SATISFIED | - (recipe.yaml has both; schema parses) |
| RCP-02: stack manifest composes a harness + recipes | ✓ SATISFIED | - (stack.yaml harness+recipes; schema parses) |
| RCP-03: `harnessed build` runs the assembler in harnessed-tools emitting Dockerfile+context + committed profile + launcher; host runs podman build | ? NEEDS HUMAN | None — emit reproducible + wiring verified; container run + host `podman build` operator-gated |
| RCP-04: assembler fans skills/commands, fails fast on name collisions | ✓ SATISFIED | - (collision → exit 1, both paths; fan byte-identical) |
| MCP-03: light stdio MCP servers run as hatago children, baked into the hatago image | ✓ SATISFIED | - (Dockerfile bakes mcp-server-time; hatago.config declares stdio child); live spawn confirmed at checkpoint |
| MODE-03: `harnessed <stack>` (isolated) mounts only the assembled profile — no host config layer | ✓ SATISFIED | - (profile-only mount; no host `~/.claude`); live launch confirmed at checkpoint |
| AUTH-02: isolated auth via ro `.credentials.json` + generated `.claude.json` stub that boots headlessly with no prompt | ? NEEDS HUMAN | None — stub/ro-mount/no-token verified; headless no-prompt boot is Pitfall A, operator-gated |
| MCP-01: a running isolated stack is a podman pod (harness + hatago) on harnessed-net | ? NEEDS HUMAN | None — pod-compose code verified; "running" needs podman |
| MCP-02: hatago aggregates the stack's MCP servers behind one Streamable-HTTP endpoint the `.mcp.json` points at | ? NEEDS HUMAN | None — `.mcp.json` single-endpoint verified; live aggregation/connection operator-gated |
| TST-01: per-stack capability test asserts a live `--fresh` headless instance exposes exactly the declared servers/skills | ? NEEDS HUMAN | None — oracle/diff/dispatch verified; asserting a LIVE instance operator-gated |
| TST-02: the check renders a markdown capability report (status table) | ✓ SATISFIED | - (render + exit-code demonstrated on samples) |

**Coverage:** 6/11 SATISFIED · 5/11 NEEDS HUMAN (live confirmation operator-gated) · 0 BLOCKED

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `lib/harnessed-isolated-config.sh` | 13-22, 57-67 | `[INFERENCE]` candidate `.claude.json` stub field set (hasCompletedOnboarding/firstStartTime/numStartups/oauthAccount/userID) | ℹ️ Info | Not a gap — documented Pitfall A candidate set, explicitly gated by the 02-02 operator checkpoint and to be pinned as a fixture once proven. No token keys present. |

**Anti-patterns:** 0 blockers, 0 warnings, 1 informational (no TODO/placeholder/no-op/stub found anywhere in the delivered code).

## Human Verification Required

Three blocking `checkpoint:human-verify` gates — each needs a host with rootless podman + real Claude OAuth credentials (and, for checkpoint 3, a host `python3` with `ruamel.yaml`+`rich`). None are runnable by the verifier.

### 1. Build the stack (Plan 02-01 gate)
**Test:** `./harnessed build tracer-time`
**Expected:** builds `harnessed-tools` (from `tools/Dockerfile`) and `harnessed-hatago` (from `base/Dockerfile.hatago`); re-emits `profiles/tracer-time/.claude/skills/time-helper/SKILL.md` + `hatago.config.json` idempotently (already committed, byte-identical); `hatago.config.json` lists the `time` server (`command:uvx`,`args:[mcp-server-time]`).
**Why human:** image build + host `podman build` require rootless podman; the verifier must not run podman/docker.

### 2. Launch the isolated pod headlessly (Plan 02-02 gate — highest risk, Pitfall A)
**Test:** `./harnessed tracer-time --fresh`, then probe: `podman exec harnessed-tracer-time-<projhash> bash -lc 'claude -p "list your connected MCP servers" --output-format json'` and `podman exec … bash -lc 'claude mcp list'`.
**Expected:** drops into `claude` with NO onboarding/login/theme prompt and the project mounted; the probe returns JSON (not a prompt) and the `time` MCP server shows connected via hatago's single endpoint. If the working stub differs from the candidate field set, note the exact fields to pin the snapshot fixture.
**Why human:** needs a real pod launch + real credentials; the headless no-prompt boot is the unverifiable-statically crux.

### 3. Run the capability test green (Plan 02-03 gate — Phase success-criteria gate)
**Test:** `./harnessed test tracer-time` (and a negative run: rename `recipes/time/skills/time-helper` to a different leaf, re-run, then restore).
**Expected:** builds if needed, launches `--fresh` headless, renders the markdown `capability | kind | status` table with `time` → `✓ connected` and `time-helper` → `✓ present`, exits `0`. Negative run marks the missing capability `✗` and exits non-zero.
**Why human:** requires launching a live `--fresh` headless instance and introspecting it via `podman exec`.

## Gaps Summary

**No implementation gaps found.** Every required artifact exists and is substantive (no stubs, placeholders, TODOs, or no-op bodies), all cross-plan key links are statically wired, the emit is reproducible (byte-identical re-assembly), the collision gate fails fast naming both paths, the assembler is shellout-free (emit-only), the isolated stub is token-free with the host config untouched, and the capability report drives a single structured exit code. The phase is **code-complete**; the only outstanding items are the three operator-gated live checkpoints above, which require host rootless podman + real Claude credentials that the verifier cannot exercise. Hence `human_needed`, not `gaps_found`.

## Verification Metadata

**Verification approach:** Goal-backward (ROADMAP goal + 4 success criteria) cross-referenced with the 12 plan `must_haves.truths` and all 11 Phase-2 requirement IDs.
**Must-haves source:** PLAN.md frontmatter (`must_haves`) + ROADMAP success criteria + REQUIREMENTS.md.
**Automated checks run by verifier (all passed):**
- `bash -n harnessed lib/*.sh` → all parse OK (8 files).
- `PYTHONPATH=tools python -c 'import harnessed.capability, harnessed.report, harnessed.assemble, harnessed.schema, harnessed.synclinks, harnessed.emit, harnessed.cli'` → all imports OK.
- Assemble `tracer-time` into `/tmp/bd` + `diff -r profiles/tracer-time /tmp/bd/profiles/tracer-time` → byte-identical (reproducible emit).
- Capability oracle dry-run → `mcp=['time'] skills=['time-helper'] commands=[]` (derived, not hardcoded).
- Report exit-code sample → all-green `exit=0`, missing-skill `exit=1` with `✗` cell.
- Collision dry-run (crafted `time2` dup skill) → `exit 1`, both source paths named.
- Shellout audit of `tools/harnessed/*.py` → only `capability.py` (the host test driver) uses `subprocess`; the assembler modules are clean. `harnessed` has no `CONTAINER_HOST`/`DOCKER_HOST`/`.sock`.
- Wiring spot-checks → `.mcp.json` single hatago endpoint; `hatago.config.json` time = stdio child (no url).
**Human checks required:** 3 (operator-gated, listed above).
**Static gates:** all green. **podman/docker/launch:** not run (operator-only).

---
*Verified: 2026-06-15*
*Verifier: Claude (subagent VerifyP2)*
