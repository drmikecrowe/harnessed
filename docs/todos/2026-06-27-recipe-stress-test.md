# Recipe Stress-Test: 11 Real-World Packages

> [!WARNING]
> **Planning artifact — pre-dates the host-native restructure. Snippets are illustrative ONLY.**
> The `recipe.yaml` / `Dockerfile` examples below use the **old schema** and will not build:
> `harnesses:` field (removed — recipes are harness-independent), `FROM harnessed-claude:latest` and
> `ARG HARNESS=` in recipe Dockerfiles (forbidden — the assembler prepends them), `expect.tools:`
> (not a real kind — it's `skills`/`commands`/`plugins`/`mcp`), and `recipes/` paths (now
> `catalog/recipes/`). For current syntax see [recipe-authoring.md](../guides/recipe-authoring.md).
>
> **What's still valuable:** the classification matrix, per-package install commands / data models,
> the Architecture Gaps, and the Considerations. The gaps were re-audited against the live code on
> 2026-06-27 — the confirmed ones (settings.json merge, persistent data folders, multi-container
> services) are tracked in [immediate.md](immediate.md); the rest closed as not-gaps.

> **Purpose:** validate the recipe architecture (`.planning/RECIPE-ARCHITECTURE-MILESTONE.md`)
> against real packages. Each package is classified by recipe type, data model, and the specific
> challenges it surfaces. Gaps in the architecture are collected at the end.

---

## Classification Matrix

| Package | Type | Runtime | MCP? | Hooks? | Data store | Recipe shape |
|---|---|---|---|---|---|---|
| **serena** | MCP server | Python (uvx) | stdio | no | `.serena/` per-project | MCP recipe |
| **agentmemory** | MCP server + memory | Node (npm) | **HTTP :3111** | **yes (12)** | SQLite (0 external DBs) | **service + recipe** |
| **headroom** | compression proxy/MCP | Python (pip) | stdio or proxy | no | CCR cache (local files) | MCP recipe |
| **gbrain** | brain/MCP + daemon | Bun (TypeScript) | stdio + HTTP | no | PGLite or Postgres | **service + recipe** |
| **solidspec** | CLI + skills | Rust (cargo) | no | no | spec files in project | skills recipe |
| **codebase-memory-mcp** | MCP server | **C binary** | stdio | no | SQLite `.codebase-memory/` | MCP recipe (binary) |
| **context-mode** | MCP + hooks | Node (npm) | stdio | **yes (6)** | SQLite FTS5 | **MCP + hooks recipe** |
| **tokensave** | MCP server | Rust (cargo) | stdio | git hooks | libSQL `.tokensave/` | MCP recipe |
| **caveman** | skills only | Node (install) | no | auto-activate | none | skills recipe |
| **hindsight** | service sidecar | Docker (postgres) | network-native | no | Postgres volume | **existing service** |
| **hyperpowers** | skills + hooks | Shell/Markdown | no | **yes** | task docs in project | skills recipe |

---

## Per-Package Analysis

### 1. serena — semantic code intelligence MCP

**Repo:** `github.com/oraios/serena` · Python · MIT · 25.7K stars

**What it is:** MCP server providing IDE-level semantic code retrieval, editing, refactoring. Uses
language servers (LSP) for 40+ languages. Has a per-project memory system (`.serena/memories/`).

**Install:** `uvx --from git+https://github.com/oraios/serena serena start-mcp-server` (or
`pip install serena && serena start-mcp-server`).

**Recipe:**
```yaml
# recipes/serena/recipe.yaml
name: serena
description: Semantic code intelligence — IDE-level retrieval, editing, refactoring via LSP.
harnesses: [claude, omp]
mcp:
  servers:
    - name: serena
      command: uvx
      args: [--from, git+https://github.com/oraios/serena@v1.2.0, serena, start-mcp-server, --context, ide-assistant]
      transport: stdio
```
```dockerfile
# recipes/serena/Dockerfile
FROM harnessed-claude:latest
# No build step needed — uvx resolves at runtime via hatago.
# Language servers install lazily on first use (serena auto-installs them).
```

**Data model:** `.serena/` in the project directory — project config (`project.yml`) + memories
(`memories/*.md`) + language server cache. Persists via the project mount. Shared across stacks
that work on the same project.

**Challenge — language server binaries:** Serena auto-installs language servers on first use
(`pip install` / `npm install` per language). These need network access at runtime (or pre-baking
in the image). For offline-capable stacks, the recipe Dockerfile could pre-install common language
servers. For online stacks, serena handles it at runtime.

**Verdict:** Clean fit. stdio MCP server, hatago child. No hooks, no service. The only subtlety
is language server installation (runtime vs bake).

---

### 2. agentmemory — persistent memory server

**Repo:** `github.com/rohitg00/agentmemory` · TypeScript · Apache 2.0 · 23.8K stars

**What it is:** Persistent memory for AI coding agents. 53 MCP tools, 12 auto hooks, 15 skills.
Runs its own HTTP server on :3111. Built on the iii engine. Zero external databases (embedded).

**Install:** `npm install -g @agentmemory/agentmemory && agentmemory` (starts server on :3111).

**This package breaks the mold.** It's NOT a stdio MCP server — it's a long-running HTTP server
with its own port. It also installs hooks (PreToolUse, PostToolUse, SessionStart, etc.) and skills.
Three integration surfaces: MCP (HTTP), hooks, skills.

**Recipe shape — service + recipe:**
```yaml
# recipes/agentmemory/recipe.yaml
name: agentmemory
description: Persistent memory for AI coding agents — 53 MCP tools, auto hooks, session recall.
harnesses: [claude, omp]
mcp:
  servers:
    - name: agentmemory
      service: agentmemory          # → network-native, hatago URL-proxies to the service
      transport: http
      url: http://agentmemory:3111/mcp    # DNS name within the runtime group
hooks:
  # Merged into settings.json (hook scripts are image-baked by the Dockerfile)
  PreToolUse: [{ matcher: "*", command: "agentmemory-hook pre-tool" }]
  PostToolUse: [{ matcher: "*", command: "agentmemory-hook post-tool" }]
  SessionStart: [{ matcher: "*", command: "agentmemory-hook session-start" }]
expect:
  tools: [agentmemory]              # the server binary
  skills: [memory-recall]           # a smoke-check skill
```

The service definition (own image, own volume):
```yaml
# services/agentmemory/service.yaml
name: agentmemory
image: ghcr.io/rohitg00/agentmemory:latest    # or built from the recipe Dockerfile
port: 3111
volume: agentmemory-data
```

**Data model:** SQLite embedded store. Must persist across sessions (the whole point is persistent
memory). The service volume (`agentmemory-data`) handles this.

**Surfaces GAP 1 (HTTP-native MCP) and GAP 2 (hooks registration).** See Architecture Gaps below.

---

### 3. headroom — context compression

**Repo:** `github.com/headroomlabs-ai/headroom` · Python+Rust · Apache 2.0 · 47.8K stars

**What it is:** Compresses tool outputs, logs, RAG chunks before they reach the LLM. 60–95% fewer
tokens. Three modes: library, proxy, MCP server.

**Install:** `pip install "headroom-ai[all]"` or `npm install headroom-ai`.

**Recipe (MCP mode — simplest):**
```yaml
name: headroom
description: Context compression — 60-95% fewer tokens via smart routing + AST/code/prose compressors.
harnesses: [claude, omp]
mcp:
  servers:
    - name: headroom
      command: headroom
      args: [mcp]
      transport: stdio
```

**Challenge — the proxy mode.** Headroom can also run as a proxy (`headroom proxy --port 8787`)
that intercepts LLM API calls and compresses them in-flight. This is architecturally different
from an MCP server — it's a network intermediary between the agent and the LLM provider. Harnessed
doesn't currently model this (the harness talks directly to the LLM). Supporting proxy mode would
require routing the harness's LLM traffic through headroom, which is a network-level change.

**Verdict:** MCP mode is a clean fit (stdio, hatago child). Proxy mode is out of scope for now —
it requires a network-intermediary model that harnessed doesn't have.

---

### 4. gbrain — knowledge brain

**Repo:** `github.com/garrytan/gbrain` · TypeScript (Bun) · MIT · 23.9K stars

**What it is:** A knowledge brain for AI agents — synthesis, graph traversal, gap analysis. Can
run as stdio MCP (`gbrain serve`) or HTTP MCP (`gbrain serve --http`). Uses PGLite (embedded
Postgres, no server) or external Postgres/Supabase at scale.

**Install:** `bun install -g github:garrytan/gbrain && gbrain init --pglite`.

**Recipe shape — service + recipe (like agentmemory):**
```yaml
name: gbrain
description: Knowledge brain — synthesis, graph traversal, gap analysis across people/companies/ideas.
harnesses: [claude, omp]
mcp:
  servers:
    - name: gbrain
      service: gbrain
      transport: http
      url: http://gbrain:3112/mcp
expect:
  tools: [gbrain]
```

The service runs `gbrain serve --http` with a persistent volume for the PGLite database.

**Data model:** PGLite database (embedded Postgres). The brain accumulates knowledge over time —
this is long-lived personal data that MUST persist and grow. Service volume (`gbrain-data`).

**Challenge — the dream cycle.** GBrain runs a nightly "dream cycle" (cron jobs that enrich and
consolidate). This is a daemon, not an on-demand MCP server. It needs to run continuously. This
fits the service model (long-running container).

---

### 5. solidspec — spec-driven development

**Repo:** `github.com/jyjeanne/solidspec` · Rust · MIT · 6 stars (early)

**What it is:** CLI tool for multi-methodology spec-driven development. 7 workflows (minimal,
spec-driven, security-first, tdd-driven, intent-driven, apex-driven, intent-apex). Generates spec
files, plan files, task lists in the project repo.

**Install:** `cargo install solidspec` (from source — no binary releases yet).

**Recipe:**
```yaml
name: solidspec
description: Multi-methodology spec-driven development — spec → plan → tasks → implement → ship.
harnesses: [claude, omp, opencode, codex, gemini]   # registers slash commands for many agents
expect:
  tools: [solidspec]
```
```dockerfile
FROM harnessed-claude:latest
ARG SOLIDSPEC_REF=v0.1.0
RUN cargo install --git https://github.com/jyjeanne/solidspec --tag ${SOLIDSPEC_REF}
```

**Data model:** Spec files in the project repo (`spec.md`, `plan.md`, `tasks.md`). Managed by git.
No external data store.

**Verdict:** Clean fit. Pure CLI + skills recipe. No MCP, no hooks, no service. Like caveman.

---

### 6. codebase-memory-mcp — code intelligence (C binary)

**Repo:** `github.com/DeusData/codebase-memory-mcp` · C · MIT · 12.2K stars

**What it is:** MCP server that indexes codebases into a persistent knowledge graph. 158 languages
via tree-sitter. Single static binary, zero runtime dependencies. 14 MCP tools.

**Install:** `curl ... | bash` (downloads prebuilt binary from GitHub releases).

**Recipe:**
```yaml
name: codebase-memory
description: Code intelligence — 158-language knowledge graph via tree-sitter. Single binary, zero deps.
harnesses: [claude, omp, opencode, codex, gemini, antigravity]
mcp:
  servers:
    - name: codebase-memory
      command: codebase-memory-mcp
      transport: stdio
```
```dockerfile
FROM harnessed-claude:latest
ARG CBM_VERSION=1.2.0
RUN curl -fsSL "https://github.com/DeusData/codebase-memory-mcp/releases/download/v${CBM_VERSION}/codebase-memory-mcp-linux-amd64.tar.gz" \
    | tar xzf - -C /tmp && install -m 0755 /tmp/codebase-memory-mcp /usr/local/bin/ && rm -rf /tmp/*
```

**Data model:** SQLite database at `.codebase-memory/` in the project directory. Per-project index.
Persists via the project mount.

**Challenge — binary install via curl.** Not a package manager (pip/npm/cargo). The recipe
Dockerfile downloads from GitHub releases. The pin is the release version in the URL. The
assembler's pin validation needs to accept GitHub release URLs (not just git clone --branch).

**Verdict:** Clean fit for the Dockerfile model. Surfaces that pin validation must handle release
URLs, not just git refs.

---

### 7. context-mode — context window optimization

**Repo:** `github.com/mksglu/context-mode` · TypeScript · ELv2 · 18K stars

**What it is:** MCP server that sandboxes tool output (98% reduction), persists session memory
(SQLite FTS5), and enforces routing via hooks. 11 MCP tools + 6 hooks.

**Install:** `npm install -g context-mode` or Claude Code plugin marketplace.

**Recipe:**
```yaml
name: context-mode
description: Context window optimization — sandbox tools (98% reduction), session continuity, routing enforcement.
harnesses: [claude, omp]
mcp:
  servers:
    - name: context-mode
      command: context-mode
      transport: stdio
hooks:
  PreToolUse: [{ matcher: "Bash|Read|WebFetch", command: "context-mode hook claude-code beforetool" }]
  PostToolUse: [{ matcher: "*", command: "context-mode hook claude-code aftertool" }]
  PreCompact: [{ matcher: "*", command: "context-mode hook claude-code precompress" }]
  SessionStart: [{ matcher: "*", command: "context-mode hook claude-code sessionstart" }]
```

**Data model:** SQLite FTS5 session store. Per-session (deleted on fresh session). Persists during
a session across compactions.

**Surfaces GAP 2 (hooks registration).** The recipe needs to declare hooks that the assembler
merges into `settings.json`. The hook scripts (the `context-mode hook` commands) are image-baked.

---

### 8. tokensave — semantic code intelligence (Rust)

**Repo:** `github.com/aovestdipaperino/tokensave` · Rust · MIT · 246 stars

**What it is:** MCP server with pre-indexed semantic knowledge graph. 80+ MCP tools, 50+ languages.
libSQL graph DB. Also installs git hooks (post-commit, post-checkout for auto-sync).

**Install:** `cargo install tokensave` or `brew install` or prebuilt binaries.

**Recipe:**
```yaml
name: tokensave
description: Semantic code intelligence — 80+ tools, knowledge graph, 50+ languages, 100% local.
harnesses: [claude, omp, opencode, codex, gemini, antigravity]
mcp:
  servers:
    - name: tokensave
      command: tokensave
      transport: stdio
```
```dockerfile
FROM harnessed-claude:latest
ARG TOKENSAVE_VERSION=0.8.0
RUN cargo install tokensave --version ${TOKENSAVE_VERSION}
```

**Data model:** libSQL database at `.tokensave/` in the project directory. Per-project. Persists
via the project mount.

**Challenge — git hooks.** Tokensave installs post-commit/post-checkout git hooks for auto-sync.
In a container, these would need to be in the project's `.git/hooks/` dir. Since the project is
mounted, the hooks persist with the project. But installing them requires running `tokensave install --git-hook yes` which modifies the project's git config. This is a recipe Dockerfile step that
runs against the image (not the project) — the hooks would need to be installed at runtime
(per-project), not at build time.

**Verdict:** MCP recipe with a runtime hook-installation step. The git hooks are per-project
runtime setup, not image-bake.

---

### 9. caveman — token compression skill

**Repo:** `github.com/JuliusBrussee/caveman` · JavaScript · MIT · 76K stars

**What it is:** Claude Code skill that makes the agent talk concisely ("caveman"). Cuts ~75% of
output tokens. Pure skill — no MCP, no data, no hooks (auto-activates via skill activation).

**Install:** `curl ... | bash` (installs skill files into agent skills dirs).

**Recipe:**
```yaml
name: caveman
description: Token compression skill — cuts ~75% of output tokens by talking concisely.
harnesses: [claude, omp, opencode, codex, gemini]
expect:
  skills: [caveman, caveman-compress, caveman-stats]
```
```dockerfile
FROM harnessed-claude:latest
ARG HARNESS=claude
ARG CAVEMAN_REF=v2.1.0
RUN git clone --branch ${CAVEMAN_REF} --depth 1 https://github.com/JuliusBrussee/caveman.git /tmp/caveman \
    && cd /tmp/caveman && ./install.sh --host ${HARNESS} \
    && rm -rf /tmp/caveman
```

**Data model:** None. Pure skill.

**Verdict:** Cleanest possible recipe. Skills-only, exactly like gstack.

---

### 10. hindsight — memory/recall service (multi-container stack)

**URL:** `hindsight.vectorize.io` · Docker (AlloyDB Omni + app)

**What it is:** Memory and recall system for AI agents. The user has a complete working deployment
at `~/.config/hindsight/docker-compose.yml` — a 3-container docker-compose stack, NOT a single
sidecar.

**The real topology (from `~/.config/hindsight/docker-compose.yml`):**

``+hindsight-net (bridge)
  ├── db (google/alloydbomni:17)          Postgres + vector + ScaNN extensions
  │     port 5438, volume alloydb_data
  ├── alloydb-init (one-shot)             Creates database + CREATE EXTENSION vector, alloydb_scann
  │     depends_on: db (service_started)
  └── hindsight (ghcr.io/vectorize-io/hindsight)
        ports 8888 (API) + 9999 (MCP/control plane)
        depends_on: alloydb-init (service_completed_successfully)
        env: LLM keys, DB URL, tenant API key, rate-limit config
```

**Secrets:** varlock + 1Password (`.env.schema` with `op://` refs). Resolves:
- `ZAI_API_KEY`, `OPENROUTER_API_KEY` (LLM provider keys for reflect/consolidation)
- `HINDSIGHT_API_TENANT_API_KEY` (tenant auth — shared by API + control plane)
- LLM provider config (model, base URL, rate limits)

**Recipe (the MCP declaration — thin):**
```yaml
name: hindsight
description: Memory and recall — AlloyDB-backed persistent memory with AI reflect/consolidate.
harnesses: [claude, omp]
mcp:
  servers:
    - name: hindsight
      service: hindsight
      transport: http
      url: http://host.containers.internal:8888/mcp
```

**The real challenge — this is a multi-container stack, not a single sidecar.** The current service
model (`services/<name>/service.yaml`) assumes one image, one port, one volume. Hindsight needs:
- **2+ containers with a dependency chain** (db → init → app)
- **Multiple ports** (8888 API + 9999 control plane)
- **Secrets resolution** (varlock `op://` refs → env)
- **A specialized DB image** (AlloyDB Omni with vector + ScaNN extensions)
- **An init step** (CREATE DATABASE + CREATE EXTENSION)

**Surfaces GAP 7 (multi-container service stacks).** See Architecture Gaps below.

**How to turn the existing deployment into a recipe:**
The user has a working docker-compose stack. The cleanest path is:
1. The service definition wraps the existing compose file — `svc up hindsight` runs
   `docker compose -f ~/.config/hindsight/docker-compose.yml up -d` (with varlock secret resolution).
2. The recipe declares the MCP connection to the running stack.
3. The service model extends to support compose-file-backed services (not just single-image sidecars).

This is NOT just "extract an MCP declaration." The service model itself needs to grow to express
multi-container topologies with dependencies, init steps, and secrets.
---

### 11. hyperpowers — workflow skills

**Repo:** `github.com/withzombies/hyperpowers` · Shell/Markdown · MIT · 80 stars

**What it is:** Workflow guidance for Claude Code — task tracking, plan management, TDD, code
review, debugging skills. Skills + hooks + commands + agents. All markdown/shell.

**Install:** Claude Code plugin marketplace or git clone into `.agents/skills/`.

**Recipe:**
```yaml
name: hyperpowers
description: Workflow guidance — brainstorming, planning, TDD, code review, debugging skills.
harnesses: [claude]
expect:
  skills: [brainstorming, writing-plans, executing-plans, review-implementation, verification-before-completion]
```
```dockerfile
FROM harnessed-claude:latest
ARG HYPERPOWERS_REF=v0.3.0
RUN git clone --branch ${HYPERPOWERS_REF} --depth 1 https://github.com/withzombies/hyperpowers.git /tmp/hp \
    && cp -r /tmp/hp/.agents/skills/* /home/harnessed/.claude/skills/ \
    && cp -r /tmp/hp/.claude-plugin /home/harnessed/.claude/.claude-plugin \
    && rm -rf /tmp/hp
```

**Data model:** Task docs in the project (`plans/active/<slug>/`). Managed by git.

**Challenge — hooks.** Hyperpowers includes hooks (session-start context injection, skill
activation suggestions, stop-time reminders). These need `settings.json` hook registrations.

**Verdict:** Skills recipe with hooks. Like context-mode, surfaces GAP 2.

---

## Architecture Gaps Surfaced

### GAP 1: HTTP-native MCP servers (not stdio)

**Packages:** agentmemory (:3111), gbrain (:3112), headroom (proxy mode)

**Problem:** The hatago model wraps stdio MCP servers (spawn as child, stdio→HTTP). But some MCP
servers are themselves HTTP servers with their own ports. These can't be hatago children.

**Existing coverage:** The McpServer schema already has `transport: http`, `url`, and `service:`
fields. The hatago URL-proxy mode handles network-native servers. So the schema supports it.

**What's missing:** The recipe needs a way to declare that an MCP server runs as a service (not
a hatago child). The `service:` field + a `services/` entry handles this — but the recipe model
currently doesn't have a way to declare a service dependency. The recipe says "I need service X
running" and the stack composition ensures it.

**Resolution:** recipe.yaml `mcp.servers[].service: <name>` already references a service. The
stack's `services: [agentmemory]` list ensures the service starts. This works today — the gap is
just that no recipe has used it yet. **No architecture change needed, just a new recipe pattern.**

### GAP 2: Hooks registration ⚠️ (real gap)

**Packages:** agentmemory (12 hooks), context-mode (6 hooks), hyperpowers (hooks), tokensave (git hooks)

**Problem:** The recipe model has `mcp:` (merged into hatago config) and `expect:` (smoke check).
But several packages also install hooks — `PreToolUse`, `PostToolUse`, `SessionStart`, etc. — that
the harness discovers from `settings.json`. The recipe has no way to declare hooks.

**Why it matters:** Hooks are how tools like agentmemory and context-mode enforce their behavior
(auto-saving memories, sandboxing tool output). Without hooks, the MCP server is present but the
automatic behavior doesn't fire.

**Proposed resolution:** Add a `hooks:` field to recipe.yaml, merged by the assembler into the
profile's `settings.json`:

```yaml
# recipe.yaml
hooks:
  PreToolUse:
    - matcher: "Bash|Read|WebFetch"
      command: "context-mode hook claude-code beforetool"
  PostToolUse:
    - matcher: "*"
      command: "context-mode hook claude-code aftertool"
```

The assembler merges all recipes' `hooks:` into one `settings.json` (same merge model as `mcp:`).
The hook scripts themselves are image-baked by the recipe Dockerfile.

**Harness-specific hooks:** Different harnesses have different hook formats (Claude Code's
`settings.json` hooks vs omp's hook config). The `harnesses:` field scopes which harnesses a
recipe supports, and the assembler generates the right format per harness.

**This is the one real architecture gap.** It requires:
1. A `hooks:` field in recipe.yaml + the schema (`Recipe.hooks`)
2. Assembler merge logic (merge hooks across recipes into `settings.json`)
3. Harness-specific hook format generation (claude vs omp vs others)

### GAP 3: Per-project data stores (mostly handled)

**Packages:** serena (`.serena/`), codebase-memory-mcp (`.codebase-memory/`), tokensave (`.tokensave/`)

**Analysis:** Most of these create their data IN THE PROJECT DIRECTORY. Since the project is
mounted (rw), these persist naturally across container restarts. **No architecture change needed.**

**Edge case — tools that store data outside the project:** gbrain uses PGLite at a configurable
path. If configured to `~/.gbrain/`, it needs a mount. If configured to the project dir, it's
fine. The recipe Dockerfile or an env var can set the path. The data-driven mount manifest (§4c
of the milestone) can declare a tool-specific data mount if needed.

### GAP 4: Binary downloads (not package managers)

**Packages:** codebase-memory-mcp (GitHub release binary)

**Analysis:** The recipe Dockerfile handles this naturally: `RUN curl ... | tar xzf ... && install`.
The pin is the release version in the URL. The assembler's pin validation needs to accept pinned
release URLs, not just `git clone --branch <tag>`.

**Resolution:** Extend pin validation (ASM-02) to recognize GitHub release URL patterns
(`releases/download/v<X.Y.Z>/...`) as pinned. A floating `releases/latest` URL is rejected.
**Minor extension to ASM-02, not a new architecture concept.**

### GAP 5: The service-recipe boundary

**Packages:** hindsight (multi-container stack), agentmemory (HTTP server), gbrain (daemon + DB)

**Analysis:** The distinction is clear in principle:
- **stdio MCP server** → recipe (hatago child, spawned on demand)
- **HTTP/container/server** → service (own image, own volume, long-running)
- A recipe can reference a service via `mcp.servers[].service: <name>`

But the current service model (`services/<name>/service.yaml`: one image, one port, one volume)
is too simple for real-world services like hindsight (3 containers, dependencies, init step,
secrets). See GAP 7.

For simple HTTP MCP servers (agentmemory, gbrain in PGLite mode), the single-container service
model works. The gap is specifically multi-container stacks.

### GAP 6: Git hooks (per-project runtime setup)

**Packages:** tokensave (post-commit/post-checkout), potentially others

**Analysis:** Git hooks live in the project's `.git/hooks/` directory. They can't be baked into
the image (the project is mounted, not the image's git). They must be installed at runtime, per
project.

**Resolution:** The recipe can declare a "first-run" or "project-setup" step that installs git
hooks when the container starts against a new project. This is a runtime concern, not a build-time
one. The recipe Dockerfile installs the hook SCRIPTS in the image; a startup hook or the harness's
session-start mechanism installs them into the project's `.git/hooks/`.

**This is a minor gap** — it's a runtime setup pattern, not an architecture-level missing concept.
The hooks registration (GAP 2) could subsume this: a `SessionStart` hook that symlinks the
image-baked git hooks into the project.

### GAP 7: Multi-container service stacks ⚠️ (real gap)

**Packages:** hindsight (AlloyDB + init + app), potentially gbrain at scale (Postgres + app)

**Problem:** The service model assumes one image, one port, one volume. Hindsight's real topology
(from `~/.config/hindsight/docker-compose.yml`) is a docker-compose stack:

```
db (AlloyDB Omni) → alloydb-init (one-shot) → hindsight (app, 2 ports)
```

This needs:
- **Multiple containers with a dependency chain** (db must start before init, init must complete
  before app)
- **An init step** (CREATE DATABASE + CREATE EXTENSION vector, alloydb_scann)
- **Multiple ports** (8888 API + 9999 control plane)
- **Secrets resolution** (varlock `op://` refs → env vars, same as the harnessed secrets layer)
- **A specialized DB image** (AlloyDB Omni, not vanilla postgres)
- **Inter-container networking** (app reaches db via DNS name on a private bridge)

The current `service.yaml` schema (`name`, `image`, `port`, `volume`) cannot express this.

**Proposed resolution — compose-file-backed services:**

Extend the service model so a service can be backed by a docker-compose/podman-compose file
instead of a single image:

```yaml
# services/hindsight/service.yaml
name: hindsight
compose: docker-compose.yml          # ← compose file in the service dir (or a path)
port: 8888                           # primary port (for host.containers.internal reachability)
healthcheck: "curl -sf http://localhost:8888/health"
secrets: true                        # resolve ~/.config/hindsight/.env.schema via varlock
```

`svc up hindsight` runs `docker compose up -d` (with varlock-resolved env), waits for the
healthcheck, and the recipe's MCP declaration points at `host.containers.internal:8888/mcp`.

The user already has this working at `~/.config/hindsight/`. The service definition wraps the
existing compose file rather than reimplementing it. This is the "don't reinterpret the install"
principle applied to services — run the existing compose stack, don't rebuild it.

**Why this matters:** Real-world services (databases with extensions, multi-tier apps, init
scripts) are naturally multi-container. Forcing them into a single-image model would require
reimplementing their topology, which is exactly the "reinterpret the install" anti-pattern the
recipe model rejects.


## Additional Architecture Considerations

Three decisions the stress-test surfaced that need to be captured in the architecture spec.

### CONSIDERATION 1: Secret source pluggability (beyond 1Password)

**Surfaced by:** hindsight (`.env.schema` with `op://` refs), but every service with secrets.

Today harnessed wires varlock + 1Password exclusively. The `.env.schema` uses
`@plugin(@varlock/1password-plugin@0.3.2)` and `op(op://Vault/Item/field)` refs. But not every
operator uses 1Password.

**The `.env.schema` is already the interface — backends are pluggable.** The `@plugin` directive
is the extension point. Today's options:

| Secret source | How it works | Status |
|---|---|---|
| **1Password** | `@plugin(...1password-plugin)` + `op(op://...)` refs | Wired today |
| **Plain `.env` file** | No `.env.schema` → inert → plain env passthrough | Works today |
| **Literal values in schema** | `KEY=value` (no function call) → varlock resolves literal | Works today |
| **KeePassXC** | Needs a varlock plugin + `keepassxc(entry://...)` refs | Not wired — needs a plugin |
| **Bitwarden** | Needs a varlock plugin + `bw(...)` refs | Not wired |

The architecture spec should state: the secret resolution layer is pluggable via varlock
plugins. The `.env.schema` `@plugin` directive selects the backend. Operators who don't use
1Password can: (a) use plain `.env` files (no resolution), (b) use literal values in the schema,
or (c) write/use a varlock plugin for their password manager. Each service's `.env.schema`
declares its own plugin — different services can use different backends.

**Two distinct host-integration concerns for password managers:**

**A. Secret resolution (launch-time, host-side).** Varlock runs on the HOST, resolves
`op://`/`keepassxc://`/`bw://` refs to values, passes as env to the container. The container
never talks to the password manager. This is the varlock plugin concern (per-backend TBD):

- **1Password:** solved — `op` app-auth talks to the desktop app on the host.
- **KeePassXC:** `keepassxc-cli` reads the `.kdbx` file on the host. For unlocked-session access
  (no master password re-entry), needs IPC to the running KeePassXC app via DBus/socket — TBD
  whether the varlock process can reach it.
- **Bitwarden:** `bw` CLI uses API auth (login + unlock → session key). No desktop app needed,
  but the session key must be acquired/persisted non-interactively for automated builds — TBD.

**B. In-container crypto operations (runtime, socket-forwarded).** SSH signing (git commits/tags)
and GPG signing need the host's agent sockets mounted into the container. This is the §4a
host-integration layer — **already established, shared by every stack:**

- **SSH signing:** `SSH_AUTH_SOCK` forwarded into the container. Works for ALL password managers
  that provide SSH agent integration — 1Password, KeePassXC (`Settings → SSH Agent`), and Bitwarden
  (`Settings → SSH Agent`) all add keys to the system SSH agent. The existing socket mount handles
  all three; no per-password-manager socket is needed.
- **GPG signing with hardware keys (YubiKey):** GPG agent SSH socket + `~/.gnupg` (ro) +
  YubiKey USB device passthrough (`--device`). Already in §4a. The YubiKey appears inside the
  container as a `/dev/hidraw*` device; the GPG agent (running on the host) handles the
  cryptographic operations via the forwarded socket. Works for `git commit --gpg-sign` and
  `git tag -s` inside the container, signed by the hardware key on the host.

**Summary:** concern A (secret resolution) needs per-backend varlock plugins (TBD for KeePassXC
and Bitwarden). Concern B (crypto agent forwarding) is already solved by the §4a mount layer and
is password-manager-agnostic — any manager that feeds the system SSH agent works with the existing
`SSH_AUTH_SOCK` forward. GPG/YubiKey signing is also already handled.

### CONSIDERATION 2: Shared database services

**Surfaced by:** hindsight (AlloyDB Omni), gbrain (PGLite/Postgres at scale).

**A database is a service, and multiple recipes can share one DB instance with separate
databases.** Instead of each service running its own Postgres:

```
services/postgres/                    ONE shared Postgres service
  init/
    001-create-hindsight-db.sql       CREATE DATABASE hindsight_db
    001-create-gbrain-db.sql          CREATE DATABASE gbrain_db

recipes/hindsight/recipe.yaml         declares: needs postgres, database hindsight_db
recipes/gbrain/recipe.yaml            declares: needs postgres, database gbrain_db
```

When services DON'T share: hindsight uses AlloyDB Omni (Postgres + vector + ScaNN extensions) —
specialized enough to warrant its own instance. gbrain in PGLite mode is embedded (no external
DB). The decision criteria: same engine + same extensions = share one instance, separate
databases. Different engine or extension sets = separate instances.

### CONSIDERATION 3: Data storage — bind mounts, not named volumes

**Surfaced by:** hindsight (named volume `alloydb_data`), all services with persistent data.

**Decision: use bind mounts at `~/.local/share/harnessed/{service}/`, not named volumes.**

| Concern | Named volumes | Bind mounts |
|---|---|---|
| Inspectability | Opaque (need runtime commands) | `ls`, `du`, `tree` directly |
| Backup | Runtime-specific export | `tar` / `rsync` / `cp` (any tool) |
| Runtime portability | Podman ≠ docker ≠ Apple container volumes | Host paths work everywhere |
| Orphan risk | Volumes survive service removal; accumulate | Dir is visible, manually cleanable |
| Consistency | Session state already uses bind mounts — volumes are inconsistent | Same model as the state dir |

The service data path convention:

```
~/.local/share/harnessed/
  hindsight/db-data/         AlloyDB data dir (bind-mounted into db container)
  agentmemory/data/          SQLite store
  gbrain/pglite/             PGLite database
```

For compose-file-backed services (GAP 7), the compose file's named volumes are replaced with
bind-mount declarations parameterized by `HARNESSED_DATA_DIR` (defaults to
`${XDG_DATA_HOME:-$HOME/.local/share}/harnessed`, set by the launcher before invoking compose).
The hindsight compose file changes from `alloydb_data:/var/lib/postgresql/data` to
`${HARNESSED_DATA_DIR}/hindsight/db-data:/var/lib/postgresql/data`.

UID mapping: rootless podman maps the container user to the host user via `--userns=keep-id`.
The launcher creates the data dir with correct permissions before starting the service (same
pattern as the state-dir creation today).
---

## Summary: What the Architecture Handles vs What It Doesn't

### Handled cleanly (no changes needed):

| Pattern | Packages | Why it works |
|---|---|---|
| stdio MCP server (hatago child) | serena, headroom (MCP mode), codebase-memory-mcp, tokensave | Existing `mcp:` + hatago stdio→HTTP |
| Skills-only recipe | caveman, solidspec, hyperpowers, gstack | Existing Dockerfile recipe model |
| Simple HTTP service (1 image, 1 port) | agentmemory, gbrain (PGLite mode) | Existing `services/` + `mcp.servers[].service` |
| Per-project data in project dir | serena, codebase-memory-mcp, tokensave | Project mount (rw) persists it |
| Binary install via curl | codebase-memory-mcp | Recipe Dockerfile `RUN curl ... && install` |
| Pinned source (tag/SHA) | all | Existing ASM-02 pin validation |

### Needs architecture work:

| Gap | Packages | What's needed |
|---|---|---|
| **Hooks registration** (GAP 2) | agentmemory, context-mode, hyperpowers | `hooks:` field in recipe.yaml → merged into `settings.json` by assembler. Hook scripts image-baked. |
| **Multi-container service stacks** (GAP 7) | hindsight, gbrain (at scale) | Service model extends to compose-file-backed services (multi-container, dependencies, init steps, secrets). The user's working `~/.config/hindsight/docker-compose.yml` is the reference topology. |
| **Pin validation for release URLs** (GAP 4) | codebase-memory-mcp | ASM-02 extension: recognize `releases/download/v<X.Y.Z>/` as pinned |
| **Git hooks at runtime** (GAP 6) | tokensave | SessionStart hook or runtime setup step (subsumed by GAP 2) |

---

## Recipe Authoring Priority

Ordered by architecture-fit (cleanest first, surfacing gaps last):

### Tier 1 — Clean fits (no architecture changes, validates the model)

1. **caveman** — pure skills, no MCP, no hooks. Simplest possible recipe after gstack.
2. **serena** — stdio MCP server, per-project data via project mount. Validates the MCP recipe.
3. **solidspec** — CLI + skills via cargo. Validates the fat-base (Rust runtime pre-installed).
4. **tokensave** — stdio MCP via cargo + per-project libSQL. Validates Rust runtime in base.
5. **codebase-memory-mcp** — stdio MCP via binary download. Validates non-package-manager installs.
6. **headroom** (MCP mode only) — stdio MCP via pip. Clean fit. Proxy mode deferred.

### Tier 2 — Simple service-backed recipes (validates single-container service integration)

7. **agentmemory** — HTTP MCP server as a single-container service + recipe declaring MCP + hooks.
   Validates the service-recipe boundary for simple services. (Hooks need GAP 2.)
8. **gbrain** (PGLite mode) — HTTP MCP + embedded DB as a single-container service. Validates
   persistent-volume services.

### Tier 3 — Multi-container service (validates GAP 7 resolution)

9. **hindsight** — the real stress test. 3-container docker-compose stack (AlloyDB + init + app)
   with secrets, dependencies, and an init step. The user has a working deployment at
   `~/.config/hindsight/`. This recipe validates compose-file-backed services.

### Tier 4 — Surfaces the hooks gap (validates once GAP 2 is resolved)

10. **context-mode** — MCP + hooks. The hooks are essential (routing enforcement).
11. **hyperpowers** — skills + hooks. Workflow hooks (session-start, stop-time reminders).

### Deferred

12. **headroom** (proxy mode) — network intermediary between agent and LLM. Architecturally out
    of scope — requires a network-intermediary model harnessed doesn't have.
13. **gbrain** (Postgres at scale) — multi-container (Postgres + app). Same GAP 7 as hindsight.

---

## Recommended Execution Order

1. **Build Tier 1 recipes** (caveman, serena, solidspec, tokensave, codebase-memory-mcp, headroom
   MCP) — six recipes that validate the model with zero architecture changes.

2. **Resolve GAP 2 (hooks)** — add `hooks:` to recipe.yaml + assembler merge. Unblocks Tier 4.

3. **Build Tier 2 recipes** (agentmemory, gbrain PGLite) — validate single-container service +
   recipe integration.

4. **Resolve GAP 7 (multi-container services)** — extend service model for compose-file-backed
   stacks. Unblocks Tier 3.

5. **Build Tier 3 recipe** (hindsight) — the real stress test. Wraps the user's existing
   `~/.config/hindsight/docker-compose.yml` as a compose-file-backed service.

6. **Build Tier 4 recipes** (context-mode, hyperpowers) — validate hooks registration.

---

## Recommended Execution Order

1. **Build Tier 1 recipes** (caveman, serena, solidspec, tokensave, codebase-memory-mcp) — these
   validate the recipe model with zero architecture changes. Five working recipes proves the model.

2. **Build Tier 2 recipes** (hindsight, gbrain) — validate the service-recipe boundary and
   HTTP-native MCP.

3. **Resolve GAP 2 (hooks)** — add `hooks:` to recipe.yaml + assembler merge. This unblocks
   Tier 3.

4. **Build Tier 3 recipes** (context-mode, hyperpowers, agentmemory) — validate hooks + the most
   complex multi-surface recipe.

5. **Defer Tier 4** (headroom proxy mode) — noted as a future network-intermediary model.
