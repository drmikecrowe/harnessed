# External Integrations

> Reference for the `harnessed` codebase. Covers external APIs/services, the MCP gateway
> (hatago), authentication providers, databases (none — confirmed), webhooks, image/
> vulnerability scanning, and registry interactions.
>
> **Core invariant (design §15):** the host needs only Podman. No daemon-in-container, no
> API socket is ever mounted. External network egress is **deny-by-default** inside running
> stacks (`lib/egress-firewall.sh`); every external endpoint a stack reaches must be on the
> whitelist.

---

## 1. Egress surface — what the codebase talks to

Running stacks see a **locked-down** network. `lib/egress-firewall.sh:11-34` is the complete
allow-list:

```bash
WHITELIST=(
    api.anthropic.com          # Anthropic / Claude API
    statsig.anthropic.com      # Claude telemetry/feature flags
    github.com                 # git, gh CLI, release downloads, raw files
    api.github.com
    codeload.github.com
    objects.githubusercontent.com
    raw.githubusercontent.com
    uploads.github.com
    alive.github.com
    registry.npmjs.org         # npm registry
    pypi.org                   # Python packages
    files.pythonhosted.org
    mise.jdx.dev               # mise tool manager
)
```

Plus two always-allowed targets computed at runtime: the default-route gateway (`HOST_GW`)
and the podman host-gateway `host.containers.internal` (`PODMAN_GW`, `169.254.1.2`) —
needed so pod members can reach host-published service sidecars
(`lib/egress-firewall.sh:55-63`). Extra domains (e.g. a Z.AI API host) are appended as
arguments by the launcher.

**Use this list as the source of truth** for what a running stack can contact. Adding a new
external integration that the harness must reach at runtime means adding its host here.

### Build-time egress (image builds, un-firewalled)

Image *builds* run on the host and are not behind the egress firewall, so they reach
additional endpoints to fetch installers and binaries:

| Endpoint | Reached by | Purpose |
|---|---|---|
| `claude.ai/install.sh` | `base/Dockerfile.harnessed-claude:7` | Claude Code CLI installer |
| `opencode.ai/install` | `base/Dockerfile.harnessed-opencode:31` | opencode platform binary |
| `antigravity.google/cli/install.sh` | `base/Dockerfile.harnessed-antigravity:30` | `agy` Go binary |
| `astral.sh/uv/<ver>/install.sh` | `base/Dockerfile.hatago:17` | uv/uvx (Python tool runner) |
| `mise.run` | `base/Dockerfile.harnessed-base:51`, `tools/Dockerfile:109` | mise runtime manager |
| `downloads.1password.com/linux/...` | `base/Dockerfile.harnessed-base:28-32`, `tools/Dockerfile:62-67` | 1Password CLI + desktop app (apt repo) |
| `github.com/.../osv-scanner` releases | `tools/Dockerfile:38-54` | osv-scanner static Go binary (SHA256-verified) |
| `registry.npmjs.org` | all `pnpm add -g` / `pnpm install` | JS packages |
| `pypi.org` / `files.pythonhosted.org` | `pip install` / `uv tool install` | Python packages |

---

## 2. The MCP gateway — hatago

[hatago](https://github.com/himorishige/hatago) (`@himorishige/hatago-mcp-hub@0.0.16`) is the
**single MCP aggregation point** for every isolated stack. It is the only thing the harness
container's MCP config points at.

### Architecture

A running isolated stack is a podman pod with two members sharing a netns:

```
        podman pod: harnessed-<stack>-<proj>
    ┌──────────────────────────────────────────────┐
    │  [ harness container ]  ──→  [ hatago ]        │
    │    .mcp.json → localhost:3535   MCP hub · HTTP │
    └─────────────────────────┬────────────────────┘
                              │ (hatago proxies)
                   ┌──────────┴──────────┐
                   ▼                     ▼
            stdio children        network-native URLs
            (baked in image)      (incl. shared services)
```

- **hatago** serves one **Streamable-HTTP** endpoint on port `3535` → `http://localhost:3535/mcp`
  (`base/Dockerfile.hatago:45-46`, `tools/harnessed/emit.py:25-26`). `HATAGO_ENDPOINT` is the
  constant every harness config references.
- The harness `.mcp.json` (`emit.write_mcp_json`) points at **exactly one** entry — hatago —
  never at a stdio server directly.
- hatago's own config (`profiles/<stack>/hatago.config.json`, `emit.write_hatago_config`)
  declares each server as either a **stdio child** (baked into the hatago image, spawned by
  hatago) or a **network-native proxy** (reached by URL, including shared services).

### MCP server transports (`tools/harnessed/schema.py:69-92`)

A recipe declares MCP servers via `mcp.servers[]`. Two transports:

| Transport | How hatago serves it | Baked? |
|---|---|---|
| `stdio` (default) + `command` | hatago spawns it as a child (stdio → HTTP) | **Yes** — the command + its deps must be in the hatago image |
| `http` / `sse` + `url` | hatago proxies by URL | No — reached at runtime |
| `service: <name>` | resolved to `http://host.containers.internal:<port>/mcp` | No — a shared service sidecar |

`McpServer.is_stdio_child` is the discriminator (`schema.py:89-92`). The assembler emits a
`hatago-baked.json` manifest of stdio servers so the hatago Dockerfile can bake them
(`emit.write_baked_manifest`).

### How each harness reaches hatago

Every harness is configured (baked into its image) to point one remote MCP server at the
fixed in-pod hub address:

| Harness | Config file | Shape |
|---|---|---|
| claude / omp | `.claude/.mcp.json` (emitted profile) | `{ "mcpServers": { "hatago": { "url": "…/mcp" } } }` |
| opencode | `~/.config/opencode/opencode.json` | `{ "mcp": { "hatago": { "type": "remote", "url": "…/mcp" } } }` |
| gemini | `~/.gemini/settings.json` | `{ "mcpServers": { "hatago": { "url": "…/mcp", "type": "http" } } }` |
| antigravity (agy) | `~/.gemini/config/mcp_config.json` | `{ "mcpServers": { "hatago": { "serverUrl": "…/mcp" } } }` |
| codex | `~/.codex/config.toml` | `[mcp_servers.hatago]\nurl = "…/mcp"` |

The endpoint is **always** `http://localhost:3535/mcp` because pod members share a netns.
Transparent mode is the degenerate case: no hatago, no profile — MCP comes from the host's own
config mounted live.

### Shared service sidecars

A shared service (`harnessed svc up <name>`) is its own image/container/volume on a
host-published port, reached via `host.containers.internal:<port>` (the primary model) or by
DNS name over the opt-in `HARNESSED_NET` bridge. The only implemented service is **ping**
(`services/ping/service.yaml` — a FastMCP streamable-http tracer on port 8080). A recipe
references a service via `mcp.servers[].service`; the assembler resolves it to a hatago
URL-proxy entry.

---

## 3. Authentication providers

Auth is **seeded, never baked or committed.** Every credential is a read-only bind mount or
a resolved env value; no token ever lands in an image layer or the repo.

### Harness auth (per `lib/harnessed-isolated-config.sh`)

| Harness | Credential source | Env fallback | Notes |
|---|---|---|---|
| **claude / omp** | `~/.claude/.credentials.json` (ro) + a **generated** token-free `.claude.json` stub | `CLAUDE_CODE_OAUTH_TOKEN` | The stub carries only onboarding/identity fields (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID`) — **zero** token keys. The host `~/.claude.json` blob is **never** mounted (it races with host Claude and corrupts state). |
| **opencode** | `~/.local/share/opencode/auth.json` (ro, XDG data) | `ANTHROPIC_API_KEY`, `OPENCODE_AUTH_CONTENT` | No onboarding gate; mounting the host file is sufficient. |
| **gemini** | `~/.gemini/oauth_creds.json` + `google_accounts.json` (ro) | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Google OAuth credential cache. |
| **antigravity (agy)** | **None mountable** | **None documented** | agy uses Google OAuth into the OS **system keyring (Secret Service)**. A clean-room container has no keyring daemon, so agy prompts for an interactive printed-URL login on first launch and does **not** persist across recreates. This is a known limitation of the antigravity harness in isolated mode (`base/Dockerfile.harnessed-antigravity:19-23`, `lib/harnessed-isolated-config.sh:63-70`). |
| **codex** | `~/.codex/auth.json` (ro) | `OPENAI_API_KEY` | Written by `codex login` (ChatGPT-account OAuth or API key). If absent, codex prompts to log in on launch. |

The generated Claude stub is built with `jq` (`lib/harnessed-isolated-config.sh:114-124`):

```bash
jq -n \
    --argjson oauthAccount "$oauth_account" \
    --argjson userID "$user_id" \
    --arg firstStartTime "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" \
    '{ hasCompletedOnboarding: true,
       firstStartTime: $firstStartTime,
       numStartups: 1,
       oauthAccount: $oauthAccount,
       userID: $userID }' > "$stub"
```

### Secrets resolution — varlock + 1Password (opt-in, `lib/harnessed-secrets.sh`)

The opt-in secrets subsystem resolves `op://` references in a host `.env.schema` into a
mode-0600 dotenv, spread into the container via `--env-file`. It is **inert by default**:
`resolve_secret_env` returns immediately if `$HARNESSED_SCHEMA`
(`~/.config/harnessed/.env.schema`) is absent (`lib/harnessed-secrets.sh:53`).

Two resolution paths, decided by what is available on the host:

| Path | When | Mechanism |
|---|---|---|
| **Host** (default) | `varlock` is on the host `$PATH` | `varlock load --format env`. The 1Password desktop app authorizes the `op` CLI by **calling application** (the terminal), so app-auth works on the host but **cannot** work inside a throwaway container (the agent socket there is the SSH agent, not the op app-auth transport). |
| **Headless** (fallback) | `OP_SERVICE_ACCOUNT_TOKEN` is set (no host varlock — CI, the nightly timer) | A `--rm` tools container resolves `op://` refs via HTTPS bearer auth (no desktop app, no socket). The scratch dir is mounted as `$CONTAINER_HOME` so varlock's plugin writes under a host-owned path. |

If neither is available, resolution fails with a clear error pointing at the install options
(`lib/harnessed-secrets.sh:87-92`). The resolved dotenv is **unquoted** before use
(`KEY="value"` → `KEY=value`) so `podman --env-file` reads the value, not literal quotes
(`lib/harnessed-secrets.sh:113-114`).

The `.env.schema` DSL (`@plugin(@varlock/1password-plugin@1.2.0)`, `@initOp(allowAppAuth=true)`)
is documented in `.env.schema.example`. Per-service schemas live in
`~/.config/<service>/.env.schema`.

### Scanner-token auth — snyk / socket (`harnessed auth`)

`harnessed auth snyk|socket` drives the vendor CLI's own auth inside a `--rm -it` tools
container so the token persists to the rw-mounted host `~/.config` (`auth_scanner`,
`lib/harnessed-secrets.sh:130-193`):

- **snyk** — OAuth browser flow. snyk binds `127.0.0.1:8080` *inside* the container and
  redirects the host browser there. Port publishing does **not** work under rootless pasta
  (`-p 127.0.0.1:8080:8080` hits the outward interface, not loopback → "Connection reset").
  The reliable fix is `--network=host` (scoped to this one-shot auth container only; snyk
  binds loopback so nothing is LAN-exposed). Token → `~/.config/configstore/snyk.json`.
- **socket** — prompts for an API token (no browser callback) → no host networking needed.

`--rm` guarantees no image layer captures the token; the `HOME=$CONTAINER_HOME` override is
load-bearing — without it the vendor CLI writes to the unmounted `/home/tools/.config` and
the token is lost on exit. The 1Password SSH agent socket is mounted if present so SSH-based
signing works during the auth session.

---

## 4. Databases — none

**Confirmed: there are no databases in the implemented codebase.** A search for
`postgres|sqlite|mysql|redis|mongodb` across the repo finds matches only in:
- `.claude/` skill content (the GSD framework's research/checklist templates — not harnessed code)
- `.npm/_cacache/` (npm registry metadata cache — unrelated)
- `.planning/` phase docs (discussing pnpm `better-sqlite3` as a *hypothetical* future
  `allowBuilds` entry)

The design doc (`docs/harnessed-design.md` §3, §9) references **hindsight** as a planned
"postgres + MCP" shared service and **openbrain** as another, but neither is implemented —
the only service under `services/` is `ping` (a stateless FastMCP tracer). The hatago hub and
all scanners are stateless at runtime; the only persistent state is filesystem-backed
(profiles, service volumes, host-mirrored `~/.claude/projects/`).

**Implication:** no connection strings, no DB drivers, no migrations. If a future service
needs a database, follow the sidecar pattern (`services/<name>/` with its own Dockerfile +
`service.yaml`), reached via `host.containers.internal:<port>`.

---

## 5. Webhooks — none

There are no inbound webhooks and no outbound webhook deliveries in the codebase. The
`harnessed rescan` nightly job is **timer-driven** (`systemd/harnessed-rescan.timer`,
`OnCalendar=daily`), not webhook-triggered. Scanner auth is interactive OAuth/API-token, not
webhook callback (snyk's loopback redirect is a local OAuth callback, not a registered webhook).

---

## 6. Image & vulnerability scanning

The supply-chain gate is the core security integration. It runs at three points:
**build-time** (source + image), **nightly** (online re-scan), and is gated in pure Python
at CVSS ≥ 7.0.

### The severity gate (`tools/harnessed/scan.py`)

The **only** HIGH decision point is `scan.gate()` (`scan.py:119-132`), which implements a
pure CVSS v3.1 base-score computation (`_cvss3_base`, `_roundup`) over OSV finding vectors.
`HIGH = 7.0`. A finding at or above the threshold adds its id to `highs`; the build aborts.
Below-threshold findings render as **warnings** and never fail.

```python
HIGH = 7.0  # The build ABORTS at >= HIGH; below is a warning.
```

This matters because osv-scanner's `scan` exits 1 on *any* finding with no severity flag, so
the exit code cannot be the gate — the CVSS math is pure Python over `--format json`
(`scan.py` docstring, "RESEARCH Pattern 2 / Pitfall 3").

### Scanners

| Scanner | When | Credential | Role | Abort? |
|---|---|---|---|---|
| **osv-scanner** `v2.3.8` | build (source + image, **offline**); nightly (image, **online**) | none (public DB) | Source lockfiles, vendored `node_modules`, and `podman save` image archives | Yes — HIGH ids via `gate()` |
| **pip-audit** `2.10.1` | build (source) | none | Python deps in recipe `requirements.txt`/`pyproject.toml` | No — warnings only (its JSON carries no CVSS) |
| **snyk test** `--severity-threshold=high` | build (source), env-gated | `SNYK_TOKEN` (`snyk auth`) | npm/pnpm trees | Yes — `snyk` exit 1 ⇒ HIGH ids (`_snyk_vuln_ids`) |
| **Socket.dev** `socket scan create` | build (source), env-gated | `SOCKET_SECURITY_API_KEY`/`TOKEN` (`socket login`) | Deeper supply-chain signals | No — warnings only (Socket has no CVSS threshold) |

Credentialed scanners (snyk, socket) are **env-gated**: present → use silently; missing → warn
and skip (the build stays non-interactive/reproducible for CI and the nightly timer). The
credential-free osv-scanner + pip-audit remain the baseline gate. Tokens reach the tools image
via env or `varlock`-resolved `op://` refs — never an image layer (design §7).

### Three scan entrypoints (`tools/harnessed/cli.py`)

| Subcommand | Function | Offline? | Driven by |
|---|---|---|---|
| `scan` | `run_source_scan` — scoped source/Python scan of one stack (`scan.py:285`) | Yes | `harnessed build <stack>` (BLD-02a) |
| `scan-image` | `run_image_scan` — scan a `podman save` archive (`scan.py:319`) | **Yes** (pre-seeded OSV DB) | `build_stack` (BLD-02b) |
| `scan-image-online` | `run_image_scan_online` — same, but **online** (`scan.py:342`) | **No** — drops `--offline` so osv-scanner sees newly-disclosed CVEs | `harnessed rescan` (SEC-04 nightly) |

### The offline DB (deterministic builds)

`tools/Dockerfile:37-55` pre-seeds the OSV DB into `XDG_CACHE_HOME=/opt/osv-cache` so
build-time scans run deterministically with **no** osv.dev/deps.dev hit at scan time. The DB
is seeded per-ecosystem (PyPI, npm) by a scan with `--download-offline-databases` against real
manifests; scans use `--offline --offline-vulnerabilities`. This is the "Open Q3 LOCK" — the
nightly *online* re-scan is what catches post-build CVEs.

### osv-scanner binary integrity

The static Go binary is downloaded from a pinned GitHub release and **checksum-verified
against the release `SHA256SUMS` before `chmod +x`** (`tools/Dockerfile:38-54`, threat
T-03-05 — "never trust an unverified download").

---

## 7. Registry & distribution interactions

### Container images — local-only, no registry

**There is no container registry.** Every image is built locally on the host via `podman build`
and referenced by its local tag (`harnessed-base:latest`, `harnessed-hatago:latest`, …). Images
are never pushed or pulled from a remote registry. The only "distribution" is `install.sh`,
which `git clone`s the repo and symlinks the `harnessed` / `container` scripts into `~/.local/bin`
(`install.sh:64-74`). Image lineage is local `FROM` only (design §6).

### Package registries

| Registry | Client | What's pulled |
|---|---|---|
| **npm** (`registry.npmjs.org`) | `pnpm` (never `npm`) | JS deps: hatago hub, pnpm-global CLIs (varlock/snyk/socket), web/ Astro deps, harness CLIs (via mise `npm:` backend) |
| **PyPI** (`pypi.org`, `files.pythonhosted.org`) | `pip` / `uv` | Python deps (ruamel.yaml, rich, pip-audit, `mcp[cli]`) |
| **GitHub releases** | `curl` (checksum-verified) | osv-scanner binary (`tools/Dockerfile`) |
| **GitHub repos** | `mise use -g github:...` | omp (`github:can1357/oh-my-pi@16.0.1`, `base/Dockerfile.harnessed-omp:20`) |
| **Vendor installers** | `curl \| bash` | claude, opencode, antigravity (`base/Dockerfile.harnessed-*`) — the curl-installer exception |

### Supply-chain policy enforcement on registries

`blockExoticSubdeps: true` (`lib/pnpm/config.yaml`) blocks git/tarball/non-registry subdeps at
the npm registry. `minimumReleaseAge: 1440` quarantines newly-published versions (24h cooldown)
so a compromised release isn't installed the moment it lands. `verifyStoreIntegrity: true`
content-addresses the pnpm store. `minimumReleaseAgeExclude` is the documented escape hatch
for first-party / just-published deps (used for `socket@1.1.122` in `tools/Dockerfile:102`).

---

## 8. External services NOT integrated (designed but unimplemented)

For completeness — these appear in the design doc but have **no implementation** in the repo:

- **hindsight** (postgres + MCP memory service) — referenced in `docs/harnessed-design.md` §3/§9;
  no `services/hindsight/` exists.
- **openbrain** (shared memory service) — same; design-only.
- **Apple `container` runtime** — no shared-netns/pod equivalent; tracked as a follow-up needing
  a named-network + non-localhost MCP endpoint (`lib/harnessed-runtime.sh:17-18`).

---

*Last verified against source: 2026-06-22.*
