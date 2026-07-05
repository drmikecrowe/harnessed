# repowise recipe — implementation plan

Goal: make repowise (repowise-dev/repowise) available in a stack as a **code health / change-risk /
dependency-graph intelligence layer** — defect-risk scoring, graph-aware refactoring plans, git-history
hotspots, and architectural-decision mining — over the project, with its index living in the user's
project folder (`.repowise/wiki.db`).

Upstream: <https://github.com/repowise-dev/repowise> · PyPI `repowise` (latest **0.27.0**, AGPL-3.0,
requires Python ≥3.11). Canonical install `pip install repowise` / `uv tool install repowise`. repowise
runs as an MCP server; stdio is the default transport (`repowise mcp --transport stdio`; streamable-http
and legacy SSE are also supported via `--transport`).

## Recipe shape

```
   harness container  (hatago in-container; project bind-mounted)
     hatago  ──stdio──►  repowise mcp --transport stdio   (sees the project via cwd)
     hatago serves one Streamable-HTTP endpoint :3535  ──►  agent connects
```

repowise's default transport is stdio, so it is a plain hatago stdio child — same shape as the serena
and codebase-memory-mcp recipes, unblocked by the hatago consolidation
(docs/done/2026-06-29-hatago-consolidation.md) for process placement, but **not** for project
resolution — see "Open questions" below. Once resolved, it runs in the harness container, resolves the
project, and writes `.repowise/` into it on first use. **No skill shipped** — upstream's slash
commands (`/repowise:init`, `/repowise:health`, …) ship only through its own Claude plugin marketplace
install (`/plugin marketplace add repowise-dev/repowise`), which is a separate distribution channel from
a portable harnessed skill; the recipe declares only the MCP server.

```
catalog/recipes/repowise/
  recipe.yaml            # stdio MCP entry; expect.mcp
  Dockerfile              # bake the pinned repowise CLI into the agent image
  PLAN.md
```

## What this recipe does NOT do

- Does not run `repowise init` at build or run time — that command auto-registers MCP servers, installs
  a PostToolUse hook into `~/.claude/settings.json`, and generates `.mcp.json`/`AGENTS.md`/`CLAUDE.md`.
  harnessed owns all of that; running it would fight the assembler's own config.
- Does not pre-build the index at image-build time — `.repowise/wiki.db` is per-project state and the
  full index (graph + git + docs + health) can take minutes; it is built lazily via the MCP tools (or an
  explicit `repowise init --index-only` the user runs themselves) on first real use, not baked into the
  image.
- Does not wire the documentation-generation LLM step (`repowise init`'s Generation phase) to any
  particular model/key — that is a per-project/user decision, not a recipe concern.

## Open questions / follow-ups

- **BLOCKING — project resolution:** confirmed by inspecting `launcher.py` (hatago is `exec -d`'d with
  no `-w`, so it inherits the container's default dir) and `emit.py` (the emitted stdio MCP entry has no
  `cwd` field) that hatago spawns stdio children with cwd = `/home/harnessed`, not the project root. The
  project is instead bind-mounted at its exact host path via `paths.container_project_path()` (path
  mirroring, MNT2-02) — i.e. `/home/mcrowe/myproject` on the host is `/home/mcrowe/myproject` in the
  container, unrelated to cwd. `repowise mcp --transport stdio` with no path argument resolves its
  target from cwd, so as shipped it would index `/home/harnessed`, not the project. This is the exact
  same open gap serena's PLAN.md flags for `--project-from-cwd` — not new to this recipe, but not
  resolved by the hatago consolidation either. Two ways to unblock, either fixed once for both recipes:
  (a) have emit.py set `cwd` on stdio MCP entries to the mirrored project path, or (b) have the
  assembler template the project path into each recipe's `args` (repowise then takes it as a positional
  argument: `[mcp, --transport, stdio, <project_path>]`). Until one lands, do not ship this recipe.
- **AGPL-3.0**: repowise is copyleft. Fine for personal/dogfood use in this stack; flag before any
  distribution scenario that would trigger AGPL's network-use clause.
- **Overlap with existing recipes**: repowise's Graph layer overlaps `codebase-memory-mcp`, and
  `repowise distill` overlaps `rtk`/`caveman`'s output-compression job. This recipe is scoped narrowly
  to the pieces those don't cover — code health, change-risk, refactoring plans, decision mining — not
  as a wholesale replacement. Consider whether `mcp.servers[0].args` should later restrict the tool
  surface (`--tools "get_health,get_risk,get_why,get_dead_code"`) to avoid duplicate graph/search tools
  competing with codebase-memory-mcp in the same stack.
