# Authoring recipes

A **recipe** is a hand-authored integration definition for **one** capability bundle (an MCP server,
a set of skills, a vendored plugin, …). A **stack** composes a harness plus a chosen set of recipes
([stacks guide](stacks.md)). Recipes are assembled **ahead of time** into a committed, version-
controlled profile — nothing is resolved at container start (design §5, §11).

For the *why* (why recipes exist, why Claude-canonical is the single format, why pnpm), read
[docs/harnessed-design.md §5 & §11](../harnessed-design.md). This guide shows the *how* with worked
examples from this repo's `recipes/`.

## What a recipe is

A recipe lives at `recipes/<name>/recipe.yaml`. It can contribute to three things:

- **MCP layer** — server entries (under `mcp.servers`) merged into the stack's hatago config.
- **File-extension layer** — `skills` / `commands` (and `agents`/`hooks`/`rules` via plugins) in
  Claude-canonical form, fanned into harness-native profile paths.
- **Dockerfile body** — installation steps appended to the derived stack image; the primary way to
  install tooling, frameworks, or CLIs into the stack. The assembler concatenates Dockerfile bodies
  in recipe order to build the derived `harnessed-<stack>` image.

A recipe may have any combination of these, or (like `recipes/omp`, `recipes/opencode`, `recipes/gemini`,
`recipes/antigravity`, and `recipes/codex`) none — it can exist only to declare a runtime contract. Only the fields the recipe exercises are required; the assembler parses the rest
forward.

## The `recipe.yaml` schema

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`Recipe`,
`McpServer`, `FileExt`). Key fields:

```yaml
name: <recipe-name>            # required
description: <one-liner>        # optional
harnesses: [claude]             # optional — harnesses this recipe is compatible with (e.g. [claude],
                                # [claude, omp]). Omit to allow all harnesses. The assembler rejects
                                # composing a claude-only recipe onto an omp stack with a validation
                                # error before emitting any Dockerfile.
expect: [skill-name]            # optional — capabilities the Oracle 2 capability test must confirm
                                # present after a successful build; checked by `harnessed test`.

# --- MCP layer (optional) ---
mcp:
  servers:
    - name: <server>            # required
      command: <cmd>            # stdio servers only — hatago spawns this as a child (stdio→HTTP)
      args: [<arg>, ...]        # optional
      transport: stdio          # stdio (default) | http
      # network-native (transport: http) — instead of `command`, reference a URL or a service:
      url: <http-url>           # optional, direct URL
      service: <service-name>   # optional, references services/<name>/service.yaml (resolved to a URL)
      url_env: <ENV>            # optional, env injected into the instance
      env: {<k>: <v>}           # optional
      headers: {<k>: <v>}       # optional

# --- File-extension layer (optional) ---
skills:                         # standalone skill dirs shipped by this recipe
  - path: skills/<skill-name>   # relative to the recipe dir; leaf name = harness-native target
commands:                       # same shape as skills
  - path: commands/<cmd-name>
```

Notes:

- `transport` is **explicit** (design RESEARCH Pitfall B). A `stdio` server (with `command`) is run
  by hatago as a child and must be available inside the hatago image; the harness never speaks to
  this command directly. A network-native server (`transport: http`) is proxied by hatago by URL.
- The assembler **fans** each skill/command dir into the harness-native profile path
  (`.claude/skills/<leaf>`, `.claude/commands/<leaf>`) and **fails fast on name collision**
  (design §7).
- Forward-parsed fields (`plugins`, `deps`, `hooks`, `extensions`) are accepted but only exercised
  where relevant; see [`recipes/omp/recipe.yaml`](../../recipes/omp/recipe.yaml) for `extensions`.

If a recipe needs to install tooling into the stack image, it ships a `Dockerfile` alongside
`recipe.yaml`. The assembler concatenates the Dockerfile bodies of all recipes in the stack's recipe
order, prepends `FROM harnessed-${HARNESS}:latest`, and builds the derived `harnessed-<stack>`
image from the result. See "Worked example 3" for the full pattern.

## Worked example 1: the `time` recipe (stdio MCP + a standalone skill)

[`recipes/time/recipe.yaml`](../../recipes/time/recipe.yaml) is the tracer bullet — exactly one
light stdio MCP server and one standalone skill:

```yaml
name: time
description: Time and timezone queries via the network-free uvx mcp-server-time stdio MCP server.

mcp:
  servers:
    - name: time
      command: uvx
      args: [mcp-server-time]
      transport: stdio

skills:
  - path: skills/time-helper
```

- `command: uvx`, `args: [mcp-server-time]` — a light **Python** MCP server run via `uvx` (the uv
  runner; see *Supply-chain rules* below). hatago spawns `uvx mcp-server-time` as a child and wraps
  its stdio into the single HTTP endpoint the harness talks to.
- `transport: stdio` is explicit: the harness never runs `uvx` itself; it reaches hatago.
- `skills/time-helper` is a standalone skill dir shipped by this recipe; it lands at
  `.claude/skills/time-helper` in the assembled profile.

A stack that references it (`stacks/tracer-time`, `stacks/claude-multi`) builds + runs it via:

```bash
harnessed build tracer-time && harnessed tracer-time
harnessed test tracer-time      # capability report: ✓ time (mcp) connected, ✓ time-helper (skill) present
```

## Worked example 2: the `ping` recipe (a service reference, no command)

[`recipes/ping/recipe.yaml`](../../recipes/ping/recipe.yaml) is the other MCP shape — a
**network-native** server referenced by service, with no `command`:

```yaml
name: ping
description: Tracer shared service — a network-native ping MCP server.

mcp:
  servers:
    - name: ping
      service: ping
      transport: http
```

- No `command`: this is a **service reference**, not a stdio child. The assembler resolves
  `service: ping` → a hatago URL-proxy entry pointing at the running sidecar
  (`http://ping:8080/mcp`). hatago proxies it; the service runs as its own container on the shared
  network (design §3, §9).
- `transport: http` because the server is already network-native (Streamable HTTP).
- The sidecar itself is authored under [`services/ping/`](../../services/ping/) — see the
  [service-authoring guide](service-authoring.md).

Contrast: `time` (stdio child hatago must bake + spawn) vs `ping` (HTTP sidecar hatago proxies by
URL). Use stdio for light, dependency-free servers you want baked in; use a service for stateful or
shared systems that outlive any instance.

## Transports

| Transport | When | Notes |
| --- | --- | --- |
| **stdio** | light server hatago runs as a child | hatago wraps stdio→HTTP; bake the server into the hatago image via `pnpm dlx` (Node) / `uvx` (Python). The harness only sees hatago's HTTP endpoint. |
| **streamable-http** | a network-native server (your own service, or a remote) | One endpoint, `POST` + optional `GET`/SSE stream. Reference by `url:` or `service:`. |
| ~~SSE~~ | **deprecated** | SSE is deprecated in the current MCP spec (2025-06-18) and in Claude Code. Use **Streamable HTTP** for new servers. |

See the "What NOT to Use" table in [`CLAUDE.md`](../../CLAUDE.md).

## Supply-chain rules

Two hard rules, both enforced by the build ([design §7](../harnessed-design.md)):

1. **pnpm everywhere (no `npm`/`npx`).** Every JavaScript install — global, per-recipe, hatago's
   bundled servers — uses **pnpm**; `pnpm dlx` replaces `npx`. A managed supply-chain config applies
   `minimumReleaseAge` cooldowns and lifecycle-script default-deny. **Recipe validation** (part of
   `harnessed build`, BLD-03) flags any raw `npm`/`npx` in a recipe's scripts/deps and points at the
   pnpm equivalent — the build fails fast until you fix it.
2. **`uvx` for Python MCP servers.** Light Python servers (like `mcp-server-time`) run via `uvx`,
   the uv runner. Python dependencies declare `deps.python` (`pyproject.toml` → `uv venv` +
   `uv pip install -e .`, or `requirements.txt` → `uv pip install -r`).

`harnessed build` then scans recipe sources + dependencies with osv-scanner + pip-audit
(credential-free, always) and snyk/Socket.dev when a token is present — **failing on high-severity**
findings. See the [troubleshooting guide](troubleshooting.md) for scan-failure diagnostics.

## Adding a recipe to a stack

Author `recipes/<name>/recipe.yaml`, then reference it from a stack's `recipes:` list. See the
[stacks guide](stacks.md) for composition, scaffolding (`harnessed new`), and the full build → run →
test lifecycle.

## See also

- [docs/harnessed-design.md §5 & §11](../harnessed-design.md) — the *why* (composition unit, recipe schema, dependency model).
- [Stacks guide](stacks.md) — compose recipes into a stack.
- [Service-authoring guide](service-authoring.md) — author the `ping`-style sidecar a service-ref recipe points at.
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `Recipe` / `McpServer` / `FileExt` models.
