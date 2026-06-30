# serena recipe — implementation plan

Goal: make Serena (oraios/serena) available in a stack as **LSP-backed semantic code intelligence** —
symbol-level retrieval, editing, refactoring, and reference lookup across 40+ languages — with
per-project state (`.serena/`) living in the user's project folder.

Upstream: <https://github.com/oraios/serena> · PyPI `serena-agent` (latest **1.5.3**, MIT, requires
Python ≥3.11,<3.15; GitHub tag `v1.5.3`). Canonical install `uv tool install -p 3.13 serena-agent`; legacy
run-from-source `uvx -p 3.13 --from git+https://github.com/oraios/serena@<tag> serena`. Serena runs as an
MCP server; **stdio is the default transport** (`start-mcp-server`; Streamable HTTP is also supported via
`--transport streamable-http`).

> [!IMPORTANT]
> **Contingent on the hatago consolidation**
> ([docs/todos/2026-06-29-hatago-consolidation.md](../../todos/2026-06-29-hatago-consolidation.md)).
> Serena is a stdio MCP server that reads/edits the **project**. hatago is the MCP interface — it wraps
> stdio→HTTP ([emit.py:160-171](../../src/harnessed/emit.py)) — so serena is a plain stdio child. The only
> dependency is landing hatago in the harness container so the stdio child sees the project mount. Until
> that lands, this recipe is correct in shape but cannot reach the project — do not ship it.

## Recipe shape

```
   harness container  (hatago in-container; project bind-mounted)
     hatago  ──stdio──►  serena start-mcp-server   (sees the project; .serena/ lands in it)
     hatago serves one Streamable-HTTP endpoint :3535  ──►  agent connects
```

Serena's default transport is stdio, so it is a plain hatago stdio child. It runs in the harness container,
sees the project, and writes `.serena/` into it. Recipes already bake into the harness image
(`Dockerfile.harnessed-<stack>`), so the CLI install is an ordinary recipe Dockerfile step. **No skill
shipped** — upstream offers none; the recipe declares only the MCP server.

```
catalog/recipes/serena/
  recipe.yaml            # stdio MCP entry; expect.mcp
  Dockerfile             # bake the pinned serena CLI into the agent image
  PLAN.md
```

### recipe.yaml

```yaml
name: serena
description: Serena — LSP-backed semantic code intelligence over the project.
expect:
  mcp: [serena]
mcp:
  servers:
    - name: serena
      command: serena
      args: [start-mcp-server, --context, ide, --project-from-cwd]
      # transport: stdio (serena's default). hatago spawns it in-container → it sees the project.
```

No `url:`, no `transport: http`, no port, no `hooks:`. The stdio child needs neither startup-hooks nor any
daemon lifecycle — hatago owns the spawn.

### Dockerfile (bake the `serena` CLI into the agent image)

`uv` is a mise global in `harnessed-base` (`Dockerfile.harnessed-base:106`), on PATH via the mise shims, so
the derived agent image can install serena at build time. `~/.local/bin` is already on PATH
(`Dockerfile.harnessed-base:52`), so the baked `serena` resolves at runtime. No `FROM`, no `ARG HARNESS`
(the assembler prepends `FROM harnessed-${HARNESS}:latest`); pin exact, never `@latest`.

```dockerfile
# Bakes the serena CLI into the AGENT image. hatago spawns it as a stdio child.
USER harnessed
ARG SERENA_VERSION=1.5.3
RUN uv tool install -p 3.13 "serena-agent==${SERENA_VERSION}"
```

- `==1.5.3` is an exact pin → passes `validate_pin` (no `@latest`/`:latest`/`--branch`). `uv tool install`
  is in the authoring-guide table. Build-time network fetches Python 3.13 + deps (not firewalled at build).
- Alternative pin form (run-from-source, matches the legacy uvx docs): bake
  `uvx -p 3.13 --from git+https://github.com/oraios/serena@v1.5.3 serena` warm-up instead. Prefer the
  PyPI artifact (canonical, MIT, faster, no git).
- `--context ide` is serena's harness-agnostic generic context for terminal clients (disables serena's
  basic file/search tools to avoid overlap with the harness's own). Claude-specific gains
  (`--context claude-code` + a system-prompt override + `serena-hooks`) are out of recipe scope.

## Test stack

```yaml
# catalog/stacks/claude_serena/stack.yaml
name: claude_serena
harness: claude
recipes: [serena]
```

## Build / test lifecycle

```bash
harnessed build claude_serena    # assemble + derived image (bakes serena CLI); supply-chain pin gate
harnessed claude_serena <proj>   # launch; hatago spawns serena as a stdio child
harnessed test  claude_serena    # capability: ✓ serena (mcp) connected via hatago://servers
```

Gated on the consolidation. Manual verification (the capability test only confirms the server connected —
verify behavior):

- In a real project, `find_symbol` / `find_referencing_symbols` return symbol-level results; a
  `rename_symbol` updates all references across files in one call.
- `.serena/` appears in the project dir **on the host** (persists via the project bind-mount) after first
  activation; re-launching the same project reuses it.

## Risks / checks

- **cwd / project access:** confirm hatago spawns the stdio child with cwd = project root so
  `--project-from-cwd` resolves the project (resolve as part of the consolidation). If cwd is not the
  project, pass an explicit project path instead.
- **Lazy language-server install vs the egress firewall.** serena auto-installs an LSP per language on
  first use; the default egress firewall (`launcher._apply_firewall`, `launcher.py:491-497`;
  `NO_FIREWALL=true` / `--no-firewall` to skip) blocks that, so LSP-backed features silently fail for any
  un-baked language. LSPs cache in the instance home (ephemeral → re-install per instance). Lean lazy (per
  the stress-test), but either allow egress on first activation, pre-warm common LSPs in the recipe
  Dockerfile (a throwaway `serena project index` against polyglot stub sources — best-effort, serena's LSP
  install is opaque), or accept per-language first-use latency under allowed egress. Tell the user.
- **`.serena/` persistence.** Lives in the project dir (`project.yml` + `memories/*.md` + LSP cache),
  persisted via the project bind-mount — no special wiring. Shared across stacks/instances that open the
  same project. Suggest gitignoring `.serena/` if the project is a repo.
- **Claude-tool-hooks (`serena-hooks`) = GAP 2.** serena's recommended `remind`/`activate`/`auto-approve`
  hooks are Claude Code **tool** hooks (PreToolUse/SessionStart in `settings.json`) — a separate,
  currently-unsupported mechanism, **not** launcher startup-hooks. With no skill shipped, the agent uses
  the serena MCP tools directly; the system-prompt override (`claude --system-prompt=…`) is a harness
  launch arg, out of recipe scope.
- **Agent-image bloat (acceptable).** Baking serena + deps (anthropic, pydantic, flask, starlette,
  tiktoken, …) into the agent image adds weight to every stack that composes serena — that's the correct
  trade for this shape (the server runs there). It does **not** pollute stacks that don't use serena.
