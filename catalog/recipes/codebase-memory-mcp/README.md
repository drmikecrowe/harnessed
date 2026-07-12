# codebase-memory-mcp

A codebase knowledge graph. Indexes the project with tree-sitter across 158 languages into an
embedded SQLite graph, then answers "where is X / what calls Y" from the graph instead of grepping
the tree into context. 14 tools: `index_repository`, `search_graph`, `trace_path`, `query_graph`
(Cypher), `get_architecture`, `detect_changes`, and more.

Wired as a **stdio MCP server** — hatago spawns the binary as a child and wraps stdio→HTTP. The
binary is installed via mise's `github:` backend and takes no arguments: it detects the repo from
its working directory and auto-indexes.

Upstream: <https://github.com/DeusData/codebase-memory-mcp>
