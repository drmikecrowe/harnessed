# gbrain recipe — implementation plan

Goal: make GBrain available in a stack as a **shared, long-lived knowledge brain** — synthesis,
graph traversal, and gap analysis across people/companies/ideas — that multiple instances read and
write as **one** memory, independent of any single project.

Upstream: <https://github.com/garrytan/gbrain> · TypeScript (Bun) · MIT · ~23.9K stars · install
`bun install -g github:garrytan/gbrain`. PGLite (embedded Postgres) for personal/local brains, real
**Postgres + pgvector** for any HTTP/shared deployment.

> **⚠ Read this first — the headline finding overturns the working assumption.**
> The stress-test (GAP 5, line 573) assumed "gbrain in PGLite mode, the single-container service
> model works." **Upstream contradicts that.** GBrain's own
> [`SECURITY.md`](https://github.com/garrytan/gbrain/blob/master/SECURITY.md) states, unambiguously:
> *"`gbrain serve --http` requires a Postgres engine. PGLite is local-only by design and the
> `access_tokens` / `mcp_request_log` tables don't exist in the PGLite schema… Running `--http`
> against a PGLite-backed install fails fast with a clear error message at startup."* PGLite can only
> serve **stdio** (`gbrain serve`); the **HTTP transport is Postgres-only.**
>
> Therefore a **shared** gbrain service (the only shape that delivers GBrain's value — see below)
> **cannot be a PGLite single container.** It needs a real Postgres+pgvector. That is either a
> **BYO external Postgres** (one gbrain app container — works **today**, no GAP 7) or a
> **managed Postgres sidecar** (two containers — **GAP 7**, deferred). PGLite is a dead end for a
> network service. *(`docs/mcp/DEPLOY.md` half-implies OAuth tables work on PGLite; this is the #1
> thing to re-verify at `harnessed build` — see Risks. `SECURITY.md` is the hardening authority and
> wins.)*

## Recipe shape — SERVICE SIDECAR (+ recipe reference)

GBrain is unambiguously a **shared, instance-independent brain**, not a per-project tool:

- README: "the production brain behind my OpenClaw and Hermes deployments: 146,646 pages… It
  ingests meetings, emails, tweets… while I sleep." "the brain layer your AI agent has been
  missing." "drop GBrain in as your team's shared institutional memory."
- Data lives in `~/.gbrain/` + a brain repo (markdown), **never in a project dir** — contrast the
  per-project tools (serena `.serena/`, beads `.beads/`). The whole value is cross-session,
  cross-project recall.
- Multiple coding agents connect to **one** brain (`claude mcp add` / `codex mcp add` against one
  `gbrain serve --http` host).
- "It's easier to ship a **daemon** that runs 24/7 to ingest, enrich, and consolidate… GBrain is
  that daemon, generalized."

→ **SERVICE** (`catalog/services/gbrain`) + a recipe that references it via
`service: gbrain, transport: http`. The service is its own image/container/volume, host-published,
lifecycle independent of any instance; `claude+gbrain` and `omp+gbrain` read and write **one**
brain (design §3/§9, same value proposition as `hindsight`). This is the shape the stress-test
classified under **GAP 5 (service-recipe boundary)** and, for the Postgres variant, **GAP 7**.

**Why not the other shapes:**

- **stdio child** (`command: gbrain, args: [serve]`) — rejected. A stdio child is spawned
  on-demand by hatago and torn down: it does **not** run continuously (no dream cycle) and is
  **per-hatago-instance** (each stack's hatago spawns its own child = its own brain unless they
  share a `~/.gbrain` mount, which the stdio-in-hatago model gives them no way to do). It also runs
  in the HATAGO image with no project access — fine for gbrain (brain isn't in the project) but it
  still defeats the shared/long-lived value. (This *is* the README's "zero server" local path; it's
  the right shape for a single laptop, the wrong shape for a shared harnessed brain.)
- **HTTP daemon in the harness instance** (recipe Dockerfile bakes; `pre_agent` launches;
  `url:http://localhost:<port>/mcp`) — rejected for the same reason: per-instance, not shared, and
  gbrain's HTTP needs Postgres (a second process/container) which the harness instance isn't the
  right place to host. The daemon-in-harness pattern is for per-project servers; gbrain is shared.

### Two tiers

| Tier | Shape | Containers | Status |
| --- | --- | --- | --- |
| **v1 (now)** | gbrain app container + **operator-supplied external Postgres** (`DATABASE_URL` → Supabase / Neon / self-hosted pgvector) | **1** | Works today — fits `service.yaml` (one image/port/volume). DB is out-of-band. |
| **v2 (deferred)** | gbrain app + **managed Postgres+pgvector** sidecar (init: `CREATE EXTENSION vector`) | **2** | **GAP 7** (multi-container) — same shape/tier as `hindsight`; blocked on compose-file-backed services. |

v1's "BYO external Postgres" is the deliberate escape hatch that keeps gbrain **single-container**
(today's service model) without re-implementing gbrain's topology. The operator provisions
pgvector-enabled Postgres once (Supabase/Neon free tiers both ship pgvector); harnessed points the
service at it. CONSIDERATION 2 (shared DB) is acknowledged as an out-of-band gap, not a blocker.

```
catalog/services/gbrain/
  service.yaml            # 1 image (gbrain app), port 3112, volume for the brain repo
  Dockerfile              # oven/bun:<tag> → bun install -g gbrain@<sha> → init → auth create → serve --http
catalog/recipes/gbrain/
  recipe.yaml             # service-ref + bearer header (token = secret → user-overlay)
  PLAN.md                 # this file
```

## `catalog/services/gbrain/service.yaml` (v1 sketch — do NOT create yet)

```yaml
name: gbrain
image: harnessed-gbrain:latest      # service's own image lineage (built from its Dockerfile)
volume: gbrain-data                 # brain repo (markdown, system of record) + ~/.gbrain config.
                                    #   See CONSIDERATION 3: prefer bind-mount
                                    #   ~/.local/share/harnessed/gbrain/ over a named volume.
port: 3112                          # stress-test allocation (agentmemory 3111, gbrain 3112);
                                    #   set on the server via `gbrain serve --http --port 3112`.
healthcheck: "curl -sf http://localhost:3112/.well-known/oauth-authorization-server || exit 1"
# OAuth discovery is an unauthenticated 200 — confirms the HTTP server is up without a token.
```

`DATABASE_URL` (operator's external Postgres+pgvector) and the bearer-token minting are handled in
the Dockerfile / first-run init (below), not the manifest.

### Deferred v2 (GAP 7) sketch

Once compose-file-backed services land (GAP 7), the self-contained shape mirrors `hindsight`:

```yaml
name: gbrain
compose: docker-compose.yml          # gbrain app + postgres (pgvector) + one-shot init (CREATE EXTENSION vector)
port: 3112
healthcheck: "curl -sf http://localhost:3112/.well-known/oauth-authorization-server || exit 1"
secrets: true                        # varlock .env.schema for DATABASE_URL + API keys (CONSIDERATION 1)
```

The compose file's named volumes become bind-mounts parameterized by `HARNESSED_DATA_DIR`
(stress-test CONSIDERATION 3, lines 748–752).

## `catalog/recipes/gbrain/recipe.yaml` (sketch — do NOT create yet)

```yaml
name: gbrain
description: Knowledge brain — synthesis, graph traversal, gap analysis (shared, long-lived brain service).

mcp:
  servers:
    - name: gbrain
      service: gbrain          # resolved → http://host.containers.internal:3112/mcp (assemble.py)
      transport: http
      headers:
        Authorization: "Bearer ${GBRAIN_TOKEN}"   # long-lived bearer minted by `gbrain auth create`
expect:
  mcp: [gbrain]                # capability test probes the connected server (NOT `tools:` — obsolete)
```

- **`service: gbrain` + `transport: http`** — a network-native server hatago proxies by URL (the
  `ping` recipe shape). No `command`: gbrain is not a hatago stdio child.
- The gbrain MCP endpoint is at **`/mcp`** (README/DEPLOY: `gbrain connect https://host/mcp`),
  which is exactly the path the service resolver emits (`http://host.containers.internal:<port>/mcp`).
- **`headers.Authorization`** — `gbrain serve --http` **requires auth** (there is no auth-less HTTP
  mode; `missing_auth` is a hard error). On a **Postgres** brain, the **legacy long-lived bearer**
  (`gbrain auth create`) works and is a static header hatago can inject. hatago cannot run an OAuth
  client-credentials flow, so a long-lived bearer (not a short-lived OAuth token) is the only fit.
  **The token is a secret** — it lands in plaintext in the emitted `hatago.config.json`
  (`$XDG_DATA_HOME/harnessed/profiles/<stack>/`, host-local, never an image layer, never committed).
  Same posture as `openbrain-example`'s `?key=` URL: the committed recipe uses a placeholder; the
  real recipe with the live token belongs in the **user-overlay catalog**
  (`~/.config/harnessed/catalog/recipes/gbrain/`). (`url_env`/header env-substitution is not yet
  wired end-to-end per the recipe-authoring guide — confirm at build; if unwired, the literal token
  goes in the user-overlay recipe.)
- **`expect: mcp: [gbrain]`** — the stress-test snippet used `harnesses:`/`expect: tools:`, both
  **obsolete** post-restructure. `Recipe` has no `harnesses` field (recipes are harness-agnostic by
  design); `Expect` kinds are `skills/commands/plugins/mcp`. Use `expect: mcp`.

## Service `Dockerfile` (sketch)

A **service** Dockerfile has its **own full lineage** (`FROM`, `USER`, `CMD`) — unlike a *recipe*
Dockerfile, which must omit `FROM`/`ARG HARNESS` and toggle `USER root`/`USER harnessed`
(recipe-authoring guide "Rules for recipe Dockerfiles"). gbrain mandates **Bun** as both runtime
and installer (Bun-specific APIs, `bun.lockb`); this is an upstream-driven exception to "pnpm
everywhere," analogous to Python servers using `uvx` — see *Install & pinning*.

```dockerfile
# oven/bun is the runtime gbrain requires. Pin the exact tag (no :latest) — verify latest at build.
FROM oven/bun:1.2-debian

# gbrain ships NO semver git tags (only two `eval-run-v*` markers). Pin to a commit SHA
# (like the gstack recipe's fetch-by-SHA). HEAD at planning time: 814258d — refresh at build.
ARG GBRAIN_REF=814258dda67945ffec9457a1e73980e947b7e462
ENV GBRAIN_HTTP_TRUST_PROXY=0     # hatago is a direct single-hop proxy; keep default loopback trust

WORKDIR /app
RUN bun install -g github:garrytan/gbrain#${GBRAIN_REF}

# First-run init against the operator's external Postgres (DATABASE_URL supplied at `svc up` via env).
# pgvector must already be enabled in that DB (Supabase/Neon ship it; self-hosted needs
# `CREATE EXTENSION vector`). gbrain's init creates the rest of the schema.
RUN mkdir -p /data/.gbrain
ENV GBRAIN_DATA_DIR=/data/.gbrain

# Mint the long-lived bearer hatago will send (idempotent across restarts; token stored hashed in DB).
# The plaintext is printed once to stderr at first init — capture it into the recipe's header (user-overlay).
# (For a fresh DB; on an existing brain this is a no-op / re-uses the existing token.)
# CMD launches the HTTP server bound to all interfaces so the pod's host-gateway (host.containers.internal) reaches it.
EXPOSE 3112
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl -sf http://localhost:3112/.well-known/oauth-authorization-server || exit 1
CMD ["sh", "-c", "gbrain init --migrate-only --yes && gbrain serve --http --bind 0.0.0.0 --port 3112"]
```

Notes:

- **`--bind 0.0.0.0`** is mandatory — gbrain defaults to `127.0.0.1` (loopback) and would refuse the
  pod's host-gateway otherwise (DEPLOY.md "bind explicitly").
- **`--public-url`** is *not* set: the brain is reached over the pod network at
  `host.containers.internal:3112`, not a public domain; no OAuth issuer/redirect needs it.
- **Dream cycle (nightly enrichment)** — `gbrain serve --http` is the MCP surface only; the
  overnight consolidation runs as gbrain's own `autopilot`/cron, not inside the serve process. v1
  ships serve-only (search/think/capture all work; the brain is fully usable). A follow-up adds the
  dream cycle in-container (a process supervisor running `gbrain autopilot` alongside serve) or via
  host cron calling `gbrain` over the volume — **not** a second container (that would be GAP 7).
- The pin gate (`validate_pin`) runs over *recipe* Dockerfile bodies; the service image is gated by
  BLD-02 (image scan) instead. Pin both anyway: the `oven/bun` tag and the gbrain SHA.

## Install & pinning

- **Runtime: Bun.** gbrain is a Bun project — `bun install`, `bun run test`, Bun-specific server
  APIs. It cannot be installed or run with pnpm. The supply-chain rule "pnpm everywhere (no
  `npm`/`npx`)" targets the npm ecosystem; **Bun is a distinct, upstream-mandated runtime**, the
  same way Python servers use `uvx`. The BLD-03 raw-`npm`/`npx` lint
  (`_RAW_NPM_RE = \bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b`) does **not** match `bun`, so
  `bun install` passes the lint. Document this deviation at the top of the Dockerfile so it isn't
  "fixed" to pnpm.
- **No published container image.** gbrain is a Bun package, not an OCI image (no `ghcr.io/garrytan`
  package exists; CI is Docker-backed for tests only). Build the service image from the pinned
  `oven/bun` base + `bun install -g …#<sha>`.
- **Pin to a commit SHA.** `git ls-remote --tags` shows only two `eval-run-v*` markers — **no
  semver release tags**. So pin by SHA (`github:garrytan/gbrain#<sha>`), exactly like the `gstack`
  recipe's fetch-by-SHA. HEAD at planning: `814258dda67945ffec9457a1e73980e947b7e462`; refresh to
  latest at `harnessed build` and record it. A bare `github:garrytan/gbrain` (default branch) is a
  floating ref and fails pin validation.

## Data model & storage

- **System of record = the brain repo** (markdown files), synced into Postgres for retrieval
  (README "Brain repo is the system of record"). **Retrieval index = Postgres + pgvector**
  (HNSW + BM25) — the operator-supplied external DB in v1.
- **Where the brain lives:** the markdown brain repo + `~/.gbrain/config.json` (API keys, engine
  config) inside the **service container**, persisted via the service **volume** (`gbrain-data`).
  The Postgres retrieval index lives in the operator's external DB (out-of-band). This is **not**
  in-project data — there is no project bind-mount for the brain (it is shared across projects).
- **CONSIDERATION 3 — bind mount, not named volume.** The brain is precious, long-lived,
  operator-owned data. Per the stress-test decision (lines 725–756), prefer a **bind mount** at
  `~/.local/share/harnessed/gbrain/` (inspectable with `ls`/`tree`, backup-able with `tar`/`rsync`,
  portable across podman/docker, no orphan risk) over an opaque named volume. The current
  `service.yaml` `volume:` field carries a named-volume name (the `ping` pattern); reconcile at
  implementation — either follow the existing field convention or, per CONSIDERATION 3, mount the
  bind dir. Flag this as a check.

## CONSIDERATION 2 — shared database services

- The "PGLite avoids the shared-DB gap" hope is **moot**: PGLite can't serve HTTP, so a shared brain
  is Postgres-backed regardless.
- v1 points gbrain at an **operator-supplied external Postgres** (Supabase/Neon/self-hosted
  pgvector). harnessed does **not** manage that DB — there is **no shared-DB service story today**
  (acknowledged gap, CONSIDERATION 2). The operator provisions it once; multiple recipes *could*
  later share one Postgres instance with separate databases (`gbrain_db`, etc.) when the
  same-engine/same-extensions criterion holds (lines 703–723).
- v2 (managed Postgres sidecar) makes the DB harnessed-managed but is **GAP 7** (multi-container).

## GAP analysis

- **GAP 1 (HTTP-native MCP): handled.** gbrain is itself an HTTP MCP server (`serve --http`). The
  `service:` + `transport: http` shape is the documented network-native path; no architecture
  change (GAP 1 resolution, lines 494–496). Port 3112.
- **GAP 5 (service-recipe boundary): handled.** gbrain is a long-running daemon + DB → service; the
  recipe references it via `mcp.servers[].service`. The single-container service model fits v1
  (BYO external Postgres). The **multi-container** variant is GAP 7.
- **GAP 7 (multi-container service stacks): blocks v2.** A self-contained gbrain (app + managed
  Postgres+pgvector + init step) is the same shape as `hindsight` and is **deferred to Tier 3**
  (stress-test line 818: "gbrain (Postgres at scale) — multi-container. Same GAP 7 as hindsight").
  v1 sidesteps it by externalizing Postgres.
- **GAP 2 (hooks): not needed.** gbrain's value is the running brain service, not agent-side hooks.
  Its 43 upstream skills are agent-workspace skills (out of scope for this recipe — they belong to
  the *agent platform* shape like OpenClaw/Hermes, not the harnessed memory layer).

## Test stack & lifecycle

```yaml
# catalog/stacks/claude_gbrain/stack.yaml
name: claude_gbrain
harness: claude
recipes: [gbrain]
services: [gbrain]          # launcher runs ensure_service_up(gbrain) on launch
```

```bash
harnessed svc up gbrain          # build image (first use) + create volume + run -d + wait healthcheck
                                 #   (DATABASE_URL + API keys supplied via env / .env.schema)
harnessed build claude_gbrain    # assemble + build derived image (supply-chain pin gate)
harnessed claude_gbrain          # launch; stack auto-starts the gbrain service
harnessed test  claude_gbrain    # capability report: ✓ gbrain (mcp) connected
```

Manual verification (the capability test only confirms the MCP connects):

- `harnessed svc list` shows `gbrain` healthy on 3112; `curl …/.well-known/oauth-authorization-server` → 200.
- Inside an instance, an MCP `search`/`get_brain_identity` call returns brain data (proves the
  bearer header + `host.containers.internal` proxy + DATABASE_URL all resolve).
- Capture from a second harness (e.g. `omp+gbrain`) writes to the **same** brain — the shared-state
  proof (SVC-02), mirroring `claude+hindsight` / `omp+hindsight`.
- Stop the stack; `gbrain` service keeps running and the next instance re-attaches to the same brain
  (service lifecycle is independent of any instance).

## Phasing

1. **v1 — single-container service + BYO external Postgres (ship now).**
   `service.yaml` + service `Dockerfile` + `recipe.yaml` (service-ref + bearer header in
   user-overlay). Operator supplies a pgvector-enabled Postgres `DATABASE_URL`. No GAP 7.
2. **v1.1 — dream cycle in-container.** Add `gbrain autopilot` (or a cron loop) alongside
   `gbrain serve --http` behind a process supervisor. Still one container.
3. **v2 — self-contained managed Postgres (deferred, GAP 7).** Once compose-file-backed services
   ship, add a `docker-compose.yml` (gbrain app + postgres+pgvector + init) and switch
   `service.yaml` to `compose:`. Removes the operator's BYO-DB prerequisite. Same tier as
   `hindsight`.

## Risks / checks

- **#1 — the PGLite-vs-Postgres doc conflict.** `docs/mcp/DEPLOY.md` implies OAuth tables work on
  PGLite; `SECURITY.md` says `--http` "fails fast" on PGLite and the audit/auth tables are
  Postgres-only. Treat `SECURITY.md` as authoritative (PGLite = stdio-only, HTTP = Postgres-only).
  **Verify at `harnessed build`:** does a recent gbrain build still reject `--http` on PGLite? If a
  newer release reconciled this (PGLite-compatible audit sink + OAuth tables), the cheapest possible
  shape opens up — a true single-container PGLite service. Until proven, plan for Postgres.
- **Auth secret on disk.** The long-lived bearer lands in `hatago.config.json` (plaintext,
  host-local). Real token only in the user-overlay recipe, never committed. Confirm `headers:`
  env-substitution wiring; if unwired, literal token in user-overlay (same as `openbrain-example`).
- **pgvector prereq.** The operator's external Postgres must have `vector` enabled (Supabase/Neon
  do; self-hosted needs `CREATE EXTENSION vector`). Surface in the service's `.env.schema`/docs.
- **`--bind 0.0.0.0` + loopback trust.** Binding all interfaces is required for pod reachability.
  `GBRAIN_HTTP_TRUST_PROXY=0` (default) keeps forwarded-header spoofing off; hatago is a direct
  single-hop proxy so loopback trust semantics are correct. CORS not needed (hatago isn't a browser).
- **Dream cycle not in serve.** v1 = MCP surface only; enrichment deferred (v1.1). State explicitly
  in the skill/docs so operators don't expect overnight consolidation from a v1 service.
- **No semver tags.** Pin is a SHA; refresh and record at each build. A floating default-branch ref
  fails the pin gate.
- **API keys.** gbrain needs an embedding provider key (`ZEROENTROPY_API_KEY` default, or
  `OPENAI_API_KEY`/`VOYAGE_API_KEY`) and, for `think`/synthesis, an LLM key (`ANTHROPIC_API_KEY`).
  Supply via the service env / `.env.schema` (CONSIDERATION 1 — varlock backend of the operator's
  choice); they are not harnessed's to manage.
