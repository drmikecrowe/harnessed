# hindsight recipe — implementation plan

Goal: let a harnessed stack reach the operator's **already-running** hindsight memory service —
Vectorize's AlloyDB-backed recall/retain/reflect engine — as a network-native MCP server.
**No image is baked, no container is spawned by harnessed**:
hindsight runs on the host (the operator's `docker compose` stack); the pod just dials it.

Upstream: <https://hindsight.vectorize.io> · image `ghcr.io/vectorize-io/hindsight` · repo
`github.com/vectorize-io/hindsight`. Operations: `retain()` / `recall()` / `reflect()` against a
per-bank **memory bank**.

This file is the *how*. The decision rationale (why url-recipe-not-service, why the host deployment
is the source of truth) is inline below.

## The host deployment (source of truth — not theory)

The operator runs hindsight at `/home/mcrowe/.config/hindsight/`. This is a **3-container**
`docker-compose` stack, and it is the topology the recipe targets:

```
hindsight-net (bridge)
  ├── db            google/alloydbomni:17        Postgres + vector + alloydb_scann extensions
  │                 host port 5438, volume alloydb_data
  ├── alloydb-init  one-shot                      CREATE DATABASE + CREATE EXTENSION (vector, scann)
  │                 depends_on: db (started)
  └── hindsight     ghcr.io/vectorize-io/hindsight:${HINDSIGHT_VERSION:-latest}
                    host ports 8888 (API + MCP) and 9999 (control-plane web UI)
                    depends_on: alloydb-init (completed_successfully)
```

Ports (verified against the deployment + upstream docs):

- **8888** — API server **and the MCP endpoint** (`/mcp/<bank_id>/`). This is what the pod reaches.
- **9999** — control-plane / web UI (bank config, mission/directives/disposition). **Not MCP.** The
  operator manages banks here; the agent never needs it.
- 5438 — Postgres, inter-container only.

Auth: the deployment enables `hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension`, so the
MCP endpoint requires `Authorization: Bearer <HINDSIGHT_API_TENANT_API_KEY>`. Secrets resolve on the
**host** from `/home/mcrowe/.config/hindsight/.env.schema` (varlock + 1Password, `op://` refs) when
the operator runs `docker compose up` — the LLM provider keys, tenant key, and rate-limit config all
live there and never enter the pod.

## Why a url recipe, not a harnessed service

hindsight is a **multi-container compose stack** (db → init → app + dependencies + init step +
secrets). harnessed services are **single-container today** (`service.yaml`: one `image`, one `port`,
one `volume`). A native `catalog/services/hindsight/` is **blocked on GAP 7** (compose-file-backed
services; see `docs/todos/2026-06-27-recipe-stress-test.md` §GAP 7, lines 593–639).

But the operator already runs the stack on the host. So the path that works **today** is the third
MCP shape — a **network-native server referenced by `url:`** that hatago proxies (`recipe-authoring`
Worked example 4 / `openbrain-example`). hatago rewrites a host address to the podman host-gateway
`host.containers.internal`, so the pod reaches the host deployment over the gateway. **No new
feature, no image, no service model change.** This is the PRIMARY path.

| Path | Status | What it needs |
| --- | --- | --- |
| **PRIMARY — `url:` recipe → host deployment** | ✅ works today | the host stack running; one recipe |
| **Phased — native compose service** | ⛔ GAP 7 | `service.yaml` gains `compose:`; see "Native compose service (GAP 7)" |

## Recipe shape

```
catalog/recipes/hindsight/
  recipe.yaml                 # TEMPLATE: url MCP entry (placeholders for bank_id + key)
  PLAN.md                     # this file
```

No `Dockerfile` (nothing to bake — hindsight is not a stdio child hatago spawns, and the host
deployment owns its own image lineage). No `hooks/` (no project-side state; memory lives on the host
DB, not in the project). This is the `openbrain-example` shape verbatim. **No skill is shipped**:
upstream hindsight offers none (it is an HTTP backend, not a skill package); the agent uses the MCP
server directly, and a user may add a skill later.

### recipe.yaml (repo — TEMPLATE)

Mirrors `catalog/recipes/openbrain-example/recipe.yaml`: a url-based MCP server with placeholders,
shippable as a reference. The operator materializes the **real** recipe in the user-overlay catalog
(see "Secrets / the live recipe").

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/recipe.schema.json
# Recipe: hindsight — TEMPLATE for reaching an already-running host hindsight deployment.
#
# Shape: a network-native MCP server referenced by DIRECT URL (no `command`, not a stdio child
# hatago bakes; no `service`, not a local sidecar). hatago proxies it; the harness only sees
# hatago's single endpoint. Same shape as openbrain-example (recipe-authoring "Worked example 4").
#
# hindsight runs ON THE HOST as a docker-compose stack (AlloyDB Omni + init + app). The pod reaches
# it over the podman host-gateway: localhost:8888 from the host → host.containers.internal:8888
# from the pod. Port 8888 is the API + MCP endpoint; 9999 is the control-plane UI (not MCP).
#
# The MCP endpoint is per-bank: /mcp/<bank_id>/. Replace BANK_ID and the Bearer key below with your
# real values in a USER-OVERLAY copy — never commit a real key (see "Secrets").
#
# Transport: http (Streamable HTTP). SSE is deprecated and rejected by the build.
name: hindsight
description: Vectorize hindsight — AlloyDB-backed memory/recall as a host-running MCP server (retain/recall/reflect).

mcp:
  servers:
    - name: hindsight
      url: http://host.containers.internal:8888/mcp/BANK_ID/
      transport: http
      headers:
        Authorization: "Bearer REPLACE_WITH_HINDSIGHT_API_TENANT_API_KEY"
```

- **`url:`** — the per-bank MCP endpoint on the host API port, rewritten to `host.containers.internal`
  (hatago runs *in the pod*; a host `localhost` is unreachable as `localhost` from the pod). The
  trailing `/mcp/<bank_id>/` is upstream's scoping convention — each memory bank is its own MCP
  surface. `BANK_ID` is a placeholder; the operator substitutes their bank (created via the UI/API).
- **`headers:`** — the Bearer key. The assembler writes `url` + `headers` **verbatim** into the
  generated `hatago.config.json` under `$XDG_DATA_HOME/harnessed/profiles/<stack>/` (host-local,
  never an image layer, never committed). `url_env` exists in the schema but is **not yet wired into
  emission** (`recipe-authoring.md` "Auth and secrets"), so the key cannot ride in env-substituted
  form today — it is a literal in the recipe. Hence the placeholder + overlay pattern.

## Secrets / the live recipe

hindsight needs the tenant API key for MCP auth. The host deployment keeps its own secrets
(`~/.config/hindsight/.env.schema`, resolved by varlock + 1Password when the operator runs compose);
those never enter the pod. The **only** secret the pod needs is the Bearer key, and only because the
host has auth enabled.

Two ways to provide it, **both keep secrets out of the repo and out of any image layer**:

1. **Bearer key in the user-overlay recipe (default — keeps host auth on).** Copy the whole
   `hindsight/` recipe dir into `~/.config/harnessed/catalog/recipes/hindsight/` and substitute the
   real `BANK_ID` + Bearer value. The overlay is searched first and wins on name clash, so only
   `recipe.yaml` carries the live url + header. The resolved header lands
   in the host-local `hatago.config.json` (mode-0600 area), never committed, never baked. This is
   the `openbrain-example` local-overlay workflow verbatim.

2. **Disable auth on the host (zero secrets in the pod).** If the host is a trusted single-user box
   and 8888 is not exposed beyond it, drop `HINDSIGHT_API_TENANT_EXTENSION` from the deployment env.
   The MCP endpoint then needs no Bearer header → the recipe has no `headers:` at all → **no secret
   touches the pod**. Simpler, but removes auth from the host deployment; only acceptable where the
   port is host-local.

> Limitation to record in the architecture: because `url_env`/header env-substitution is not wired
> today, the key is a literal in the overlay recipe. Wiring `headers` (and `url`) through the
> secrets layer (so the Bearer value resolves from `~/.config/harnessed/.env.schema` at launch, like
> a sidecar's env) would remove the literal entirely — note as a follow-up alongside GAP 7.

## Data model

hindsight's data lives in the **`alloydb_data` named volume on the host** (the existing deployment's
docker-managed volume) — **not** in the project, **not** in the pod. This is the point:

- **Instance-independent.** Stop/recreate the stack, switch harnesses, open another project — the
  memory persists. `claude+hindsight` and `omp+hindsight` read and write **one** bank.
- **Genuinely a *service* lifecycle**, unlike per-project tools (beads' `.beads/` lives in the
  project; hindsight's memory outlives any project). The pod is a stateless client of a host-owned
  store.
- The pod never mounts, reads, or writes this volume. It speaks MCP over HTTP only.

## Test stack

```yaml
# catalog/stacks/claude_hindsight/stack.yaml
name: claude_hindsight
harness: claude
recipes: [hindsight]
```

No `services:` — hindsight is not a harnessed-managed sidecar; it's a host deployment the recipe
references by URL. (Contrast `ping`, which declares `services: [ping]` because harnessed owns its
lifecycle.)

## Build / test lifecycle

```bash
harnessed build claude_hindsight      # assemble + build derived image (no hindsight image baked; pin gate N/A for it)
harnessed claude_hindsight            # launch; hatago proxies the host MCP endpoint
harnessed test  claude_hindsight      # capability report: ✓ hindsight (mcp) connected
```

Prerequisites the operator confirms **on the host** before launch (the recipe cannot start the
stack):

- `docker compose -f ~/.config/hindsight/docker-compose.yml up -d` is up and healthy (8888 answers).
- A memory bank exists (create one via the UI at `http://localhost:9999` or the memory-banks API);
  its id is the `BANK_ID` in the overlay recipe.
- The overlay recipe at `~/.config/harnessed/catalog/recipes/hindsight/recipe.yaml` carries the real
  bank id + Bearer key (or auth is disabled on the host).

Manual verification (the capability test only checks the MCP server connects — verify the
*behavior*):

- From inside the instance, `recall` returns results after a `retain` against the same bank (proves
  the pod → host.containers.internal:8888 path and the Bearer header round-trip work).
- A second stack (`omp_hindsight`) against the **same** bank sees the retained memory (proves the
  shared-memory / instance-independent property).
- Confirm the key did not leak: `grep` the committed profile returns nothing; `podman history` of the
  derived image returns nothing (the key is in `hatago.config.json`, host-local, not an image layer).

## Native compose service (GAP 7 — the phased clean alternative)

The long-term clean shape is a real harnessed service that **owns** hindsight's lifecycle, so
`svc up hindsight` brings up the whole stack and `svc down` tears it down — instead of the operator
running compose by hand and the recipe pointing at it. This requires extending the service model to
**compose-file-backed services** (GAP 7, stress-test lines 615–639). Sketched manifest shape:

```yaml
# services/hindsight/service.yaml   (BLOCKED on GAP 7 — not buildable today)
name: hindsight
compose: docker-compose.yml          # ← the compose file in the service dir (or a path)
port: 8888                           # primary port (host.containers.internal reachability + healthcheck)
healthcheck: "curl -sf http://localhost:8888/health"
secrets: true                        # resolve ~/.config/hindsight/.env.schema via varlock
```

When GAP 7 lands, `svc up hindsight` would: run `docker compose up -d` with varlock-resolved env,
wait the healthcheck, and the recipe switches from `url:` to `service: hindsight` (the assembler
resolves that to the same `http://host.containers.internal:8888/mcp` proxy). Two GAP-7
sub-decisions the stress-test already captures, applied to hindsight:

- **Bind mounts, not named volumes (CONSIDERATION 3).** The compose file's `alloydb_data` named
  volume becomes a bind mount at `${HARNESSED_DATA_DIR}/hindsight/db-data` (inspectable, portable
  across podman/docker, backup-friendly). The launcher creates the dir + UID-maps it.
- **Secrets (CONSIDERATION 1).** `secrets: true` resolves the existing
  `~/.config/hindsight/.env.schema` via the shared varlock layer — the same schema the host
  deployment already uses, not a second copy.

Until then, the **url recipe is the only path that works**, and it is genuinely good: it leverages
the deployment the operator already trusts and keeps harnessed out of the business of reimplementing
hindsight's topology (the "don't reinterpret the install" principle, applied to a running service).

## Phasing

1. **Now (works today):** ship the template `recipe.yaml` (placeholders).
   The operator drops the real recipe into `~/.config/harnessed/catalog/recipes/hindsight/` with the
   live bank id + Bearer key (or disables host auth). No feature work, no image.
2. **When GAP 7 lands:** add `catalog/services/hindsight/` (compose-backed), flip the recipe from
   `url:` to `service: hindsight`, and the operator stops running compose by hand.

## Risks / checks

- **Floating image tag.** The deployment's `ghcr.io/vectorize-io/hindsight:${HINDSIGHT_VERSION:-latest}`
  and `google/alloydbomni:${HINDSIGHT_DB_VERSION:-17}` are floating (default `:latest` / `:17`). For
  the **PRIMARY url path this is invisible to harnessed** — the host manages its own image, and the
  assembler pin gate never sees it (nothing is pulled by `harnessed build`). For the **GAP-7 native
  service**, the operator must pin `HINDSIGHT_VERSION=<exact-tag>` / a digest in the env or the build
  pin gate rejects it. Call this out in the deployment instructions either way.
- **Bank id is operator-specific.** The MCP endpoint is per-bank; the recipe cannot hardcode it. The
  template uses `BANK_ID`; the agent discovers its bank scope from the connected MCP server (no skill
  is shipped). Verify the overlay substitutes a real, existing bank (created via UI/API) or the
  connection 404s.
- **Auth-on vs auth-off.** Default path (Bearer header) keeps the host's security posture but puts a
  literal key in the host-local `hatago.config.json`. Auth-off path removes the key entirely but only
  on a trusted, host-local 8888. Document the tradeoff; let the operator pick.
- **`9999` is not MCP.** A common mistake is pointing the url at the control-plane UI port. The MCP
  endpoint is on **8888** under `/mcp/<bank_id>/`. The recipe comments state this explicitly.
- **Shared-bank write contention is upstream's problem, not harnessed'.** Multiple concurrent
  instances write one bank; hindsight serializes/consolidates. The recipe comments note the bank is
  shared cross-project state, not isolated per-instance.
