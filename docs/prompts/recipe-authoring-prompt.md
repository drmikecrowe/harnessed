# Recipe-authoring prompt

A reusable base prompt for handing an LLM the job of authoring **one** `harnessed`
recipe. Paste the block below and fill in the brief at the bottom.

- **External LLM (no repo access):** the prompt is self-contained — use it as-is.
- **An agent that can read this repo:** trim the schema/example blocks and instead say
  *"Read [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) and the
  `recipes/time` + `recipes/ping` examples,"* then keep only the **Hard rules**,
  **Decision guide**, **Acceptance**, and the brief — the guide is the single source of truth.
- If the recipe needs a `service:` sidecar, also fold in
  [`docs/guides/service-authoring.md`](../guides/service-authoring.md); this prompt covers the
  recipe file, not the service it points at.

---

````markdown
# Task: author a `harnessed` recipe

You are authoring ONE recipe for `harnessed` — a tool that assembles isolated,
single-purpose AI-harness containers. A **recipe** is a hand-authored integration
for one capability bundle (an MCP server and/or a set of skills/commands). Recipes
are composed into **stacks** and assembled **ahead of time** into a committed,
version-controlled profile — nothing is resolved at container start.

A recipe lives at `recipes/<name>/recipe.yaml` and contributes to two layers:
- **MCP layer** — server entries under `mcp.servers`, merged into the stack's hatago config.
- **File-extension layer** — `skills` / `commands` in Claude-canonical form, fanned
  into harness-native profile paths.
A recipe may have either layer, both, or neither.

## Output

Produce the full file tree, each file in its own fenced block with its path:
1. `recipes/<name>/recipe.yaml`
2. Any skill/command dirs it ships: `recipes/<name>/skills/<leaf>/SKILL.md` (frontmatter
   `name` + `description`, then markdown body).
Do not write prose outside the files except a short rationale for the transport choice.

## `recipe.yaml` schema (only fields you exercise are required)

```yaml
name: <recipe-name>            # required
description: <one-liner>       # optional

mcp:                           # MCP layer (optional)
  servers:
    - name: <server>           # required
      # stdio child (hatago spawns it, stdio→HTTP) — REQUIRES command:
      command: <cmd>
      args: [<arg>, ...]
      transport: stdio         # explicit; default
      # OR network-native (hatago proxies by URL) — no command:
      url: <http-url>          # direct URL, OR
      service: <service-name>  # reference services/<name>/service.yaml → http://<name>:<port>/mcp
      transport: http
      url_env: <ENV>           # optional
      env: {<k>: <v>}          # optional
      headers: {<k>: <v>}      # optional

skills:                        # file-extension layer (optional)
  - path: skills/<leaf>        # leaf dir name = harness-native target (.claude/skills/<leaf>)
commands:
  - path: commands/<leaf>
```

## Hard rules (non-negotiable — the build enforces these)

1. **Transport is explicit.** Decide and justify:
   - **stdio** for a light, dependency-free server hatago bakes into its image and
     spawns as a child. The harness never runs the command itself.
   - **streamable-http** (`url:` or `service:`) for a network-native server (your own
     sidecar or a remote). One endpoint, POST + optional GET/SSE stream.
   - **SSE is deprecated** (MCP spec 2025-06-18 and Claude Code). NEVER author a new SSE server.
2. **pnpm everywhere — no `npm`/`npx`.** Any JS install uses `pnpm`; `pnpm dlx` replaces `npx`.
   Raw `npm`/`npx` in scripts/deps fails the build.
3. **`uvx` for light Python MCP servers** (e.g. `uvx mcp-server-time`). Heavier Python deps
   declare `deps.python` (pyproject.toml or requirements.txt, installed via uv).
4. **No name collisions.** Each skill/command leaf fans into `.claude/skills/<leaf>` etc.
   and the assembler fails fast on a duplicate leaf name across the stack — pick a unique leaf.
5. **A `service:` ref needs a separate service to exist** (its own image/Dockerfile/server +
   `services/<name>/service.yaml`). If the brief implies a stateful/shared/long-lived backend,
   say so and note the service must be authored too (out of scope for this recipe file).

## Decision guide

- Light, self-contained tool you want baked in → **stdio** (`command` + `args`).
- Stateful, shared, or long-lived backend that outlives any instance → **service ref**
  (`service:` + `transport: http`) + a companion service.
- A behavior/instruction bundle with no server → **skills/commands only**, no `mcp:`.

## Worked example (stdio MCP + a standalone skill)

```yaml
# recipes/time/recipe.yaml
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
```markdown
<!-- recipes/time/skills/time-helper/SKILL.md -->
---
name: time-helper
description: Ask the time MCP server for the current time in any IANA timezone and convert times.
---
# Time Helper
Use the `time` MCP server (exposed through the hatago hub at the harness's single MCP
endpoint) to answer time questions. Call `get_current_time` with an IANA timezone...
```

## Acceptance (how it'll be validated)

The recipe is added to a stack and exercised with:
`harnessed build <stack>` (assemble + supply-chain scan, fails on raw npm/npx and on
HIGH-severity vuln) → `harnessed test <stack>` (capability report: each declared MCP
server connects, each skill/command is present). Author so both pass.

────────────────────────────────────────
## THE RECIPE TO BUILD

- **Name:** <recipe-name>
- **What capability it adds:** <one or two sentences>
- **Backing MCP server (if any):** <package / command / URL, and whether it's stdio-light,
  your own HTTP sidecar, or a remote>
- **Skills/commands to ship (if any):** <names + what each instructs the agent to do>
- **Notes/constraints:** <auth, env vars, network needs, etc.>
````
