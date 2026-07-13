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

### Secret gate (recommended)

This repo refuses to commit or push a secret, via [pre-commit](https://pre-commit.com) +
[gitleaks](https://github.com/gitleaks/gitleaks). Enable it once per clone:

```bash
mise use -g gitleaks@8.30.1                                   # or: brew install gitleaks
git config --global --unset-all core.hooksPath                # see below — pre-commit requires this
bd hooks install                                              # beads hooks, per-repo (bd's default)
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Bump the pinned gitleaks with `pre-commit autoupdate`.

**`core.hooksPath` must not be set globally.** pre-commit hard-refuses to install while it is
(*"Cowardly refusing to install hooks with `core.hooksPath` set"*), because a global hooks dir
silently overrides every repo's own `.git/hooks`. `bd hooks install` defaults to per-repo
`.git/hooks`, so beads never needed the global setting — unset it and install beads per repo.

**Existing hooks survive.** pre-commit renames any hook already in place to `<name>.legacy` and
chains to it, so the beads `pre-commit` / `pre-push` keep running. (In a git worktree these live in
the shared common dir — `$(git rev-parse --git-common-dir)/hooks` — not `.git/hooks`.)

**Two stages, because they catch different things.** The gitleaks hook scans the **staged tree** —
the earliest point, before a secret exists in history. `.githooks/gitleaks-push` (a `repo: local`
pre-push hook) scans the **commits being pushed**, which is the only way to catch a secret that
entered history some other way: `git commit --no-verify`, a rebase or cherry-pick, or a clone from a
machine with no hooks. Push is the irreversible step. Both fail closed; override deliberately with
`SKIP=gitleaks-push git push …` (or `SKIP=gitleaks git commit …`).

**Use `id: gitleaks`, never `id: gitleaks-system`.** gitleaks' `.pre-commit-hooks.yaml` omits
`pass_filenames: false` on the `-system` id, so pre-commit appends the staged filenames, `gitleaks
git … FILE` reads `FILE` as its *repo path* argument, scans it as a repo, finds "0 commits", and
exits 0 — reporting **Passed** on a live secret. It fails open. (Verified; it is tempting because it
reuses a system binary rather than building its own.)

The container side is gated separately and needs no setup: the `mikes-universal-setup` recipe wires
a `PreToolUse` hook that denies the agent's `git commit` / `git push` tool call outright — not a git
hook, so `--no-verify` cannot reach it.

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

### Recipe varieties (one tool, several wirings)

When the same tool needs several mutually-exclusive wirings, ship them as a recipe **family**: a dir
whose children are each a complete recipe. A stack names one with a ref.

```
catalog/recipes/beads/          # family — no recipe.yaml of its own, NOT a usable ref
  README.md                     # shared docs: how to choose, shared setup
  stealth/{recipe.yaml,Dockerfile,README.md}        # → `beads/stealth`
  team/{recipe.yaml,Dockerfile,README.md}           # → `beads/team`
```

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes: [beads/team]
```

The ref is simply the variety's path under `catalog/recipes/`; a family is exactly one dir deep. Each variety is
self-contained (own `recipe.yaml`, `Dockerfile`, `tests/`) and is hashed independently — editing one
variety does not rebuild stacks using another. Sibling varieties are **implicitly mutually
exclusive**: a stack listing two of them fails at assemble time, so do not list them in each other's
`conflicts:`. Worked example: `catalog/recipes/beads/`.

## Add an agent or a service

- **agent** → `catalog/agents/<name>/agent.yaml` (`harness`, `image`, `dockerfile`) + the Dockerfile
  it points at. Agents are not recipes.
- **service** → `catalog/services/<name>/` (`service.yaml` + `Dockerfile` + server). See
  [docs/guides/service-authoring.md](docs/guides/service-authoring.md).

## Compose + test a stack

Stacks are **harness-free**, named after their recipes **`<recipe>[_<recipe>…]`** (underscores
between fields, hyphens within a name; not after a harness). The harness is a run-time positional.
Scaffold + run the loop:

```bash
harnessed new <recipes>… --recipes a,b,c
harnessed build <stack> <harness>  # assemble + build images for that harness (host-native)
harnessed test  <stack> <harness>  # capability report — every declared capability present?  (auth-free)
```

Personal/experimental catalog entries can live in `~/.config/harnessed/catalog/` instead of the repo
— they overlay the repo catalog (yours wins on a name clash).

## Tests

- `uv run pytest -q` — fast unit + assembly oracle (no containers); run before every PR.
- `HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py` — live: builds each stack and
  asserts every declared skill/command/plugin/MCP is present in the running container. Add your stack
  to the catalog and it's covered automatically.

A contribution is done when `harnessed test <your-stack>` is green and the live integration test passes.
