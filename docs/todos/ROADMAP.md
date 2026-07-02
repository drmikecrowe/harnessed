# harnessed — ROADMAP

**Current as of 2026-06-29.** Distilled from the prior `immediate.md` (confirmed work, verified
against code), the 2026-06-27 `plan-ceo-review` ([roadmap-triage.md](2026-06-27-roadmap-triage.md)),
and TIER 0 closure ([session-handoff](2026-06-27-session-handoff.md) ·
[tier0-plan](2026-06-27-tier0-implementation-plan.md)). This is the living forward doc — **hand it to
`plan-ceo-review` to re-rank and lock the next slice.**

---

## Strategy (set by CEO review, 2026-06-27 — confirm or revise)

**Capability-first / dogfood.** The goal is *not* outside adoption yet (no PyPI / install-script /
remote needed for now). The loop is **author recipe → compose stack → `harnessed test`**. Everything
below is ranked by *"does this serve that loop,"* not by feature glamour. Multi-container services
(hindsight) are explicitly the bottom priority.

## Status snapshot

- **Tests:** 126 passed, 6 skipped. Gated by hermetic CI on PR + push to `main` (required `pytest`
  check; the 6 skips are the `HARNESSED_PODMAN`-gated integration tests).
- **Recipes that exist:** `greet`, `gstack`, `ping`, `time`, `floating-recipe`, `openbrain-example`
  (a url-based remote-MCP *template*). **No context-management recipes authored yet** — that is the
  next feature, and the whole roadmap is sequenced to unblock it.
- **No recipe writes `settings.json` yet** — the merge infra (below) is in place, awaiting its first
  consumer (context-mode / agentmemory / hyperpowers).

## Done — TIER 0 (the prerequisites for authoring the first context recipe)

- ✅ **settings.json post-build merge** (was the #1 confirmed bug). Installer-written
  `~/.claude/settings.json` (hooks, permissions) is now merged with harnessed's required `mcp__hatago`
  grant *after* the image builds, instead of a from-scratch stub clobbering it `:ro`. Unit matrix +
  podman integration test green. Context recipes can now ship hooks that actually fire.
- ✅ **CI** — hermetic `uv run --extra dev pytest` on PR + push to `main`, required status check.
- ✅ **`--agent-start-folder`** — opens the agent in a chosen subfolder of the (fully-mounted)
  project; covers the linked-worktree workflow (mount the parent dir + point at the worktree), which
  retired the planned `.bare` auto-mount as unnecessary.

---

## The locked next slice (CEO review, 2026-06-29 — recipe-first)

**D1 is no longer a paper decision.** The CEO review chose **recipe-first**: author a real context
recipe now and let it *spec* persist, rather than deciding the scope-key in the abstract. The spike is
**context-mode (project-scoped)** — deliberately the harder half of D1, so the `sha1(project_path)`
keying gets exercised instead of deferred. agentmemory (global) was rejected as the spike: it only
exercises the trivial global path and skips validating the just-shipped settings.json merge.

**Persist declaration shape (refined by /autoplan eng+DX review, 2026-06-29):** scope is an **explicit
key**, not inferred from the string shape (a bare-name-vs-path convention silently flips isolation
semantics — UC1):

```yaml
persist:
  project: [context]     # → ~/.local/share/harnessed/<recipe>/<sha1(project)>/context  (isolated per project)
  global:  [~/.gbrain]   # → the tool's real host dir, allowlist-gated (shared with host-native runs)
```

- **project key** is a **bare name** validated by a charset allowlist `^[A-Za-z0-9._-]+$` (reject
  `.`/`..`/empty), mapped via the **same `paths.instance_name` helper** that names the pod (no
  independent `sha1` — avoids trailing-slash/symlink drift). Renaming/moving the project orphans its
  data — documented, not silently migrated.
- **global** entries name a real host dir, gated by a **user-owned default-deny allowlist**
  (`~/.config/harnessed/persist-allowlist`) — the recipe references it, never self-authorizes. Resolved
  target is `realpath`-canonicalized and hard-denied under `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/harnessed`, `$HOME` even if listed. *(A `global:` entry rw-mounts a host dir into the
  otherwise-sandboxed pod — without this gate a recipe could mount host secrets. UC2.)*

**The slice (revised order — T4a is the binding prereq; T1/T2/T7/T8 parallelize):**
1. **T1 · schema `--strict`** — a **known-field allowlist** (typed ∪ forward-parsed: keep
   `extensions`/`plugins`/`deps`/`hooks`/`scripts` for D-14 forward-compat — a blanket reject breaks
   omp + the supply-chain lint), **on by default** in `build`+`test` with a `--no-strict` escape. Also
   flip `schemas/recipe.schema.json` to `additionalProperties:false` so the editor catches `skkills:`
   live. Typo errors carry a Levenshtein "did you mean" hint.
2. **T4a · persist schema + project scope** — the explicit-key field above, charset validation, shared
   key helper, mounts emitted by a **new `_persist_mounts(stack, recipes, project)`** appended in
   `launch()` (NOT a `_build_mount_args` signature change — matches the `_omp_agent_mount` pattern).
3. **T4b · global allowlist** *(its own security-design task, split out of persist)* — the user-owned
   default-deny mechanism above.
4. **T3 · author context-mode** (project-scoped) — namespace the host dir by **recipe name AND project
   hash** (two recipes both choosing `project:[context]` must not collide); loud inline comment that
   bare = per-project; it must actually **green** the round-trip (no placeholder like
   `openbrain-example`).
5. **T6 · tests** — FAST-layer units cover the pure logic (parse / charset validation / project-key /
   allowlist) so default CI catches regressions; the **podman-gated** lane (skipped by default) runs the
   round-trip (write → `--fresh` → read) **+ two-project isolation**. The **sentinel is injected
   host-side** so the oracle stays auth-free. Default `pytest` green does NOT prove persistence —
   document that in the test module.
6. **T5 · ownership guard** — a minimal `--userns=keep-id` mkdir that **fails loudly on owner mismatch**;
   apply where global real-dirs bite. Largely redundant for harnessed-created project dirs (don't
   gold-plate).
7. **T2 · `capability.py` cleanup** *(DEMOTED — not a prereq)* — delete the stdout regex
   (`capability.py:237`); the instance name is already host-derivable via `paths.instance_name()`. The
   round-trip test computes it directly, so T2 never blocked T6.

See spec §A for the underlying mechanics. Full per-task list + audit trail:
`~/.gstack/projects/drmikecrowe-harnessed/tasks-eng-review-*.jsonl` and `…-autoplan-audit.md`.

## Ranked open work

### TIER 1 — the recipe-first slice
See "The locked next slice" above for the authoritative, /autoplan-reviewed task breakdown (T1–T9,
revised order). Summary: **T4a (persist schema + project scope) is the binding prereq**; T1 (`--strict`,
on-by-default), T7 (HATAGO_PORT), T8 (`_service_refs` test), and T2 (capability.py cleanup, demoted)
parallelize. T4a → {T4b global-allowlist security · T3 author context-mode · T5 ownership guard ·
T6 round-trip + two-project isolation test}.

### TIER 1b — quick wins (independent of the persist slice, land any time)
| Item | Why now |
|------|---------|
| **T10 · `rules:` recipe field** (spec §E) | Mirrors the existing `skills:` field; `.claude/rules/` is already an `_EXT_SUBDIRS` entry mounted `:ro` by the launcher, just unpopulated. Near-zero new code — schema field + `LinkSyncer` registration only. Feature request 2026-07-02: recipe-declared markdown rules/system-prompt content. |
| **T11 · local catalog symlinks** (spec §F) | DX convenience: surface `~/.config/harnessed/catalog/{agents,recipes,services,stacks}` inside the repo tree as `catalog/{kind}.local` symlinks, so the user overlay is editable/browsable without leaving the repo. `harnessed build` ensures both the host-side dirs and the symlinks exist. Purely filesystem convenience — `catalog_roots()` already resolves the overlay directly and needs no change. Feature request 2026-07-02. |

### TIER 2 — secrets (conditional, but now has a first consumer)
| Item | Trigger / note |
|------|----------------|
| **launch-time env-secret injection + `secrets:` decl** (spec §B) | Needed the moment a context MCP requires an API key. **New pressure:** `openbrain-example` carries its key in the URL because `url_env` is parsed by the schema but never emitted — wiring `url_env` is a concrete first slice. |
| **`secrets.md` docs drift** (spec §C) | *Cheap, independent, do anytime.* The guide documents a launch-time varlock/`--env-file` flow that **does not exist** in code. Either build §B or correct the guide — don't leave it asserting unbuilt behavior. |

### TIER 3 — background hygiene, no urgency
- **Scan-subsystem cleanup** — dead `scan.py` + `test_scan.py`, legacy `harnessed-tools`,
  advisory-only supply chain. Mostly deletion; gated on **D2**.
- **HATAGO_PORT consolidation** — the port is duplicated across **four** sites, not three: `paths.py:20`
  (imported by `launcher.py`), an independent literal in `emit.py:31`, `capability.py:54`
  (`os.environ.get("HATAGO_PORT","3535")`), **plus a hardcoded endpoint string `http://localhost:3535/mcp`
  at `capability.py:48`**. Trap: `capability.py:54` honors a `HATAGO_PORT` env override but `paths.py:20`
  is a bare constant — naively importing it drops the override. Fix: a `paths.py` **accessor that honors
  the env var**, import it in the other three, fold in the endpoint string.
- **persist lifecycle GC** *(new, from /autoplan)* — persist dirs live at `XDG_DATA/harnessed/<stack>/…`,
  a sibling of `profiles_root()`, so `harnessed clean`/`rm` never touch them. Document the gap now;
  defer a `harnessed persist prune` subcommand to TODOS.
- **`_service_refs` — repro the bug first, then fix + test.** The claimed catalog-root bug
  (`launcher.py:645-653`) was **not visible on inspection** — it uses `load_stack_with_recipes(None, …)`,
  which resolves both catalog roots correctly. Either it's subtler than a read shows, was already fixed,
  or it's misdiagnosed. Do not start a fix until a failing repro exists; the missing test stands either
  way.

### BOTTOM — explicitly deprioritized
- **Compose-backed multi-container services** (spec §D) — serves the hindsight recipe (lowest
  priority). Needs its own design doc and a new `podman compose` host dependency. Revisit when
  hindsight comes back up. The single-container `service:` path already works (see `ping`).

## Open decisions (for the review)
- **D1 · persist scope-key — RESOLVED (CEO review 2026-06-29).** Recipe-first: context-mode (project
  scope) is the spike; storage follows scope (project → bare-name shadow tree; global → tool's real
  host dir). See "The locked next slice" above.
- **D2 · scan subsystem** — keep `run_image_scan_online` (nightly rescan) or delete the gating
  scanner + `harnessed-tools` + `test_scan.py`? Optional opt-in `--strict-scans`? Gates TIER 3.
  *(Verified still present in the tree: `scan.py`, `tests/test_scan.py`, `run_image_scan_online`.)*
- **D3 · omp rw mount** — the omp agent dir is rw-mounted with full host credential access; accept
  the documented trade-off (ARCHITECTURE.md §4c — intentional), or copy-on-start / ro auth files? The
  outside voice flagged this as under-ranked **for the incoming context-recipe class** (persistent
  state + possibly-egressing MCP); re-weigh blast radius when the first such recipe lands, but it
  remains a deliberate, documented exception — not a bug to "fix" back to isolation.
- **D4 · secrets.md** — build §B as the delivery vehicle (guide becomes accurate), or correct the
  guide now and track the launch flow under §B?

---

## Item specs (reference — verified against code)

### §A · `persist:` — recipes declare persistent data folders
`Recipe` (`schema.py`) has **no** `persist:`/`data:`/`mounts:` field; the only rw mounts are hardcoded
in `_build_mount_args` (session/history, omp agent, project, per-instance stubs). Out-of-project state
(`~/.gbrain/`, global caches) is ephemeral. Direction: a `persist:` list on `recipe.yaml`; harnessed
creates the host dir (`--userns=keep-id` ownership) and adds an rw `-v` per folder, scoped per D1. Use
**bind mounts under `~/.local/share/harnessed/...`, not named volumes.** Also add a recipe-authoring
step: enumerate the tool's persistence paths (in-project already covered; out-of-project → `persist:`).

### §B · launch-time env-secret injection + `secrets:` declaration
At launch, harnessed injects **zero** env secrets and calls varlock **zero** times (only build-time
`SNYK_TOKEN` for the scan layer, `launcher.py:327`). File-based auth (Claude OAuth, omp, gemini/codex)
reaches the pod via ro mounts, but **arbitrary env-var secrets (API keys for MCP servers/services)
have no path in.** Direction: a `secrets:` block on `recipe.yaml`/`service.yaml` naming **key + source
type** (`varlock` / `env` / `envfile`), resolved host-side at launch and injected as `-e` / mode-0600
`--env-file`. Recipes are shared catalog content — name only the key + source, never an inline
`op://` ref (that leaks the author's vault structure). Never write resolved values to disk
(`hatago.config.json` / profile); never log them. First concrete consumer: emit `url_env` for
url-based MCP recipes like `openbrain-example`.

### §C · `secrets.md` documents an unbuilt launch flow
`docs/guides/secrets.md` (lines ~48–54) describes a launch-time flow — detect `.env.schema` →
`varlock load --format env` → mode-0600 temp `--env-file` → spread into both pod members → unlink —
that **does not exist** in code. Either build §B (preferred — the guide is effectively the spec) or
correct the guide to match today's reality (build-time `SNYK_TOKEN` only). See D4.

### §D · compose-backed multi-container services
`ServiceDef` is single-container (name/image/port/volume); `_ensure_service` does one build + one
`run -d`. It cannot express the reference case (hindsight: db → init → app, two ports, secrets,
specialized DB image). Direction — **delegate, don't reinterpret:** `ServiceDef` gains a `compose:`
field (path to the user's existing compose file, mutually exclusive with `image:`); `harnessed svc up`
runs `podman compose -f <file> up -d` with secret-resolved env (built on §B), waits on a healthcheck,
and the recipe's `service:` MCP ref points at the app port via `host.containers.internal:<port>`.
Needs its own design doc — open questions: compose runtime dependency, named-vs-bind volumes,
lifecycle surface (`svc up|down|list`).

### §E · `rules:` — recipe-declared markdown mounted at `.claude/rules/`
Parallel field to `skills:` in `Recipe` (`schema.py`): `rules: [{path: rules/my-rule}]`, parsed by the
same `_parse_fileext`, registered in `synclinks.LinkSyncer` (`assemble.py`), fanned into
`profile_dir/.claude/rules/<name>` by the existing `LinkSyncer.fan()` copytree. **No emit or launcher
change required** — `.claude/rules` is already in `_EXT_SUBDIRS` and already mounted `:ro` by the
launcher; it's just never populated because no recipe declares it today. Also add `rules` to
`KNOWN_RECIPE_FIELDS` and to `schemas/recipe.schema.json` (matters once T1 `--strict` flips
`additionalProperties:false` — otherwise `rules:` fails schema validation the moment `--strict` lands).
Scope: schema field + `LinkSyncer` registration + one round-trip test (recipe declares a rules dir →
built profile has `.claude/rules/<name>/*.md`) + a CONTRIBUTING.md line under "how to add a recipe".
Decided 2026-07-02: ship `rules:` now; a harness-agnostic free-form "system prompt" field is a separate,
lower-priority ask (no CLAUDE.md/AGENTS.md generation pipeline exists to receive it) — only build that
if a concrete non-Claude harness needs it.

### §F · local catalog symlinks — DX convenience for editing the user overlay
`catalog_roots()` (`paths.py:67`) already resolves `~/.config/harnessed/catalog` as the first-wins
overlay root — this feature does **not** touch catalog resolution. It's purely a filesystem convenience:
surface that overlay inside the repo tree so an author can browse/edit it without `cd`-ing to
`~/.config/harnessed`. On `harnessed build` (top of the `build()` Typer command, before the
`_build_stack`/`_build_images_cmd` dispatch — new helper e.g. `_ensure_local_catalog_links()`):
1. `mkdir(parents=True, exist_ok=True)` for `~/.config/harnessed/catalog/{agents,recipes,services,stacks}`
   (not `base` — that subdir is repo-internal base-image content, not user-authorable).
2. For each of the four kinds, ensure `catalog/<kind>.local` in the **current working directory**
   symlinks to `~/.config/harnessed/catalog/<kind>` — create if absent, leave alone if already the
   correct symlink, **error loudly** (don't silently overwrite) if the path exists and is not that
   symlink.
3. Add `catalog/*.local` to `.gitignore` (the existing root-level `.local` line only matches the
   repo-root pip dir, not `catalog/*.local` — needs its own entry).

**Open question, not yet resolved:** should step 2 fire unconditionally in whatever cwd `harnessed
build` runs from (creating `catalog/*.local` in arbitrary project directories with no `catalog/` of
their own), or only when a `catalog/` dir already exists at cwd (i.e., only inside a harnessed repo
checkout)? Leaning toward gating on "cwd already has a `catalog/` dir" — this is a repo-maintainer /
recipe-author convenience, not something a consumer of `harnessed build <stack>` in an unrelated project
should see appear. Also note: this is the first `os.symlink`/`Path.symlink_to` call in `src/harnessed/`
— no existing precedent to follow.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | HOLD_SCOPE; recipe-first slice locked; 0 critical gaps; 3 doc corrections |
| Eng Review | `/plan-eng-review` (via `/autoplan`) | Architecture & tests (required) | 1 | clean | 1 critical (allowlist) + 2 high (mount seam, T2 mis-scope) resolved; 13 auto-decisions |
| DX Review | `/plan-devex-review` (via `/autoplan`) | Recipe-author DX | 1 | clean | scope-ambiguity + allowlist-wall fixed via UC1/UC2; on-by-default `--strict` |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | skipped (no UI scope) |

- **CROSS-MODEL:** Codex not installed throughout — independent voices were Claude subagents (CEO
  outside-voice + eng + DX). CEO outside-voice: 8 pts, 2 folded in, 1 rejected (`openbrain-example` is a
  user-copied template; key lives in the user's own overlay). Eng+DX converged independently on the same
  two issues (persist scope ambiguity + the global-allowlist hole) → raised as user challenges, both
  resolved: explicit `{project,global}` key (UC1) and a user-owned default-deny allowlist with T4 split
  into T4a/T4b (UC2).
- **VERDICT:** CEO + ENG + DX CLEARED — recipe-first slice reviewed and locked; ready to implement.
  Binding prereq: T4a (persist schema). Full task list in `tasks-eng-review-*.jsonl`.

NO UNRESOLVED DECISIONS
