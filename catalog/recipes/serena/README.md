# serena

LSP-backed semantic code intelligence: symbol retrieval, references, type hierarchy, precise
symbol-level editing and refactoring across 40+ languages — an LSP answering structural questions
rather than a grep guessing at them.

Wired as a **stdio MCP server**: hatago spawns `serena start-mcp-server --context ide
--project-from-cwd` as a child *inside the agent container*, so it sees the bind-mounted project and
writes `.serena/` into the project dir on the host.

> Serena cannot be a harnessed **service**. Services get a published port and a named volume but no
> project bind-mount, and they are shared across every instance and project — so a serena service
> would come up with no project to index. The stdio child is the shape that works.

`serena init` (the language-server backend config) is baked at build time, so there is no manual
setup step.

Upstream: <https://github.com/oraios/serena>
