# Phase 6: Tech-debt cleanup (harnessed-net reconciliation + stale comments + SUMMARY frontmatter) - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 17 (4 design-doc locations + 5 comment-only code/manifests + 6 SUMMARY files + 2 referenced-not-changed)
**Analogs found:** 17 / 17 (every target has a concrete in-repo analog — this is a reconcile-to-existing-patterns phase, not a new-pattern phase)

> **Phase character.** This is a behavior-preserving cleanup phase. "Patterns" here are **existing
> in-repo conventions to replicate verbatim**, not new abstractions to invent. The three highest-value
> analogs, in priority order: (1) the **SUMMARY backfill template** (§SUMMARY frontmatter below),
> (2) the **doc-reconciliation prose** already shipped in `docs/guides/service-authoring.md:163-166`
> + the replacement-doc comments, (3) the **bash comment house style** in `lib/harnessed-*.sh`.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| **Item A — design doc reconciliation** | | | | |
| `docs/harnessed-design.md` §3 (diag edge) | doc | n/a (prose) | `docs/guides/service-authoring.md:163-166` + `lib/harnessed-isolated.sh:121-126` | exact (in-repo accurate framing) |
| `docs/harnessed-design.md` §9 (shared-svc model) | doc | n/a (prose) | `docs/guides/service-authoring.md:163-166` + `lib/harnessed-services.sh:98-102` | exact |
| `docs/harnessed-design.md` §13 (CLI comment + Naming) | doc | n/a (prose) | `tools/harnessed/assemble.py:63-67` replacement-doc comment | exact |
| `lib/harnessed-isolated.sh:70` (`$net` var) | utility (bash) | n/a (comment-only) | `lib/harnessed-services.sh:25-28` (`ensure_harnessed_net` clarifying-comment style) | exact |
| **Item A — referenced, NOT changed (operator-prereq source for §9 callout)** | | | | |
| `lib/egress-firewall.sh:55-63` | utility (bash) | n/a (doc source only) | — (read-only source the §9 callout cites) | n/a |
| `services/ping/server.py:19-25` | service (python) | request-response | — (read-only source the §9 callout cites) | n/a |
| **Item B — stale-comment sweep** | | | | |
| `lib/harnessed-services.sh:4` + `:63-67` | utility (bash) | n/a (comment-only) | replacement-doc style at `lib/harnessed-services.sh:98-102` | exact |
| `lib/harnessed-isolated.sh:23-26` | utility (bash) | n/a (comment-only) | replacement-doc style at `lib/harnessed-isolated.sh:121-126` | exact |
| `services/ping/service.yaml:3` | config (yaml) | n/a (comment-only) | accurate `service.yaml` body lines `:7-11` (unchanged) | exact |
| `recipes/ping/recipe.yaml:4`, `:6` | config (yaml) | n/a (comment-only) | `docs/guides/service-authoring.md:163-166` | exact |
| `systemd/harnessed-rescan.service:4` (adjacency) | config (unit) | n/a (comment-only) | — (single-word substitution; no analog needed) | n/a |
| **Item C — SUMMARY frontmatter backfill** | | | | |
| `01-01` / `01-02` / `01-03-SUMMARY.md` (D-08) | doc (frontmatter) | n/a | `.planning/phases/02-isolated-tracer-bullet-stack/02-01-SUMMARY.md:1-63` | **exact (canonical template)** |
| `04-02` / `04-03` / `04-04-SUMMARY.md` (D-09) | doc (frontmatter) | n/a | `02-01-SUMMARY.md:7` (`# Dependency graph` header line) | **exact (one-line insert)** |

---

## Shared Patterns (the three analogs the executor copy-adapts from)

### Shared Pattern 1 — SUMMARY frontmatter + `# Dependency graph` block (D-08 / D-09)

**Canonical source:** `.planning/phases/02-isolated-tracer-bullet-stack/02-01-SUMMARY.md` (the de-facto 02–05 schema, all fields populated). **Copy-adapt verbatim** — do not invent a new shape (RESEARCH "Don't Hand-Roll" row 1).

**Verbatim YAML frontmatter block (template — populate per-plan):**

```yaml
---
phase: 01-containerized-engine-transparent-stack      # ← substitute per Phase-01 plan
plan: 01                                              # ← 01 / 02 / 03
subsystem: infra                                      # ← Phase 01 plans are all infra (bootstrap/images/transparent)
tags: [podman, bash, base-image, claude-code, lineage] # ← substitute per-plan content

# Dependency graph
requires:
  - phase: <prior-phase-or-"(none)">                  # ← Phase 01 plans require nothing external (greenfield); use "(none)" or omit
    provides: <comma-list of upstream artifacts>
provides:
  - <bullet list of what THIS plan delivered>
affects: [01-02-..., 01-03-...]                        # ← the downstream plan ids this plan unblocks

# Tech tracking
tech-stack:
  added: [<pinned versions>]
  patterns: [<established patterns>]

key-files:
  created: [<paths>]
  modified: [<paths>]

key-decisions:
  - "<one-line-per-decision, quoted>"

patterns-established:
  - "<one-line-per-pattern, quoted>"

requirements-completed: [ENG-01, ENG-02, ...]         # ← from REQUIREMENTS.md IDs

# Metrics
duration: <~Nmin>
completed: 2026-06-14                                  # ← the plan's actual completion date (already in the prose)
---
```

**Verbatim `# Dependency graph` block from `02-01-SUMMARY.md:7-18`** (the exact shape — 1 header line + `requires:`/`provides:`/`affects:`):

```yaml

# Dependency graph
requires:
  - phase: 01-foundation
    provides: harnessed dispatcher, lib/harnessed-common.sh (build_images/ensure_images/lifecycle), base/Dockerfile.harnessed-{base,claude}, stacks/transparent/stack.yaml
provides:
  - Recipe schema (recipes/<name>/recipe.yaml) + stack manifest schema (stacks/<name>/stack.yaml)
  - tracer-time stack instance (claude + time recipe) and the time recipe (uvx mcp-server-time stdio + time-helper skill)
  - harnessed-tools emit-only Python assembler image (schema/synclinks/assemble/emit/cli) with fail-fast collision reporting
  - Committed profiles/tracer-time/ (.claude/skills/time-helper + .mcp.json → hatago endpoint + hatago.config.json + baked-servers.json)
  - base/Dockerfile.hatago (hatago hub + baked uvx mcp-server-time)
  - harnessed build <stack> subcommand (emit-only assemble → host podman build) + HARNESSED_HATAGO_IMAGE/HARNESSED_TOOLS_IMAGE
affects: [02-02-isolated-launcher, 02-03-capability-test]
```

**The D-09 gap is exactly one missing comment line.** Comparing `02-01-SUMMARY.md:5-8` (correct) vs `04-02-SUMMARY.md:5-7` (gap):

```yaml
# 02-01 (CORRECT — has the header):              # 04-02 (GAP — header missing):
tags: [podman, hatago, mcp, ...]                  tags: [state-persistence, cli, ...]
                                                   (blank line)
# Dependency graph          ← PRESENT             (blank line — then jumps straight to:)
requires:                                         requires:      ← header "# Dependency graph" MISSING
```

**D-09 fix = insert the single line `# Dependency graph` immediately before each `requires:` in `04-02`/`04-03`/`04-04-SUMMARY.md`.** Preserve all existing frontmatter content verbatim (D-09: "add only the missing structural pieces, do not rewrite history").

> **Observation for the planner (in-scope per D-09, NOT scope creep):** the same three 04-* files *also* drop the `# Tech tracking` comment before `tech-stack:` (e.g. `04-02-SUMMARY.md:15-16` goes `affects:` → blank → `tech-stack:` with no header, vs `02-01-SUMMARY.md:19-21` which has `# Tech tracking`). D-09 names only `# Dependency graph`. The planner decides whether to normalize `# Tech tracking` in the same touch (it is the identical one-line-comment class of edit and keeps the 04-* files structurally identical to 02-*/03-*); if conservative, do only `# Dependency graph` as D-09 literally specifies.

---

### Shared Pattern 2 — Doc-reconciliation prose (Item A design §3/§9/§13)

**Canonical accurate framing already shipped in-repo — mirror it, do not author fresh networking prose** (RESEARCH "Don't Hand-Roll" row 2). Two sources, both `[VERIFIED]`:

**(a) User-facing guide** — `docs/guides/service-authoring.md:163-166` (the exact paragraph to mirror in design §9):

> **Networking note:** by default isolated stacks use rootless (pasta) networking, so pod members reach
> a shared service via the host gateway `host.containers.internal:<port>`. That is why `server.py`
> adds `host.containers.internal` to FastMCP's allowed hosts. On hosts that support rootless bridges,
> set `HARNESSED_NET=<name>` and members resolve the service by DNS name instead (`http://<name>:<port>`).

**(b) Replacement-doc code comment** — `tools/harnessed/assemble.py:63-67` (D-07 canonical example — the prose pattern design §13's CLI comment should adopt):

```python
            # Rootless model (plan 04-01 fix): no bridge — services publish to 0.0.0.0 and peers
            # reach them via the podman host gateway `host.containers.internal`. A rootless bridge
            # is unsupported on most hosts (netavark "Operation not supported"), so DNS-by-service-
            # name over harnessed-net was replaced with the host-gateway address.
            server.url = f"http://host.containers.internal:{svc.port}/mcp"
```

**The vocabulary to reuse verbatim** (these phrases already appear in shipped code/docs — use them, don't paraphrase):
- "publish to `0.0.0.0`" / "publishes its port to `0.0.0.0`"
- "podman host gateway `host.containers.internal:<port>`"
- "rootless bridge is unsupported on most hosts (netavark 'Operation not supported')"
- "`HARNESSED_NET=<name>` opt-in for bridge-capable hosts" / "DNS-by-service-name … opt-in"
- "`host.containers.internal` (`169.254.1.2`)" — the literal address from `lib/egress-firewall.sh:62`

**Operator-prereq callout (D-02) — the two deps to document in §9, with their already-shipped code citations:**
1. **Egress-firewall dependency.** Source: `lib/egress-firewall.sh:55-63` (verbatim comment below) — `PODMAN_GW=$(getent ahosts host.containers.internal …)` + the allow rule. Without it the proxy path is blocked.
   ```bash
   # Allow access to the host gateway (for connecting to local services on the host). Rootless podman
   # has TWO relevant gateways: the default-route gateway (HOST_GW) and the podman host-gateway
   # `host.containers.internal` — the address shared service sidecars publish their ports to (plan
   # 04-01). iptables is netns-wide, so allowing this unblocks the whole pod, including the hatago
   # MCP proxy that reaches host-published services.
   ```
2. **FastMCP `allowed_hosts` requirement.** Source: `services/ping/server.py:19-25` (verbatim below) — a Streamable-HTTP service proxied over `host.containers.internal` MUST add it to `TransportSecuritySettings.allowed_hosts` or FastMCP's DNS-rebinding protection returns `421 Misdirected Request`. Commit `6f6c1b3`.
   ```python
   # The service is proxied by hatago over the podman host-gateway `host.containers.internal`
   # (plan 04-01 rootless model). FastMCP's DNS-rebinding protection rejects that Host header by
   # default (421 Misdirected Request), so allow it alongside the localhost defaults.
   mcp.settings.transport_security = TransportSecuritySettings(
       enable_dns_rebinding_protection=True,
       allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "host.containers.internal:*"],
   )
   ```

---

### Shared Pattern 3 — Bash / YAML comment house style (Item B stale-comment rewrites)

**Canonical style sources:** `lib/harnessed-services.sh:1-15` (file header) + `:17-28` (function doc-comments) + the replacement-doc comments at `:98-102`. House rules observed:

1. **File-header block** — `#!/usr/bin/env bash` shebang, then a `# <libname> — <one-line role> (plan XX-YY / REQ-NN).` summary line, then a blank `#` line, then 2–5 short `#` paragraphs explaining responsibility/persistence/host-native-ness, closing with an `# Expects <ENVARS>` line (see `harnessed-services.sh:1-15`).
2. **Function doc-comment** — single `#` line summary ending in `.`, then a blank `#`, then optional `#` detail lines (see `ensure_named_net` at `:17-18`, `svc_up` at `:63-67`).
3. **Stale-vs-signal test (D-07):** a comment asserting the bridge model as *current* = STALE (rewrite). A comment documenting a *replacement* ("X was replaced with Y because Z") = SIGNAL (keep/clarify). The replacement-doc comments at `assemble.py:63-67`, `harnessed-services.sh:98-102`, `harnessed-isolated.sh:121-126` are the SIGNAL template — Item B rewrites should converge stale comments *toward* this replacement-doc form, not delete context.

**Replacement-doc SIGNAL template (the target form for rewritten Item B comments):**
```bash
# Rootless service model (plan 04-01 fix): publish the port to 0.0.0.0 — NO bridge. Peers reach
# the service via the podman host gateway host.containers.internal:<port>. The HARNESSED_NET
# bridge is an opt-in for bridge-capable hosts (inert here: netavark "Operation not supported").
```

**YAML-manifest comment style** (`services/ping/service.yaml:1-6`, `recipes/ping/recipe.yaml:1-6`): top-of-file `# <kind>: <name> — <one-line role> (plan / REQ).` then blank `#` then 2–4 `#` detail lines, then the first YAML key. Item B rewrites the *content* of these comment blocks to the publish+host-gateway model; the *shape* (header `#` summary + detail `#`s) stays.

---

## Pattern Assignments (per-file concrete edits)

### Item A — `docs/harnessed-design.md` (4 locations)

> **LINE-NUMBER DRIFT ALERT.** CONTEXT/RESEARCH cite §9:245-247, §13:381, §13:390. The **actual**
> stale text in the current file is at the snapshot-anchored lines below (the file has shifted by
> ~6 lines since those docs were written). **The executor MUST re-`read` each range before editing**
> and anchor on the snapshot tag, not the CONTEXT line number.

| Location (actual, snapshot-anchored) | Current stale text | Analog to mirror | Required direction |
|---|---|---|---|
| `docs/harnessed-design.md:54` (§3 ASCII edge label) | `MCP over harnessed-net` (the diagram edge from pod-box to shared-service boxes) | `docs/guides/service-authoring.md:163-166` | Reconcile the edge label: harness↔shared-service reachability is `host.containers.internal:<port>` (primary); note `HARNESSED_NET` bridge as opt-in. The harness↔hatago edge (line 52, `MCP hub · HTTP`) is the shared-pod **netns** (`localhost`) — leave that one. |
| `docs/harnessed-design.md:251-253` (§9 "Shared instance, concurrent.") | "One long-lived `hindsight` container on `harnessed-net`, owned by the *service* not any instance; postgres serves both instances at once. An instance starts it if absent; it outlives instances (`harnessed svc up/down`)." | `docs/guides/service-authoring.md:163-166` + `lib/harnessed-services.sh:98-102` | KEEP the lifecycle/ownership prose (service-scoped, outlives instances — still true). REWRITE the reachability clause: the service publishes its port to `0.0.0.0`; peers reach it via `host.containers.internal:<port>` (primary); the `harnessed-net` bridge + DNS-by-name is the `HARNESSED_NET` opt-in for bridge-capable hosts. |
| `docs/harnessed-design.md:387` (§13 CLI surface) | `harnessed svc up <service>    # start a shared service on harnessed-net` | `tools/harnessed/assemble.py:63-67` | Rewrite the inline comment to: `# start a shared service (publishes its port; peers reach it via host.containers.internal, or by DNS name under HARNESSED_NET)`. |
| `docs/harnessed-design.md:396` (§13 Naming/identity) | `shared services: global by name (\`hindsight\`), on \`harnessed-net\`.` | `docs/guides/service-authoring.md:163-166` | Rewrite to: `shared services: global by name (\`hindsight\`), reached via the host gateway \`host.containers.internal:<port>\` (or by DNS name over the \`HARNESSED_NET\` bridge on bridge-capable hosts).` |

**§9 operator-prereq callout (D-02):** add a new subsection/callout immediately after the §9 lifecycle bullets (after line 255) covering (1) the `host.containers.internal`/`169.254.1.2` egress-firewall dep [citing `lib/egress-firewall.sh:55-63`] and (2) the FastMCP `allowed_hosts` dep [citing `services/ping/server.py:19-25`, commit `6f6c1b3`]. Use the verbatim code excerpts in **Shared Pattern 2** above.

**Out of scope (D-06 — DO NOT TOUCH):** the `[INFERENCE — verify]` markers at `docs/harnessed-design.md:412` and `:440`.

### Item A — `lib/harnessed-isolated.sh:70` (the genuinely-dead `$net` var)

**Disposition (D-04): LEAVE the line, add a clarifying comment.** The variable is assigned-but-never-read (the live networking block at `:127-131` reads `${HARNESSED_NET:-}` directly, not `$net`), but D-01/D-03 anchor their narrative on this exact expression as proof the default name is `harnessed-net`, and D-04's rule is "if unsure, leave it and add a clarifying comment."

**Analog style:** the `ensure_harnessed_net` clarifying comment at `lib/harnessed-services.sh:25` ("Ensure the default shared bridge exists (harnessed-net). Idempotent."). Insert a one-line comment above `:70`:

```bash
    # Preserved as the literal default-name anchor (D-01/D-03); the live networking block at :127-131
    # reads ${HARNESSED_NET:-} directly, so $net is assigned-but-unused on this path. KEPT per D-04.
    local net="${HARNESSED_NET:-harnessed-net}"
```

### Item A — `lib/egress-firewall.sh:55-63` + `services/ping/server.py:19-25` (REFERENCED, not changed)

These are the **source citations** for the §9 operator-prereq callout above. Their verbatim content is in **Shared Pattern 2**. No edit — the executor reads them to quote/cite.

### Item B — stale-comment rewrites (6 statements + 1 adjacency)

For each, rewrite the *content* toward the **Shared Pattern 3 replacement-doc SIGNAL form**; preserve the comment *shape*.

| Location | Current stale text (snapshot-anchored) | Required rewrite direction |
|---|---|---|
| `lib/harnessed-services.sh:4` | "A shared service is its OWN image/container/volume on harnessed-net, with a lifecycle independent of any instance" | "…on a host-published port (reachable via `host.containers.internal:<port>`; or by DNS name over the `HARNESSED_NET` bridge on bridge-capable hosts), with a lifecycle independent of any instance" |
| `lib/harnessed-services.sh:63-67` (`svc_up` doc-comment) | "…runs -d on harnessed-net with --label harnessed-service=<name> + --userns=keep-id, then waits for the healthcheck." | Rewrite to reflect the shipped publish-to-`0.0.0.0` model (no `--network` flag) — see `lib/harnessed-services.sh:98-102` / `:117-124` for the actual `svc_up` body. Mirror `assemble.py:63-67`. |
| `lib/harnessed-isolated.sh:23-26` (pod-network comment) | "Pod network: harnessed-net is the DEFAULT for isolated stacks (plan 04-01 / SVC-02) so pod members resolve shared services by DNS name (http://<service>:<port>). Set HARNESSED_NET=<name> to override the network name (advanced/multi-network)." | Rewrite to: DEFAULT is rootless (pasta) — members reach shared services via `host.containers.internal:<port>`; the `HARNESSED_NET` bridge is the opt-in for bridge-capable hosts (DNS-by-name). Members share a netns either way → harness always reaches hatago at `localhost:$HATAGO_PORT`. (Note: line `:27` `HARNESSED_NET="${HARNESSED_NET:-}"` and the live block `:127-131` are CORRECT — only the comment is stale.) |
| `services/ping/service.yaml:3-4` | "The smallest shared-service sidecar: its own image/container/volume on harnessed-net, exposing one `ping` tool over MCP streamable-http." | Rewrite "on harnessed-net" → "host-published (reachable via `host.containers.internal:8080`; or by DNS name over the `HARNESSED_NET` bridge on bridge-capable hosts)". |
| `recipes/ping/recipe.yaml:4` + `:6` | ":4 …resolves `service: ping` → {url: http://ping:8080/mcp, type: http}…  :6 …the service runs as its own container on harnessed-net (design §3/§9)." | Rewrite the URL `http://ping:8080/mcp` → `http://host.containers.internal:8080/mcp` (the actual shipped rewrite from `assemble.py:67`); rewrite "on harnessed-net" → host-published + `HARNESSED_NET` opt-in. |
| `systemd/harnessed-rescan.service:4` (adjacency) | "Assumes the `harnessed` launcher is installed at ~/.local/bin/harnessed (`harnessed install` shim, Phase 4) or on PATH." | This is an *adjacency* (correct as-is — `harnessed install` is Phase 4). **No edit required** unless the planner finds an actual stale reference; RESEARCH lists it as adjacency-only. |

**Item B EXCLUDES (D-06/D-07 — DO NOT TOUCH):** the replacement-doc SIGNAL comments at `tools/harnessed/assemble.py:63-67`, `lib/harnessed-services.sh:98-102`, `lib/harnessed-isolated.sh:121-126` — these are correct (D-07). Also excludes the OPEN `[INFERENCE]` markers (M2/H3 deferred).

### Item C — SUMMARY backfill (D-08) + normalize (D-09)

**D-08 — Phase 01 SUMMARYs (backfill full frontmatter):**

| File | Current state | Action |
|---|---|---|
| `.planning/phases/01-containerized-engine-transparent-stack/01-01-SUMMARY.md` | Opens with `# Plan 01-01 Summary: …` H1; only `**Completed:**` / `**Requirements:**` prose lines (lines 1-4) | Prepend the full YAML frontmatter block from **Shared Pattern 1** (populate `phase: 01-containerized-engine-transparent-stack`, `plan: 01`, `subsystem: infra`, plan-specific `tags`, a `# Dependency graph` block, etc.). Mine the existing prose body (`## What was built`, `## Key decisions honored`, `## Files`, `## Commits`) to populate `provides:`/`key-files`/`key-decisions`/`requirements-completed`. **Preserve the existing prose body verbatim** — only prepend frontmatter + the `# Dependency graph` block. |
| `01-02-SUMMARY.md` | (same prose-only form — RESEARCH confirmed all 3 lack frontmatter) | Same backfill; populate `requires:` from 01-01's `provides:` (01-02 is the transparent launcher, depends on 01-01's bootstrap). |
| `01-03-SUMMARY.md` | (same) | Same backfill; `requires:` from 01-01/01-02 (01-03 is the capability test / transparent stack, per the dir name). |

**Phase 01 reference content** (already in `01-01-SUMMARY.md` prose — use for the `requires`/`provides`/`requirements-completed` fields):
- `requirements-completed: [ENG-01, ENG-02]` (from line 4 `**Requirements:** ENG-01, ENG-02`)
- `completed: 2026-06-14` (from line 3)
- Commits `1e52029`, `009c781` (lines 31-32)
- `requires:` → `(none)` / greenfield (Phase 01 is the foundation)

**D-09 — Phase 04 SUMMARYs (insert the `# Dependency graph` header only):**

| File | Gap (snapshot-anchored) | Action |
|---|---|---|
| `04-02-SUMMARY.md:6-7` | `tags:` → blank → `requires:` (no `# Dependency graph` header) | Insert `# Dependency graph` line between the blank line and `requires:`. |
| `04-03-SUMMARY.md:6-7` | `tags:` → blank → `requires:` (no header) | Same one-line insert. |
| `04-04-SUMMARY.md:7-8` | `gap_closure: true` → blank → `requires:` (no header) | Same one-line insert. |

**D-09 preserves all existing frontmatter content** — the three 04-* files already have correct `phase`/`plan`/`subsystem`/`tags`/`requires`/`provides`/`affects`/`tech-stack`/etc. Only the single `# Dependency graph` comment line is missing. (See the **Shared Pattern 1** D-09 gap comparison for the exact before/after.)

---

## No Analog Found

None. Every file-to-modify in this phase has a concrete in-repo analog (this is a reconcile-to-existing-patterns phase by design — RESEARCH "Don't Hand-Roll" rows 1–2).

---

## Metadata

**Analog search scope:** `docs/`, `docs/guides/`, `lib/`, `services/ping/`, `recipes/ping/`, `systemd/`, `tools/harnessed/`, `.planning/phases/0[1-4]-*/`
**Files scanned for analogs:** 17 target + 4 canonical-source (`02-01-SUMMARY.md`, `service-authoring.md`, `assemble.py`, `egress-firewall.sh`)
**Pattern extraction date:** 2026-06-21
**Key cross-check:** line-number drift between CONTEXT/RESEARCH (§9:245-247, §13:381/390) and the actual `docs/harnessed-design.md` (stale text at §9:251-253, §13:387/396) — executor MUST re-`read` and anchor on snapshot tags, not CONTEXT line numbers.
