---
phase: 04-shared-services-recipe-breadth-full-cli
plan: 01
subsystem: infra
tags: [podman, rootless, shared-services, mcp, fastmcp, host-gateway, sidecar, svc]

# Dependency graph
requires:
  - phase: 02-isolated-tracer-bullet-stack
    provides: the isolated pod model (harness + hatago), capability test, the emit-only assembler
provides:
  - ServiceDef/load_service — a service definition model (image/volume/port/healthcheck) read from services/<name>/service.yaml
  - lib/harnessed-services.sh — svc_up/svc_down/svc_list + ensure_service_up + ensure_named_net; the shared-service lifecycle
  - harnessed svc up|down|list — the §13 service command group
  - assembler service→URL resolution — _resolve_service_servers maps service-referenced MCP servers to hatago http-proxy entries
  - services/ping — a lightweight FastMCP streamable-http tracer service (own image + service-scoped volume)
  - the rootless service networking model — publish-to-0.0.0.0 + host.containers.internal reachability (no bridge)
affects: [shared-services, omp-harness, recipe-breadth, state-persistence, networking]

# Tech tracking
tech-stack:
  added: [mcp[cli] (FastMCP streamable-http), python:3.12-slim service base]
  patterns:
  - "Rootless shared service: standalone container publishing its port to 0.0.0.0, reached by peers via the podman host-gateway host.containers.internal:<port> — NOT a bridge (rootless bridges are unsupported on most hosts)"
  - "Service-scoped named volume <service>-data survives `svc down` by default (--purge to destroy) — one memory across instances"
  - "Assembler resolves service-referenced MCP servers (service: <name>, no command) to hatago {url, type:http} entries; emit stays dumb"
  - "Proxied FastMCP service must add the host-gateway to TransportSecuritySettings.allowed_hosts (DNS-rebinding protection rejects host.containers.internal by default → 421)"

key-files:
  created:
  - lib/harnessed-services.sh
  - services/ping/service.yaml
  - services/ping/Dockerfile
  - services/ping/server.py
  - recipes/ping/recipe.yaml
  - stacks/ping-time/stack.yaml
  - tools/test-fixtures/services/svc-test/service.yaml
  - tools/test-fixtures/recipes/svc-recipe/recipe.yaml
  - tools/test-fixtures/stacks/svc-stack/stack.yaml
  modified:
  - tools/harnessed/schema.py
  - tools/harnessed/assemble.py
  - lib/harnessed-isolated.sh
  - lib/harnessed-common.sh
  - lib/egress-firewall.sh
  - harnessed

key-decisions:
  - "Rootless shared services use publish-to-0.0.0.0 + host.containers.internal reachability, NOT a bridge. The design assumed harnessed-net (a rootless bridge) for DNS-by-service-name; the checkpoint proved rootless bridges are unsupported here (netavark 'create bridge: Operation not supported' for ANY container on ANY user-defined bridge). The publish+host-gateway model preserves the design intent (one service, many attachers, service-scoped volume, independent lifecycle) and works on rootless podman everywhere."
  - "The egress firewall must allow host.containers.internal (169.254.1.2), not just the default-route gateway (192.168.4.1). iptables is netns-wide, so the harness's firewall also gates hatago — without the host-gateway rule, the proxy path is blocked. The firewall's stated intent ('connect to local services on the host') now covers both gateways."
  - "FastMCP streamable-http services proxied over host.containers.internal must add it to TransportSecuritySettings.allowed_hosts. The default allowed_hosts (127.0.0.1/localhost/[::1]) rejects the proxy Host header with 421 Misdirected Request — the connection is reachable but the MCP handshake dies at the HTTP layer."
  - "A service is its OWN container on the host network, NOT a pod member — its lifecycle is independent of any instance (design §9). Two pods resolve host.containers.internal:8080 to the SAME service container (the SVC-02 proof)."

patterns-established:
  - "services/<name>/{service.yaml,Dockerfile,server.py} is the service layout; service.yaml is flat scalars (name/image/volume/port/healthcheck) parsed by load_service (mirrors load_recipe/load_stack)"
  - "svc up is idempotent (no-op if running), builds the image on first use (BLD-02 scan), creates the named volume, publishes -p port:port, waits the healthcheck"
  - "An isolated stack auto-starts its declared services (stack.services[]) via ensure_service_up after pod create — an instance starts it if absent; it outlives instances"
  - "The harnessed-tools image BAKES the assembler package — any assembler change requires rebuilding the image before `harnessed build` reflects it"

requirements-completed: [SVC-01, SVC-02, SVC-03]

# Metrics
duration: ~120min
completed: 2026-06-16
---

# Phase 4 Plan 01: Shared Service Sidecars Summary

**A service-scoped shared sidecar model for rootless podman: standalone containers publishing to 0.0.0.0, concurrently attachable by many instances over the podman host-gateway `host.containers.internal` — with `harnessed svc up|down/list` lifecycle and assembler service→URL resolution, proven by two instances attaching to one ping service.**

## Performance

- **Duration:** ~120 min (executor auto-tasks + checkpoint diagnosis + 3 rootless-networking fixes + proofs)
- **Tasks:** 4 auto + 1 human-verify checkpoint (approved via podman: svc lifecycle + concurrent-attach + capability test)
- **Files:** 17 (9 created + 8 modified)

## Accomplishments
- `ServiceDef`/`load_service` in schema.py + the `services/ping/` tracer service (FastMCP streamable-http, one `ping` tool + `/health`, FROM python:3.12-slim) + the `ping` recipe (service-referenced MCP server) + the `ping-time` stack (time + ping, services: [ping]). (SVC-01)
- `lib/harnessed-services.sh` — `svc_up` (idempotent; own image + named volume + label + healthcheck wait), `svc_down` (volume KEPT by default, `--purge` to destroy), `svc_list` (label filter), `ensure_service_up`, `ensure_named_net`; wired as the `svc up|down|list` command group in the launcher. (SVC-01, SVC-03)
- Assembler `_resolve_service_servers` resolves `service:`-referenced MCP servers to hatago `{url, type:http}` entries by reading the service port; service servers are excluded from baked-servers.json (proxied, not baked). The capability oracle counts them. (SVC-01)
- The rootless service model: publish-to-0.0.0.0 + `host.containers.internal` reachability, firewall host-gateway allow, and FastMCP host-header allow — proven by `harnessed test ping-time` (time + ping both connected) and the SVC-02 concurrent-attach proof (one ping container, two pods, both reach it).

## Task Commits

1. **Task 1: ServiceDef/load_service + ping tracer service + ping recipe/stack** — `8918f7a` (feat)
2. **Task 2: svc up/down/list lifecycle lib + launcher svc wiring** — `d155728` (feat)
3. **Task 3: service auto-start + shared network in the isolated launcher** — `ac37f37`, `a2fe06e` (feat)
4. **Task 4: assembler resolves service-referenced MCP servers to URLs + fixtures** — `eaa9d9d` (feat)

Checkpoint fixes (3 rootless-networking defects surfaced by the human-verify):
5. **Rootless service networking — publish + host-gateway (no bridge)** — `9c8f54c` (fix)
6. **Allow podman host-gateway in egress firewall** — `b50e04c` (fix)
7. **Allow host.containers.internal Host header in ping service (FastMCP dns-rebinding)** — `6f6c1b3` (fix)

## Files Created/Modified
- `lib/harnessed-services.sh` (NEW) — the service lifecycle (svc_up/down/list + ensure_service_up + ensure_named_net).
- `tools/harnessed/schema.py` — `ServiceDef` + `load_service` (mirrors load_recipe).
- `tools/harnessed/assemble.py` — `_resolve_service_servers` (service→url resolution before emit).
- `lib/harnessed-isolated.sh` — auto-starts declared services after pod create; pod uses default networking (bridge only if HARNESSED_NET set).
- `lib/egress-firewall.sh` — allows the podman host-gateway (host.containers.internal) alongside HOST_GW.
- `services/ping/{service.yaml,Dockerfile,server.py}` (NEW) — the FastMCP streamable-http tracer + its image.
- `recipes/ping/recipe.yaml`, `stacks/ping-time/stack.yaml` (NEW) — the service recipe + composing stack.
- `tools/test-fixtures/{services/svc-test,recipes/svc-recipe,stacks/svc-stack}` (NEW) — the resolver-layout fixture.
- `harnessed` — the `svc up|down|list` command group (parsed before the stack-name fallthrough).

## Decisions Made
- **Publish + host-gateway, not a bridge.** See key-decision #1 — the single most important pivot. The design's harnessed-net bridge is unworkable on rootless podman here; publish-to-0.0.0.0 + host.containers.internal preserves every design invariant and is portable.
- **Service = standalone container, not a pod member.** Keeps its lifecycle independent of instances (design §9). Two pods attach to the one published port.
- **HARNESSED_NET kept as an explicit opt-in bridge** for hosts that DO support rootless bridges; default is the portable host-gateway model.

## Deviations from Plan

### Auto-fixed Issues

**1. Rootless bridge unsupported — networking model replaced**
- **Found during:** Task 5 checkpoint (`./harnessed svc up ping` → `netavark: create bridge: Operation not supported (os error 95)`).
- **Issue:** The plan made `harnessed-net` (a rootless bridge) the default; rootless podman on this host cannot create bridge interfaces (confirmed: ANY container on ANY user-defined bridge fails identically; default pasta works).
- **Fix:** Services publish `-p port:port` to 0.0.0.0; instances reach them via `host.containers.internal:<port>`. The pod reverts to default networking (bridge only if HARNESSED_NET explicitly set). The assembler URL changed from `http://<service>:<port>/mcp` to `http://host.containers.internal:<port>/mcp`.
- **Files modified:** lib/harnessed-services.sh, tools/harnessed/assemble.py, lib/harnessed-isolated.sh.
- **Verification:** `svc up ping` → `0.0.0.0:8080->8080/tcp`, healthy; peer container + pod member both reach host.containers.internal:8080.
- **Committed in:** `9c8f54c`.

**2. Egress firewall blocked the host-gateway (and thus hatago)**
- **Found during:** Task 5 checkpoint (`ping: ✗ missing` despite reachability; hatago logs: "Streamable HTTP error").
- **Issue:** The firewall allowed only the default-route gateway (192.168.4.1); the podman host-gateway (host.containers.internal → 169.254.1.2) was not allowed. iptables is netns-wide, so the harness's firewall also blocked hatago (shared pod netns).
- **Fix:** egress-firewall.sh resolves host.containers.internal and allows its IP alongside HOST_GW.
- **Files modified:** lib/egress-firewall.sh.
- **Verification:** fresh instance's firewall has a 169.254 allow rule; hatago reaches ping.
- **Committed in:** `b50e04c`.

**3. FastMCP DNS-rebinding protection rejected the proxy Host header**
- **Found during:** Task 5 checkpoint (ping server logs: `421 Misdirected Request`, `Invalid Host header: host.containers.internal:8080`).
- **Issue:** FastMCP's TransportSecuritySettings default allowed_hosts (127.0.0.1/localhost/[::1]) rejects `Host: host.containers.internal` — the MCP handshake dies at the HTTP layer even though the socket connects.
- **Fix:** ping server sets allowed_hosts to include `host.containers.internal:*` (keeps protection for all other hosts).
- **Files modified:** services/ping/server.py.
- **Verification:** `harnessed test ping-time` → ping ✓ connected.
- **Committed in:** `6f6c1b3`.

(Plus: the stale `harnessed-tools` image baked the pre-fix assembler — rebuilt so `harnessed build` emits the host-gateway URL. No commit; image artifact.)

---

**Total deviations:** 3 auto-fixed (all at the Task 5 checkpoint — the planned bridge model was wrong for rootless podman).
**Impact on plan:** The networking model pivoted from bridge-DNS to publish+host-gateway. Every design invariant is preserved (one service, many attachers, service-scoped volume, independent lifecycle); the model is now portable to all rootless-podman hosts. No scope creep.

## Issues Encountered
- The three deviations above are the issues — all rootless-networking realities the plan's RESEARCH couldn't have known without a rootless-podman host in hand. The checkpoint (Task 5) did exactly its job.

## Self-Check: PASSED
- [x] `svc up ping` → service up, `0.0.0.0:8080->8080/tcp`, healthy; `svc list` shows it; `svc down` keeps the volume, `--purge` removes it.
- [x] `harnessed test ping-time` → time ✓, ping ✓, time-helper ✓, exit 0.
- [x] SVC-02: one ping container, two concurrent ping-time pods, both hatago members reach host.containers.internal:8080.
- [x] assembler resolves ping → `http://host.containers.internal:8080/mcp` (not in baked-servers.json).
- [x] no service container runs --privileged or mounts a daemon socket; the ping image scans clean (BLD-02).

## Next Phase Readiness
- Shared services work rootlessly and concurrently — the foundation for real stateful sidecars (hindsight/openbrain) is proven.
- 04-02 (state persistence + CLI) and 04-03 (omp + recipe breadth) build on the same isolated launcher (04-02's state fix and 04-03's harness dispatch are independent of the service networking).
- **Update RESEARCH §2b + design doc** to reflect publish+host-gateway (not bridge) so the next reader isn't misled — the plan's bridge assumption is superseded.

---
*Phase: 04-shared-services-recipe-breadth-full-cli*
*Completed: 2026-06-16*
