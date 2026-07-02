# Contributing to harnessed

harnessed is a **standard Python project** plus a **catalog** of things you compose. Read
[ARCHITECTURE.md](ARCHITECTURE.md) for the layout and the precise meaning of agent / recipe / service
/ stack. Most contributions are **catalog** additions — new recipes for common frameworks.

## Dev setup

Host prerequisite: **podman** (or docker) + **uv**.

```bash
uv sync --extra dev                 # create .venv, install harnessed (editable) + pytest
export PATH="$PWD/.venv/bin:$PATH"   # put the `harnessed` CLI on PATH
uv run pytest -q                     # fast unit + assembly tests (no containers)
```

The CLI runs on the host; edits under `src/harnessed/` take effect immediately (no image rebuild).

## Add a recipe (the common case)

A recipe lives at `catalog/recipes/<name>/recipe.yaml`. Recipes are **harness-independent** — never
add a `harnesses:` field; if you need harness-specific install steps, branch on `${HARNESS}` inside
the recipe's Dockerfile. Three ways a recipe delivers capability:

- **MCP server** — `mcp.servers:` (stdio child via `command:`, or network-native via `url:`/`service:`).
- **Skill / command** — ship a `skills/<leaf>/` or `commands/<leaf>/` dir; the assembler fans it into
  the profile's `.claude/`.
- **Rules** — ship a `rules/<leaf>/` dir; the assembler fans it into the profile's `.claude/rules/` (system-prompt-equivalent guidance for Claude Code).
- **Dockerfile** — install into the agent image's `~/.claude/…` (or install a CLI). Because the
  assembler can't see what a Dockerfile installs, **declare it** so the capability test can probe it:

```yaml
name: my-recipe
description: One line.
expect:                       # only what your Dockerfile delivers (not skills:/commands: dirs)
  skills:   [my-skill]
  commands: [my-cmd]
  plugins:  [my-plugin]
  mcp:      [my-server]
```

Recipe Dockerfiles: **no `FROM`**, **no `ARG HARNESS`** (the assembler supplies both); **pin every
download** (no `@latest` / `--branch main` — the build rejects floating refs). See
[docs/guides/recipe-authoring.md](docs/guides/recipe-authoring.md); worked examples: `catalog/recipes/time`
(stdio MCP + skill), `catalog/recipes/ping` (service ref), `catalog/recipes/gstack` (Dockerfile).

## Add an agent or a service

- **agent** → `catalog/agents/<name>/agent.yaml` (`harness`, `image`, `dockerfile`) + the Dockerfile
  it points at. Agents are not recipes.
- **service** → `catalog/services/<name>/` (`service.yaml` + `Dockerfile` + server). See
  [docs/guides/service-authoring.md](docs/guides/service-authoring.md).

## Compose + test a stack

Stacks are named **`<agent>_<recipe>[_<recipe>…]`** (underscores between fields, hyphens within a
name). Scaffold + run the loop:

```bash
harnessed new <agent>_<recipes>… --harness <agent> --recipes a,b,c
harnessed build <stack>            # assemble + build images (host-native)
harnessed test  <stack>            # capability report — every declared capability present?  (auth-free)
```

Personal/experimental catalog entries can live in `~/.config/harnessed/catalog/` instead of the repo
— they overlay the repo catalog (yours wins on a name clash).

## Tests

- `uv run pytest -q` — fast unit + assembly oracle (no containers); run before every PR.
- `HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py` — live: builds each stack and
  asserts every declared skill/command/plugin/MCP is present in the running container. Add your stack
  to the catalog and it's covered automatically.

A contribution is done when `harnessed test <your-stack>` is green and the live integration test passes.
