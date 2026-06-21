---
status: clean
phase: 06-tech-debt-cleanup
reviewed_at: 2026-06-21
reviewer: omp-reviewer-proxy
---

# Phase 06 — Advisory Code Review

> Advisory only. This gate NEVER blocks execution. It evaluates the **committed**
> phase-06 diff (`git diff 27ac680..HEAD`) against the CONTEXT D-01..D-10 scope and
> the SC-1/2/3 success criteria. The dirty working tree (pre-existing user WIP:
> multi-harness additions, `.agents/` deletions) is explicitly excluded — only
> committed blobs were reviewed via `git show HEAD:<path>`.

## Scope

Files reviewed (committed phase-06 changes only):

| File | Change class |
|---|---|
| `docs/harnessed-design.md` | doc reconciliation (§3 diagram, §9 model + new "Operator prerequisites" subsection, §13 CLI help + naming) |
| `lib/harnessed-isolated.sh` | comment reconciliation (B1: pod-network block) + D-04 clarifying comment on retained `$net` |
| `lib/harnessed-services.sh` | comment reconciliation (file header + `svc_up` doc-comment) |
| `services/ping/service.yaml` | yaml comment reconciliation |
| `recipes/ping/recipe.yaml` | yaml comment reconciliation |
| `systemd/harnessed-rescan.service` | comment reconciliation (install mechanism) |
| `.planning/phases/01-*/0{1,2,3}-SUMMARY.md` | frontmatter backfill (D-08) |
| `.planning/phases/04-*/0{2,3,4}-SUMMARY.md` | `# Dependency graph` header normalization (D-09) |

## Verification performed

Independent checks run against committed blobs (not the executor's claims):

- **bash syntax** — `bash -n` on `git show HEAD:lib/harnessed-{isolated,services}.sh` → both **OK**.
- **YAML parse** — `yaml.safe_load` on committed `services/ping/service.yaml` + `recipes/ping/recipe.yaml` → both **OK**.
- **D-06 (INFERENCE markers)** — both `[INFERENCE — …]` markers present in HEAD at `:427` and `:453`, content-identical to base (`:407`/`:433`); only line-shifted by the inserted prerequisites section. **Untouched. ✓**
- **D-07 (replacement comments)** — `tools/harnessed/assemble.py` absent from the phase-06 diffstat → its host-gateway replacement comment is untouched. **Kept. ✓**
- **Factual cross-refs** in the new design subsection verified against source:
  `lib/egress-firewall.sh:62` = `PODMAN_GW=$(getent ahosts host.containers.internal …)` (+ `:63` iptables allow), distinct from default-route `HOST_GW` at `:60-61`; `services/ping/server.py:19-25` = `TransportSecuritySettings(allowed_hosts=[…, "host.containers.internal:*"])`; `docs/guides/service-authoring.md:163` "Networking note" exists.

## Findings

No actionable findings. Observations below are all `praise` (verified-correct) — included
to document what this gate confirmed rather than to flag defects.

- **[praise] `docs/harnessed-design.md` §9 + new "Operator prerequisites" subsection (lines 240-265).**
  The old "Shared instance, concurrent … on `harnessed-net`" bullet is correctly rewritten to:
  publish to `0.0.0.0` → peers reach via host gateway `host.containers.internal:<port>` (PRIMARY) →
  `harnessed-net` bridge + DNS-by-name is the `HARNESSED_NET` opt-in for bridge-capable hosts
  (with the netavark "Operation not supported" rationale). The new prerequisites subsection records
  the egress-firewall allow rule and FastMCP `allowed_hosts` as **operator prerequisites**, exactly
  per D-02, and every line reference it cites resolves to the claimed code.

- **[praise] bash hygiene — `bash -n` clean on both edited launchers.** Comment-only edits did not
  disturb quoting/expansion. Note: the diff viewer reported "4 Bash parse errors" on
  `lib/harnessed-isolated.sh`; that is a **tooling artifact** of the side-by-side diff format (the
  `..` continuation markers + dual added/removed columns are not valid bash), **not** a real syntax
  fault. `bash -n` on the actual committed blob passes. No action required.

- **[praise] `systemd/harnessed-rescan.service:4` — a genuine accuracy fix, not a cosmetic edit.**
  The old "(`harnessed install` shim, Phase 4)" conflated two distinct mechanisms: `harnessed install
  <stack>` writes a per-**stack** launcher shim (`harnessed:17,58,177-181`), whereas the top-level
  `harnessed` launcher the rescan service depends on is installed by the **curl bootstrap**
  (`README.md:55-60`, `install.sh`). The new "installed by the curl bootstrap" is the correct
  reconciliation. Worth calling out because it fixed a real factual error rather than restyling.

- **[praise] D-06 / D-07 compliance.** The two OPEN `[INFERENCE]` markers were left intact
  (deferred empirical work, D-06); the assemble.py replacement-documenting comment was left intact
  (D-07). Scope discipline held.

- **[praise] `lib/harnessed-isolated.sh:65-68` — `$net` retention comment.** The new comment
  correctly explains why the assigned-but-unused-on-this-path `local net="${HARNESSED_NET:-…}"` is
  kept as the "literal default-name anchor," citing D-01/D-03/D-04. This is precisely the
  "if unsure, leave it and add a clarifying comment" posture D-04 prescribes — the comment is the
  deliverable, not a smell to remove.

- **[praise] SUMMARY frontmatter normalization fidelity.** `01-{01,02,03}-SUMMARY.md` received a
  pure structural insertion (frontmatter + `# Dependency graph` block) **before** the preserved
  `# Plan 0X-0Y Summary:` heading and `**Completed:**` line; no prose meaning altered.
  `04-{02,03,04}-SUMMARY.md` received only the missing `# Dependency graph` header line. Values
  are internally consistent with the known phase deliverables (no field appears fabricated).

- **[praise] cross-file consistency.** design §3/§9/§13, both `lib/*.sh`, both edited yaml files,
  and the systemd unit now describe one and the same model: publish + `host.containers.internal`
  PRIMARY, `HARNESSED_NET` bridge as opt-in. No file contradicts another; no stale "bridge as
  default" assertion remains in the reviewed set.

## Verdict

Clean. This is a proportionate, high-quality comment/doc/yaml/markdown reconciliation with **zero
new runtime logic** and **zero actionable issues**. Every comment that was rewritten now matches the
shipped behavior it sits next to (verified against `egress-firewall.sh`, `server.py`, the launcher
subcommand dispatch, and the README install flow); both edited bash files pass `bash -n`; both edited
yaml files parse; the frontmatter edits are pure structural additions with prose preserved; and the
CONTEXT scope guardrails held exactly — the `[INFERENCE]` markers (D-06) and the assemble.py
replacement comment (D-07) were both left untouched, while `$net` was retained with the D-04
clarifying comment it called for. The phase is safe to merge as-is. This review is advisory and does
not block the load-bearing goal-achievement verification.
