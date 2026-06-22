# Architecture — `harnessed`

> Generated 2026-06-22. Grounded in `docs/harnessed-design.md` (authoritative) and corroborated
> against the actual source. The design doc is the source of truth for *why*; this document is the
> source of truth for *how the code is wired*.

`harnessed` is a **bash-first CLI** that composes named containerized "stacks" of AI coding
harnesses (`claude` / `omp` / `opencode` / `gemini` / `antigravity` / `codex`) on **Podman**
(Docker-compatible). The host's only dependency is the container engine; every other piece of logic
either lives in dependency-free bash or in a single containerized Python toolset. This document
walks the layering, the two config modes, runtime composition, the Python tools image, the egress
firewall, and the build/scan/rescan lifecycle.

---

## 1. Architectural pattern

`harnessed` follows a **thin-host-bootstrap + containerized-toolset** split, layered as:

```
┌──────────────────────────────────────────────────────────────────────┐
│  harnessed  (the `harnessed` executable: dependency-free host bash)  │
│    parse argv → detect_runtime → dispatch                            │
└───────────────┬──────────────────────────────────────────────────────┘
                │ sources (just-in-time)
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  lib/harnessed-*.sh  (the bash module library)                       │
│   common · cli · runtime · services · secrets · mounts ·            │
│   isolated · isolated-config · transparent · rescan · claude-config │
│   + lib/egress-firewall.sh                                           │
└───────┬───────────────────────────────────────┬──────────────────────┘
        │ emit-only invocation (build)          │ host podman build/run (launch)
        ▼                                       ▼
┌─────────────────────────┐         ┌──────────────────────────────────┐
│ harnessed-tools (Python)│         │ host podman (the ONLY daemon)    │
│  the assembler image    │         │  pod create / run / exec / build │
│  assemble·scan·test     │         │  NEVER driven from a container   │
└─────────────────────────┘         └──────────────────────────────────┘
```

Three properties make this hold together:

1. **Podman is the only host dependency.** The host bootstrap (`harnessed` + `lib/harnessed-*.sh`)
   is plain bash with no Python/node/uv — version roulette is confined to images. See `CLAUDE.md`
   §"Tech stack" and design §15.
2. **No Docker-out-of-Docker (DooD).** The Python toolset **only emits files** into a bind-mounted
   build dir; it never mounts the daemon socket and never invokes `podman`. The *host* runs
   `podman build` on the emitted Dockerfiles and `podman run` for the live pod. This removes the
   API-socket mount, the host-absolute-path bind footgun, and TTY-tunneling cost (design §15).
3. **`FROM` is for base lineage only; composition happens at runtime.** Docker `FROM` is linear
   inheritance — there is no "union two sibling images" operator. So harness + hatago + services are
   *never* baked together; they are combined in a podman **pod** at launch (design §3, §6).

---

## 2. Layering: the launcher → lib module split

### The bootstrap: `harnessed`

`harnessed` (the root executable, ~410 lines) is the single host entry point. It:

1. Resolves its own directory (following symlinks so a PATH symlink works) and exports
   `HARNESSED_DIR`.
2. Sources `lib/harnessed-common.sh` (which transitively sources `lib/harnessed-runtime.sh`).
3. Calls `detect_runtime` to pick podman over docker (`lib/harnessed-common.sh:52-61`).
4. Parses argv with a `case`/`while` loop and dispatches to subcommand handlers or a launch path.

Dispatch is **just-in-time sourcing**: each subcommand sources only the lib it needs (`svc)` sources
`harnessed-services.sh`; `list`/`stop`/`rm`/`new`/`install` source `harnessed-cli.sh`; `auth)`
sources `harnessed-secrets.sh`; `rescan)` sources `harnessed-rescan.sh`; `test)` drives host
Python). The launch path (`harnessed:394-411`) sources either `harnessed-transparent.sh` or
`harnessed-isolated.sh` based on the resolved stack name.

### The lib module library (`lib/`)

| Module | Role | When sourced |
|---|---|---|
| `lib/harnessed-common.sh` | Logging, runtime detection, image build/ensure, instance lifecycle, identity. The shared substrate. | always (by the bootstrap) |
| `lib/harnessed-runtime.sh` | Provider abstraction (`rt_*`): hides podman-pods vs docker-shared-netns vs (future) Apple `container`. | always (sourced by common.sh) |
| `lib/harnessed-cli.sh` | First-class subcommands by name: `list`/`stop`/`rm`/`new`/`install`/`uninstall` | subcommand dispatch |
| `lib/harnessed-mounts.sh` | The §4a host-integration mount layer (auth/signing/agents/firewall), shared by EVERY stack | launch paths |
| `lib/harnessed-transparent.sh` | The transparent launcher — host config mounted live | `harnessed transparent` / default |
| `lib/harnessed-isolated.sh` | The isolated launcher — composes the pod (harness + hatago), attaches | `harnessed <stack>` |
| `lib/harnessed-isolated-config.sh` | Isolated §4b auth seeding (ro credential + generated `.claude.json` stub) | isolated launcher |
| `lib/harnessed-claude-config.sh` | Transparent `.claude.json` copy-on-start safety | transparent launcher |
| `lib/harnessed-services.sh` | Shared service lifecycle (`svc up/down/list`, `ensure_service_up`) | `svc` dispatch + isolated launcher |
| `lib/harnessed-secrets.sh` | Opt-in varlock + 1Password resolution (`resolve_secret_env`) + scanner-token auth | isolated/transparent launch + `build` + `auth` |
| `lib/harnessed-rescan.sh` | Nightly image re-scan (`harnessed_rescan_images`) | `rescan` dispatch + systemd timer |
| `lib/egress-firewall.sh` | Runs *inside* the container (NET_ADMIN): whitelist-based iptables egress | mounted into every instance |

**Convention:** every lib module is host-native bash. The header of each module states the contract
it expects (`HARNESSED_DIR`, `CONTAINER_RUNTIME`, etc.) and what it sources. Use the same shape for
new modules — a clearly-commented `usage:` line, append-to-`MOUNT_ARGS` rather than global mutation
where a caller owns the array.

---

## 3. The transparent vs isolated config-mode split

There is **one** executable and **one** engine. Stacks differ on a single axis: *where the config
layer (skills/commands/hooks/MCP) comes from* (design §2).

| Mode | Config source | Mental model | Pod? | hatago? | Assembler? |
|---|---|---|---|---|---|
| **`transparent`** | host `~/.claude` (+ `.codex`/`.config/opencode`/`.gemini`) mounted **live** | "my laptop, sandboxed" | no | no | no |
| **`isolated`** | the assembled, committed `profiles/<stack>/.claude` only; auth seeded; **nothing** from host config | "clean room with exactly what I picked" | yes | yes | yes |

### What is shared (the §4a host-integration layer)

Both modes build on `harnessed_host_integration_mounts` in `lib/harnessed-mounts.sh:11-83`. This is
the **operational** mount layer — credentials, signing, agents, firewall — *not* the
config-experiment surface, so it belongs in every instance:

- 1Password SSH agent socket, GPG agent SSH socket + `~/.gnupg` (ro), YubiKey USB passthrough
- `~/.ssh` (ro), git config (ro), `/etc/machine-id` (ro), `~/.zai.json` (ro)
- per-tool `~/.config/<tool>` dirs (from `extra-tools.txt`)
- the egress firewall script mounted to `/usr/local/sbin/egress-firewall`
- the current project folder mounted at `/home/harnessed/<relpath>`

Base run flags are appended here too: `$(rt_userns_args)` (provider-specific UID mapping),
`--cap-add NET_ADMIN`, `-w`, and TERM. This module is the one place to add a new host-integration
mount that applies to *all* stacks.

### What differs (the §4b config source)

**`transparent`** (`lib/harnessed-transparent.sh`): mounts host config live —
`~/.claude` (rw, append-mostly dir tree), `~/.codex`, `~/.config/opencode`, `~/.gemini`. The one
safety fix: `~/.claude.json` is **never** rw-bind-mounted (it's a whole-file blob Claude rewrites
constantly — a shared rw mount races and corrupts host state). Instead
`harnessed_claude_json_copy_mount` (`lib/harnessed-claude-config.sh:10-24`) seeds a writable
per-instance copy under `$XDG_STATE_HOME/harnessed/<instance>/.claude.json` once and mounts *that*.

**`isolated`** (`lib/harnessed-isolated.sh`): carries no host config layer. Auth is seeded by
`harnessed_isolated_auth_mounts` (`lib/harnessed-isolated-config.sh`):

- `~/.claude/.credentials.json` mounted **read-only** (the real OAuth token; never copied into a
  profile or image layer).
- a **generated**, token-free `~/.claude.json` stub carrying only onboarding/identity fields
  (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID`) — zero
  credential values. opencode/gemini/codex seed their own credential stores instead (HRN-02..05).

The config source itself is the committed profile, **copy-on-started** into a per-instance state dir
(`lib/harnessed-isolated.sh:131-138`): the committed profile is the immutable template; the running
harness never writes runtime state (projects/, backups/, caches) back into the version-controlled
tree. A normal recreate **reuses** accumulated `.claude`; `--fresh` wipes + reseeds (clean-room).

---

## 4. Runtime composition: how a stack is composed at runtime

A running `isolated` stack is a podman **pod** composed at runtime — harness container + hatago +
attached services — sharing a network namespace. This is the core model (design §3):

```
        podman pod: harnessed-<stack>-<projhash>
   ┌───────────────────────────────────────────────────┐
   │  [ harnessed-<harness> ]  ──→  [ hatago ]          │
   │    mounts cwd + profile      MCP hub · :3535       │
   └─────────────────────────────┬─────────────────────┘
                                 │ MCP over the pod netns (localhost:3535)
            ┌────────────────────┴───────────────────────┐
            ▼                                            ▼
     [ hindsight ]                              [ openbrain ]    ← shared services
     own image · volume · lifecycle             (attached by reference,
                                                host-published, independent)
```

### The pipeline: recipe → profile scan → pod assembly → harness attach

`harnessed build <stack>` → `harnessed <stack>` runs the full lifecycle. The pieces, in order:

**1. Recipe → profile (emit-only assemble).** `build_stack` (`lib/harnessed-common.sh:115-191`)
ensures the `harnessed-tools` assembler image exists, then runs it **emit-only**:

```bash
"$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" assemble "$stack" --root "$ROOT" --build-dir "$ROOT"
```

The assembler (`tools/harnessed/assemble.py:73-112`) loads `stacks/<stack>/stack.yaml` + its recipes
(`schema.load_stack_with_recipes`), **fails fast** on raw npm/npx (`validate_no_raw_npm`) and on MCP
server-name collisions (`_merge_servers`), then **fans** each recipe's skills/commands into the
harness-native profile path (`.claude/skills/<leaf>`), **resolves** service-referenced MCP servers to
network URLs (`_resolve_service_servers`), and **emits**:

- `profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` — the assembled profile
- `profiles/<stack>/.claude/.mcp.json` — exactly **one** entry pointing at hatago
  (`emit.write_mcp_json`):
  ```json
  { "mcpServers": { "hatago": { "type": "http", "url": "http://localhost:3535/mcp" } } }
  ```
- `profiles/<stack>/.claude/settings.json` — pre-approves the hatago hub's MCP tools
- `profiles/<stack>/hatago.config.json` — declares each server as a hatago child/proxy
- `profiles/<stack>/baked-servers.json` — the stdio servers the hatago image must bake

**2. Profile scan (supply-chain gate).** The assembler runs a **scoped** source/Python scan of just
this stack's recipe dirs + emitted profile (`tools/harnessed/scan.py`, `run_source_scan`). osv-scanner
(offline) + pip-audit are the credential-free baseline; snyk/Socket.dev run only when a token is
present (warn-and-skip otherwise). The gate aborts on CVSS ≥ HIGH (`scan.HIGH = 7.0`, computed from
the CVSS v3.1 vector in `scan._cvss3_base`/`scan.gate`).

**3. Image build (host).** The *host* builds the hatago image from the emitted artifacts:
`podman build -t harnessed-hatago:latest -f base/Dockerfile.hatago`. Then a **host-driven image scan**
runs: `podman save` → throwaway tar → `harnessed-tools scan-image` in a `--rm` container.

**4. Pod assembly + harness attach (host launch).** `harnessed <stack>` resolves the harness image
(claude/omp/opencode/gemini/antigravity/codex), lazily builds non-claude images only when needed
(`ensure_omp_image`, etc.), then `harnessed_isolated` (`lib/harnessed-isolated.sh:33-274`):

1. tears down any existing pod/instance under `--fresh` (`rt_group_teardown`);
2. reuses or reseeds the per-instance profile copy (§3);
3. `rt_group_create` — creates the pod (podman) / no-op (docker, hatago owns the netns);
4. **auto-starts** declared `services:` via `ensure_service_up` (a standalone container, *not* a pod
   member; lifecycle independent of the pod);
5. resolves opt-in secrets (`resolve_secret_env`) into a mode-0600 temp `--env-file`, spread into
   *both* pod members, then wiped via a `RETURN` trap;
6. runs hatago (`rt_hatago_placement`) serving the single Streamable-HTTP endpoint on `:3535`;
7. runs the harness member (`rt_harness_placement`) with `sleep infinity`;
8. `apply_firewall` on the harness container (NET_ADMIN; shared netns → covers hatago);
9. **waits** for hatago readiness (a TCP probe loop on `:$HATAGO_PORT`), then attaches.

The attach branches on the harness (`lib/harnessed-isolated.sh:240-270`): claude loads the profile's
hatago endpoint via `claude --mcp-config <cfg> --strict-mcp-config`; omp runs `omp --profile`; the
others run their bare CLI (opencode/gemini/antigravity/codex reach hatago via image-baked config, not
`.mcp.json`). `HARNESSED_HEADLESS=true` skips the attach and leaves the pod up for `podman exec`
introspection — this is the capability-test path.

### The provider abstraction (`rt_*`)

`lib/harnessed-runtime.sh` hides the two ways to express a shared-netns group:

- **podman** → a **pod** (`pod create` + `run --pod`); rootless UID via `--userns=keep-id` set on the
  pod's infra container.
- **docker** → a **shared-netns pair**: hatago runs first, the harness joins with
  `--network container:<instance>-hatago`; rootless docker remaps UIDs daemon-side so `--userns` is
  omitted.

Keep launchers runtime-independent: call `rt_group_create` / `rt_hatago_placement` /
`rt_harness_placement` / `rt_group_teardown` / `rt_uses_pods`, never branch on `$CONTAINER_RUNTIME`
in launcher code. Apple `container` has no shared-netns equivalent and is a tracked follow-up (not
handled here).

### Networking: the rootless host-gateway model

Pod members share a netns, so the harness always reaches hatago at `localhost:$HATAGO_PORT` (default
3535). Shared *services* publish their port to `0.0.0.0` and are reached via the podman host gateway
`host.containers.internal:<port>` — **rootless bridges are unsupported on most hosts** (netavark
"Operation not supported"), so the `HARNESSED_NET` bridge is an explicit opt-in for bridge-capable
hosts (DNS-by-name) (design §9). Two operator prerequisites keep this working:
`lib/egress-firewall.sh:55-63` adds an iptables allow rule for `host.containers.internal`, and a
Streamable-HTTP service proxied over it MUST add it to `TransportSecuritySettings.allowed_hosts`
(canonical: `services/ping/server.py:19-25`).

---

## 5. The Python tools image (`harnessed-tools`)

`harnessed-tools` (`tools/Dockerfile`, built from `tools/`) is the **build-time assembler image** — a
single Python toolset that holds *all* assembly logic. It is distinct from the runtime bash layer:

- **Emit-only.** Its entrypoint (`harnessed-tools`) is invoked as
  `assemble` / `scan` / `scan-image` / `scan-image-online` / `test` (`tools/harnessed/cli.py`). The
  `assemble`/`scan` subcommands only read/write the bind-mounted build dir; they never invoke
  podman and never mount the daemon socket (design §15, threat T-02-03).
- **Python + rich + ruamel.yaml + scanners.** Built from `python:3.13-slim`; adds jq, a
  checksum-verified pinned `osv-scanner`, pre-seeded offline OSV DBs, varlock/`op`/snyk/socket (all
  *inert* unless a `.env.schema` or token exists), and a managed pnpm supply-chain config
  (`minimumReleaseAge`/`strictDepBuilds`).
- **UID-paired.** The image creates a `tools` user at uid 1000, paired with `--userns=keep-id` at
  run, so emitted files in the bind-mounted build dir are owned by the host user, not root.

The Python package (`tools/harnessed/`) is a clean module set:

| Module | Role |
|---|---|
| `tools/harnessed/schema.py` | Typed `Recipe` / `Stack` / `McpServer` / `FileExt` / `ServiceDef` models; `HARNESS_CONFIG_DIR`; the raw-npm lint (`validate_no_raw_npm`); `expected_capabilities` (the test oracle) |
| `tools/harnessed/assemble.py` | The assembly orchestration (`assemble`) — merge servers, resolve services, fan skills, drive `emit` |
| `tools/harnessed/emit.py` | Pure file-emission (`reset_profile`, `write_mcp_json`, `write_hatago_config`, `write_baked_manifest`); `HATAGO_ENDPOINT` |
| `tools/harnessed/scan.py` | The supply-chain gate: CVSS computation, `gate`, `run_source_scan`, `run_image_scan`, `run_image_scan_online` |
| `tools/harnessed/capability.py` | The per-stack capability test: manifest oracle vs live `--fresh` introspection (`run_capability_test`) |
| `tools/harnessed/report.py` | Renders the capability result as a rich markdown table (or `--json` for CI) |
| `tools/harnessed/synclinks.py` | Fans skills/commands into harness-native paths; `CollisionError` on name clash |

**Why a container, not host Python:** it removes host Python/node/uv version roulette and keeps the
host dependency surface at "podman only." The one exception is `harnessed test`, which drives host
podman (launch + `podman exec` introspection + teardown) and so runs host-native Python — resolved
via `HARNESSED_PYTHON` / `uv run --with ruamel.yaml --with rich` / a system python3
(`harnessed:358-378`).

---

## 6. The egress-firewall layer

The egress firewall (`lib/egress-firewall.sh`) is the primary exfiltration control: it runs **inside**
each instance as root (the container has `--cap-add NET_ADMIN` from the §4a layer), flushes the
OUTPUT chain, sets default DROP, then allows only loopback, established/related, DNS, the podman host
gateways, and a small **whitelist** of resolved domains (api.anthropic.com, GitHub, npm registry,
pypi.org, mise.jdx.dev, …). Extra domains (e.g. a Z.AI endpoint) are appended at call time.

It is applied by `apply_firewall` (`lib/harnessed-common.sh:383-392`), which is **idempotent** via a
`/run/egress-firewall-active` flag file and is skipped with `--no-firewall`. Because iptables is
netns-wide, applying it on the harness container covers the whole pod (hatago included). Rules are
in-memory, so they are re-applied at each session start. This is the layer to extend when a new
recipe needs a new outbound destination.

---

## 7. Build / scan / rescan lifecycle

```
harnessed build <stack>
  └─ ensure harnessed-tools image  (build from tools/Dockerfile on first use)
  └─ EMIT:  harnessed-tools assemble <stack>   → profiles/<stack>/ + hatago.config.json
  └─ SOURCE SCAN: harnessed-tools scan <stack>  → HIGH+ ⇒ abort
  └─ HOST BUILD:  podman build base/Dockerfile.hatago → harnessed-hatago:latest
  └─ IMAGE SCAN:  podman save → harnessed-tools scan-image → HIGH+ ⇒ abort

harnessed <stack>           → compose pod, attach  (auto-builds missing images)
harnessed test <stack>      → --fresh headless launch + manifest-oracle assertion
harnessed rescan            → nightly: re-scan installed images ONLINE (fresh DB)
```

**Build** (`build_stack`) is the gated path: assemble (emit-only) → scoped source scan → host hatago
build → image scan. A HIGH finding at either scan aborts the build (`scan.ScanError` propagates as a
non-zero exit). The credential-free osv-scanner + pip-audit are always the baseline; snyk/Socket.dev
are token-gated (warn-and-skip when absent — the build stays non-interactive/reproducible). Scanner
tokens reach the scan step as **env only** (forwarded from the launcher env or varlock-resolved),
never a profile or image layer.

**Test** (`harnessed test`) is the capability oracle (design §18): it derives *expected* MCP
servers/skills/commands from the manifest (`schema.expected_capabilities`), launches the stack
`--fresh` headless, introspects the live pod (hatago's `hatago://servers` resource, the mounted
profile filesystem), diffs actual-vs-expected into one structured result, and tears the instance
down. The same result drives a rich markdown report (`report.py`) and the CI exit code — one
mechanism, two audiences. **There are no assembler unit tests by design** — the assembler is covered
*transitively* (wire the wrong thing and the capability test fails).

**Rescan** (`harnessed rescan` / `lib/harnessed-rescan.sh`, driven by
`systemd/harnessed-rescan.timer`) is the post-build CVE catch: it iterates installed
`harnessed-*`-labelled images, `podman save`s each, and re-scans it **online** (fresh osv.dev DB, via
`scan-image-online`) so a CVE disclosed *after* build still surfaces. Each image is scanned
independently (a HIGH on one does not abort the rest); the overall exit code tracks any failure. The
timer requires `loginctl enable-linger $USER` so it fires while logged out.

---

## 8. Key abstractions (glossary)

- **Stack** — a named manifest (`stacks/<name>/stack.yaml`): one harness + recipes + (optional)
  services. The unit you launch.
- **Recipe** — a hand-authored integration definition (`recipes/<name>/recipe.yaml`) contributing to
  the MCP layer and/or the file-extension layer (design §5).
- **Profile** — the generated, committed output (`profiles/<stack>/`) mounted into the harness
  container; the version-controlled source of truth for an isolated stack's config.
- **hatago** — the MCP hub. Aggregates all of a stack's MCP servers behind **one** Streamable-HTTP
  endpoint (`localhost:3535/mcp`); spawns stdio servers as children (stdio→HTTP), proxies network
  servers by URL.
- **Shared service** — a heavy/stateful sidecar (own image/container/volume, host-published,
  lifecycle independent of any instance); attached by reference (`services:` in the stack).
- **Instance** — one running pod (isolated) or container (transparent), named
  `harnessed-<stack>-<projhash>`; identity is stack + project path.
- **Provider** — the container runtime, abstracted by `rt_*`: podman (pods) or docker (shared
  netns).

## 9. Entry points

| Entry point | What it is |
|---|---|
| `harnessed` | The host bootstrap CLI (dependency-free bash). Parses argv, dispatches to subcommands or a launch path. |
| `container` | Back-compat alias → `harnessed transparent` (muscle memory). Symlinked by `install.sh`. |
| `tools/harnessed/cli.py` (`main`) | The `harnessed-tools` console script (the assembler image entrypoint): `assemble`/`scan`/`scan-image`/`scan-image-online`/`test`. |
| `lib/egress-firewall.sh` | Runs *inside* each instance (not a host entry point) as `/usr/local/sbin/egress-firewall`. |
| `services/<name>/server.py` | A service's MCP server (e.g. `services/ping/server.py`); its own image, run host-published. |

## 10. State management

State is **default-persistent, `--fresh` to wipe** (design §9):

- **Harness state** (isolated): `projects/` + `history.jsonl` persist to a harnessed-owned host dir
  with a **legible** flattened project slug (`$XDG_STATE_HOME/harnessed/<project>/<stack>/.claude`),
  so sessions survive instance recreation and stay inspectable. `--fresh` is the throwaway path.
- **Service volumes are service-scoped & harness-independent** (`<service>-data`, e.g. `ping-data`)
  — this is what lets `claude+hindsight` and `omp+hindsight` share *one* memory. A service is a
  shared instance: one long-lived container, outlives instances (`svc up/down`); `--purge` destroys
  the volume.
- **Ephemeral state** (sessions/, caches) stays in a per-instance path.
- **Credentials** are env-only / ro-mount-only — never a profile, a committed file, or an image
  layer (same rule for Claude auth and scanner tokens).

## See also

- `docs/codebase/STRUCTURE.md` — directory layout, naming, and where to add new code.
- `docs/harnessed-design.md` — the authoritative *why* (decisions §2–§9, schemas §10–§13).
- `docs/guides/` — recipe-authoring, stacks, service-authoring, secrets, troubleshooting.
