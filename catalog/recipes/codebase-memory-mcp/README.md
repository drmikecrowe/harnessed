# codebase-memory-mcp

A codebase knowledge graph. Indexes the project with tree-sitter across 158 languages into an
embedded SQLite graph, then answers "where is X / what calls Y" from the graph instead of grepping
the tree into context. 14 tools: `index_repository`, `search_graph`, `trace_path`, `query_graph`
(Cypher), `get_architecture`, `detect_changes`, and more.

Wired as a **stdio MCP server** — hatago spawns the binary as a child and wraps stdio→HTTP. The
binary is installed by `install.sh` (both the container build and a `--host` launch) via mise's
`github:` backend, and takes no arguments: it detects the repo from its working directory and
auto-indexes.

## Host footprint — what it writes outside harnessed, and how to remove it

`install.sh` deliberately does **not** run `mise use -g` on the host — `mise use -g` adds cbm to your
global mise config and to every shell you open. It installs the versioned tool and links the binary
into the stack's own bin dir instead. What that leaves behind:

| Path | Written by | Remove with |
| --- | --- | --- |
| `~/.local/share/mise/installs/…/codebase-memory-mcp/<version>/` | `mise install github:DeusData/codebase-memory-mcp@<version>` | `mise uninstall github:DeusData/codebase-memory-mcp@<version>` |

The symlink itself lives in the stack tool tree and goes with the stack:
`rm -r "${XDG_DATA_HOME:-$HOME/.local/share}/harnessed/tools/<stack>"`.

cbm's own SQLite index is written under the project it indexes. It goes with the project.

Upstream: <https://github.com/DeusData/codebase-memory-mcp>
