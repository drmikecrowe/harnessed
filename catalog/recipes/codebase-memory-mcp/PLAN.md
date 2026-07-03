# codebase-memory-mcp recipe — implementation plan

Goal: expose [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (cbm) as an MCP
server giving an agent structural code intelligence over the mounted project — a tree-sitter knowledge
graph across 158 languages (14 tools: `index_repository`, `search_graph`, `trace_path`, `query_graph`
Cypher, `get_architecture`, `detect_changes`, …). Single static C binary, zero runtime deps, embedded
SQLite.

Upstream: <https://github.com/DeusData/codebase-memory-mcp> · C · MIT · latest release **v0.8.1**
(2026-06-12). Transport: **stdio**.

> [!IMPORTANT]
> **Contingent on the hatago consolidation**
> ([docs/todos/2026-06-29-hatago-consolidation.md](../../todos/2026-06-29-hatago-consolidation.md)).
> cbm is a stdio MCP server that indexes the project. hatago is the MCP interface — it wraps
> stdio→HTTP ([emit.py:160-171](../../src/harnessed/emit.py)) — so cbm is a plain stdio child. The only
> dependency is landing hatago in the harness container so the stdio child sees the project mount. Until
> that lands, this recipe is correct in shape but cannot index (no project) — do not ship it.

## Recipe shape

```
   harness container  (hatago in-container; project bind-mounted)
     hatago  ──stdio──►  codebase-memory-mcp   (sees the project)
     hatago serves one Streamable-HTTP endpoint :3535  ──►  agent connects
```

cbm is a stdio server that hatago spawns as a child. Recipes already bake into the harness image
(`Dockerfile.harnessed-<stack>`), so the binary install is an ordinary recipe Dockerfile step.
The recipe ships no skill — upstream offers none; a user may add one later.

```
catalog/recipes/codebase-memory-mcp/
  recipe.yaml
  Dockerfile             # bake the cbm binary into the agent image
  PLAN.md
```

### recipe.yaml

```yaml
name: codebase-memory-mcp
description: 158-language codebase knowledge graph (tree-sitter) via a stdio MCP server.
expect:
  mcp: [codebase-memory-mcp]
mcp:
  servers:
    - name: codebase-memory-mcp
      command: codebase-memory-mcp
```

### Dockerfile

Appended to `Dockerfile.harnessed-<stack>`. cbm is a static C binary — needs nothing from the base
image's node/pnpm/python/uv.

```dockerfile
USER root
ARG CBM_VERSION=0.8.1
RUN set -euo pipefail; \
    arch="$(uname -m)"; \
    case "$arch" in x86_64|amd64) arch="amd64";; aarch64|arm64) arch="arm64";; *) echo "unsupported $arch" >&2; exit 1;; esac; \
    asset="codebase-memory-mcp-linux-${arch}.tar.gz"; \
    base="https://github.com/DeusData/codebase-memory-mcp/releases/download/v${CBM_VERSION}"; \
    cd /tmp; \
    curl -fsSL "${base}/${asset}" -o "${asset}"; \
    curl -fsSL "${base}/checksums.txt" -o checksums.txt; \
    grep " ${asset}\$" checksums.txt | sha256sum -c -; \
    tar xzf "${asset}"; \
    install -m 0755 codebase-memory-mcp /usr/local/bin/codebase-memory-mcp; \
    rm -rf /tmp/*
USER harnessed
```

> **Do NOT run cbm's own installer.** `scripts/setup.sh` / the `install` command auto-configures 11
> agents (writes `.mcp.json`, skills, hooks, `AGENTS.md`). Harnessed owns all of that. Replicate **only**
> the binary-extract step, as the README "Manual install" does.
>
> Build-from-source fallback (only if a pinned release URL is ever unavailable): `USER root` →
> `apt-get install -y build-essential zlib1g-dev` (zlib1g-dev is already in the base image) → fetch-by
> tag `git clone --branch v0.8.1 --depth 1` → `scripts/build.sh` → `install build/c/codebase-memory-mcp
> /usr/local/bin/`. Heavier image; prefer the release binary. This is "GAP 4 — binary download"
> ([stress-test §6](../../todos/2026-06-27-recipe-stress-test.md)): confirm the assembler's pin gate
> accepts a pinned `releases/download/v0.8.1/…` URL (it rejects floating `releases/latest`).

## Test stack

```yaml
# catalog/stacks/claude_codebase_memory/stack.yaml
name: claude_codebase_memory
harness: claude
recipes: [codebase-memory-mcp]
```

## Build / test lifecycle

```bash
harnessed build claude_codebase_memory   # pin gate runs here (pinned release URL must pass)
harnessed claude_codebase_memory         # launch; hatago spawns cbm as a stdio child
harnessed test  claude_codebase_memory   # ✓ codebase-memory-mcp (mcp) connected
```

Gated on the consolidation. Manual behavior check (the capability test only proves the MCP connects):
against a real project, `index_repository(repo_path=…)` succeeds, `get_graph_schema` returns node/edge
counts, `trace_path` returns a call chain, and the index lands **in the project dir on the host**.

## Data model

cbm uses **embedded SQLite, no external DB** — no shared-DB service gap.

- **Live index should pin into the project** so it survives instance re-create (the README default
  `~/.cache/codebase-memory-mcp/` is the instance home = ephemeral). **Verify at consolidation** that
  hatago spawns stdio children with **cwd = project root** so the cache lands under the project — or that
  cbm resolves it from the absolute `repo_path` passed to `index_repository()`. Resolve as part of the
  consolidation if needed.
- **Team-shared artifact:** `.codebase-memory/graph.db.zst` (zstd graph snapshot) — cbm writes it on
  `index_repository`, re-imports on a fresh instance before incremental indexing. Commit it.

## Risks / checks

- **cwd / cache pinning:** see Data model — confirm the stdio child runs with the project as cwd, else
  the live index lands in ephemeral instance home. A consolidation item.
- **Pin gate:** confirm `releases/download/v0.8.1/…` passes pin validation (no `@latest`/`:latest`/
  `--branch main`); resolved at `harnessed build`.
- **Checksum verify in-image:** `sha256sum -c` against `checksums.txt` must match the exact asset name
  (note the `-portable` tarball sibling — pin the standard `codebase-memory-mcp-linux-<arch>.tar.gz`).
- **No runtime language-server install:** cbm's 158 grammars + Hybrid LSP are compiled in. Unlike
  `serena` (installs LSPs at runtime), there is **no** runtime network/`pip`/`npm` need.
- **Concurrency:** single-writer SQLite. One instance per project; two instances on one project dir will
  contend (same as `beads`/`serena`).
