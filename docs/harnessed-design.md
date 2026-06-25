# harnessed — Isolated, Composable Harness Stacks

> **Status:** Design spec (resolved via discuss/grill session). Architecture decisions
> (§2–§9) are **confirmed**. Schemas, repo layout, and CLI (§10–§13) are **proposed**
> and open for review. Items in §14 are **to verify during execution**.
>
> **Names:** the executable is **`harnessed`**; what it launches is a **stack** — a podman pod with
> the harness container + hatago + shared services.

## 1. Problem

A prior attempt to **merge** a curated set of skills/plugins/MCP into the host config
(`~/.agents` + `sync-plugin-links` + universal-hooks) failed: a single shared host namespace
(`~/.claude`, `~/.agents`) cannot hold every experiment at once — openbrain and hindsight
collide, per-runtime `settingSources` drift, and vendored deps pollute `~`.

**Insight:** do the merge **per container**, where each stack is isolated, so the collision
that killed the host merge disappears by construction.

## 2. Single mode: isolated

There is **one** executable, `harnessed`. Every stack shares the same base image, the same
host-integration mounts (§4), the same project mount, and host auth. Config source is always:
**auth seeded + the assembled stack profile mounted; nothing from host config** — a "clean room
with exactly what I picked."

## 3. Core model: stack = harness container + hatago + shared services

A running **stack** is composed **at runtime**, in a podman **pod** on a shared network — **not**
at build time. (`FROM` is linear inheritance + multi-stage `COPY --from`; it cannot union two
sibling systems. See §6.)

> **Provider abstraction.** The shared-netns group is runtime-abstracted by
> `lib/harnessed-runtime.sh` (`rt_*` helpers): podman uses a **pod** (`pod create` + `run --pod`,
> rootless uid via `--userns=keep-id`); docker uses a **shared-netns pair** — hatago runs first,
> the harness joins with `--network container:<instance>-hatago` (rootless docker remaps uids
> daemon-side, no `--userns`). Apple `container` has no shared-netns equivalent (one VM+IP per
> container) and is a **tracked follow-up** (needs a named network + non-localhost MCP endpoint),
> not yet supported.

            podman pod: harnessed-<stack>-<proj>
        ┌──────────────────────────────────────────────┐
        │  [ harnessed-<harness> ]  ──→  [ hatago ]      │
        │    mounts cwd + profile      MCP hub · HTTP    │
        └───────────────────────────────────────┬───────┘
                                                 │ MCP over host.containers.internal (HARNESSED_NET: opt-in)
                          ┌──────────────────────┴──────────────────────┐
                          ▼                                              ▼
                   [ hindsight ]                               [ openbrain ]
                   shared · service-scoped                     shared · service-scoped
                   own image · volume · lifecycle              own image · volume · lifecycle
```

- **harness container** — runs the harness (`claude`/`omp`/`opencode`/`gemini`/`antigravity`/`codex`), auth seeded, current folder mounted,
  stack profile mounted into the harness config dir.
- **hatago** — MCP hub. Aggregates all of the stack's MCP servers behind **one** HTTP endpoint;
  the harness container's `.mcp.json` points at `localhost:<port>`. Light `npx`/`uvx` stdio servers run as
  hatago's children (baked into the hatago image); heavy services are proxied over the network.
- **shared services** — heavy/stateful systems (hindsight = postgres+MCP, openbrain). Each is
  its **own** image/container/volume, **service-scoped and harness-independent**, with a
  lifecycle independent of any instance. Multiple harnessed instances attach to the **same** running service concurrently.

## 4. Mounts: host-integration layer + isolated config source

Two distinct mount layers that compose for every stack.

### 4a. Host-integration layer (shared by ALL stacks)

Ported verbatim from `container.sh`'s `start_new_container` — these are credentials, signing,
and agents, *not* the config-experiment surface, so they belong in every instance:

- 1Password SSH agent socket (`SSH_AUTH_SOCK`)
- GPG agent SSH socket + `~/.gnupg` (ro) — YubiKey SSH / commit signing
- YubiKey USB device passthrough (`--device`)
- `~/.ssh` (ro), git config (ro), `/etc/machine-id` (ro)
- `~/.zai.json` (ro) and per-tool `~/.config/<tool>` dirs (editor configs, etc.)
- egress firewall (`--cap-add NET_ADMIN`, `egress-firewall.sh`)
- the current project folder, mounted at the work dir

### 4b. Config source — surgical per-file mounts

Auth seeded, config from the profile via **surgical per-file mounts** — the core isolation trick:

- The real credential is **`~/.claude/.credentials.json`** (OAuth token). Mount it read-only.
  Auth credential mounts are handled by the §4a host-integration layer — never by the per-harness
  manifest (manifests list only config/skill files, never auth credential paths).
- **`~/.claude.json`** is *not* auth — it's `oauthAccount` metadata + ~450 KB of config/state
  (`projects`, `mcpServers`, caches). **Do not mount it.** **Generate** a minimal stub with only
  the fields needed to skip onboarding (see §14 — exact set to verify).
- **Surgical per-file mounts via `lib/manifests/<harness>.yaml`.** Profile assets are NOT mounted
  as a whole `profiles/<stack>/` directory. Each harness has a YAML manifest
  (`lib/manifests/claude.yaml`, `lib/manifests/omp.yaml`, etc.) with two top-level keys:
  - `profile_files`: individual filenames (e.g. `.mcp.json`, `settings.json`) mounted read-only
    from `profiles/<stack>/` into the container's harness config dir. The bash helper
    `lib/harnessed-manifest-mounts.sh` reads the manifest at launch time and applies harness-aware
    container target paths: claude/omp/opencode mount profile files to `~/.claude/<f>`;
    gemini/antigravity/codex skip profile file mounting (their MCP config is image-baked).
  - `history_dirs`: `$HOME`-relative paths bind-mounted read-write for history surfacing (e.g.
    `.claude/projects`, `.claude/todos`, `.claude/tasks` for claude).

  Why surgical? Mounting a whole directory lets host defaults (other skills, stale config, personal
  CLAUDE.md) bleed into the container — exactly the "no host defaults" invariant §4 protects.
  Individual per-file mounts make the container's config surface exactly what the profile declares,
  no more.
- Session state — `~/.claude/projects/` + `history.jsonl` — persists to the **host** by default,
  so sessions survive instance recreation and stay inspectable. The project is mounted at a stable
  in-container path (e.g. `/home/harnessed/<relpath>`) so Claude's slug is legible
  (`-home-harnessed-<relpath>`), under a harnessed-owned dir so it never pollutes the host's own
  `~/.claude`. `session_state: volume` (§12) opts into a throwaway per-instance volume instead.

Every stack is authenticated but carries **no host defaults** — exactly what was picked.

## 5. Composition unit: recipes (hand-authored, not dynamic)

A **recipe** is a hand-authored integration definition for **one** project (hindsight, gsd,
caveman, headroom, …). A **stack** is a harness + a chosen set of recipes. Nothing is resolved
at runtime; recipes are assembled ahead of time into committed artifacts.

A recipe can contribute to **two layers**:
- **MCP layer** → server entries merged into the stack's hatago config (and/or a shared service ref).
- **File-extension layer** → `skills`/`commands`/`agents`/`hooks`/`rules` in Claude-canonical form.

## 6. Image tier — `FROM` is for base lineage only

`FROM` gives **linear** inheritance; multiple `FROM`s = multi-stage build whose **last** stage is
the image, with `COPY --from=…` pulling artifacts from earlier stages. There is **no** "union two
images" operator. So systems are **not** combined via `FROM`; they are combined at runtime (§3).

Legitimate build-time images:

- `harnessed-base` — mise/node/python + common tooling → `FROM harnessed-base` → **`harnessed-claude`**, **`harnessed-omp`**, **`harnessed-opencode`**, **`harnessed-gemini`**, **`harnessed-antigravity`**, **`harnessed-codex`**.
- `hatago` — the hub + the *light* `npx`/`uvx` stdio MCP servers baked in.
- **Per heavy service** — `services/hindsight/Dockerfile`, `services/openbrain/Dockerfile`, each
  standalone, independently versioned, reusable across stacks.

## 7. Assembly — Dockerfile recipe model + supply-chain gate

A **recipe** contributes a `Dockerfile` (no `FROM` line) that the assembler concatenates into the
derived stack Dockerfile. The recipe's `recipe.yaml` carries metadata only — MCP server declarations,
harness compatibility, and a smoke-check list. Build steps live in the Dockerfile, not in YAML fields.

### Recipe = Dockerfile body

Each recipe's `Dockerfile` declares `ARG HARNESS=<default-harness>` at the top. This lets the body
reference `${HARNESS}` for harness-specific installs (e.g. `pnpm dlx @gstack/install --host ${HARNESS}`).
The assembler:

1. Strips each recipe's `ARG HARNESS` declaration (and any `FROM` line — recipes must not have one).
2. Emits `FROM harnessed-${HARNESS}:latest` as the derived Dockerfile header.
3. Concatenates recipe bodies in declaration order under that header, annotated with recipe names as comments.
4. Writes the result to `profiles/<stack>/Dockerfile.harnessed-<stack>`.

Example emitted derived Dockerfile:
```dockerfile
# Generated by harnessed assemble — do not edit.
FROM harnessed-claude:latest
ARG HARNESS=claude

# ── recipe: time ──
# (time MCP server is baked into the hatago config — no RUN steps needed)

# ── recipe: gstack (pinned) ──
ARG GSTACK_REF=v1.4.0
RUN git clone --branch ${GSTACK_REF} --depth 1 https://github.com/garrytan/gstack.git \
    ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup --host ${HARNESS}
```

### recipe.yaml declares metadata, not build steps

`recipe.yaml` carries:
- `name`, `description` — identity.
- `harnesses:` — the harnesses this recipe's installer supports. The assembler refuses to compose
  the recipe onto a stack whose harness is not listed (clean error, not a cryptic build failure).
- `mcp.servers:` — MCP server entries merged into `hatago.config.json` across all recipes in the stack.
- `expect:` — a smoke-check subset of skills/tools the capability test (§18) asks the agent about.
  Not a completeness oracle; `expect:` confirms the install landed, not that nothing extra was added.

The prior assembly model — which resolved plugins, fanned skills/commands trees into the profile, and
committed them — is superseded. Skills are image-baked by recipe Dockerfiles; the profile carries
only assembler-generated config files (`.mcp.json`, `settings.json`).

### Supply chain = pin sources in Dockerfiles + scan the derived image

**Two non-negotiables on every recipe Dockerfile:**

1. **Pin every source.** A floating ref (`--branch main`, unversioned `pnpm dlx @pkg`) is a
   validation error — the assembler refuses before any build starts. Acceptable pins: `--branch v1.4.0`,
   `pnpm dlx @pkg@1.2.3`, `ARG PKG_REF=abc123def` (commit SHA).

2. **Scan the built derived image.** After `podman build` produces `harnessed-<stack>:latest`:
   - **osv-scanner V2 (always-on, credential-free):** `osv-scanner scan image harnessed-<stack>:latest`.
     Fails on high-severity findings. Catches transitive CVEs that a source-only scan misses — the
     recipe model runs arbitrary upstream installers, so scanning the derived image is the only gate
     that sees what actually landed.
   - **Snyk container scan (warn-and-skip if no `SNYK_TOKEN`):** `snyk container test harnessed-<stack>:latest --severity-threshold=high`.
     Never prompts; build stays non-interactive.
   - **Socket.dev (warn-and-skip if no `SOCKET_SECURITY_API_KEY`):** source-scan coverage (Socket
     has no container-image mode; the recipe Dockerfile source directories are the scan target).

`harnessed build` fails on high-severity findings. A nightly job (the systemd-timer pattern) can
re-scan installed `harnessed-<stack>` images so a CVE disclosed after build still surfaces.

### Assembler output

For each stack build the assembler produces:
- `profiles/<stack>/Dockerfile.harnessed-<stack>` — the concatenated derived Dockerfile.
- `profiles/<stack>/hatago.config.json` — MCP server config assembled from `recipe.yaml mcp.servers`
  entries across all recipes.
- `profiles/<stack>/.mcp.json` and `profiles/<stack>/settings.json` — per-stack config files mounted
  surgically into the container at launch (§4b).

The host then runs `podman build --build-arg HARNESS=<agent> -t harnessed-<stack>:latest -f profiles/<stack>/Dockerfile.harnessed-<stack> .`.

### Scanner credentials (snyk / Socket.dev)

Only the credentialed scanners need this; `osv-scanner` and `pip-audit` use public DBs. Same rule
as Claude auth: **reference host creds, never bake or commit them.**

- **Present → use, silently.** Sources, in order: raw `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` env
  or host config (`~/.config/configstore/snyk.json`); **or**, if you use varlock (§16, optional), an
  `op(op://…)` ref in `~/.config/harnessed/.env.schema`. Either way it reaches `harnessed-tools` at
  launch — never an image layer.
- **Missing → warn and skip that scanner**, not an interactive prompt. `harnessed build` must stay
  non-interactive / reproducible (CI, the nightly timer), and a typed token must never land in a
  repo or image layer. The credential-free `osv-scanner` + `pip-audit` remain the baseline gate.
- **Opt-in setup:** `harnessed auth snyk|socket` runs the CLI's own `auth` inside the tool
  container and persists to the mounted host config — so a token is set deliberately, once.

### pnpm everywhere (supply-chain policy)

All JavaScript installs — **global, per-recipe, and hatago's bundled servers** — use **pnpm**, not
npm/npx. Rationale: <https://pnpm.io/supply-chain-security>. A managed pnpm config (shipped in
`harnessed-base` / `lib/`) enables:

- **`minimumReleaseAge`** — quarantine newly published versions (cooldown) so a compromised
  release isn't installed the moment it lands.
- **lifecycle scripts default-denied** — `strictDepBuilds` (live in the global config) makes
  pnpm exit non-zero on any unreviewed postinstall/build script. The curated `allowBuilds`
  except-list is **project-scoped** (pnpm-workspace.yaml / config-dependencies): pnpm v11
  rejects it from the global config, so it is deferred until a build-script package (e.g.
  esbuild) actually needs to run.
- **store integrity verification** + content-addressed store.

`minimumReleaseAge`, `strictDepBuilds`, and store-integrity ship in the managed global
`~/.config/pnpm/config.yaml` (shipped from `lib/pnpm/config.yaml`) — **not** `.npmrc`, which
is auth/registry-only in v11. (`allowBuilds` is the one exception: it belongs in each
project's `pnpm-workspace.yaml`, not the global config — verified in the phase-3 checkpoint.)

`npx <pkg>` → `pnpm dlx <pkg>`; `npm install` → `pnpm install`. **Recipe validation** (part of
`harnessed build`) flags any raw `npm`/`npx` in a recipe Dockerfile and points at the pnpm
equivalent.

## 8. Canonical format = Claude Code; omp via bridge

Claude Code format is the **single source of truth** for skills/commands/hooks/plugins. Other
harnesses adapt *out* of it:

- **claude** — native; mount directly.
- **omp** — consumes Claude-format hooks/skills at runtime via
  `claude-hooks-bridge` (`~/Programming/AI/omp-extensions/claude-hooks-bridge`) +
  `lib-pi-adapter.sh`. **No re-authoring.** The `omp` base recipe pulls these in.
- **opencode** — consumes the **same** Claude-canonical profile: it reads `.claude/skills/**/SKILL.md`
  and `~/.claude/CLAUDE.md` natively (no bridge, no re-authoring). MCP is wired via the image-baked
  `~/.config/opencode/opencode.json`, which declares one remote (Streamable-HTTP) MCP server pointing
  at the hatago hub — opencode **ignores `.mcp.json`**. Caveat: `.claude/commands` and `.claude/agents`
  are NOT consumed (skills + CLAUDE.md/AGENTS.md port directly).
- **gemini** — mounts the **same** `.claude/` profile as claude/omp/opencode (`HARNESS_CONFIG_DIR["gemini"] = ".claude"`)
  but does NOT natively consume Claude skills/commands (its native asset format differs). Capability wiring is MCP via the
  image-baked `~/.gemini/settings.json`, whose `mcpServers` points one remote (Streamable-HTTP) server at the hatago hub.
- **antigravity (agy)** — mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["antigravity"] = ".claude"`) but likewise
  does NOT natively consume Claude skills/commands. Capability wiring is MCP via the image-baked
  `~/.gemini/config/mcp_config.json`, whose `mcpServers` points one remote server (`serverUrl`) at the hatago hub.
- **codex (OpenAI Codex CLI)** — mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["codex"] = ".claude"`) but likewise
  does NOT natively consume Claude skills/commands (it reads `AGENTS.md` + its own `~/.codex/prompts` format). Capability wiring is MCP via the
  image-baked `~/.codex/config.toml`, whose `[mcp_servers.hatago]` entry points one remote (Streamable-HTTP) server at the hatago hub
  (`url = "http://localhost:3535/mcp"` — codex 0.139+ natively supports remote Streamable-HTTP MCP, no stdio bridge).

**One harness per stack.** A stack targets exactly one of `claude`, `omp`, `opencode`, `gemini`, `antigravity`, *or* `codex`, never two at once.

## 9. State & lifecycle

- **Default persistent, `--fresh` to wipe.** Accumulation is the *value* of a memory system;
  `--fresh` gives a clean-room comparison run (throwaway volume).
- **Service volumes are service-scoped & harness-independent** — `hindsight-data`, not
  `harnessed-data-<stack>`. This is what lets `claude+hindsight` and `omp+hindsight` share **one**
  memory.
- **Shared instance, concurrent.** One long-lived `hindsight` container, owned by the *service*
  not any instance; postgres serves both instances at once. An instance starts it if absent; it
  outlives instances (`harnessed svc up/down`). The service **publishes its port to `0.0.0.0`**
  and peers reach it via the podman host gateway **`host.containers.internal:<port>`** (the
  primary reachability model); the `harnessed-net` bridge + DNS-by-name is the **`HARNESSED_NET`
  opt-in** for bridge-capable hosts (a rootless bridge is unsupported on most hosts — netavark
  "Operation not supported").
- **Harness-state** — `projects/` + `history.jsonl` persist to the **host** by default
  (harnessed-scoped, path-mirrored for a stable slug; `session_state: volume` for throwaway).
  Other ephemeral state (`sessions/`, caches) stays in a per-instance volume.

### Operator prerequisites for the host-gateway reachability model

The publish + host-gateway model above depends on two operator-side controls that already ship
in the repo. They are documented here as **prerequisites**, not implementation details:

1. **Egress-firewall allow rule for `host.containers.internal`.** Rootless podman exposes the
   host gateway at `host.containers.internal` (`169.254.1.2`). `lib/egress-firewall.sh:55-63`
   computes `PODMAN_GW=$(getent ahosts host.containers.internal …)` and adds an iptables allow
   rule for it — distinct from the default-route gateway. Without this rule the proxy path is
   blocked (iptables is netns-wide, so it gates hatago too).
2. **FastMCP `allowed_hosts`.** A Streamable-HTTP service proxied over
   `host.containers.internal` MUST add it to `TransportSecuritySettings.allowed_hosts`, or
   FastMCP's DNS-rebinding protection returns `421 Misdirected Request`. Canonical implementation:
   `services/ping/server.py:19-25` (commit `6f6c1b3`); see also the "Networking note" in
   `docs/guides/service-authoring.md`.

---

## 10. Proposed: repo layout

```
code-container/
  harnessed                    # Python CLI entry point (pipx install / uvx harnessed); see §15
  .env.schema.example          # varlock secrets template → ~/.config/harnessed/.env.schema (§16)
  tools/                       # harnessed-tools Python package: CLI + assembler
    pyproject.toml             # [project.scripts] harnessed = "harnessed.launcher:app"
    harnessed/                 # launcher, cli, assemble, schema, emit, scan, paths
  base/
    Dockerfile.harnessed-base    # mise/node/python + common tooling
    Dockerfile.harnessed-claude  # FROM harnessed-base + claude install
    Dockerfile.harnessed-omp     # FROM harnessed-base + omp install
    Dockerfile.hatago          # hatago + light pnpm-dlx/uvx MCP servers
  services/                    # heavy/stateful sidecars, each its own image
    hindsight/Dockerfile
    openbrain/Dockerfile
  recipes/                     # hand-authored per-integration definitions
    omp/recipe.yaml            # base recipe: claude-hooks-bridge + pi-adapter
    hindsight/recipe.yaml
    gsd/recipe.yaml
    caveman/recipe.yaml
  stacks/                      # authored stack manifests (harness + recipes)
    claude-openbrain-headroom-caveman/stack.yaml
  profiles/                    # GENERATED + committed; mounted into the harness container
    claude-openbrain-headroom-caveman/
      .mcp.json                # hatago endpoint (at profile root, NOT in .claude/)
      settings.json
      hatago.config.json
  lib/                         # runtime bash injected into instances (NOT the assembler — see tools/)
    egress-firewall.sh         # iptables allow for host.containers.internal gateway
```

Relationship: `recipes/` (inputs) + `stacks/<name>/stack.yaml` (composition) → **assemble** →
`profiles/<name>/` (committed output, mounted) + hatago config + ensured images.

## 11. Proposed: recipe schema (`recipes/<name>/recipe.yaml`)

```yaml
name: hindsight
description: Hindsight long-term memory (postgres + MCP)

# --- MCP layer ---
mcp:
  servers:
    - name: hindsight
      service: hindsight        # references services/hindsight → shared sidecar
      url_env: HINDSIGHT_URL    # optional env injected into the instance

    # light server alternative (hatago runs it as a child, wraps stdio→HTTP):
    # - name: fetch
    #   command: uvx
    #   args: ["mcp-server-fetch"]
    #   transport: stdio

# --- File-extension layer (Claude-canonical) ---
plugins:                        # vendored via vendor-plugin
  - marketplace: hindsight
    plugin: hindsight-memory
    # or: { url: ..., sha: ..., subdir: ... }

skills:                         # standalone skill dirs shipped by this recipe
  - path: skills/hindsight-docs

hooks:
  event_dir: hooks              # NN-name.sh handlers grouped under <Event>.d/

# Dependencies — uv for Python, pnpm for Node (never npm/npx — see §7). Usually AUTO-DETECTED
# from a vendored plugin's own files; declare here for standalone recipes / overrides.
deps:
  python: pyproject.toml        # requirements.txt → `uv pip install -r`
                                # pyproject.toml   → `uv venv` + `uv pip install -e .`
  node: package.json            # → `pnpm install` (managed supply-chain config)
```

`omp` base recipe:

```yaml
name: omp
description: omp/pi base — consume Claude-format hooks/skills

extensions:                     # omp-native extensions installed into the instance
  - package: npm:@ryan_nookpi/pi-extension-claude-hooks-bridge
```

## 12. Proposed: stack manifest (`stacks/<name>/stack.yaml`)

```yaml
name: claude-openbrain-headroom-caveman
harness: claude               # claude | omp | opencode | gemini | antigravity | codex  (exactly one)
permissions: yolo             # prompt (default) | yolo — writes per-harness skip-permission
                              #   config (Permissions.md) into the profile; safe in an isolated instance

recipes: [openbrain, headroom, caveman]
services: [openbrain]         # shared services attached by reference

state:
  persist: true               # default; `--fresh` overrides at runtime
  session_state: host         # host (default — projects/history persist, inspectable) | volume
```

## 13. Proposed: CLI surface

```
harnessed <stack> [path]      # start/attach a stack against cwd (or path), then exec the harness
harnessed build <stack>       # assemble recipes → profile + images (build-time)
harnessed install <stack>     # write ~/.local/bin/<stack> launcher shim (see below)
harnessed uninstall <stack>   # remove the launcher shim
harnessed --fresh <stack>     # start with empty state volumes
harnessed new <stack> --harness claude --recipes a,b,c   # scaffold a stack manifest
harnessed list                # stacks + running instances
harnessed stop <stack>
harnessed rm <stack>
harnessed clean               # remove built profiles from XDG data dir
harnessed svc up <service>    # start a shared service (publishes its port; peers reach it via host.containers.internal, or by DNS name under HARNESSED_NET)
harnessed svc down <service>
harnessed svc list
harnessed auth snyk|socket    # one-time: set a scanner token (persisted to host config)
```

**Naming/identity (proposed):**
- pod: `harnessed-<stack>-<projhash>` — same stack runnable across projects without recreate
  (bind mounts are fixed at creation, so the project is part of identity).
- shared services: global by name (`hindsight`), reached via the host gateway `host.containers.internal:<port>` (or by DNS name over the `HARNESSED_NET` bridge on bridge-capable hosts).

### Generated launcher shim (`harnessed install`)

`harnessed install <stack>` writes an executable `~/.local/bin/<stack>` so you can launch an instance
by name from anywhere (mirrors the repo's existing `install.sh`, which puts `container` on PATH):

```bash
#!/usr/bin/env bash
# generated by `harnessed install claude-openbrain-headroom-caveman`
HARNESSED_PATH=/home/you/Programming/.../harnessed     # abs path to the harnessed executable
HARNESSED_NAME=claude-openbrain-headroom-caveman       # the stack to launch
exec "$HARNESSED_PATH" "$HARNESSED_NAME" "$@"           # "$@" forwards an optional project path
```

Then `claude-openbrain-headroom-caveman [path]` from any directory starts that instance.
`harnessed uninstall <stack>` removes the shim.

## 14. Open / to verify during execution

- **Minimal `.claude.json` stub fields.** Boot an instance and confirm no re-login/onboarding prompt.
  Candidate set: `oauthAccount`, `userID`, `hasCompletedOnboarding` (+ possibly `firstStartTime`,
  `numStartups`). [INFERENCE — verify empirically.]
- **Per-server MCP transport.** Which servers already speak Streamable HTTP vs need hatago's
  stdio→HTTP wrapping (hindsight already runs as postgres+MCP, likely network-native).
- **Intra-stack collision policy.** Confirm fail-fast (reuse `sync-plugin-links`' conflict exit)
  is the desired behavior vs last-wins/namespacing when two recipes ship the same skill/command name.
- **Harness config mount points.** Exact target paths per harness (claude `~/.claude/...`;
  omp config dir) for the profile mount. *(Resolved, HRN-02)* opencode mounts the **same** `.claude/`
  profile as claude/omp (`HARNESS_CONFIG_DIR["opencode"] = ".claude"`), plus a baked
  `~/.config/opencode/opencode.json` MCP config and a read-only `~/.local/share/opencode/auth.json`.
- *(Resolved, HRN-03 — gemini)* gemini mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["gemini"] = ".claude"`); the
  gemini-cli is already installed and working in `harnessed-base` (v0.46.0, pure-JS, no broken postinstall), so the
  `harnessed-gemini` image just bakes a global `~/.gemini/settings.json` whose `mcpServers` points one remote (Streamable-HTTP)
  server at `http://localhost:3535/mcp`. Auth: host `~/.gemini` OAuth creds (mounted) or `GEMINI_API_KEY`/`GOOGLE_API_KEY` env.
- *(Resolved, HRN-04 — antigravity)* antigravity mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["antigravity"] = ".claude"`); the
  `agy` CLI is installed via the official vendor curl installer (`curl -fsSL https://antigravity.google/cli/install.sh | bash` — a standalone Go binary in `~/.local/bin`). The `harnessed-antigravity` image bakes a `~/.gemini/config/mcp_config.json` whose `mcpServers` points one
  remote server (`serverUrl`) at `http://localhost:3535/mcp`. Auth: `ANTIGRAVITY_API_KEY` env or one-time OAuth creds.
- *(Resolved, HRN-05 — codex)* codex mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["codex"] = ".claude"`); codex-cli
  is already installed and working in `harnessed-base` (v0.139.0, `npm:@openai/codex` ships platform binaries as optionalDependencies —
  no blocked postinstall), so the `harnessed-codex` image just bakes a global `~/.codex/config.toml` whose `[mcp_servers.hatago]` entry
  points one remote server (`url = "http://localhost:3535/mcp"`) at the hatago hub (codex 0.139+ natively supports remote Streamable-HTTP MCP —
  no stdio bridge). Auth: host `~/.codex/auth.json` (mounted ro) or `OPENAI_API_KEY` env.
- **hatago placement.** Confirmed: in the pod over HTTP (not stdio inside the harness container) to keep npx/uvx out of
  the harness container — re-verify once a real stack is built.
- **Editor/tool configs in isolated mode.** §4a mounts `~/.config/<tool>` (nvim, etc.) for all
  stacks as operational. Confirm that's wanted in `isolated` instances, or gate behind a flag if a
  truly empty environment is ever needed.
- **Host-projects scope.** Does `session_state: host` write the host's own `~/.claude/projects/`
  (full continuity with host claude) or a harnessed-owned dir (`~/.harnessed/projects/`) to keep
  instance sessions separate? (Recommendation: harnessed-owned.)
- **Container home path.** `/home/harnessed/<relpath>` (vs `container.sh`'s `/container/$USER`)
  for a legible, stable project slug — confirm it doesn't break the harness installs.
- **pnpm rollout (resolved, phase 3).** mise routes its `npm:` backend through pnpm
  (`npm.package_manager=pnpm`, confirmed in the harnessed-base build). `minimumReleaseAge=1440`
  + `strictDepBuilds` (default-deny) ship in the global config. `allowBuilds` is project-scoped
  (pnpm-workspace.yaml) — v11 rejects it globally — so the allowlist is deferred until a
  build-script package (esbuild) actually needs to run.
- **`CLAUDE_CONFIG_DIR` relocation.** Verify whether it relocates `~/.claude.json` (not just the
  `.claude/` dir). If yes, both modes can point Claude at a per-instance config dir instead of
  copy-on-start, fully decoupling container state from the host file. [INFERENCE — verify.]

## 15. Proposed: implementation — Python CLI (pipx/uvx) + podman

**Host dependencies: podman/docker + Python (via pipx or uvx).** `harnessed` is distributed as a
Python package; the only additional host tool is podman.

- **Install:** `pipx install harnessed` (persistent, on PATH) or `uvx harnessed` (zero-install, runs
  the latest published version). `pipx` installs into an isolated venv; no host Python pollution.
- **`harnessed` Python CLI (Typer).** All launch/build/list/stop logic lives in
  `tools/harnessed/launcher.py` as a Typer CLI. `os.execvp` is used for the interactive attach so
  the TTY is native with no tunneling.
- **Assembly (build time).** `harnessed build <stack>` runs the assembler in-process: parse/validate
  YAML, emit `.mcp.json` + `settings.json` + `hatago.config.json` into
  `$XDG_DATA_HOME/harnessed/profiles/<stack>/`, then drives `podman build` for the derived image.
  All assembly logic lives in the Python package — no separate container image needed.
- **Profile location.** Profiles live in `$XDG_DATA_HOME/harnessed/profiles/<stack>/` (defaults to
  `~/.local/share/harnessed/profiles/<stack>/`). `harnessed clean` removes them.
- **Podman is invoked directly on the host.** No API socket, no DooD, no host-absolute-path footgun.
  The launcher builds mount args with host-absolute paths by construction.

**Why no DooD.** Separating "generate the build/run inputs" (the assembler, in-process Python) from
"execute `podman build`/`podman run`" (host podman subprocess) removes every cost of driving the
daemon from inside a container:

- **No API socket to mount, no `CONTAINER_HOST`/`DOCKER_HOST`.** podman is invoked directly on the host.
- **No host-absolute-path footgun.** The launcher runs on the host, so `$HOME`/`$PWD`/project paths
  are host-native by construction — the classic DooD bind-path gotcha cannot occur.
- **Clean TTY for free.** `os.execvp` on the host process gives native TTY with no tunneling.

Net install: `pipx install harnessed` (or `uvx harnessed` for zero-install); first `harnessed build`
assembles the profile and builds the container images. Podman/docker + pipx/uvx are the only host deps.

**Runtime abstraction (provider-agnostic isolated mode).** The shared-netns group is abstracted
by `lib/harnessed-runtime.sh` (`rt_*`): podman → pod; docker → shared-netns pair
(`--network container:<hatago>`); Apple `container` not yet (tracked). The harness-matrix UAT —
`tools/uat/phase-06.sh`, run via `./tools/uat/run-uat.sh 6` (`--quick` = manifest/validation only) —
is the systematic cross-harness proof and the regression gate for the provider port: one capability
test per supported harness over the `<harness>-time` proof stacks, plus a fast manifest check.

## 16. Proposed: secrets — varlock + 1Password (optional)

**varlock is optional — harnessed works fully without it.** It's an opt-in secrets source: if you
use it, secrets resolve from **1Password** instead of loose files. varlock reads a `.env.schema`
(`@env-spec` DSL) whose secret values are `op(op://Vault/Item/field)` references, validates them, and
injects the resolved values into a process (`varlock run -- <cmd>`, or `varlock load --format env`
to emit the dotenv, which is what harnessed uses — see below). Copying the shipped
`.env.schema.example` is what turns it on; users who skip it lose nothing else.

**Schema locations (XDG):**

- `~/.config/harnessed/.env.schema` — harnessed-level secrets (e.g. `SNYK_TOKEN`,
  `SOCKET_SECURITY_API_KEY`). The repo ships **`.env.schema.example`** to copy here.
- `~/.config/<service>/.env.schema` — per-service secrets (e.g. `~/.config/hindsight/.env.schema`),
  loaded when that service starts (`harnessed svc up <service>`).
- (optional, later) per-stack overrides referenced from `stack.yaml`.

**How harnessed uses it:**

- On launch, `harnessed` checks for a relevant `.env.schema`. **Present (opt-in) →** resolution runs
  `varlock load --format env` **on the host**; the resolved dotenv is written to a mode-0600 temp
  env-file that the launcher spreads into the container (`--env-file`, unlinked after launch). This
  reaches **all** launch paths — the isolated pod, per-service sidecars
  (`~/.config/<service>/.env.schema`), and the build scan. **Absent (the default) →** plain host env
  passthrough (the §7 scanner present/skip logic still applies); with no schema, varlock is never
  invoked.
- **App-auth runs on the host, not in the container.** 1Password's desktop app authorizes the `op` CLI
  by *calling application* — the user's terminal. An `op` running inside a throwaway container has no
  host app to bind the grant to, so app-auth (`@initOp(allowAppAuth=true)`) fails there ("cannot
  connect to 1Password app") regardless of which socket is mounted. The `~/.1password/agent.sock`
  mounted in §4a is the **SSH agent** (for git commit signing), **not** the `op` app-auth transport.
  So varlock + `op` run on the host; the resolved env is what crosses into the container.
- The in-container path is the **headless fallback**, used only when the host has no `varlock` (e.g.
  CI, the nightly timer): there the schema resolves inside a `--rm` tools container with
  `OP_SERVICE_ACCOUNT_TOKEN` (HTTPS bearer auth — no desktop app, no app-auth, no socket). It stays
  **inert unless a schema exists.**
- Resolved secrets are injected as **env only** — never written to the repo, a committed profile, or
  an image layer (same rule as Claude auth).

## 17. Proposed: documentation (first-class deliverable)

Docs are a **gated deliverable, not an afterthought** — `harnessed` is a tool other people (and
future-you) must operate. Required surface, by audience:

- **README.md** — what `harnessed` is, install (`pipx install` / `uvx harnessed`), first-run
  build, a 60-second quickstart.
- **docs/harnessed-design.md** (this file) — architecture + decisions; the source of truth for *why*.
- **Recipe authoring guide** — writing `recipes/<name>/recipe.yaml`: MCP servers, file extensions,
  deps, the Claude-canonical rule, the pnpm rule — with one worked example end to end.
- **Stack guide** — composing recipes into `stacks/<name>/stack.yaml`; `permissions` /
  `session_state`; `harnessed install`.
- **Secrets setup** — varlock + 1Password (§16): copying `.env.schema.example`, `op(op://…)` refs.
- **Service authoring** — adding a heavy sidecar under `services/` (image + `.env.schema`).
- **Troubleshooting / ops** — podman socket, first-run build, auth/onboarding, `--fresh`,
  inspecting host-persisted sessions.

Cadence: each section lands **with** the feature it documents (a feature isn't "done" until its docs
exist), per this repo's existing AGENTS.md / README conventions. This design spec stays current as
decisions change (as it has through this session).

## 18. Testing — integration only, behavior through the instance

Per the project's TDD philosophy (`tdd` skill): **test behavior through the public interface, and
write tests that survive refactors.** For harnessed the public interface is the **running instance**, and
the behavior is "the instance exposes exactly the MCP servers / skills / commands its stack declares."

- **No assembler unit tests.** Testing assembler internals couples to implementation and breaks on
  refactor — the anti-pattern the TDD skill warns against. The assembler is covered *transitively*:
  wire the wrong thing and the capability test fails.
- **The stack manifest is the test oracle.** Expected capabilities (`recipes` → MCP servers +
  skills/tools; `services`) are derived from `stack.yaml` + its recipes; the test asserts the live
  instance matches. It reads like a spec: "`gstack-time` exposes MCP `time` and skills `review`, `qa`."

**Two-oracle capability test (per stack):**

The capability test uses two complementary oracles that prove different things:

**Oracle 1 — Structured MCP probe (deterministic).** Hit hatago's `hatago://servers` resource — a
JSON snapshot of the connected child servers behind the hub — and/or `claude mcp list`. Assert that
every `mcp.servers` entry declared in the stack's recipes appears as connected. No model call; fast
and deterministic.

**Oracle 2 — Un-primed agent probe (behavioral).** Ask the harness, headless, what capabilities it
has — deliberately NOT priming it with the expected list. The prompt names the `expect:` skills/tools
from the recipe PLUS a **decoy** capability (a name that exists in neither the recipe nor the image).
The agent must report which it has and which it lacks, without the test telling it which are real.

```bash
podman exec <container> claude -p 'You have a set of skills and tools available. For EACH name below, answer "have" or "missing" — do not assume; check what is actually loaded.

office-hours, plan-ceo-review, review, qa, ship, browse, <decoy-not-installed>

Respond as JSON: {"have": [...], "missing": [...]}'
```

**Negative control (anti-sycophancy gate).** The decoy MUST appear in `missing`. If the agent
claims the decoy is present, the test exits with status **INVALID** — distinct from a normal
capability-failure non-zero exit. INVALID means priming/sycophancy was detected: the model is
hallucinating agreement, not reporting what it actually loaded. An INVALID result causes the run to
fail regardless of how all other capabilities scored.

Why un-primed with a negative control? Naming expected capabilities in a "respond YES" prompt primes
the model to confirm capabilities it never loaded. The decoy closes that hole: a model that actually
checked its loaded skills gets the decoy right; a model hallucinating agreement claims it.

**Assertion logic:**
1. Oracle 1: assert each `mcp.servers` entry appears in `hatago://servers` — fail if not connected.
2. Oracle 2: assert decoy is in `missing` → INVALID if it is in `have`; assert each `expect:` entry is in `have` — fail any that appear in `missing`.

**Capability report — the test output is a user artifact.** `harnessed test <stack>` writes
`profiles/<stack>/capability-report.md` after every run, rendering a per-capability table showing
✓/✗ for each MCP server and `expect:` entry, plus an INVALID banner when priming is detected:

```
## gstack-time — capability report
| capability      | kind  | status      |
|-----------------|-------|-------------|
| time            | mcp   | ✓ connected |
| office-hours    | skill | ✓ present   |
| plan-ceo-review | skill | ✓ present   |
| review          | skill | ✓ present   |
| qa              | skill | ✓ present   |
| ship            | skill | ✓ present   |
| browse          | tool  | ✓ present   |

INVALID: agent claimed decoy capability '<decoy>' — sycophancy/priming detected.
```

`harnessed build` renders it with `rich` (already in the tools image; markdown → terminal); CI
consumes the same structured result as the assertion. One mechanism, two audiences — the user sees
how complete/healthy the build is, CI sees green/red.

**Build harnessed itself in vertical slices** (tracer bullets, not horizontal): the first slice is a
minimal stack — one harness + one MCP server + one skill — with its capability test green end to end
(assemble → run → assert). Then add recipes one at a time, each with its own red→green capability
test. Never "write all recipes, then all tests."

**Honest tradeoff:** integration-only means an assembler bug surfaces as a capability failure, not a
pinpointed unit failure — coarser to debug. Mitigate with clear assembler errors (e.g. pin-validation
rejections with the offending line) so a failed build says *what* it couldn't wire.
