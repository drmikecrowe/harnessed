# Phase 4 Research: Shared Services + Recipe Breadth + Full CLI

**Researched:** 2026-06-16
**Question:** What do I need to know to PLAN Phase 4 well?

Phase 4 extends the Phase 2/3 isolated-stack foundation with three capabilities:
(1) shared service sidecars with their own image/volume/lifecycle (`svc up/down/list`);
(2) persistent state by default + `--fresh` throwaway + the full CLI surface;
(3) the `omp` harness via `claude-hooks-bridge`, plus a second recipe proving recipe breadth.

---

## 1. Baseline architecture (what exists — the extension point)

### 1a. The launcher (`harnessed`)

Host bash bootstrap (`harnessed`). Current surface:
- `transparent [path]` / `<stack> [path] [--fresh]` → launch
- `build <stack>` → emit-only assemble + host `podman build`
- `test <stack>` → per-stack capability test
- flags: `--list`, `--stop`, `--remove`, `--clean`, `--fresh`, `--no-firewall`, `--root <dir>`

Arg parsing is a positional/flag `case` loop (lines 57–115). Lifecycle flags (`--list/--stop/--remove/--clean`) set booleans dispatched at lines 183–184/191–192. **Phase 4 converts these to subcommands** (`list/stop/rm`) and adds `new`, `install`, `uninstall`, `svc up/down/list`. The parser must accept `svc` as a first-class command (it has a nested subcommand: `svc up <service>`).

### 1b. Common helpers (`lib/harnessed-common.sh`)

- `detect_runtime` → `CONTAINER_RUNTIME` (podman preferred, docker fallback).
- `build_stack(stack)` — emit-only assemble → scoped source scan → host `podman build` hatago → host image scan. `ROOT=${HARNESSED_ROOT:-$HARNESSED_DIR}`.
- `generate_instance_name(stack, project_path)` → `harnessed-<stack>-<projhash>` (projhash from the project path).
- `project_relpath(project_path)` → host `$HOME`-relative path → mounted at `$CONTAINER_HOME/<relpath>` for a legible Claude slug.
- `list_instances`, `stop_instance`, `remove_instance`, `clean_instances` — operate on `harnessed-*` containers/pods by name prefix. `stop_if_last_session` guards against nuking a multi-attached instance.
- Image constants: `harnessed-base:latest`, `harnessed-claude:latest`, `harnessed-hatago:latest`, `harnessed-tools:latest`. **No `harnessed-omp` and no `harnessed-<service>` images yet.**
- `CONTAINER_HOME=/home/harnessed`.

### 1c. Isolated launcher (`lib/harnessed-isolated.sh`)

`harnessed_isolated(stack, project_path, fresh)`:
- Pod = instance name (`harnessed-<stack>-<projhash>`). Members: harness (`harnessed-claude`, `sleep infinity`) + hatago (`harnessed-hatago`, serves `:3535`).
- **Network is opt-in:** `HARNESSED_NET` env → creates a named bridge + `--network $HARNESSED_NET` on the pod. **Default is pasta (pod-local netns) — members share localhost but there is NO named bridge by default.** This is the gap for shared services (SVC-02: concurrent attach needs a shared named network).
- **State is currently wiped every (re)create:** line 81 `rm -rf "$run_claude"` then `cp -a profile/.claude run_claude`. Per-instance state dir: `$XDG_STATE_HOME/harnessed/$instance/.claude`. This is host-side but NOT persistent across recreates — contradicts STA-01 (persistent by default).
- Copy-on-start copies the committed `profiles/<stack>/.claude` into the per-instance state dir and mounts THAT `rw`. The committed profile is the immutable template.
- `--fresh` currently tears down the pod/instance (lines 52–56) but NOT the state dir (the `rm -rf` at line 81 wipes it regardless). So `--fresh` and "not fresh" are identical today — both get a clean copy. **STA-01 requires: skip the wipe when not fresh (persist); wipe only under `--fresh` (or a dedicated state volume).**
- Interactive attach: `podman exec -it ... claude --mcp-config <mcp> --strict-mcp-config`.

### 1d. Auth config (`lib/harnessed-isolated-config.sh`)

`harnessed_isolated_auth_mounts(instance)`:
- ro `~/.claude/.credentials.json` mount (real OAuth token).
- generated `.claude.json` stub (jq): `hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID`. Zero tokens. State dir: `$XDG_STATE_HOME/harnessed/$instance/`.

### 1e. Schema (`tools/harnessed/schema.py`)

`Stack` dataclass already carries: `services: list[str]`, `state: dict`, `permissions: str|None`. `McpServer` carries: `service: str|None`, `url: str|None`, `url_env: str|None`, `transport`, `headers`, `env`.

- `HARNESS_CONFIG_DIR = {"claude": ".claude"}` — **omp not mapped yet.** `stack.harness_config_dir` raises `SchemaError` for unmapped harnesses. So `harness: omp` in a stack.yaml is a hard error today.
- `expected_capabilities(stack, recipes)` derives the test oracle (mcp servers + skills + commands). Services are NOT yet part of the capability oracle — only recipes contribute.

### 1f. Assembler + emit (`tools/harnessed/assemble.py`, `emit.py`)

- `assemble(root, stack, build_dir)` → loads stack+recipes, validates no-raw-npm, fans skills/commands (`LinkSyncer`, fail-fast collision), merges MCP servers (fail-fast duplicate-name), emits profile.
- **`emit._hatago_entry(server)` is the key extension point for services:** a stdio child → `{command, args, env}`; a network-native server (when `server.is_stdio_child` is False) → `{url, type=transport, headers}`. **A service-referenced MCP server (has `service` set, no `command`) is already classified network-native** — so the assembler can emit it as a hatago URL-proxy entry pointing at `http://<service>:<port>`. The wiring to RESOLVE `service` → URL is the new work.
- `.mcp.json` = single hatago entry (`type: http`, `url: http://localhost:3535/mcp`). `settings.json` pre-approves `mcp__hatago`.
- `baked-servers.json` lists stdio servers the hatago image must bake.

### 1g. Capability test (`tools/harnessed/capability.py`)

`run_capability_test(root, stack, ...)` → expected (manifest oracle) → `launch_headless` (`harnessed <stack> --fresh`, `HARNESSED_HEADLESS=1`) → `wait_ready` (polls hatago :3535) → `introspect` (hatago `hatago://servers` resource → `claude mcp list` → LLM backstop; skills/commands from filesystem + LLM) → `build_report` (expected-vs-live diff) → teardown. Structured result → rich table or `--json`. **This is the harness for 04-03's second-recipe proof and the omp capability test.**

### 1h. hatago config format

```json
{"version":1,"logLevel":"info","mcpServers":{"<name>":{"command":"...","args":[...]} }}
```
Network-native entry: `{"<name>":{"url":"http://host:port","type":"http","headers":{}}}`.

---

## 2. Plan 04-01: Shared service sidecars (SVC-01, SVC-02, SVC-03)

> **⚠ SUPERSEDED — rootless networking pivot (see 04-01-SUMMARY).** §2b(ii)–(iv) below assumed a
> rootless bridge (`harnessed-net`) for DNS-by-service-name. The checkpoint proved rootless bridges
> are unsupported on the target host (`netavark: create bridge: Operation not supported` for ANY
> container on ANY user-defined bridge). The shipped model is **publish-to-0.0.0.0 + reach via the
> podman host-gateway `host.containers.internal:<port>`** — no bridge. Consequences: the assembler
> URL is `http://host.containers.internal:<port>/mcp` (not `http://<service>:<port>`); the egress
> firewall must allow `host.containers.internal` (169.254.1.2); and a proxied FastMCP service must
> add `host.containers.internal:*` to `TransportSecuritySettings.allowed_hosts`. All SVC invariants
> (one service, many attachers, service-scoped volume, independent lifecycle) are preserved.

### 2a. The model (design §3, §9)

A **shared service** is a heavy/stateful sidecar (hindsight = postgres+MCP, openbrain) that is:
- Its **own image/container/volume** (`services/<name>/`).
- **Service-scoped** — volume named `<service>-data` (e.g. `hindsight-data`), NOT `harnessed-data-<stack>`. This is what lets `claude+hindsight` and `omp+hindsight` share one memory.
- **Harness-independent** — owned by the service, not any instance. Lifecycle independent of instances.
- **Global by name** on `harnessed-net`. One long-lived container; multiple instances attach concurrently.

### 2b. What must change

**(i) A service definition model + `services/` directory.** A service is declared in `services/<name>/service.yaml`:
```yaml
name: <service>
image: <image-name>          # built from services/<name>/Dockerfile OR a pull spec
volume: <service>-data       # named volume (service-scoped)
port: <int>                  # the MCP HTTP port the service exposes on harnessed-net
healthcheck: <cmd|url>       # readiness gate
```
The assembler does NOT build service images by default (they're independent). `harnessed svc up <service>` builds-on-first-use if the image is absent (mirrors `ensure_images`).

**(ii) `harnessed-net` becomes the default for isolated stacks.** Today `HARNESSED_NET` is opt-in and defaults to pasta. SVC-02 (concurrent attach) requires a named shared bridge. **Decision: make `harnessed-net` the default network** — `harnessed_isolated` always ensures `harnessed-net` exists and attaches the pod to it. This is backward-compatible: members still reach hatago at `localhost:3535` (shared pod netns), AND now also reach shared services by DNS name (`http://hindsight:8080`) over the bridge. Keep `HARNESSED_NET` as an override.

**(iii) Service lifecycle: `harnessed svc up|down|list`.** New `svc` command group in the launcher:
- `svc up <service>` — ensure image (build if `services/<name>/Dockerfile` exists and image absent), create the named volume if absent, `run -d --network harnessed-net --name <service> -v <service>-data:<path> <image>`. Idempotent (no-op if already running). Wait for healthcheck.
- `svc down <service>` — stop + remove the container (keep the volume — that's the point of service-scoped persistence; `svc down --purge` removes the volume).
- `svc list` — show running services (filter `harnessed-*`-prefixed? No — services are named by the service, not harnessed-prefixed. Use a label: `--label harnessed-service=<name>` on the container to distinguish harnessed-managed services from unrelated containers).

**(iv) Instance → service attachment.** In `harnessed_isolated`, after pod create: for each `stack.services[]`, `ensure_service_up` (start if absent — design §9: "An instance starts it if absent"). The pod is already on `harnessed-net`, so the harness reaches the service by DNS name. **No per-instance container is added to the pod for the service** — the service is a SEPARATE container on the shared network, not a pod member. This is the concurrency model: two pods on `harnessed-net` both resolve `hindsight` to the same container.

**(v) Assembler: resolve service-referenced MCP servers to URLs.** When a recipe declares an MCP server with `service: <name>` (and no `command`), the assembler resolves it to `{"url": "http://<name>:<port>", "type": "http"}` in `hatago.config.json`. The port comes from `services/<name>/service.yaml`. `url_env` (e.g. `HINDSIGHT_URL`) is injected into the instance env if declared. The capability oracle (`expected_capabilities`) must include service-referenced servers so the capability test asserts them.

### 2c. The tracer service (what to build first)

hindsight/openbrain are heavy (postgres + MCP server). For the Phase 4 tracer bullet, the **first service should be lightweight, network-native, and self-contained**: a tiny MCP-over-HTTP server baked into a small image, exposing a single tool, on a fixed port, with a healthcheck. This lets the capability test assert "two concurrent instances both see the service's MCP server via hatago" WITHOUT standing up postgres.

**Recommended tracer: a minimal stdio→HTTP MCP server** (a small Python/Node HTTP server exposing one tool, e.g. `echo`/`ping`) in `services/ping/Dockerfile` + `service.yaml`. It exposes `http://ping:<port>/mcp` on `harnessed-net`. A `ping` recipe declares `mcp.servers: [{name: ping, service: ping, transport: http}]`. Two stacks (`tracer-time` + a second) both attach → both resolve `ping`.

**Alternative (reuse):** if a network-native MCP server is already available as a pre-built image, use it. But a from-scratch tiny server is deterministic and supply-chain-clean (Phase 3 gate applies). The ping service keeps the image small and the build fast.

### 2d. Concurrency proof (SVC-02)

Two instances of DIFFERENT stacks (or the same stack against two projects) on `harnessed-net`, both with `ping` in scope. The capability test for each asserts `ping` is connected via hatago. Both resolve the SAME container (verified: `podman inspect` shows one `ping` container, two pods referencing it). This is the SVC-02 acceptance: one running service, two concurrent attachers.

### 2e. Pitfalls (04-01)

- **P-04-01: podman rootless bridge creation.** Rootless podman CAN create bridge networks, but behavior varies by version/distro. `podman network create harnessed-net` must succeed rootless. The design (§13) already commits to this. Verify in the checkpoint; pasta fallback only if creation fails (degrade to pod-local, which breaks shared services — so it's a hard requirement, not a graceful fallback).
- **P-04-02: DNS resolution inside the pod.** podman bridge networks provide DNS name resolution for container names. The harness reaches the service at `http://<service-name>:<port>`. Confirm the service container's `--name` resolves from pod members. (podman's built-in DNS via `aardvark-dns`.)
- **P-04-03: service vs pod-member confusion.** The service is NOT a pod member — it's a standalone container on the shared network. Adding it as a pod member would couple its lifecycle to the pod (wrong — design §9). The hatago proxy reaches it over the network, like any external HTTP MCP server.
- **P-04-04: hatago healthcheck for network servers.** hatago connects network servers lazily. The capability test's `hatago://servers` resource must report the service server as connected. If hatago only connects on first use, the test must trigger a tools/list or the LLM backstop probes it.
- **P-04-05: volume lifecycle.** `svc down` must NOT remove the volume by default (service-scoped persistence). `--purge` is the explicit destroy.

---

## 3. Plan 04-02: State persistence + full CLI (STA-01, STA-02, CLI-01, CLI-02, CLI-03)

### 3a. State persistence (STA-01, STA-02)

**STA-01 — persistent by default, `--fresh` throws away.** Today `harnessed_isolated` does `rm -rf run_claude` + copy-on-start EVERY create (line 81). Fix:
- **Default (persistent):** if the per-instance state dir `$XDG_STATE_HOME/harnessed/$instance/.claude` already exists, REUSE it (do not wipe). Copy-on-start only on FIRST create (dir absent) — seeding the immutable profile template into fresh state.
- **`--fresh`:** wipe the state dir before copy-on-start (current behavior), giving a clean-room run. This makes `--fresh` actually distinct from default.

This is a ~5-line change in `harnessed_isolated`: gate the `rm -rf` behind `if [ "$fresh" = "true" ]`.

**STA-02 — session history persists host-side with a legible slug.** Session state is `~/.claude/projects/` + `history.jsonl`. Currently the per-instance state dir IS host-side (`$XDG_STATE_HOME/harnessed/$instance/`), and `project_relpath` already gives a legible slug (`/home/harnessed/<relpath>`). With STA-01's persistence fix, `projects/` + `history.jsonl` survive recreation automatically — they live in the persistent state dir. **The STA-02 work is mostly the persistence fix + verifying the slug is legible and harnessed-scoped** (not polluting the host's own `~/.claude`). The design §14 "Host-projects scope" recommends harnessed-owned (`~/.local/state/harnessed/<instance>/`) — which is already the convention. So STA-02 is satisfied by STA-01's persistence + the existing legible-slug convention.

**`stack.yaml` `state` field.** The schema already parses `state: {persist, session_state}` forward (D-14). Wire `state.persist: false` (or `--fresh`) to the wipe. Default `persist: true`.

### 3b. Full CLI (CLI-01, CLI-02, CLI-03)

**CLI-01 — `list|stop|rm` as subcommands.** Today these are `--list/--stop/--remove` flags. Convert to first-class subcommands that operate on stacks AND instances by name. `list` shows stacks (from `stacks/*/stack.yaml`) + running instances (from `list_instances`). `stop <stack>` / `rm <stack>` operate by stack name (find running instances for that stack). Keep the `--list/--stop/--remove` flags as hidden aliases for muscle memory, OR migrate cleanly (design §13 shows `list/stop/rm` — migrate, the `container` alias only covers `transparent`).

**Decision: keep `--list/--stop/--remove/--clean` working (back-compat) AND add `list/stop/rm` subcommands.** The positional/flag parser already handles barewords; add `list|stop|rm|new|install|uninstall|svc` to the case. This avoids breaking the Phase 1-3 muscle memory while delivering the §13 surface.

**CLI-02 — `harnessed new <stack> --harness <h> --recipes a,b,c`.** Scaffolds `stacks/<stack>/stack.yaml` from a template. This is a tools-image subcommand (`harnessed-tools new`) OR host-side (it's pure file write — no podman). **Host-side is simpler and consistent with `install`** (which is also host bash). A small function in the launcher (or a `lib/harnessed-new.sh`) writes the manifest via a heredoc. Validates: harness in `{claude, omp}`; recipes exist under `recipes/`. Refuses to overwrite an existing stack.

**CLI-03 — `harnessed install|uninstall <stack>`.** Writes/removes `~/.local/bin/<stack>` launcher shim (design §13 generated launcher). The shim is host bash: `HARNESSED_PATH=<abs>; exec "$HARNESSED_PATH" "<stack>" "$@"`. `uninstall` removes it. Verify `~/.local/bin` exists/writable; create if absent. This mirrors the repo's own `install.sh` pattern.

### 3c. Pitfalls (04-02)

- **P-04-06: `rm -rf` on persistent state is destructive.** The STA-01 fix must gate the wipe carefully — only under `--fresh` OR `state.persist: false`. A logic bug here nukes accumulated session history. The acceptance test MUST distinguish "recreate keeps state" from "recreate wipes state" (the whole point).
- **P-04-07: subcommand vs stack-name collision.** A stack could theoretically be named `list` or `stop`. The parser must treat known subcommands as subcommands BEFORE falling through to stack-name resolution. (Low risk — document the reserved words.)
- **P-04-08: `install` shim path.** The shim embeds an ABSOLUTE path to `harnessed`. If the repo moves, the shim breaks. That's acceptable (design §13 does the same) — the shim is regenerated by `install`. Document it.
- **P-04-09: `new` recipe validation.** `harnessed new` referencing a non-existent recipe should warn (not hard-fail — the recipe might be authored after the stack). But an invalid harness value IS a hard error.

---

## 4. Plan 04-03: omp harness + recipe breadth (HRN-01)

### 4a. omp = Oh My Pi (the host harness)

omp is a Claude-Code-compatible coding agent harness (v16, installed via mise). Key facts (verified on this host):
- Binary: `~/.local/share/mise/installs/github-can1357-oh-my-pi/16.0.1/omp`
- Config dir: `~/.omp`
- Non-interactive: `omp -p` (process prompt + exit); `--mode json` for structured output.
- Extensions: `omp -e <file>` / `--extension <file>` (repeatable); `--no-extensions` disables discovery.
- Skills: `--skills <glob>` filters; omp discovers skills from its skill dirs.
- Profiles: `--profile <name>` isolates auth/sessions/settings/caches.
- Hooks: `--hook <file>` loads a hook/extension file.

### 4b. claude-hooks-bridge (the integration)

`@drmikecrowe/omp-claude-hooks-bridge` (local: `~/Programming/AI/omp-extensions/claude-hooks-bridge/`). It is an omp extension (TypeScript/Bun, `omp.extensions` manifest) that:
- Reads `.claude/settings.json` hooks from the project root.
- Maps Claude hook events → omp lifecycle events: SessionStart→`session_start`, UserPromptSubmit→`before_agent_start`, PreToolUse→`tool_call`, PostToolUse→`tool_result`, Stop→`agent_end`.
- Maps omp tool names → Claude equivalents; handles `permissionDecision`/exit-2 blocking.
- Installed in omp via `omp plugin install @drmikecrowe/omp-claude-hooks-bridge`.

So for a `harnessed-omp` stack: the profile is STILL Claude-canonical (`.claude/skills,commands,hooks,rules` — the single source of truth, design §8), and omp consumes it via the bridge extension. **No re-authoring.**

### 4c. What must change

**(i) `base/Dockerfile.harnessed-omp`** — `FROM harnessed-base` + install omp (via mise, mirroring the host install) + pre-install the bridge extension (`omp plugin install @drmikecrowe/omp-claude-hooks-bridge`). Build image `harnessed-omp:latest`.

**(ii) Schema mapping.** `HARNESS_CONFIG_DIR["omp"] = ".claude"` — the profile is Claude-canonical regardless of harness (design §8: single source of truth). The harness_config_dir is `.claude` for both. The DIFFERENCE is the image (`harnessed-omp`) and the attach command. (If omp requires a separate config mount point, that is a §14 "to verify" item — the plan's checkpoint resolves it.)

**(iii) Launcher dispatch.** `harnessed_isolated` (or a parallel `harnessed_isolated_omp`) uses `harnessed-omp:latest` for the harness member and attaches via `omp --profile <isolated> -e <bridge>` instead of `claude --mcp-config`. The MCP wiring: omp reaches hatago the same way (the profile's `.mcp.json` points at `http://localhost:3535/mcp`) — verify omp reads `.mcp.json` or pass it via omp's config overlay (`--config`). 

**(iv) omp base recipe + a second recipe (recipe breadth).** The success criterion: "A second recipe added to a stack is exposed by the running instance and verified by its own capability test." Build a second lightweight recipe (e.g. a `fetch`-style skill, or reuse an existing no-dep skill) added to a stack alongside `time`. The capability test asserts BOTH recipes' capabilities are live. For the omp path: an `omp` stack (`harness: omp`) running the same Claude-canonical recipes via the bridge.

### 4d. Capability test for omp

`capability.py` launches `harnessed <stack> --fresh` headless and introspects via `claude mcp list` / hatago resource / LLM. For an omp stack, the headless attach is `omp -p` and introspection uses omp's tool/skill listing. **The capability test's harness-detection must branch on `stack.harness`:** claude → `claude -p --output-format json`; omp → `omp -p --mode json`. The MCP introspection (hatago `hatago://servers`) is harness-INDEPENDENT (it's the hatago HTTP resource) — so the primary MCP check works for omp unchanged. Only the skill/command + LLM backstop differs.

### 4e. Pitfalls (04-04)

- **P-04-10: omp reading `.claude/skills/`.** omp has its own skill discovery. Whether it reads Claude-canonical `.claude/skills/` natively is **[INFERENCE — verify in checkpoint]**. If not, the bridge or a skills-dir symlink/`--skills` glob resolves it. The plan must verify this empirically (design §14 "Harness config mount points").
- **P-04-11: omp MCP config.** omp may not read `.claude/.mcp.json` the way `claude --mcp-config` does. Verify omp's MCP wiring (likely `--config` overlay or omp's own `.mcp.json` location). The hatago endpoint is the same; only how omp is TOLD about it differs.
- **P-04-12: omp headless onboarding.** Like Claude's `.claude.json` stub, omp may need auth/profile seeding to boot headless without prompts. omp `--profile` isolates this; the credentials mount (Phase 2 AUTH-02) seeds auth. Verify omp boots headless.
- **P-04-13: bridge version drift.** The bridge is an external npm package. Pin it (the image `omp plugin install` pins to the published version). A bridge update could change event mapping.

---

## 5. Patterns to reuse (cross-cutting)

| Need | Existing analog | Where |
|------|----------------|-------|
| New image (omp/service) | `build_images` builds base→claude→hatago via `podman build` | `harnessed-common.sh:42-72` |
| New CLI subcommand | the `build`/`test` case branches in the launcher | `harnessed:62-77` |
| Service lifecycle (run -d, named volume, healthcheck) | `harnessed_isolated` pod create + `run -d` members | `harnessed-isolated.sh:100-117` |
| Network ensure | the `HARNESSED_NET` create-if-absent block | `harnessed-isolated.sh:90-94` |
| Schema field addition | `services`/`state`/`permissions` already parse-forward | `schema.py:100-118` |
| Network-native hatago entry | `emit._hatago_entry` network branch | `emit.py:87-91` |
| Capability oracle extension | `expected_capabilities` derives from recipes; add services | `schema.py:293-302` |
| Capability test branch per harness | `capability.launch_headless` + introspect | `capability.py:194-465` |
| Generated launcher shim | repo `install.sh` symlink pattern; design §13 | `install.sh` |
| Scaffolding a manifest | recipe/stack.yaml conventions | `stacks/tracer-time/stack.yaml` |

---

## 6. Dependency / wave structure

- **04-01 (services)** and **04-02 (state+CLI)** are largely **independent** — they touch different parts of the launcher (`svc` group + isolated.sh network/service attachment vs. state-wipe gating + CLI subcommands). They can be **Wave 1 (parallel)**.
- **04-03 (omp + recipe breadth)** depends on 04-01 OR 04-02 only loosely: it needs the capability-test-per-recipe model (already exists from Phase 2) and benefits from 04-02's `new` scaffolding. It can run in **Wave 2**, but is not hard-blocked. The omp image build is independent. **Recommendation: Wave 2 (after 04-01/04-02 land)** so the second-recipe + omp capability test runs against a stable launcher.

---

## 7. Security posture (ASVS L1 — each plan needs a threat_model block)

- **04-01 services:** a shared service on `harnessed-net` is a network-reachable surface. Threats: a malicious instance reaching another instance's service data (T: cross-tenant access via shared netns — mitigate by service-scoped volumes + no host mount); service image supply-chain (T: reuse Phase 3 scan gate for service images).
- **04-02 state/CLI:** persistent state dir holds session history (T: sensitive data at rest — it's already host-side under XDG; no new exposure). `install` shim writes to `~/.local/bin` (T: PATH injection — mitigate by writing only the named shim, not modifying PATH global). `new` writes a manifest (low risk).
- **04-03 omp:** the bridge executes hooks via `bash -lc` (T: hook injection — same as Claude hooks; isolated profile mitigates). omp image supply-chain (T: scan gate).

---

## 8. Open questions (checkpoint-resolved during execution)

1. **Does omp read `.claude/skills/` natively?** (P-04-10) — verify; bridge/symlink fallback.
2. **omp MCP config wiring** (P-04-11) — does omp read `.mcp.json` or need `--config`?
3. **omp headless auth** (P-04-12) — does `--profile` + credentials mount boot headless?
4. **podman rootless bridge DNS** (P-04-02) — confirm `<service>` name resolves from pod members.
5. **hatago network-server health reporting** (P-04-04) — confirm `hatago://servers` reports the service as connected.

All are empirically verifiable in the plan checkpoints; none blocks writing executable plans.
