# repowise

Code-health, change-risk, and dependency-graph intelligence over the project.

Wired as a **stdio MCP server** — hatago spawns it as a child with cwd = the bind-mounted project,
and `repowise mcp` resolves the project by walking up to the nearest `.repowise/`.

**One-time setup (per project).** The server only serves an *existing* index; it never builds one.
Index once, inside the agent container:

```bash
REPOWISE_SKIP_EDITOR_SETUP=1 repowise init --index-only -y \
  --no-claude-md --no-agents --no-codex --no-distill-hook
```

That writes `.repowise/wiki.db` (dependency graph, git history, code health, dead code) with no LLM
key. The flags keep repowise from registering its own MCP servers / Claude hooks / `CLAUDE.md` —
harnessed owns those. Restart the agent afterwards.

The graph-only tools (`get_overview`, `get_context`, `get_risk`, `get_health`, …) work from that
index. `search_codebase` / `get_answer` / `get_why` additionally need the generated wiki
(`repowise init --provider …` with a key) — that is a per-project choice, not baked here.

Upstream: <https://github.com/repowise-dev/repowise> (AGPL-3.0)
