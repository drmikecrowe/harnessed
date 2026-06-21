# Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `06-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 6-Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene
**Mode:** auto-resolve — user responded "use the defaults"; each gray area resolved with the scout-recommended option (no AskUserQuestion turns).
**Areas discussed:** harnessed-net reconciliation, stale-comment sweep boundary, SUMMARY frontmatter backfill

---

## harnessed-net reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Reconcile docs/design + behavior-preserving code audit; **keep** the `HARNESSED_NET` opt-in | CONCERNS H2 fix: update design §9/§13 to publish+host-gateway primary / bridge opt-in; document firewall + `allowed_hosts` prerequisites; remove only genuinely-unreachable code, gated on the capability test | ✓ |
| Remove the bridge code entirely (publish+host-gateway only) | Drop `ensure_harnessed_net` / `HARNESSED_NET` default — loses the opt-in for bridge-capable hosts | |
| Doc-reconcile only, no code audit | Match docs to shipped reality; leave all code untouched | |

**User's choice:** Use the defaults (auto-resolve) → recommended option.
**Notes:** The scout corrected the phase's "dead code" framing — `harnessed-net` is NOT dead (live default network, `harnessed-isolated.sh:63` + `ensure_harnessed_net`); what's inert on this host is the rootless bridge (`netavark: Operation not supported`, CONCERNS H2). The shipped path is publish + `host.containers.internal` (`assemble.py:65-67`). Recommended default follows H2's own recorded fix and preserves the opt-in (CONCERNS H2 says the code's opt-in preservation is correct).

---

## Stale-comment sweep boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Tight — contradicts shipped behavior only; code AND docs | Bridge-model language in design §9/§13 + any code comment asserting DNS-by-service-name over the bridge | ✓ |
| Broad — also clear OPEN `[INFERENCE]` markers | Sweep design §14 too: M2 `CLAUDE_CONFIG_DIR`, H3 omp P-04-10/11/12 | |
| Code comments only (skip docs) | Limit to in-source comments | |

**User's choice:** Use the defaults (auto-resolve) → tight.
**Notes:** OPEN `[INFERENCE]` markers are unresolved *assumptions* needing empirical confirmation (M2/H3), not stale *statements* — deferred. A comment that documents a *replacement* (`assemble.py:65-66`) is signal, not debt — keep/clarify, don't delete.

---

## SUMMARY frontmatter backfill

| Option | Description | Selected |
|--------|-------------|----------|
| Backfill Phase 01 SUMMARYs + normalize missing headers; STATE.md out of scope | Add `phase`/`plan`/`subsystem`/`tags` + `# Dependency graph` to `01-01/02/03-SUMMARY.md`; fix dropped headers in 04-* | ✓ |
| Backfill + also normalize STATE.md frontmatter | Include STATE.md's `gsd_state_version`/`milestone`/`progress` schema | |
| Normalize headers only (skip 01 backfill) | Only fix the dropped `# Dependency graph` headers | |

**User's choice:** Use the defaults (auto-resolve) → backfill 01 + normalize; STATE.md out.
**Notes:** Phase 01 SUMMARYs are the outliers (prose `**Completed:**` headers, no YAML); 02–05 define the de-facto schema. STATE.md is a different, tool-managed schema — out of scope.

---

## Claude's Discretion

- Exact wording of the design §9/§13 reconciliation.
- The precise set of `*-SUMMARY.md` files missing the `# Dependency graph` header (confirmed ≥ `04-02`; planner verifies the rest).
- Which (if any) `harnessed-net` code fragments are genuinely unreachable across all paths.
- Commit granularity and ordering of the three work items.

## Deferred Ideas

- **M2** — `CLAUDE_CONFIG_DIR` relocation scope (`docs/harnessed-design.md:431-433`) — empirical boot test, not a comment edit.
- **H3** — omp `[INFERENCE]` markers (P-04-10/11/12, `04-RESEARCH.md:215-217`) — needs omp UAT to clear.
- **M4** — `.agents/` working-tree noise (49 unstaged deletions) — git hygiene, unrelated to the runtime.
- **L1** — HEALTHCHECK readiness gate degrades to "container running" — service-Dockerfile work.
- **L2** — `container` alias §14 open item (recommendation: keep) — formal acceptance in a later doc pass.
- **STATE.md frontmatter** — different schema, tool-managed; not a `*-SUMMARY.md`.
