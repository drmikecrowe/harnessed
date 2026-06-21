# Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Mode:** auto-resolve (user said "use the defaults" — all gray areas resolved with the recommended option, grounded in `docs/codebase/CONCERNS.md`)

<domain>
## Phase Boundary

Reconcile shipped reality with design/code/docs across three known-debt items. **No new
capabilities** — this is a behavior-preserving cleanup/reconciliation phase. The three items,
sharpened by the codebase scout:

1. **`harnessed-net` reconciliation** — NOT "remove dead network code" (the scout proves the network
   is live). It is: (a) reconcile `docs/harnessed-design.md` to the shipped publish + host-gateway
   model (CONCERNS H2), and (b) audit the `harnessed-net` code paths for *genuinely* unreachable
   logic while **keeping** the `HARNESSED_NET` opt-in.
2. **Stale comments** — comments/docs that **contradict shipped behavior** (primarily the bridge-model
   language). Code *and* docs. Excludes OPEN `[INFERENCE]` markers (those are unresolved assumptions,
   not stale statements).
3. **`*-SUMMARY.md` frontmatter hygiene** — backfill the three Phase 01 SUMMARYs (no YAML frontmatter)
   to the de-facto 02–05 schema, and normalize missing `# Dependency graph` headers. STATE.md is out
   of scope (different schema, tool-managed).

**In scope:** the three items above, behavior-preserving, verified by the existing integration
capability tests + UAT.
**Out of scope (deferred):** clearing OPEN `[INFERENCE]` markers (M2 `CLAUDE_CONFIG_DIR`, H3 omp),
`.agents/` working-tree noise (M4), HEALTHCHECK readiness (L1), the `container` alias §14 item (L2),
STATE.md frontmatter. Each is registered debt but is empirical work or unrelated surface — see
`<deferred>`.
</domain>

<decisions>
## Implementation Decisions

### harnessed-net reconciliation (the framing is corrected by the scout)
- **D-01:** **`harnessed-net` is NOT dead.** It is the live default network — `lib/harnessed-isolated.sh:63`
  (`local net="${HARNESSED_NET:-harnessed-net}"`) and `lib/harnessed-services.sh:25-28`
  (`ensure_harnessed_net()` → `ensure_named_net harnessed-net`) still create/use it. What is inert on
  this host is the **rootless bridge** path: CONCERNS H2 records `netavark: create bridge: Operation
  not supported` for any container on any user-defined bridge. The **shipped** connectivity is
  publish-to-`0.0.0.0` + the podman host-gateway `host.containers.internal`, and
  `tools/harnessed/assemble.py:65-67` already rewrites service URLs to
  `http://host.containers.internal:{port}/mcp`. The phase name's "dead code" framing is thus really
  *"bridge code preserved as a `HARNESSED_NET` opt-in that is inert here, plus docs that still describe
  the bridge as the model."*
- **D-02:** **Primary action = doc/design reconciliation** (CONCERNS H2's own recorded fix): update
  `docs/harnessed-design.md` §9 and §13 to record publish + host-gateway as the **primary** model and
  the bridge as the `HARNESSED_NET` opt-in for hosts that support it. Document the
  `host.containers.internal` (`169.254.1.2`) egress-firewall dependency (`lib/egress-firewall.sh:55-63`)
  and the FastMCP `allowed_hosts` requirement (commit `6f6c1b3`) as **operator prerequisites**, not
  implementation details.
- **D-03:** **Keep the `HARNESSED_NET` opt-in in code.** Do NOT remove `ensure_harnessed_net` /
  `ensure_named_net` / the `HARNESSED_NET:-harnessed-net` default. CONCERNS H2 states the code's
  opt-in preservation is the correct call — it is the documented escape hatch for bridge-capable hosts.
- **D-04:** **Any code removal is behavior-preserving and gated on the capability test.** The
  researcher/planner hunts for *genuinely unreachable* `harnessed-net` logic (code whose result is
  never consumed on ANY path) — not "runs but inert on this host." Anything removed MUST keep
  `harnessed test ping-time` / `harnessed test tracer-time` + the UAT green. If unsure, leave it and
  add a clarifying comment. **Do NOT reverse the publish+host-gateway pivot.**

### Stale-comment sweep boundary
- **D-05:** Scope = comments/docs that directly **contradict shipped behavior**. Primary target: the
  bridge-model language CONCERNS H2 flags (`docs/harnessed-design.md` §9/§13, plus any code comment
  still asserting DNS-by-service-name over the bridge). Both **code comments AND docs** are in scope
  (CONCERNS H2 spans both).
- **D-06:** **Exclude** OPEN `[INFERENCE]` markers — design §14 `CLAUDE_CONFIG_DIR` (`:431-433`, see
  M2) and the omp markers P-04-10/11/12 (`04-RESEARCH.md:215-217`, see H3). Those are *unresolved
  assumptions* requiring empirical confirmation, not stale *statements*. Clearing them is M2/H3 work.
- **D-07:** A comment that **documents a replacement** (e.g. `tools/harnessed/assemble.py:65-66`
  "DNS-by-service-name over harnessed-net was replaced with the host-gateway address") is **NOT stale**
  — it explains why the code is the way it is. Keep/clarify it; do not delete.

### SUMMARY frontmatter hygiene
- **D-08:** **Backfill the three Phase 01 SUMMARYs** (`01-01`/`01-02`/`01-03-SUMMARY.md`) to the
  de-facto 02–05 schema: YAML frontmatter `phase` / `plan` / `subsystem` / `tags` + a
  `# Dependency graph` block with `requires:` / `provides:`. They currently carry only prose
  `**Completed:**` / `**Requirements:**` headers.
- **D-09:** **Normalize missing `# Dependency graph` headers** in 04-* SUMMARYs that drop it (confirmed
  in at least `04-02-SUMMARY.md`; planner verifies the full set). Preserve existing frontmatter content
  — add only the missing structural pieces, do not rewrite history.
- **D-10:** **STATE.md frontmatter is OUT of scope.** It uses a different schema
  (`gsd_state_version` / `milestone` / `progress`) that is managed by the GSD tool, not a SUMMARY. The
  phase item is specifically the `*-SUMMARY.md` files.

### Verification & risk posture
- **D-11:** **Verification = re-run the integration capability tests** (`harnessed test ping-time`,
  `harnessed test tracer-time`) + the UAT suite (`tools/uat`) after changes — the project's
  integration-only stance (no new unit tests; PROJECT Out of Scope; CONCERNS M1). The stack manifest is
  the oracle.
- **D-12:** **Risk posture = strictly behavior-preserving.** No behavior change to running stacks.
  Doc/comment/frontmatter edits are zero-runtime-risk; any code change must be provably
  unreachable-removal.

### Claude's Discretion
- Exact wording of the design §9/§13 reconciliation; the precise set of `*-SUMMARY.md` files missing
  the `# Dependency graph` header; which (if any) code fragments are genuinely unreachable; commit
  granularity and ordering of the three work items.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Debt inventory (the scope source)
- `docs/codebase/CONCERNS.md` — **read first.** H2 (rootless-bridge debt + the doc/design fix this phase
  implements), M1 (integration-only testing tradeoff), the `[INFERENCE]` marker status table, and the
  Appendix "Design §14 full inventory" (which markers are OPEN vs RESOLVED).

### Design source of truth
- `docs/harnessed-design.md` §9 — shared-service model (still describes the bridge → must reconcile per D-02)
- `docs/harnessed-design.md` §13 — CLI / naming / identity (`harnessed-net` references → reconcile)
- `docs/harnessed-design.md` §14 — open items; the `[INFERENCE]` markers this phase must NOT touch (D-06)
- `docs/harnessed-design.md` §17 — docs-as-deliverable (any doc edit must keep docs matching behavior)
- `docs/harnessed-design.md` §18 — integration-only testing tradeoff (underpins D-11)

### Code the reconciliation touches / references
- `lib/harnessed-services.sh:17-28` — `ensure_named_net` / `ensure_harnessed_net` (KEEP per D-03)
- `lib/harnessed-isolated.sh:22-26,63` — `HARNESSED_NET:-harnessed-net` default + the comment explaining it
- `tools/harnessed/assemble.py:60-70` — the service-URL rewrite to `host.containers.internal` (KEEP comment per D-07)
- `lib/egress-firewall.sh:55-63` — the `host.containers.internal` (`169.254.1.2`) firewall dependency to document (D-02)
- `services/ping/` (`server.py`, `service.yaml`) + `stacks/ping-time/stack.yaml` + `recipes/ping/recipe.yaml` — the live `harnessed-net`-using service (proof the network is not dead; oracle for the capability test)

### SUMMARY schema precedent
- Any Phase 02–05 `*-SUMMARY.md` (e.g. `.planning/phases/02-isolated-tracer-bullet-stack/02-01-SUMMARY.md`) — the de-facto frontmatter + `# Dependency graph` shape to backfill into (D-08)

### Planning context
- `.planning/ROADMAP.md` — Phase 6 goal + success criteria
- `.planning/PROJECT.md` — Out of Scope (integration-only testing, no unit tests) + Key Decisions (`set -euo pipefail`, fallible probes)
- `.planning/REQUIREMENTS.md` — Phase 6 carries no new requirements (tech-debt only)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **02–05 `*-SUMMARY.md` frontmatter** — the exact schema template (`phase`/`plan`/`subsystem`/`tags` + `# Dependency graph` `requires:`/`provides:`) to backfill into Phase 01 SUMMARYs.
- **`docs/codebase/CONCERNS.md`** — the debt checklist; H2's "Fix approach" paragraph IS this phase's work spec for item 1.
- **`tools/uat/` + `tools/harnessed/capability.py`** — the verification harness (no new tests to write).

### Established Patterns
- **Integration-only testing** — the manifest is the oracle; behavior verified transitively through the running instance (CONCERNS M1). A cleanup that breaks wiring surfaces as a capability failure, so re-run `harnessed test <stack>` as the gate.
- **`[INFERENCE — verify]` convention** — unverified assumptions live in prose (design/research docs), tracked in CONCERNS' marker table, resolved empirically — NOT scattered as code TODOs. This phase respects the distinction: stale-*statement* (in scope) vs unresolved-*assumption* (deferred).
- **Bash launchers under `set -euo pipefail`**; fallible probes use `local var=$(…)` or `|| true` — any comment/code edit in `lib/*.sh` must preserve this.

### Integration Points
- `docs/harnessed-design.md` §9/§13/§14 — the doc surface to reconcile.
- The 16 `*-SUMMARY.md` files across `.planning/phases/0[1-5]-*/` — the frontmatter surface.
- `lib/harnessed-services.sh` + `tools/harnessed/assemble.py` — the network code paths referenced (read-only unless genuinely-dead logic is found).
</code_context>

<specifics>
## Specific Ideas

- The phase name's "dead code" framing is **corrected** by the scout to "inert-on-host opt-in + stale
  docs" (D-01..D-04). The single highest-value act is the CONCERNS H2 doc/design reconciliation, not
  code deletion.
- A comment that documents a *replacement* is signal, not debt (D-07) — `assemble.py:65-66` is the
  canonical example; keep it.
- The capability test (`harnessed test ping-time` / `tracer-time`) is both the regression gate AND the
  proof that `harnessed-net`-using services still work after any code touch (D-11).
</specifics>

<deferred>
## Deferred Ideas

Registered debt that is **out of this phase's three named items** — captured so it is not lost, each
belongs to its own empirical/future work:

- **M2 — `CLAUDE_CONFIG_DIR` relocation scope** (`docs/harnessed-design.md:431-433`, STATE.md lone
  Phase-1 blocker) — needs an empirical boot test, not a comment edit. Separate work.
- **H3 — omp `[INFERENCE]` markers** (P-04-10/11/12, `04-RESEARCH.md:215-217`) — needs omp UAT to clear.
- **M4 — `.agents/` working-tree noise** (49 unstaged deletions) — git hygiene, unrelated to the
  `harnessed` runtime; resolve with a deliberate commit or `git checkout`.
- **L1 — HEALTHCHECK readiness gate** degrades to "container running" — service-Dockerfile work.
- **L2 — `container` alias §14 open item** (recommendation: keep) — accept formally in a later doc pass.
- **STATE.md frontmatter** — different schema, tool-managed; not a `*-SUMMARY.md`.

None lost to scope creep — the phase stays strictly within the three named items.
</deferred>

---

*Phase: 6-Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene*
*Context gathered: 2026-06-21 (auto-resolve: all gray areas resolved with the recommended option, scout-grounded)*
