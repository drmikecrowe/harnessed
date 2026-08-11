# codebase-memory-mcp

A codebase knowledge graph. Indexes the project with tree-sitter across 158 languages into an
embedded SQLite graph, then answers "where is X / what calls Y" from the graph instead of grepping
the tree into context. 14 tools: `index_repository`, `search_graph`, `trace_path`, `query_graph`
(Cypher), `get_architecture`, `detect_changes`, and more.

Wired as a **stdio MCP server** — hatago spawns the binary as a child and wraps stdio→HTTP. The
binary comes from the recipe's `tools:` entry (mise's `github:` backend, checksum-pinned by the
`mise.lock` beside `recipe.yaml`) in both the container build and a `--host` launch. It takes no
arguments: it detects the repo from its working directory. It does **not** index on its own
(`auto_index = false` upstream); the recipe's `SessionStart` hook indexes the current checkout.

## Host footprint — what it writes outside harnessed, and how to remove it

Nothing. A host launch redirects mise's data and config dirs into the stack's own tree, so the
install never touches your global mise config (which would put cbm in every shell you open) and
never lands in `~/.local/share/mise`. Everything goes with the stack:

```
rm -r "${XDG_DATA_HOME:-$HOME/.local/share}/harnessed/tools/<stack>"
```

cbm's own SQLite index is written under the project it indexes. It goes with the project.

Upstream: <https://github.com/DeusData/codebase-memory-mcp>
