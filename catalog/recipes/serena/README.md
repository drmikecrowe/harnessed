# serena

LSP-backed semantic code intelligence: symbol retrieval, references, type hierarchy, precise
symbol-level editing and refactoring across 40+ languages — an LSP answering structural questions
rather than a grep guessing at them.

Wired as a **stdio MCP server**: hatago spawns `serena start-mcp-server --context ide
--project-from-cwd` as a child *inside the agent container*, with cwd pinned to the mirrored project
path — so it resolves the bind-mounted project and writes `.serena/` into the project dir on the host.

> Serena cannot be a harnessed **service**. Services get a published port and a named volume but no
> project bind-mount, and they are shared across every instance and project — so a serena service
> starts with no project to index. The stdio child is the shape that works.

## What is automatic, what is not

- **CLI + global config** (`uv tool install serena-agent`, then `serena init -b LSP`, the
  language-server backend) — `install.sh`, run by both the container build and a `--host` launch.
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

## Host footprint — what it writes outside harnessed, and how to remove it

On a **container** launch everything below lives inside the image and dies with it. On a `--host`
launch these land in your real home and your project, *outside* the harnessed config dir, the
install cache, and the stack bin dir — so they are yours to remove:

| Path | Written by | Remove with |
| --- | --- | --- |
| `~/.serena/serena_config.yml` (and the rest of `~/.serena/`) | `serena init -b LSP` in `install.sh` — the global language-server backend config, plus serena's project registry, which is keyed by path | `rm -r ~/.serena` |
| `<project>/.serena/` | `serena project create --index` in `setup.sh` — `project.yml`, the symbol index cache, and onboarding memories | `rm -r .serena` |

The CLI itself is stack-scoped, not global: it goes with the stack's tool tree —
`rm -r "${XDG_DATA_HOME:-$HOME/.local/share}/harnessed/tools/<stack>"`.

Upstream: <https://github.com/oraios/serena> ·
[project workflow](https://oraios.github.io/serena/02-usage/040_workflow.html)
