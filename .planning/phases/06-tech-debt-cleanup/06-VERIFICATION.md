---
status: gaps_found
phase: 06-tech-debt-cleanup
verified_at: 2026-06-21
verifier: omp-task-proxy
requirements_verified: [SC-1, SC-2, SC-3]
---

# Phase 06 Goal-Achievement Verification

> **Scope of this gate:** goal-achievement (did Phase 06 meet its *goal*), not task-completion (were
> the plan tasks run). All evidence is read against **committed blobs** (`git show HEAD:<path>` /
> `git grep ... HEAD` / the commit range `27ac680..HEAD`), NOT the dirty working tree, which carries
> pre-existing uncommitted multi-harness WIP (`.agents/` deletions, opencode/gemini/codex additions)
> that is NOT part of Phase 06.

## Goal

Per CONTEXT **D-01** (which reversed the stale ROADMAP "remove dead harnessed-net code" framing):
reconcile shipped reality with design/code/docs so that **publish-to-`0.0.0.0` + the podman host
gateway `host.containers.internal:<port>` is recorded as the PRIMARY reachability model**, the rootless
`harnessed-net` bridge is documented as the `HARNESSED_NET` opt-in for bridge-capable hosts, and the
`*-SUMMARY.md` frontmatter is normalized. Two concerns: (1) harnessed-net docs/comments
reconciliation [SC-1, SC-2], (2) SUMMARY frontmatter hygiene [SC-3].

---

## Success Criteria Verification

### SC-1 — repo-wide `harnessed-net` search returns only LIVE / opt-in / now-accurate refs — **FAIL (gaps)**

**Exact command run (committed HEAD):**

```
git grep -n 'harnessed-net' HEAD --  | grep -vE 'HEAD:\.planning/|HEAD:\.claude/'
```

The committed code unambiguously establishes the shipped model, which is the bar for "accurate":

- `lib/harnessed-services.sh` `svc_up` body — `"$CONTAINER_RUNTIME" run -d -p "$port:$port" ...` with **NO `--network` flag** (committed :120-127): the shared-service container publishes its port to `0.0.0.0`; it is **not** attached to `harnessed-net`.
- `lib/harnessed-isolated.sh` pod create (committed :125-135) — `pod_net_args=( --network "$HARNESSED_NET" )` is applied **only** `if [ -n "${HARNESSED_NET:-}" ]`: the pod is on rootless (pasta) networking **by default**; `harnessed-net` is the opt-in.
- `tools/harnessed/assemble.py:67` — the service URL is rewritten to `http://host.containers.internal:{port}/mcp` (the host-gateway form), NOT `http://<name>:<port>/mcp`.

Against that bar, the repo-wide grep returns **stale bridge-as-default assertions** in files that were
**not** in plan 06-01's `files_modified` list and were **not** audited by `06-RESEARCH.md` Item B:

**HIGH confidence (assert the bridge as the service's network AND, in most cases, the old DNS-name URL
`http://<name>:<port>/mcp` — the exact pattern B1+B4 corrected in the scoped files):**

| Committed ref | Stale assertion | Why stale |
|---|---|---|
| `docs/codebase/INTEGRATIONS.md:100` | "the service runs as its **own** container on `harnessed-net`" (+ :103 asserts resolved URL `http://ping:8080/mcp`) | svc_up has no `--network`; the resolved URL is `host.containers.internal:8080`. Identical to B1/B4. |
| `docs/codebase/INTEGRATIONS.md:112-113` | "A shared service is its **own image/container/volume** on `harnessed-net`" | Verbatim of B1's pre-correction wording; corrected in `lib/harnessed-services.sh:4` but left here. |
| `docs/codebase/INTEGRATIONS.md:270` | ASCII diagram: "HTTP proxies ──▶ shared services on `harnessed-net`" | Asserts the bridge as the transport. |
| `services/ping/server.py:6-7` | "The service runs standalone on harnessed-net; hatago proxies it as a network-native MCP server ({url: http://ping:8080/mcp, type: http})" | Asserts bridge + old DNS-name URL. **Internal inconsistency:** the *same file* at `:19-25` is the accurate host-gateway + `allowed_hosts` impl that design.md §9 cites as canonical. |
| `tools/harnessed/schema.py:128-131` | "A service is its OWN image/container/volume on `harnessed-net` ... the assembler resolves the service name → `http://<name>:<port>/mcp`" | Asserts bridge + old DNS-name URL. Identical to B1+B4. |
| `CLAUDE.md:153` | "podman **pod** `harnessed-<stack>-<projhash>` on `harnessed-net`" | The pod is on pasta by default; `harnessed-net` is opt-in. |

**MEDIUM confidence (transport phrasing "over/on harnessed-net" without the URL):**

| Committed ref | Stale assertion |
|---|---|
| `docs/codebase/INTEGRATIONS.md:110` | Heading "## Shared Services (sidecars over harnessed-net)" |
| `stacks/ping-time/stack.yaml:5` | "server proxied by hatago over harnessed-net" |
| `harnessed:51` | CLI help "Start a shared service sidecar on harnessed-net (own image + volume)" |
| `harnessed:253` | Comment "manages shared service sidecars on harnessed-net" |

**Acceptable (LIVE / opt-in / now-accurate) references — confirmed clean:** `lib/harnessed-services.sh:27,29` (`ensure_harnessed_net`/`ensure_named_net harnessed-net`, D-03 opt-in), `lib/harnessed-isolated.sh:68` (`$net` variable, D-04 anchor), `docs/harnessed-design.md:244` (now in accurate opt-in context), `tools/harnessed/assemble.py:66` (D-07 replacement-doc), and the ping service/stack manifests' *code* bodies.

**Verdict:** SC-1 is **NOT met** at the repo-wide level. The HIGH-confidence cases alone — `server.py:6-7`, `schema.py:128-131`, `INTEGRATIONS.md:100/112/270` — assert both the bridge and the old `http://<name>:<port>/mcp` URL, which is the precise pattern B1+B4 corrected and which **D-05 explicitly brings into scope** ("**any** code comment still asserting DNS-by-service-name over the bridge"). The phase's own logic is internally inconsistent: it corrected "own image/container/volume on `harnessed-net`" in `lib/harnessed-services.sh:4` (B1) and `services/ping/service.yaml:3` (B3) but left the identical wording in `schema.py:128` and `INTEGRATIONS.md:112`. **Root cause:** `06-RESEARCH.md` Item B audited only 6 files (B1–B7); the audit grep was under-inclusive and did not surface `CLAUDE.md`, `docs/codebase/INTEGRATIONS.md`, the `harnessed` CLI, `services/ping/server.py`, `tools/harnessed/schema.py`, or `stacks/ping-time/stack.yaml`. The **executor did exactly what the plan said, correctly** — the gap is an audit/planning under-inclusion that propagated to `files_modified`, not an execution error.

### SC-2 — design §3/§9/§13 + the scoped stale comments (B1–B7) reconciled — **PASS**

Commands run (committed blobs):

```
git show HEAD:docs/harnessed-design.md | grep -nc 'host.containers.internal'   → 8   (≥4)
git show HEAD:docs/harnessed-design.md | grep -n '169\.254\.1\.2'              → :257 (operator-prereq firewall)
git show HEAD:docs/harnessed-design.md | grep -n 'allowed_hosts'              → :261-262 (operator-prereq FastMCP)
git show HEAD:docs/harnessed-design.md | grep -nc 'HARNESSED_NET'             → 4
for f in lib/harnessed-services.sh lib/harnessed-isolated.sh services/ping/service.yaml recipes/ping/recipe.yaml systemd/harnessed-rescan.service; do
  git show HEAD:$f | grep -c 'on harnessed-net'                                 → 0 (each)
done
```

- `docs/harnessed-design.md` §3 diagram edge (`:54`) → `MCP over host.containers.internal (HARNESSED_NET: opt-in)`; the harness↔hatago `MCP hub · HTTP` (shared-netns) edge left intact.
- §9 (`:240-246`) → lifecycle/ownership prose preserved; reachability clause rewritten to "**publishes its port to `0.0.0.0`** ... `host.containers.internal:<port>` **(the primary reachability model)**; the `harnessed-net` bridge + DNS-by-name is the **`HARNESSED_NET` opt-in**". PRIMARY framing is unambiguous.
- §9 operator-prereq callout (`:251-265`) → documents BOTH the egress-firewall allow rule (`169.254.1.2`, `lib/egress-firewall.sh:55-63`) AND the FastMCP `allowed_hosts` requirement (`services/ping/server.py:19-25`, commit `6f6c1b3`). **D-02 fully honored.**
- §13 CLI (`:396`) and §13 Naming/identity (`:406`) → reconciled to the host-gateway-as-primary + `HARNESSED_NET` opt-in framing.
- B1–B7 corrected in all scoped files; `recipe.yaml` B4 correctly records `http://host.containers.internal:8080/mcp` as the resolved URL with `http://ping:8080/mcp` labeled as the `HARNESSED_NET` opt-in form (executor followed the authoritative `<action>` over a conflicting `<verify>` criterion — correct call). `bash -n` passes on both `lib/*.sh`; both YAML manifests parse.

### SC-3 — every `0*-SUMMARY.md` under `0[1-5]-*/` carries consistent frontmatter — **PASS**

Command run (committed HEAD):

```
for f in $(git ls-files '.planning/phases/0[1-5]-*/0*-SUMMARY.md'); do
  git show HEAD:$f | head -1 ; ... grep -c '^# Dependency graph$' ; ... '^requires:'/'^provides:'/'^affects:'/'^phase:'
done
```

All **16** SUMMARYs: `head -1 == ---`, `# Dependency graph == 1`, `requires/provides/affects/phase == 1` each. Phase 01 backfill = **144 insertions, 0 deletions** (pure insertions; prose body preserved). Phase 04 = **3 insertions, 0 deletions**, with `# Dependency graph` immediately before `requires:` in `04-02`/`04-03`/`04-04` (verified via `grep -n -A1`). `04-01` and STATE.md untouched.

---

## CONTEXT Decision Compliance

| Decision | Status | Evidence |
|---|---|---|
| **D-01** harnessed-net is NOT dead; reconcile docs to shipped reality | **honored (scoped)** / incomplete repo-wide | Scoped files fully reconciled; SC-1 gaps show reconciliation is not yet repo-wide. |
| **D-02** design §9/§13 reconciliation + operator-prereq docs | **honored** | §9 primary-model rewrite + `169.254.1.2` firewall + `allowed_hosts` callout present (committed :251-265). |
| **D-03** KEEP `HARNESSED_NET` opt-in / `ensure_harnessed_net` / `ensure_named_net` / `:-harnessed-net` default | **honored** | `services.sh:27-30`, `isolated.sh:68,126-128` intact in committed blobs. |
| **D-04** leave `$net` + clarifying comment; do NOT reverse the pivot | **honored** | `isolated.sh:65-68` preserves the line with a comment citing D-01/D-03/D-04; live block `:126-128` still gated on `${HARNESSED_NET:-}`; `$net` not wired into the launcher. |
| **D-05** scope = comments/docs contradicting shipped behavior, incl. "any code comment still asserting DNS-by-name over the bridge" | **partially honored (GAP)** | Scoped B1–B7 corrected; but D-05's literal "**any** code comment" scope was **under-implemented** — `server.py:6-7`, `schema.py:128-131`, `INTEGRATIONS.md:100/103/112/270`, `CLAUDE.md:153` assert the bridge (and the old DNS-name URL) and were missed by the audit. |
| **D-06** EXCLUDE OPEN `[INFERENCE]` markers | **honored** | Both markers intact at `design.md:427` and `:453` in committed blob; no marker edited across the range. |
| **D-07** KEEP replacement-documenting comments | **honored** | `assemble.py:63-67`, `services.sh:98-105`, `isolated.sh:119-126` intact; `service-authoring.md:163-166` untouched. |
| **D-08** backfill the three Phase 01 SUMMARYs | **honored** | `01-01/01-02/01-03` carry full schema; prose byte-identical (pure insertions). |
| **D-09** insert missing `# Dependency graph` header in Phase 04 SUMMARYs | **honored** | Header now immediately before `requires:` in `04-02/04-03/04-04`; 1 insertion each, 0 deletions. |
| **D-10** STATE.md OUT of scope | **honored** | `git diff --name-only 6be538d~1 885ecdb \| grep -c STATE.md` == 0. |

---

## Static Gates

| Gate | Command (committed blob) | Result |
|---|---|---|
| `bash -n lib/harnessed-isolated.sh` | `git show HEAD:lib/harnessed-isolated.sh \| bash -n` | **PASS** (parses clean) |
| `bash -n lib/harnessed-services.sh` | `git show HEAD:lib/harnessed-services.sh \| bash -n` | **PASS** (parses clean) |
| YAML parse `services/ping/service.yaml` | `git show HEAD:services/ping/service.yaml` → `yaml.safe_load` | **PASS** |
| YAML parse `recipes/ping/recipe.yaml` | `git show HEAD:recipes/ping/recipe.yaml` → `yaml.safe_load` | **PASS** |
| Frontmatter structure (16 SUMMARYs) | `head -1` + `# Dependency graph`/`requires:`/`provides:`/`affects:`/`phase:` counts | **PASS** (all 16 = `---` open; each block count == 1) |
| `[INFERENCE]` markers untouched | `git show HEAD:docs/harnessed-design.md \| grep -n '\[INFERENCE'` | **PASS** (:427, :453 intact) |

---

## Deferred to /gsd-verify-work

Live legs gated on rootless podman + a clean working tree (per CONTEXT D-11/D-12 and the executors'
deferral notes). Static checks are the load-bearing verification for this comment/doc/yaml/markdown
phase; these do **not** block the static goal verdict above.

- **status: deferred** — `harnessed test ping-time` (asserts the `ping` MCP connects over `host.containers.internal` — SC-1 live regression gate). Rootless `podman.socket` is inactive on the verification host.
- **status: deferred** — `harnessed test tracer-time` (asserts the isolated pod boots + the `time` MCP connects). Same podman-socket constraint.
- **status: deferred** — `bash tools/uat/run-uat.sh` (the UAT suite — D-12 no-behavior-change gate). Same constraint; additionally the working tree carries uncommitted multi-harness WIP in the files under test, so a live run would not isolate this phase's comment-only edits.

Re-run all three before `/gsd-verify-work` once the tree is committable and rootless podman is available.

---

## Verdict

**status: `gaps_found`**

- **SC-2: PASS** — the scoped design-doc reconciliation (§3/§9/§13 + the §9 operator-prereq callout)
  and the B1–B7 stale-comment sweep were executed correctly and completely; D-01..D-04, D-06, D-07
  honored for the scoped surface; `bash -n` + YAML gates green.
- **SC-3: PASS** — all 16 `0*-SUMMARY.md` open with `---` and carry a `# Dependency graph` block;
  Phase 01 backfill + Phase 04 header are pure insertions; D-08/D-09/D-10 honored.
- **SC-1: FAIL (gaps)** — the **repo-wide** grep still returns stale bridge-as-default assertions in
  un-audited files: `docs/codebase/INTEGRATIONS.md:100/103/112/270`, `services/ping/server.py:6-7`,
  `tools/harnessed/schema.py:128-131`, `CLAUDE.md:153` (HIGH), plus `INTEGRATIONS.md:110`,
  `stacks/ping-time/stack.yaml:5`, `harnessed:51/253` (MEDIUM). The HIGH cases assert both the bridge
  and the old `http://<name>:<port>/mcp` URL — the exact B1+B4 pattern D-05 explicitly brings into
  scope. This is a scope-completeness gap rooted in an under-inclusive audit (`06-RESEARCH.md` Item B),
  not an execution defect: the executor correctly and completely did what plan 06-01 specified.

**Remediation (mechanical, ~5–6 files):** extend the B1+B4 correction to `schema.py:128-131`,
`server.py:6-7`, `INTEGRATIONS.md` (§"HTTP service sidecars" + "Shared Services" + the §"Summary"
diagram), and `CLAUDE.md:153`; optionally the MEDIUM phrasing in `stack.yaml:5` and the `harnessed`
CLI `:51/:253`. Each is a comment/doc-only edit (zero runtime risk per D-12) that mirrors wording
already shipped in the reconciled `lib/harnessed-services.sh:4-6` and `recipes/ping/recipe.yaml:4-6`.

**Severity:** low runtime risk (comments/docs only) but a real completeness miss against the stated
SC-1 "repo-wide" criterion. The phase's central deliverable — reconciling the design source of truth
(`docs/harnessed-design.md`) — is done well; the residue is the same debt class in adjacent docs/code
the audit did not reach.
