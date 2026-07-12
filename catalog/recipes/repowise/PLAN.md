# repowise recipe — implementation plan

Goal: make repowise (repowise-dev/repowise) available in a stack as a **code health / change-risk /
dependency-graph intelligence layer** — defect-risk scoring, graph-aware refactoring plans, git-history
hotspots, and architectural-decision mining — over the project, with its index living in the user's
project folder (`.repowise/wiki.db`).

Upstream: <https://github.com/repowise-dev/repowise> · PyPI `repowise` (pinned **0.31.0**, AGPL-3.0,
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
(docs/done/2026-06-29-hatago-consolidation.md) for process placement, and by bd main-u5d for project
resolution: emit.py now pins each stdio child's `cwd` to the mirrored container project path, and
`repowise mcp` (no PATH) walks up from cwd to the nearest initialised `.repowise` repo. **No skill shipped** — upstream's slash
commands (`/repowise:init`, `/repowise:health`, …) ship only through its own Claude plugin marketplace
install (`/plugin marketplace add repowise-dev/repowise`), which is a separate distribution channel from
a portable harnessed skill; the recipe declares only the MCP server.

```
catalog/recipes/repowise/
  recipe.yaml            # stdio MCP entry; expect.mcp
  Dockerfile              # bake the pinned repowise CLI into the agent image
  PLAN.md
```

## Indexing is a required, user-run setup step

The MCP server **serves** an index; it does not build one. `repowise mcp` with no PATH walks up from its
cwd to the nearest *initialised* `.repowise` repo — with no index there is nothing to answer from. So
upstream's quick start makes indexing step 2, before wiring any agent:

```bash
REPOWISE_SKIP_EDITOR_SETUP=1 repowise init --index-only -y \
  --no-claude-md --no-agents --no-codex --no-distill-hook && \
  rm -f .repowise/mcp.json .mcp.json .vscode/mcp.json .vscode/extensions.json
```

Shipped as a `setup:` note (schema `setup`, gated on `condition: test ! -d .repowise`) — the same shape
tokensave uses for its own `tokensave init`. It is deliberately *not* automated via `init:`: the index is
per-project state that can take minutes on a large repo, and `init.run` executes in the attach shell on
every launch, where a non-zero exit aborts the attach.

**Correction (verified against repowise 0.31.0 source):** the `--no-*` flags do NOT stop `repowise init`
from writing its own `.mcp.json` / `.repowise/mcp.json` / `.vscode/mcp.json` — no upstream flag gates
those three writes; `REPOWISE_SKIP_EDITOR_SETUP=1` only skips *global* client registration
(`~/.claude/settings.json`), and `--no-claude-md`/`--no-agents`/`--no-codex`/`--no-distill-hook` each
gate exactly one other file, none of them the MCP configs. harnessed owns MCP registration via hatago,
so the setup command's trailing `rm -f` is a required cleanup step, not optional belt-and-suspenders.

## What this recipe does NOT do

- Does not pre-build the index at image-build time — `.repowise/wiki.db` is per-project state, not an
  image artifact.
- Does not wire the documentation-generation LLM step (`repowise init`'s Generation phase) to any
  particular model/key by default — that is a per-project/user decision, not a recipe concern.
  Index-only mode covers `get_overview` / `get_context` / `get_risk` / `get_health`;
  `search_codebase` / `get_answer` / `get_why` need real embeddings, which index-only mode never
  provides (always mock). README.md documents the opt-in full-LLM `init` invocation (drop
  `--index-only`, add `--provider … --embedder …`, route the key through harnessed's own
  `.env.schema`/`.env` secrets mechanism so it reaches the container) for users who want it.

## Open questions / follow-ups

- **RESOLVED — project resolution (bd main-u5d):** `emit.py` now sets `cwd` on stdio MCP entries to the
  mirrored container project path (`paths.container_project_path()`), and `launcher.py` passes the project
  into `write_hatago_config`. hatago therefore spawns `repowise mcp` with cwd = the project root, and
  `repowise mcp` (no PATH) walks up from there to the project's `.repowise/`. Same fix unblocked serena's
  `--project-from-cwd`. `repowise mcp [PATH]` also accepts an explicit positional path if the recipe ever
  needs to be independent of cwd.
- **AGPL-3.0**: repowise is copyleft. Fine for personal/dogfood use in this stack; flag before any
  distribution scenario that would trigger AGPL's network-use clause.
- **Overlap with existing recipes**: repowise's Graph layer overlaps `codebase-memory-mcp`, and
  `repowise distill` overlaps `rtk`/`caveman`'s output-compression job. This recipe is scoped narrowly
  to the pieces those don't cover — code health, change-risk, refactoring plans, decision mining — not
  as a wholesale replacement. Consider whether `mcp.servers[0].args` should later restrict the tool
  surface (`--tools "get_health,get_risk,get_why,get_dead_code"`) to avoid duplicate graph/search tools
  competing with codebase-memory-mcp in the same stack.
