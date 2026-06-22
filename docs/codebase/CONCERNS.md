# Concerns & Technical Debt

**Analysis Date:** 2026-06-22

This document catalogues open risks, unresolved design questions, and technical debt in the `harnessed` codebase, grounded in the **current committed state** (HEAD through the multi-harness commit `b418343` + phase-06 tech-debt cleanup). The project is at milestone v1.0: the audit (`.planning/v1.0-MILESTONE-AUDIT.md`) records **39/39 requirements satisfied, 5/5 phases passed, 5/5 E2E flows intact, 0 blockers**, classified `tech_debt` solely to surface the non-critical items below.

The dominant debt theme has shifted since the prior (2026-06-16) analysis: the v1.0 networking model (publish-to-`0.0.0.0` + podman host-gateway `host.containers.internal:<port>`, with `HARNESSED_NET` as the explicit opt-in bridge) is **reconciled and verified** — phase 06 closed the stale-comment + frontmatter-hygiene + harnessed-net-docs reconciliation (see `.planning/phases/06-tech-debt-cleanup/06-VERIFICATION.md`). The residual debt now clusters around **the multi-harness expansion**: six harnesses (claude, omp, opencode, gemini, antigravity, codex) are supported, but the harness enumeration is hand-synced across ~9 sites with no single registry driving them.

---

## High Priority

### H1 — Harness dispatch is duplicated across ~9 sites; adding a harness requires hand-syncing all of them

- **Location:** the harness enumeration is repeated, with no shared registry, in:
  - `tools/harnessed/schema.py:41-48` — `HARNESS_CONFIG_DIR` (the **one** registry, but it only maps harness→config-dir-name).
  - `lib/harnessed-common.sh:17-37` — six `HARNESS_*_IMAGE` constants, each mirrored by an `ensure_<harness>_image()` function (`:202-277`).
  - `lib/harnessed-isolated.sh:43-48` — `[ "$harness" = "omp" ]` × 6 to pick `harness_image`.
  - `lib/harnessed-isolated.sh:51-55` — `[ "$harness" = "omp" ] && ensure_omp_image` × 5.
  - `lib/harnessed-isolated.sh:88-106` — re-attach `if/elif` × 6 (one `exec` per harness).
  - `lib/harnessed-isolated.sh:241-269` — interactive-attach `if/elif` × 6 (a *second* copy of the same chain).
  - `lib/harnessed-isolated-config.sh:36,50,67,76` — auth-seeding `if` × 4 (one per non-claude harness).
  - `tools/harnessed/capability.py:318-328` — `_llm_cmd` `if` × 6 (the headless backstop argv).
  - `tools/uat/phase-06.sh:33-40` — `UAT_MATRIX` (6 entries; its own comment at `:31-32` warns: *"Keep in sync with `HARNESS_CONFIG_DIR`"*).
- **Impact:** There is no machine-checked contract that these sites agree. A seventh harness (or a rename) requires editing all ~9 locations; a missed site degrades **silently to the claude default** — every one of these chains ends in an `else`/fallthrough that runs claude. The maintainer-sync burden is already self-admitted in code (`phase-06.sh:31-32`). The two attach chains in `harnessed-isolated.sh` (re-attach at `:88` vs. fresh attach at `:241`) are near-identical copies of each other — a particularly easy place for the two copies to drift.
- **Fix approach:** Promote `HARNESS_CONFIG_DIR` (or a sibling) to the single source of truth and drive the bash side from it. Concretely: (a) emit a generated `lib/harnessed-harnesses.sh` (or a data table the launcher sources) from the Python schema at build time, so `ensure_<harness>_image`, `harness_image`, and the attach/re-attach `exec` lines are table-driven, not hand-enumerated; (b) collapse the two attach chains in `harnessed-isolated.sh` into one function parameterized by `harness` → attach-command; (c) make the UAT matrix derive from `HARNESS_CONFIG_DIR` rather than re-declaring it. Until then, treat any harness addition as a checklist item across all 9 sites.

### H2 — An unknown/typo'd `harness:` in a stack manifest silently launches claude instead of erroring

- **Location:** `lib/harnessed-isolated.sh:41-48` — reads `harness` via `sed` from `stack.yaml` and selects `harness_image` through a chain of literal `[ "$harness" = "omp" ]` checks that all fall through to the `HARNESSED_CLAUDE_IMAGE` default at `:43`. The attach command at `:267-269` likewise falls through to `claude --mcp-config …` in its `else` branch. The capability test's harness reader, `tools/harnessed/capability.py:296-300`, **catches `SchemaError` and returns `"claude"`** — so even the test path masks an unsupported harness.
- **Impact:** Validation exists in exactly two places — `harnessed new` (`lib/harnessed-cli.sh:63`, a `case` that rejects unknown harnesses) and `schema.Stack.harness_config_dir` (`schema.py:131-135`, raises `SchemaError`). But the **normal launch path never calls the schema**: `harnessed <stack>` dispatches straight into `harnessed_isolated`, which parses the YAML with `sed` and never validates. A hand-edited `stack.yaml` with `harness: typo` (or a harness added to the schema but not yet to the launcher per H1) launches a claude pod against a profile the operator believed was for a different harness — a confusing partial-success, not a clear error. The design's own §18 philosophy ("a mis-wire surfaces as a capability failure") does not rescue this case, because the capability backstop (`_harness_of`) *also* falls back to claude.
- **Fix approach:** Validate `harness` against `HARNESS_CONFIG_DIR` at the **start** of `harnessed_isolated` (and in `_harness_of`, re-raise rather than swallow). Cheapest correct option: have the bash launcher call the Python schema's `load_stack` (it already shells out to python for the capability test — `harnessed:367-372`) and fail fast on `SchemaError` before any pod is created. Alternatively, source a generated harness table (per H1) so the bash `case` is exhaustive and an unknown harness hits an explicit `*) exit 1`.

---

## Medium Priority

### M1 — `harnessed test` detects the harness via fragile `grep` instead of the schema

- **Location:** `harnessed:353-357` — five lines of `grep -q '^harness:[[:space:]]*omp' stacks/$TEST_STACK/stack.yaml && ensure_omp_image` (one per non-claude harness), duplicating the harness parse that `harnessed_isolated` already does at `:41`.
- **Impact:** Two independent parsers for the same field. The `grep` anchor `^harness:[[:space:]]*` breaks on benign YAML variants the schema accepts (e.g. a leading-BOM, `harness:` at non-zero indentation under a parent block, or an inline trailing comment). The schema's `load_stack` is the authoritative reader; bypassing it means a manifest that assembles + launches cleanly can fail the test's image-ensure step, or vice versa. This is the same root cause as H1/H2 (no shared harness registry) but surfaces specifically in the test path.
- **Fix approach:** Replace the five greps with one schema-driven read: `harness="$(...)`  via the same mechanism `harnessed_isolated` uses (or, better, a single helper both call), then a `case` over the result to drive the `ensure_*_image` call. Removes the second parser entirely.

### M2 — Brittle literal-string strip of `--userns=keep-id` from pod-member args

- **Location:** `lib/harnessed-isolated.sh:204-208` — a `for` loop that strips the literal token `--userns=keep-id` from `MOUNT_ARGS` before launching the harness member, with the comment *"Strip --userns=keep-id from the member args (inherited from the pod; illegal on a member)."*
- **Impact:** This is a leak in the `rt_*` runtime abstraction (`lib/harnessed-runtime.sh`). `rt_userns_args()` (`:29-34`) emits `--userns=keep-id` for podman and nothing for docker; the member-launch code then has to know to undo it by **exact string match**. If `rt_userns_args` ever emits a variant (`--userns=keep-id:uid=1000`, `--userns=keep-id:uidmapping=…`), the strip silently fails and the member launch breaks under podman with a confusing "userns illegal on member" error whose root cause is two files away. The abstraction advertises provider-neutrality but leaks the userns detail back to the caller.
- **Fix approach:** Add `rt_member_args()` / `rt_pod_args()` to `harnessed-runtime.sh` so the member-arg set is constructed *without* userns in the first place, rather than constructed-with-then-stripped. The caller should never have to know that userns is pod-only and pod-level.

### M3 — Apple `container` runtime has no shared-netns story (explicitly deferred)

- **Location:** `lib/harnessed-runtime.sh:17-18` — *"Apple `container` has NO shared-netns / pod equivalent (one VM + IP per container); it needs a named-network + dynamic MCP endpoint and is tracked as a separate follow-up — NOT handled here."* Tracked at `.planning/todos/pending/2026-06-21-apple-container-named-network-mcp-endpoint.md`. `tools/uat/phase-06.sh:21-23` restates it: the heavy UAT legs *"will fail until the runtime layer is provider-agnostic."*
- **Impact:** harnessed targets three OCI runtimes (podman, docker, Apple `container`) but only two are wired. The `rt_*` abstraction is structured to make the port *possible*, but a contributor who picks `container` as their runtime today gets a silent fall-through to the docker branch (`rt_uses_pods` returns false for anything not podman, including `container`), which then fails opaquely because Apple `container` does not support `--network container:<peer>`. This is acknowledged, not hidden — but it is a real gap in the "provider-agnostic" claim.
- **Fix approach:** Either (a) detect Apple `container` explicitly in `detect_runtime` and refuse with a clear "not yet supported" message (fail-fast), or (b) land the named-network + dynamic-MCP-endpoint design in the pending todo. Option (a) is cheap and removes the silent fall-through.

### M4 — Shared-service reachability depends on `host.containers.internal` resolving on the host

- **Location:** `lib/egress-firewall.sh:62-63` — `PODMAN_GW=$(getent ahosts host.containers.internal …)`; if empty, the iptables allow-rule for the podman host-gateway is silently skipped. `services/ping/server.py:7-8` documents the matching FastMCP `allowed_hosts` dependency. The assembler hardcodes the URL: `tools/harnessed/assemble.py:67` — `server.url = f"http://host.containers.internal:{svc.port}/mcp"`.
- **Impact:** This is the **shipped** networking model (rootless pasta + host-gateway, phase 04-01) and it is correct for the target host. The fragility is host-portability: on a host where `host.containers.internal` does not resolve (older podman, some docker roots, or a custom `hosts` setup), the egress firewall never opens the gateway rule AND the assembled MCP URL does not resolve — so a shared-service stack (e.g. `ping-time`) launches but its `time`/`ping` MCP server is unreachable, surfacing as a capability-test failure with no pointer to the DNS name. The `HARNESSED_NET` opt-in bridge is the documented escape hatch, but there is no detection/warning that the primary path is broken on a given host.
- **Fix approach:** At launch (or `harnessed test` time), probe `getent ahosts host.containers.internal` and emit a `print_warning` (not an error) when it is empty, naming `HARNESSED_NET` as the fallback. Cheap, and turns a silent capability failure into an actionable operator message. The dependency itself is inherent to the rootless model and should stay.

### M5 — Integration-only testing: assembler regressions surface as coarse capability failures (deliberate, but real)

- **Location:** `docs/harnessed-design.md:519-520` (§15: *"Testing is integration-only — see §18 — not assembler unit tests."*); the §18 honest-tradeoff framing. The sole automated oracle is `tools/harnessed/capability.py` (the per-stack `harnessed test` run) + the UAT suites (`tools/uat/phase-0{4,6}.sh`). There are **zero** `test_*.py` / `*_test.py` / `conftest.py` / `*.bats` files in the tree; `tools/test-fixtures/` holds *inputs* to the capability path, not assertions about assembler internals.
- **Impact:** This is a **deliberate, documented tradeoff**, not an oversight: an assembler bug surfaces as "skill X missing" or "MCP Y not connected" in the capability table, not a pinpointed unit failure. The mitigation the design names — *clear, fail-fast assembler errors* — is implemented for the high-risk paths (`tools/harnessed/assemble.py:36-47` fails fast on duplicate MCP server names; `synclinks.py` reports skill/command collisions). But other failure modes (a profile-mount path error, an MCP-merge that produces a syntactically-valid-but-wrong config, a service-URL mis-resolution) present only as a red capability row, with no assembler-level assertion to localize them. The multi-harness expansion (H1) widens the assembler's surface without widening its test coverage.
- **Fix approach:** Keep the integration-first stance. The proportionate mitigation is to make every emit/merge failure mode emit a specific, actionable error (audit `tools/harnessed/emit.py`, `assemble.py:_resolve_service_servers`, `synclinks.py` for any silent `return None` / best-effort path), so the capability test is never the *first* signal. Adding a small set of pure-function unit tests for `schema.load_stack` / `assemble._merge_servers` / `capability.build_report` (all already factored as pure, no-podman functions) would be low-cost and would catch the regressions that currently need a full pod boot to surface.

---

## Low Priority / Improvement Opportunities

### L1 — Stale `new_stack` validation comment undercounts the harness set

- **Location:** `lib/harnessed-cli.sh:55-56` — comment reads *"Validates harness ∈ {claude, omp, opencode}"*, but the actual `case` at `:63` validates all six: `claude|omp|opencode|gemini|antigravity|codex`.
- **Note:** Phase 06's comment-reconciliation sweep was scoped to `harnessed-net` references and did not catch this. A maintainer reading the comment believes only three harnesses are scaffoldable. One-line comment fix; the code is correct.

### L2 — `$net` is assigned-but-unused (deliberately kept, but a trap for maintainers)

- **Location:** `lib/harnessed-isolated.sh:74-77` — `local net="${HARNESSED_NET:-harnessed-net}"` with a four-line clarifying comment admitting *"the live pod-network block below reads `${HARNESSED_NET:-}` directly, so `$net` is assigned-but-unused on this path. KEPT per D-04 ('if unsure, leave it and add a clarifying comment')."* The live logic is at `:147-150`.
- **Note:** This is the residual of the phase-06 D-03/D-04 decision to preserve the `:-harnessed-net` default-name anchor rather than delete the dead variable. The comment mitigates the trap, but a future cleanup that removes `$net` must also confirm the literal `harnessed-net` still appears as the `ensure_harnessed_net` default at `lib/harnessed-services.sh:29` — they are coupled only by convention, not by code.

### L3 — Context-mode `PreToolUse` host hook blocked a phase-06 commit (external fragility)

- **Location:** documented in `.planning/phases/06-tech-debt-cleanup/06-01-SUMMARY.md:100,120` — *"a context-mode PreToolUse hook that pattern-matches the token `curl` in command text and had blocked the first commit attempt."*
- **Note:** This hook is **not part of harnessed** — it lives in the operator's host environment (the `context-mode` skill). It is flagged here because it is a real operational fragility for *contributors*: a commit message or command containing the token `curl` (e.g. the antigravity installer at `base/Dockerfile.harnessed-antigravity`, which runs `curl -fsSL https://antigravity.google/cli/install.sh | bash`) can trip the hook and block the commit. The phase-06 workaround was to reword a commit message. No harnessed-side action; noted for contributor onboarding docs.

### L4 — Phases 01–04 lack a `*-VALIDATION.md` artifact (process gap, not test-coverage gap)

- **Location:** `.planning/v1.0-MILESTONE-AUDIT.md:117-119` (Nyquist-coverage section) — phases 01-04 have no `VALIDATION.md`; phase 05 has one with `nyquist_compliant: false` (PARTIAL — 4 manual-only live legs, all resolved). Confirmed by directory inventory: only `05-*-VALIDATION.md` and `06-*-VALIDATION.md` exist under `.planning/phases/`.
- **Note:** The audit is explicit that this is a **missing process artifact, not a test-coverage hole** — each of phases 01-04 is otherwise covered (P1 operator live run, P2 3 live gates, P3 03-UAT 8/8, P4 phase-04.sh 16/16 tests / 50 checks live). Backfilling the four `VALIDATION.md` files is a documentation task; it does not affect the shipped product.

### L5 — Design §14 open items remain open (carried forward, low-risk)

- **Location:** `docs/harnessed-design.md:446-490` (§14 "Open / to verify during execution"). Items still unresolved as of this analysis:
  - `container` alias (`:471-472`) — recommendation "keep — zero cost"; `install.sh:23` (`BINARIES=("harnessed" "container")`) and the `container` shim already implement this. The §14 item just needs to be formally closed.
  - `CLAUDE_CONFIG_DIR` relocation (`:488-490`) — still `[INFERENCE — verify]`; if it does not relocate the top-level `~/.claude.json`, `transparent` mode's copy-on-start (`lib/harnessed-transparent.sh`) is the permanent strategy, not an interim one.
  - Editor/tool configs in isolated mode (`:475-477`) — always-mounted today; no flag to gate for a truly empty env.
  - Host-projects scope (`:478-480`) — harnessed-owned `~/.local/state/harnessed/…` is the implemented convention (`lib/harnessed-isolated.sh:132`); not test-pinned against an accidental write to the host's real `~/.claude/projects/`.
- **Note:** None of these block v1.0. They are the architect's own open questions, carried forward. The two `[INFERENCE — verify]` markers (`.claude.json` stub fields at `:448-450` is RESOLVED; `CLAUDE_CONFIG_DIR` at `:488-490` is OPEN) are explicitly excluded from phase-06's scope (D-06) and remain.

### L6 — omp harness depends on the external `claude-hooks-bridge` npm package

- **Location:** `base/Dockerfile.harnessed-omp` (installs `@drmikecrowe/omp-claude-hooks-bridge` via `omp plugin install`); described in `tools/harnessed/schema.py:31` — *"omp — Claude hooks/skills via the pre-installed claude-hooks-bridge."*
- **Note:** The omp harness is entirely dependent on this one external (owner-authored, but still external) npm package to map Claude hooks/skills into omp's lifecycle. It is pinned implicitly by `omp plugin install` (omp's plugin lock under `~/.omp/plugins`), not by a lockfile the assembler controls. A bridge update that changes event mapping or the `permissionDecision`/exit-2 contract would silently break omp stacks at the next image rebuild. Lower severity than the prior (2026-06-16) analysis assessed, because the harness matrix UAT (`tools/uat/phase-06.sh:90`, `test_harness_omp`) now exercises the omp stack end-to-end and would catch a bridge regression — but the pinning gap remains.

---

## TODOs and FIXMEs Found

**No `TODO` / `FIXME` / `HACK` / `XXX` / `WORKAROUND` / `@deprecated` markers exist in the product code** (`lib/`, `tools/`, `harnessed`, `base/`, `recipes/`, `stacks/`, `services/`, `systemd/`, `profiles/` — all searched; the only `XXX`-shape hits are `mktemp -t …XXXX` templates, not markers). The one intentional `# NOTE` marker is `tools/uat/phase-06.sh:21` (the provider-portability caveat — quoted in full in M3).

The project's convention is to track open work in **two places other than code comments**:

1. **`[INFERENCE — verify]` markers in design/research docs** — flag unverified assumptions for empirical resolution. Two remain open in `docs/harnessed-design.md` (see L5); the rest are resolved.
2. **`.planning/todos/{pending,completed}/`** — dated, filed follow-ups. Currently pending: `01-apple-container-named-network-mcp-endpoint.md` (M3). The `completed/` dir holds resolved items for traceability.

This is healthier than scattering TODOs in code (assumptions are tracked in one place and resolved empirically), but it means "open work" lives in prose/metadata, not in grep-able code comments — a contributor running `grep -rn TODO lib/` will find nothing and may wrongly conclude there is no debt. The items above are the substantive equivalent of those TODOs.

---

## Missing or Weak Areas

- **No unit tests of any kind** (see M5). Every code path — schema parsing, link-sync collision detection, MCP-merge, emit, service-URL resolution, capability diffing — is exercised only transitively through `capability.py` and the UAT suites. The pure, no-podman functions (`schema.load_stack`, `assemble._merge_servers`, `capability.build_report`, `capability.expected_capabilities`) are explicitly factored to be unit-testable but have no tests pointing at them.
- **No lockfile pinning surfaced for the Python deps beyond ranged specifiers.** `tools/pyproject.toml` ranges `ruamel.yaml` (`>=0.18,<0.19`) and `rich` (`>=14,<15`); `tools/uv.lock` is now committed (added in `b418343`), which closes the reproducibility gap — but the ranged specs mean a fresh `uv lock` can still drift within the range.
- **Deferred live-test legs from phase 06.** `.planning/phases/06-tech-debt-cleanup/06-VERIFICATION.md:143-147` defers three live gates to `/gsd-verify-work`: `harnessed test ping-time`, `harnessed test tracer-time`, and `bash tools/uat/run-uat.sh`. The deferral is principled (rootless `podman.socket` inactive on the verification host + the working tree carried uncommitted WIP at the time), and the static gates are the load-bearing verification for a comment/doc-only phase. These remain un-run on the current HEAD against a live podman host.
- **Per-harness auth-seeding coverage is uneven.** `lib/harnessed-isolated-config.sh` seeds credentials for claude/omp (ro `.credentials.json` + stub), opencode (`:36-44`), gemini (`:50-61`), and codex (`:76-84`), but antigravity (`:67-70`) explicitly *cannot* be pre-seeded — it uses Google OAuth into a system keyring that a clean-room container lacks, so `agy` prompts for an interactive login on every fresh launch and does not persist across recreates. This is a documented UX limitation (HRN-04), not a bug, but it makes antigravity the weakest of the six harnesses for isolated/reproducible use. A follow-up is filed at `.planning/todos/pending/2026-06-21-persist-agy-auth-via-in-pod-keyring.md` to close the gap via an in-pod keyring.
- **`harnessed test` exit-code contract depends on the capability report's internal assertion.** `tools/uat/phase-06.sh:51` asserts `assert_exit_zero "$UAT_RC"`, but the non-zero propagation path (`harnessed:364-378`) captures `test_rc` explicitly to defeat `set -e` — a subtle contract that a refactor of the launcher's test block could quietly break. Covered by the UAT, but only when the UAT actually runs (see the deferred-live-tests bullet above).

---

## Appendix — What changed since the 2026-06-16 analysis (resolution audit)

For traceability, the prior HIGH items and their current status:

| Prior item | Status now | Evidence |
|---|---|---|
| H1 — Phase 04 runtime verification open | **RESOLVED** | `phase-04.sh` 16/16 tests, 50/50 checks live (`.planning/v1.0-MILESTONE-AUDIT.md:68`); UAT gaps closed by 04-04. |
| H1a — Bare `harnessed` silently launches `transparent` | **RESOLVED** | No-args guard at `harnessed:91`: `[ $# -eq 0 ] && { usage; exit 0; }`. |
| H1b — State-dir slug is an opaque hash | **RESOLVED** | State dir is now keyed by a legible flattened project path: `lib/harnessed-isolated.sh:131` — `state_project="${relpath//'/'/-}"`. The hash still keys the pod/container name (DNS-label constraint), correctly decoupled. |
| H2 — Rootless-podman bridge unsupported | **RESOLVED (reconciled)** | Publish-to-`0.0.0.0` + host-gateway is the documented PRIMARY model; `HARNESSED_NET` is the explicit opt-in. Phase 06 (commits `d3eda19`, `0ec61f3`, `f39790b`, `4f925e7`, `153c0f6`) reconciled all authoritative docs/code/manifests/CLI. Surviving `harnessed-net` refs are verified live opt-in / accurate (see `.planning/phases/06-tech-debt-cleanup/06-VERIFICATION.md:50-63`). |
| H3 — omp harness unknowns unverified | **RESOLVED** | Harness-matrix UAT (`tools/uat/phase-06.sh:90` `test_harness_omp`) exercises the omp stack end-to-end. |
| M2 — `CLAUDE_CONFIG_DIR` relocation unverified | **OPEN** (see L5) | Still `[INFERENCE]` at `docs/harnessed-design.md:488-490`. |
| M4 — 49 unstaged `.agents/` deletions | **RESOLVED** | Committed in `b418343` (the multi-harness commit swept the `.agents/` cleanup). Working tree is now clean. |

The networking-reconciliation debt that dominated the prior analysis is closed; the multi-harness expansion debt (H1/H2 above) is the new center of gravity.
