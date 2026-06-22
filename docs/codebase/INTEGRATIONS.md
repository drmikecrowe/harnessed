# External Integrations

**Analysis Date:** 2026-06-22

`harnessed` is, at its core, an **integrator**: it composes a harness (one of
**claude / omp / opencode / gemini / antigravity / codex**), an MCP hub
(hatago), MCP servers (stdio children + HTTP sidecars), shared services, host
auth/signing, and supply-chain scanners into one isolated shared-netns group (a
podman pod, or a docker shared-netns pair — provider-abstracted by
`lib/harnessed-runtime.sh`).

The cardinal rule, repeated throughout: **no Docker-out-of-Docker** (design §15).
Every podman/docker call runs on the **host** via `"$CONTAINER_RUNTIME"`. The
assembler image only emits files; it never mounts a daemon socket.

## Container Runtime (the core integration)

**podman (preferred) or docker (fallback), rootless.** This is the *only* host
dependency and the substrate every other integration rides on.

- **Detection:** `detect_runtime()` in `lib/harnessed-common.sh` prefers
  podman, falls back to docker, exits if neither is found.
- **Rootless UID mapping:** the in-container `harnessed` user (UID 1000) maps to
  the host user so bind-mounted project/profile/credential paths are owned
  correctly. Provider-abstracted by `rt_userns_args()` in
  `lib/harnessed-runtime.sh`: podman rootless emits `--userns=keep-id` (set once
  in `lib/harnessed-mounts.sh:16`); rootless docker remaps uids daemon-side and
  emits nothing.
- **Group model (isolated stacks):** the harness container and hatago **share a
  netns** so the harness reaches hatago at `http://localhost:3535/mcp` with no
  cross-container networking. Provider-abstracted by `lib/harnessed-runtime.sh`:
  podman → a **pod** (`pod create` + `run --pod`; `--userns=keep-id` is a
  pod-level property, stripped from member args); docker → a **shared-netns
  pair** — hatago runs first, the harness joins with
  `--network container:<instance>-hatago`. Apple `container` is **not supported
  yet** (one VM+IP per container, no shared netns) — tracked follow-up (needs a
  named network + non-localhost MCP endpoint).
- **`transparent` mode is degenerate:** a single container, no pod, no hatago
  (`lib/harnessed-transparent.sh`).

### Networking model (rootless-first — the primary model)

This is load-bearing and was previously misdocumented. The authoritative sources
are `lib/harnessed-services.sh:71-127`, `lib/harnessed-isolated.sh:23-30,140-150`,
`services/ping/server.py:22-25`, and design §9.

**Shared services publish their port to `0.0.0.0` on rootless podman *pasta*
networking (NOT a bridge).** Rootless bridges are unsupported on most hosts —
podman netavark returns `create bridge: Operation not supported`. Peer pods and
instances reach a published service via the **podman host gateway
`host.containers.internal:<port>`**. This is the **primary** reachability model.

`HARNESSED_NET=<name>` is an **explicit opt-in bridge override** for
bridge-capable hosts only (DNS-by-name: `http://<service>:<port>`). It is NOT the
default, and NOT required for any normal flow. Setting it makes
`lib/harnessed-isolated.sh:147-150` create + attach the named network to the pod;
services still publish to `0.0.0.0` either way.

Two operator-side prerequisites make the host-gateway path work (both ship in the
repo):

1. **Egress-firewall allow rule for `host.containers.internal`.** Rootless
   podman exposes the host gateway at `host.containers.internal`
   (`169.254.1.2`). `lib/egress-firewall.sh:55-63` computes
   `PODMAN_GW=$(getent ahosts host.containers.internal …)` and adds an iptables
   allow rule for it — distinct from the default-route gateway. iptables is
   netns-wide, so this unblocks the whole pod, including the hatago MCP proxy
   that reaches host-published services. Without this rule the proxy path is
   blocked.
2. **FastMCP `allowed_hosts`.** A Streamable-HTTP service proxied over
   `host.containers.internal` MUST add it to
   `TransportSecuritySettings.allowed_hosts`, or FastMCP's DNS-rebinding
   protection returns `421 Misdirected Request`. Canonical implementation:
   `services/ping/server.py:22-25`; see also the "Networking note" in
   `docs/guides/service-authoring.md`.

**Docker caveats:** egress firewall is **best-effort** under rootless docker
(NET_ADMIN is limited), and shared service sidecars assume the podman
`host.containers.internal` name. The podman path is the reference implementation.

## hatago — the MCP Hub

**`@himorishige/hatago-mcp-hub@0.0.16`** (pinned, pnpm global — never npm/npx).
hatago aggregates every MCP server a stack declares behind **one**
Streamable-HTTP endpoint, so the harness's `.mcp.json` points at a single URL
instead of N stdio children. It proxies two server shapes: **stdio children**
(spawned as child processes; stdio↔HTTP bridging) and **HTTP proxies** (forwards
by URL to network-native sidecars).

- **Image:** `base/Dockerfile.hatago` (`FROM harnessed-base`). The hub is
  installed via
  `pnpm add -g "@himorishige/hatago-mcp-hub@${HATAGO_VERSION}"` with the managed
  `lib/pnpm/config.yaml` policy in effect (`base/Dockerfile.hatago:24-35`).
  `PNPM_HOME/bin` is pre-created on PATH (`:22-23`).
- **Endpoint:** `hatago serve --http --port 3535` (`base/Dockerfile.hatago:46`).
  The harness reaches `http://localhost:3535/mcp` (shared pod netns).
- **Pod member:** launched as the second pod member and **waited on** before the
  harness attaches — hatago connects its stdio children, fires
  `tools/list_changed`, THEN binds :3535; attaching before that yields an empty
  MCP connection (`lib/harnessed-isolated.sh:193-224`).
- **Config:** the per-stack `hatago.config.json` (emitted by the assembler,
  `tools/harnessed/emit.py`) is mounted **read-only** and appended to the CMD
  via `--config` (`lib/harnessed-isolated.sh:193-199`). Example from
  `profiles/tracer-time/hatago.config.json`:
  ```json
  {"version":1,"logLevel":"info","mcpServers":{"time":{"command":"uvx","args":["mcp-server-time"]}}}
  ```
- **Introspection:** the hub exposes a `hatago://servers` resource (JSON snapshot
  of connected children) used by the capability test (`tools/harnessed/capability.py`,
  design §18).

## MCP Servers (two transport shapes)

Recipes declare MCP servers in `recipes/<name>/recipe.yaml` under `mcp.servers`.
The assembler routes each to one of two shapes based on its declaration
(`tools/harnessed/assemble.py`, `tools/harnessed/emit.py`):

### stdio children (hatago wraps stdio → HTTP)

A server with `transport: stdio` + `command` is spawned **by hatago as a child
process**; hatago speaks stdio to it and HTTP to the harness. The harness never
invokes the command directly.

- **Canonical example:** `recipes/time/recipe.yaml:17-22` —
  `command: uvx`, `args: [mcp-server-time]`.
- **Baked for offline determinism:** stdio servers the hatago image must bake
  are recorded in `profiles/<stack>/baked-servers.json` (`tools/harnessed/emit.py`)
  and installed image-time. Today one is baked: **`mcp-server-time==2026.6.4`**
  via `uv tool install` (`base/Dockerfile.hatago:38-39`), so
  `uvx mcp-server-time` resolves offline at run time (egress firewall blocks the
  network).
- **uvx (not pip):** astral's runner is the convention for Python stdio MCP
  servers; uv's cache makes them resolvable offline.

### HTTP service sidecars (hatago proxies by URL)

A server declared with `service: <name>` + `transport: http` is **resolved by
the assembler to a network-native URL** (`tools/harnessed/assemble.py`, plan
04-01) by reading `services/<name>/service.yaml`. hatago proxies it by URL; the
service runs as its **own** container on a host-published port, reached via
`host.containers.internal:<port>` (the primary rootless model). Over the opt-in
`HARNESSED_NET` bridge, the DNS-by-name form `http://<service>:<port>` also
works.

- **Canonical example:** `recipes/ping/recipe.yaml:10-14` — `service: ping`
  resolves to `{url: http://host.containers.internal:8080/mcp, type: http}`
  (the host-gateway form; `http://ping:8080/mcp` is the `HARNESSED_NET` opt-in
  bridge form).

> **MCP transport note (design §14):** SSE is deprecated in the current MCP spec
> (2025-06-18) and in Claude Code. Use **Streamable HTTP**. hatago's
> stdio→HTTP wrapping is how servers that only speak stdio get exposed over
> Streamable HTTP.

## Shared Services (host-published sidecars)

A shared service is its **own image/container/volume** on a host-published port
(reachable via `host.containers.internal:<port>`; or by DNS name over the
`HARNESSED_NET` opt-in bridge on bridge-capable hosts), with a lifecycle
**independent of any instance** (design §3/§9). Multiple harnessed instances
attach to the same running service concurrently.

- **Lifecycle:** `harnessed svc up|down|list <service>` in
  `lib/harnessed-services.sh`. `--purge` destroys the named volume; without it
  the volume survives `svc down` (service-scoped persistence — the whole point).
  Isolated stacks auto-start declared services via `ensure_service_up`
  (`lib/harnessed-isolated.sh:158-169`).
- **Service-scoped volumes:** named `<service>-data` (e.g. `ping-data`), NOT
  `harnessed-data-<stack>` — this is what lets `claude+X` and `omp+X` share one
  memory.
- **`svc up`** (`lib/harnessed-services.sh:71-154`): builds the service image if
  absent (running the BLD-02 scan), creates the named volume if absent, then
  `podman run -d -p "$port:$port" --name "$service" --label harnessed-service=…
  $(rt_userns_args) -v "$volume:$data_path" … "$image"`. Publishes to `0.0.0.0`
  on rootless pasta; peers reach it via `host.containers.internal`. Waits up to
  30s for the healthcheck. Per-service secret resolution: a schema at
  `~/.config/<service>/.env.schema` resolves on the host via the shared
  `resolve_secret_env` (inert when absent) and spreads via `--env-file`
  (`lib/harnessed-services.sh:106-129`).
- **ping** (`services/ping/`) — the tracer sidecar. A minimal **FastMCP**
  streamable-http server (`services/ping/server.py`) exposing one `ping` tool
  on :8080 and a `/health` route for the container HEALTHCHECK. Notably, it
  explicitly allows `host.containers.internal:*` in FastMCP's
  `TransportSecuritySettings` (`services/ping/server.py:22-25`) because the
  rootless model proxies through that Host header, which DNS-rebinding
  protection rejects by default (421). Built from `services/ping/Dockerfile`
  (`python:3.12-slim` + `pip install "mcp[cli]"`).
- **hindsight / openbrain** — designed (design §3, §9, §16) as heavy/stateful
  sidecars (postgres+MCP). **Not yet implemented**: `services/` currently
  contains only `ping/`.

## Supply-Chain Scanners (build-time + nightly)

### Build-time gate (BLD-02)

`harnessed build <stack>` runs a **scoped** scan of exactly what that build
assembles — the stack's recipe dirs + the emitted profile, never the whole repo
— then an **image** scan of the built hatago image. Both abort on any HIGH+
(CVSS ≥ 7.0) finding (`tools/harnessed/scan.py:31`, `HIGH = 7.0`).

- **osv-scanner v2.3.8** (credential-free) — both halves:
  - source scan: `osv-scanner scan source --offline --offline-vulnerabilities`
    (`scan.py:170`), offline DB pre-seeded in the image.
  - image scan: host `podman save` →
    `osv-scanner scan image --offline … --archive` (`scan.py:326`). No daemon
    socket mounted — only the saved tar is passed read-only.
- **pip-audit 2.10.1** (credential-free) — any `requirements.txt` found by
  `rglob` in a recipe dir or the emitted profile; findings are **warnings only**
  (its JSON carries no CVSS, so it cannot gate).
- **CVSS gating** is computed in pure Python (`scan.py:72-115`) — the FIRST.org
  v3.1 base-score formula — so the HIGH decision is unit-testable and does not
  depend on scanner exit codes (which are deliberately swallowed, `scan.py`).

### Token-gated scanners (committed, warn-and-skip)

**snyk** and **Socket.dev** are wired in `tools/harnessed/scan.py` and shipped in
the `harnessed-tools` image (`tools/Dockerfile:116-125`). The contract is
**warn-and-skip**: if the token is absent, that scanner is skipped with a
warning and the build stays non-interactive; the credential-free osv-scanner +
pip-audit baseline gate always runs.

- **snyk** — `_scan_snyk` (`scan.py:226-258`), env-gated on `SNYK_TOKEN`. With
  `--severity-threshold=high`, snyk's **exit code IS the gate** (1 = HIGH+ at
  threshold → abort), unlike osv-scanner (whose exit 1 = any finding). Only
  scans targets with a `package.json`.
- **Socket.dev** — `_scan_socket` (`scan.py:261-282`), env-gated on
  `SOCKET_SECURITY_API_KEY` (or `_TOKEN`). Server-side scan; findings are
  **warnings only** (Socket has no CVSS threshold) and never abort the build.

One-time token setup: **`harnessed auth snyk|socket`**
(`lib/harnessed-secrets.sh:130-193`) runs the vendor CLI's own auth inside a
`--rm -it` tools container with `~/.config` rw-mounted so the token persists to
the host path (e.g. `~/.config/configstore/snyk.json`) and is **never captured in
an image layer** (T-05-07). `snyk auth` uses `--network=host` (its OAuth
callback binds loopback and rootless pasta port-forward cannot reach it);
`socket login` prompts for an API token (no callback).

### Nightly re-scan (SEC-04)

`lib/harnessed-rescan.sh::harnessed_rescan_images` iterates installed
`harnessed-*` images, `podman save`s each, and re-scans **online** (fresh
osv.dev DB — NOT the build-time offline DB) via `scan-image-online`
(`tools/harnessed/scan.py:342+`). The online mode is load-bearing: the offline
build-time DB only knows about CVEs at build time, so a stale-DB nightly would
see nothing new forever (RESEARCH Pitfall 6). A HIGH on one image surfaces but
does NOT abort the scan of the remaining images; the overall rc tracks any
failure. Triggers:

- **Manual:** `harnessed rescan` (`harnessed:306-315`).
- **Nightly:** `systemd/harnessed-rescan.timer` (`OnCalendar=daily`,
  `Persistent=true`) → `systemd/harnessed-rescan.service`
  (`ExecStart=%h/.local/bin/harnessed rescan`). Copy to
  `~/.config/systemd/user/`; **requires `loginctl enable-linger $USER`** or the
  timer does not fire while logged out (the user systemd instance is torn down
  on logout).

## 1Password (SSH signing + optional secrets)

- **SSH commit signing (`op-ssh-sign`)** — the 1Password CLI + desktop app are
  installed from 1Password's apt repo in `base/Dockerfile.harnessed-base:27-33`
  (CLI-only in the tools image, `tools/Dockerfile:57-68`).
- **SSH agent socket** — the default `SSH_AUTH_SOCK` source. Mounted from
  `~/.1password/agent.sock` and exported (`lib/harnessed-mounts.sh:24-27`).
- **Optional secrets resolution (design §16)** — varlock + `op` resolve
  `op(op://Vault/Item/field)` refs into env. The repo ships a ready-to-copy
  `.env.schema.example` (the `@env-spec` DSL with
  `@varlock/1password-plugin@0.3.2` + `@initOp(allowAppAuth=true)`, holding the
  `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` refs); copy it to
  `~/.config/harnessed/.env.schema` to opt in. Resolution runs **on the host**
  via `lib/harnessed-secrets.sh::resolve_secret_env` (`:51-124`), which calls
  `varlock load --format env` and spreads the resolved dotenv into the container
  as a mode-0600 temp `--env-file` (unlinked after launch). It reaches **all
  launch paths**: the isolated pod (`lib/harnessed-isolated.sh:177-192`), the
  transparent instance (`lib/harnessed-transparent.sh`), sidecar services
  (`lib/harnessed-services.sh:110-129` + `~/.config/<service>/.env.schema`), and
  the build scan. See STACK.md → Secrets.

**Resolution model (design §16):** 1Password's desktop app authorizes the `op`
CLI by *calling application* (your terminal), so **app-auth runs on the host** —
an `op` inside the throwaway container has no host app to bind the grant to and
fails ("cannot connect to 1Password app") no matter which socket is mounted. The
`~/.1password/agent.sock` mount above is the **SSH agent** (git signing), not
the `op` app-auth transport. Hosts without `varlock` fall back to in-container
resolution (`resolve_secret_env:68-86`), which then requires
`OP_SERVICE_ACCOUNT_TOKEN` (HTTPS bearer auth — no desktop app); scope that
token narrowly, since it leaks into any process sharing the env.

## Host Integration Mounts (§4a — shared by EVERY stack)

`lib/harnessed-mounts.sh::harnessed_host_integration_mounts()` is sourced by
both the transparent and isolated launchers and appends podman/docker
`-v`/`--device` flags to a shared `MOUNT_ARGS` array. These are **operational**
mounts (auth/signing/agents/firewall) — not the config-experiment surface,
which is mode-specific (§4b). Everything is conditional on the host actually
having the artifact, so a bare host still launches.

| Integration | Mount | File |
|---|---|---|
| Egress firewall script + NET_ADMIN | `lib/egress-firewall.sh` → `/usr/local/sbin/egress-firewall` ro; `--cap-add NET_ADMIN` | `lib/harnessed-mounts.sh:16,21`, applied `lib/harnessed-common.sh::apply_firewall` |
| 1Password SSH agent | `~/.1password/agent.sock` → `$CONTAINER_HOME/.1password/agent.sock`, `SSH_AUTH_SOCK` set | `lib/harnessed-mounts.sh:24-27` |
| GPG agent SSH socket (YubiKey) | `/run/user/$UID/gnupg/S.gpg-agent.ssh` → `.gnupg-sockets/S.gpg-agent.ssh` | `:30-35` |
| GPG config (YubiKey commit/SSH signing) | `~/.gnupg` ro | `:38-39` |
| YubiKey USB device | `--device /dev/bus/usb/$bus/$dev` (Yubico vendor 1050, probed via `lsusb`) | `:41-47` |
| Z.AI config (GLM models) | `~/.zai.json` ro | `:50-51` |
| Per-tool `~/.config/<tool>` dirs | e.g. nvim; from `extra-tools.txt`, with a name-remap table (`neovim→nvim`, skip-list for `ast-grep`/`markdownlint-cli2`) | `:54-68` |
| Git config | `~/.config/git` ro, else legacy `~/.gitconfig` ro | `:71-75` |
| Host machine-id | `/etc/machine-id` ro (lets Claude Code see the same machine, avoids re-auth) | `:78-79` |
| SSH keys/config | `~/.ssh` ro | `:81-82` |
| Project | `$project_path` → `$CONTAINER_HOME/<relpath>`, set as workdir | `:17-18` |

### Egress firewall

`lib/egress-firewall.sh` is the primary exfiltration defense (closes the vector
identified in agentic-AI security research). It flushes `OUTPUT`, sets default
`DROP`, and allowlists a fixed domain set (`lib/egress-firewall.sh:11-34`):

- Anthropic / Claude API: `api.anthropic.com`, `statsig.anthropic.com`
- GitHub (git, gh CLI, release downloads, raw): `github.com`, `api.github.com`,
  `codeload.github.com`, `objects.githubusercontent.com`,
  `raw.githubusercontent.com`, `uploads.github.com`, `alive.github.com`
- npm registry: `registry.npmjs.org`
- Python packages: `pypi.org`, `files.pythonhosted.org`
- mise tool manager: `mise.jdx.dev`

It then unblocks the podman host-gateway (`lib/egress-firewall.sh:55-63`,
`PODMAN_GW=$(getent ahosts host.containers.internal …)` + default-route
`HOST_GW`), DNS (port 53), loopback, and established/related. Extra domains
(e.g. a Z.AI endpoint host read from `~/.zai.json` via jq) are appended at apply
time (`lib/harnessed-transparent.sh:53-58`). Re-applied each session; idempotent
via a `/run/egress-firewall-active` flag (`lib/egress-firewall.sh:102-103`). Skip
with `--no-firewall`.

## Harnesses (the things being launched)

Exactly **one** harness per stack (design §8), selected by `harness:` in
`stack.yaml`. The canonical profile format is Claude Code; others adapt *out* of
it (`tools/harnessed/schema.py:41-48`, `HARNESS_CONFIG_DIR`).

- **claude** (`harnessed-claude:latest`) — `base/Dockerfile.harnessed-claude`
  (`FROM harnessed-base` + the official Claude Code installer). The isolated
  launcher attaches via `claude --mcp-config <profile>/.claude/.mcp.json
  --strict-mcp-config` (`lib/harnessed-isolated.sh:267-270`) so only the
  profile's hatago endpoint loads and account-synced servers never leak in.
- **omp** (`harnessed-omp:latest`) — `base/Dockerfile.harnessed-omp`. Built
  **lazily** via `ensure_omp_image` only when an `harness: omp` stack first
  launches (`lib/harnessed-common.sh`, plan 04-03 / HRN-01), so claude-only
  users never pull omp + the bridge. omp via the pre-installed
  **`@drmikecrowe/omp-claude-hooks-bridge`** extension; consumes the Claude
  profile via the bridge. Attach: `omp --profile "<instance>"`
  (`lib/harnessed-isolated.sh:241-243`).
- **opencode** (`harnessed-opencode:latest`) —
  `base/Dockerfile.harnessed-opencode` (`FROM harnessed-base`). Built **lazily**
  via `ensure_opencode_image` (HRN-02). Pinned opencode. Reads the **same**
  `.claude/skills/**/SKILL.md` + `~/.claude/CLAUDE.md` natively (no bridge, no
  re-authoring) but does NOT read `.claude/commands` or `.claude/agents`. MCP is
  wired via the image-baked `~/.config/opencode` (it ignores `.mcp.json`). Auth:
  ro mount of host `~/.local/share/opencode/auth.json`. Attach: bare `opencode`
  (`lib/harnessed-isolated.sh:244-249`).
- **gemini** (`harnessed-gemini:latest`) — `base/Dockerfile.harnessed-gemini`
  (`FROM harnessed-base`). Built **lazily** via `ensure_gemini_image` (HRN-03).
  The gemini-cli is already in `harnessed-base`; the image just bakes a global
  `~/.gemini/settings.json` whose `mcpServers` declares one remote
  (Streamable-HTTP) server → the hatago hub. Does NOT natively consume Claude
  skills/commands (profile mounted for parity). Auth: host `~/.gemini` OAuth
  creds (mounted) or `GEMINI_API_KEY`/`GOOGLE_API_KEY` env. Attach: bare `gemini`
  (`lib/harnessed-isolated.sh:250-255`).
- **antigravity** (`harnessed-antigravity:latest`, `agy` CLI) —
  `base/Dockerfile.harnessed-antigravity` (`FROM harnessed-base`). Built
  **lazily** via `ensure_antigravity_image` (HRN-04). The `agy` CLI is installed
  via the official vendor curl installer
  (`curl -fsSL https://antigravity.google/cli/install.sh | bash` — a standalone
  Go binary in `~/.local/bin`). Bakes `~/.gemini/config/mcp_config.json` whose
  `mcpServers` declares one remote server (`serverUrl`) → the hatago hub. Auth:
  `ANTIGRAVITY_API_KEY` env or one-time OAuth creds. Attach: bare `agy`
  (`lib/harnessed-isolated.sh:256-260`).
- **codex** (`harnessed-codex:latest`, OpenAI Codex CLI) —
  `base/Dockerfile.harnessed-codex` (`FROM harnessed-base`). Built **lazily** via
  `ensure_codex_image` (HRN-05). The codex-cli is already in `harnessed-base`
  (v0.139.0, `npm:@openai/codex` ships platform binaries as
  optionalDependencies — no blocked postinstall). The image bakes a global
  `~/.codex/config.toml` whose `[mcp_servers.hatago]` entry declares one remote
  (Streamable-HTTP) server → the hatago hub
  (`url = "http://localhost:3535/mcp"` — codex 0.139+ natively supports remote
  Streamable-HTTP MCP, no stdio bridge). Reads `AGENTS.md` but NOT Claude
  skills/commands (profile mounted for parity). Auth: host `~/.codex/auth.json`
  (mounted ro) or `OPENAI_API_KEY` env. Attach: bare `codex`
  (`lib/harnessed-isolated.sh:261-266`).
- **Canonical format = Claude Code** (design §8). omp consumes the **same**
  `.claude/` profile as claude via the bridge — no re-authoring. opencode also
  consumes the same profile natively (skills + CLAUDE.md/AGENTS.md only).
  gemini/antigravity/codex mount the same profile for parity but their real
  capability wiring is MCP via the image-baked config → hatago. The omp,
  opencode, gemini, antigravity, and codex base recipes (`recipes/{omp,opencode,
  gemini,antigravity,codex}/`) only **document** their extension/config
  dependencies; none contributes profile files of its own.
- **Transparent** (`stacks/transparent/`) mounts host `~/.claude`, `~/.codex`,
  `~/.config/opencode`, `~/.gemini` **live** (the degenerate,
  "my-laptop-sandboxed" case). It is the old `container` SKU; the `container`
  script is a thin alias → `harnessed transparent` (`install.sh:15` lists both
  binaries for the PATH symlink).

## Summary — what talks to what

```
HOST (podman/docker rootless, pasta networking)
  │
  ├── harnessed (bash bootstrap) ──lib/harnessed-*.sh──▶ pod create/run/exec (podman) | --network container: (docker)
  │        │
  │        ├── harnessed-tools (python assembler, emit-only) ──▶ profiles/<stack>/ + build-time scans
  │        │
  │        └── harnessed rescan ──▶ nightly ONLINE re-scan of installed harnessed-* images
  │
  ├── shared services (standalone containers, host-published 0.0.0.0:<port>)
  │        └── reached via host.containers.internal:<port>   (HARNESSED_NET bridge = opt-in)
  │            e.g. ping FastMCP :8080  (hindsight/openbrain designed)
  │
  └── group: harnessed-<stack>-<proj>  (shared netns: podman pod | docker --network container: pair)
        ├── [ harness: claude | omp | opencode | gemini | antigravity | codex ]
        │     mounts: §4a host-integration + profile (.claude/) + ro credential
        │     → harness-baked config points at http://localhost:3535/mcp
        │
        └── [ hatago hub ]  :3535
               ├── stdio children (uvx mcp-server-time, baked offline)
               └── HTTP proxies ──▶ host.containers.internal:<port>  (shared services)

SCANNERS:  build-time  osv-scanner + pip-audit (always) ▸ snyk/Socket (token, opt-in, warn-and-skip)
           nightly     osv-scanner ONLINE (SEC-04 timer) — catches post-build CVEs
SECRETS:   varlock + 1Password op  ▸  inert unless ~/.config/harnessed/.env.schema
           Claude/opencode/codex OAuth ▸ ro credential mounts (no stub secrets)
```
