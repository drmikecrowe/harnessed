# repowise

Code-health, change-risk, and dependency-graph intelligence over the project.

Wired as a **stdio MCP server** — hatago spawns it as a child with cwd = the bind-mounted project,
and `repowise mcp` resolves the project by walking up to the nearest `.repowise/`.

**One-time setup (per project).** The server only serves an *existing* index; it never builds one.
Index once, inside the agent container:

```bash
REPOWISE_SKIP_EDITOR_SETUP=1 repowise init --index-only -y \
  --no-claude-md --no-agents --no-codex --no-distill-hook && \
  rm -f .repowise/mcp.json .mcp.json .vscode/mcp.json .vscode/extensions.json
```

That writes `.repowise/wiki.db` (dependency graph, git history, code health, dead code) with no LLM
key. **The trailing `rm -f` is required, not cosmetic**: repowise 0.31.0 has no flag that suppresses
its own `.mcp.json` / `.repowise/mcp.json` / `.vscode/mcp.json` writes — `REPOWISE_SKIP_EDITOR_SETUP`
only skips *global* client registration (`~/.claude/settings.json`), and `--no-claude-md`/`--no-agents`/
`--no-codex`/`--no-distill-hook` each gate exactly one specific file, none of them the MCP configs.
Leave the stray files in place and you get repowise registered twice — once correctly through hatago,
once more directly through the file it wrote — and the two copies can silently diverge (e.g. one has
a working embedder, the other degrades to mock vectors, because they do not necessarily start with the
same environment). Restart the agent after running the command above.

The graph-only tools (`get_overview`, `get_context`, `get_risk`, `get_health`, …) work from that
index. `search_codebase` / `get_answer` / `get_why` need real embeddings, which the index-only path
above deliberately does not provide (it always uses a mock embedder, by design — see below).

## Optional: full LLM-powered index (real embeddings + generated summaries)

If you want `search_codebase` / `get_answer` / `get_why` backed by real semantic search instead of
empty/irrelevant mock-vector results, route your LLM key through harnessed's own secrets mechanism
(project `.env.schema`/`.env` — see [docs/guides/secrets.md](../../../docs/guides/secrets.md)) so it
reaches the **container's** environment, not just your host shell. `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
is picked up automatically both by the CLI and by the running MCP server. Then, inside the container:

```bash
REPOWISE_SKIP_EDITOR_SETUP=1 repowise init --provider gemini --embedder gemini -y \
  --no-claude-md --no-agents --no-codex --no-distill-hook && \
  rm -f .repowise/mcp.json .mcp.json .vscode/mcp.json .vscode/extensions.json
```

Drop `--index-only` — that flag is what forces the mock embedder and skips the LLM-summary
Generation phase entirely; running the full `init` is what persists `embedder: gemini` into
`.repowise/config.yaml` and builds the real wiki. This is slower (an LLM call per file/page) and a
per-project opt-in choice — not baked into the recipe by default. Other providers (`anthropic`,
`openai`, `openrouter`, `deepseek`, `ollama`, `litellm`) work the same way; see `repowise init --help`.

## `.claude/CLAUDE.md` is frozen by design

`--no-claude-md` persists `editor_files.claude_md: false` into `.repowise/config.yaml` — harnessed
owns `.claude/CLAUDE.md`, so repowise is told never to write or refresh it again, on any later `init`
or `update`. If you want repowise to own that file's content (its own hotspot/health/architecture
summary, kept current), either re-run `init` without `--no-claude-md`, or set
`editor_files: {claude_md: true}` directly in `.repowise/config.yaml` and then run
`repowise generate-claude-md` once (subsequent `repowise update` runs will keep it refreshed).

## Architecture Decision Records

repowise deterministically parses ADRs — no LLM key needed, works even with the no-key index-only
setup — from `docs/decisions/*.md`, `docs/adr/*.md`, `adr/*.md`, `decisions/*.md`, and a few sibling
conventions, **provided each file follows Nygard/MADR heading structure** (a `Context`/`Decision` or
`Decision Outcome`/`Decision Drivers` section under a `#`/`##` heading, optionally with a `status:`
front-matter field). A record missing recognizable headings is silently skipped unless an LLM
provider is configured (see above) to catch it via prose-mining instead. If `get_why`/`get_context`
are not surfacing your ADRs, check the file headings first before assuming indexing is broken.

## Host footprint — what it writes outside harnessed, and how to remove it

The CLI itself is stack-scoped in both modes (`install.sh` → `uv tool install`, redirected into the
stack tool tree on a `--host` launch), so *installing* repowise leaves nothing in your home. The
per-project index step above is what writes outside harnessed's dirs:

| Path | Written by | Remove with |
| --- | --- | --- |
| `<project>/.repowise/` | `repowise init --index-only` — `wiki.db`, `config.yaml`, and `mcp.json` | `rm -r .repowise` |
| `<project>/.mcp.json`, `<project>/.vscode/mcp.json`, `<project>/.vscode/extensions.json` | `repowise init` unconditionally, with no flag to suppress it (see above) — these are the stray duplicate MCP registrations | `rm -f .mcp.json .vscode/mcp.json .vscode/extensions.json` |

Remove the CLI with the stack's tool tree:
`rm -r "${XDG_DATA_HOME:-$HOME/.local/share}/harnessed/tools/<stack>"`.

Upstream: <https://github.com/repowise-dev/repowise> (AGPL-3.0)
