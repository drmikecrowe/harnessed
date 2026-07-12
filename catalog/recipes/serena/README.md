# serena

LSP-backed semantic code intelligence: symbol retrieval, references, type hierarchy, precise
symbol-level editing and refactoring across 40+ languages — an LSP answering structural questions
rather than a grep guessing at them.

Wired as a **stdio MCP server**: hatago spawns `serena start-mcp-server --context ide
--project-from-cwd` as a child *inside the agent container*, with cwd pinned to the mirrored project
path — so it resolves the bind-mounted project and writes `.serena/` into the project dir on the host.

> Serena cannot be a harnessed **service**. Services get a published port and a named volume but no
> project bind-mount, and they are shared across every instance and project — so a serena service
> would come up with no project to index. The stdio child is the shape that works.

## What is automatic, what isn't

- **Global config** (`serena init -b LSP`, the language-server backend) — baked at build time.
- **Project creation** (`.serena/project.yml`) — automatic: activating a directory that has no
  project file auto-generates one. No `serena project create` step needed.
- **Onboarding / memories** — automatic on first activation.
- **Symbol index** — *not* automatic. On a large project, run once inside the container:

  ```bash
  serena project index
  ```

  It pre-caches language-server symbols; without it the first symbol tool call pays the full
  language-server scan. Serena keeps the index current as files change afterwards.
- **Language servers** are downloaded per language on **first use**. The default egress firewall
  blocks that, so do the first index/activation with `harnessed <stack> <project> --no-firewall`
  (or `NO_FIREWALL=true`); otherwise LSP-backed features fail for any language whose server was
  never fetched.

Upstream: <https://github.com/oraios/serena> ·
[project workflow](https://oraios.github.io/serena/02-usage/040_workflow.html)
