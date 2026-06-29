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

## The decision to resolve first (this is what gates everything downstream)

### D1 · `persist` scope-key — **decide before any persist code**
Memory/context tools *are* persistence; state written **outside** the project dir today dies on
`--fresh`. A recipe needs to declare persistent folders and harnessed bind-mounts them — but the host
target must encode the right scope, and that shape must be settled before implementing:

- **Per-(stack, project)** — an index/cache *of this project*, keyed by the existing
  `sha1(project_path)` → `~/.local/share/harnessed/<stack>/<project-hash>/<name>/`.
- **Per-stack / global** — personal state independent of any project (a knowledge brain like gbrain)
  → `~/.local/share/harnessed/<stack>/<name>/`.

The author likely indicates scope *per folder* (the tool knows whether its data is project-scoped or
global). **Settle the declaration shape, then implement** (see spec §A). This is the single
highest-leverage unblock for the context-recipe goal.

## Ranked open work

### TIER 1 — harden the author → test loop (do alongside / right after D1)
| Item | Why now |
|------|---------|
| **persist** (spec §A) | Unblocked by D1. Without it a memory recipe "installs fine" but forgets everything across sessions. |
| **schema `--strict` author mode** | A misspelled recipe field (`skkills:`) is swallowed silently today — a real time-sink once hand-authoring N recipes. Pays off by recipe #2. |
| **`capability.py` oracle de-fragilize** | The `harnessed test` oracle scrapes the instance name from stdout via regex (`capability.py`). Harden the tool you live in — export via a machine-readable channel. |

### TIER 2 — secrets (conditional, but now has a first consumer)
| Item | Trigger / note |
|------|----------------|
| **launch-time env-secret injection + `secrets:` decl** (spec §B) | Needed the moment a context MCP requires an API key. **New pressure:** `openbrain-example` carries its key in the URL because `url_env` is parsed by the schema but never emitted — wiring `url_env` is a concrete first slice. |
| **`secrets.md` docs drift** (spec §C) | *Cheap, independent, do anytime.* The guide documents a launch-time varlock/`--env-file` flow that **does not exist** in code. Either build §B or correct the guide — don't leave it asserting unbuilt behavior. |

### TIER 3 — background hygiene, no urgency
- **Scan-subsystem cleanup** — dead `scan.py` + `test_scan.py`, legacy `harnessed-tools`,
  advisory-only supply chain. Mostly deletion; gated on **D2**.
- **HATAGO_PORT consolidation** — port defined in one place (`paths.py`), imported elsewhere;
  de-risks a future endpoint fix.
- **`_service_refs` catalog-root bug + missing test** — fix and test together.

### BOTTOM — explicitly deprioritized
- **Compose-backed multi-container services** (spec §D) — serves the hindsight recipe (lowest
  priority). Needs its own design doc and a new `podman compose` host dependency. Revisit when
  hindsight comes back up. The single-container `service:` path already works (see `ping`).

## Open decisions (for the review)
- **D1 · persist scope-key** — per-project `sha1` vs global (above). **Resolve next.**
- **D2 · scan subsystem** — keep `run_image_scan_online` (nightly rescan) or delete the gating
  scanner + `harnessed-tools` + `test_scan.py`? Optional opt-in `--strict-scans`? Gates TIER 3.
- **D3 · omp rw mount** — the omp agent dir is rw-mounted with full host credential access; accept
  the documented trade-off, or copy-on-start / ro auth files?
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
