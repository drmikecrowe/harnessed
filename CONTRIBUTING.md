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

### Git hooks

**harnessed ships hook logic, never hook wiring.** A git hook is one executable per event with no
chaining, so any tool that claims `.git/hooks/pre-commit` is at war with every other tool that wants
it. A recipe needing a host git hook ships a plain script and leaves the wiring to you.

For the whole picture — how git resolves hooks, and why worktrees share one hooks dir — see the
[Git hooks guide](https://github.com/drmikecrowe/harnessed/wiki/guides/git-hooks).

**Do not set `core.hooksPath`.** Set locally *or* globally, it makes the repo's own `.git/hooks` be
ignored entirely — which is how tools silently disable each other. (`bd init` sets a local one; in
harnessed beads is **container-only**, so nothing should be setting it on your host. If something
did: `git config --unset core.hooksPath`, adding `--global` if needed.)

## `catalog/` is a published artifact

`catalog/` is **shipped inside the wheel** (via the `src/harnessed/catalog` symlink + package-data), so
an installed `harnessed` needs no repo on disk — see [ARCHITECTURE.md](ARCHITECTURE.md) §harnessed home.
Two things follow when you touch it:

- **Never put host-local content in `catalog/`**, and never point a symlink out of it. setuptools
  follows symlinks, so anything you park there can be published. Your overlay symlinks live in
  `catalog-local/` (created by `harnessed build`, gitignored); build artifacts go in a staged temp
  context, not back into `catalog/`. `tests/test_wheel_packaging.py` builds a real wheel and fails if
  host-local content shows up in it.
- **Never key build/assembly off the CWD.** Anchor to `paths.harnessed_home()` — the directory that
  contains `catalog/` — so `harnessed build <stack>` works from any directory.

Don't delete the `src/harnessed/catalog` symlink: without it an installed harnessed has no catalog.

## Add a recipe (the common case)

A recipe lives at `catalog/recipes/<name>/recipe.yaml`. Recipes are **harness-independent** — never
add a `harnesses:` field; if you need harness-specific install steps, branch on `${HARNESS}` inside
the recipe's Dockerfile. Three ways a recipe delivers capability:

- **MCP server** — `mcp.servers:` (stdio child via `command:`, or network-native via `url:`/`service:`).
- **Skill / command** — ship a `skills/<leaf>/` or `commands/<leaf>/` dir; the assembler fans it into
  the profile's `.claude/`.
- **Rules** — ship a `rules/<leaf>/` dir; the assembler fans it into the profile's `.claude/rules/` (system-prompt-equivalent guidance for Claude Code).
- **`install:` script** — one bash file run by **both** executors, so it delivers identically in a
  container build and a `--host` launch. Write content into `"$HARNESSED_CONFIG_DIR"`, executables
  into `"$HARNESSED_BIN_DIR"`, and run an installer that only understands "global" as
  `HOME="$HARNESSED_HOME_SHIM" <installer>`. A recipe Dockerfile must **not** write into `~/.claude`:
  that content is invisible to a host launch and hidden by the profile bind-mount in a container.
  Anything genuinely container-only (root, `apt-get`) stays in the Dockerfile and is declared in
  `install.system`, whose prose reason is printed at host launch so the shortfall is never silent.

Because the assembler can't see what a script or Dockerfile installs, **declare it** so the
capability test can probe it:

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
download** (no `@latest` / `--branch main` — the build rejects floating refs).

**Write outside harnessed-owned dirs → document removal in the recipe's README.** A recipe that
touches anything beyond `$HARNESSED_CONFIG_DIR`, `$HARNESSED_BIN_DIR`, and its own persist dirs —
a global package, a file in the user's home, a system service — must say in its README exactly what
it leaves behind and how to remove it. A host launch runs against the user's real machine, where
there is no image to throw away, so "uninstall the stack" cannot mean anything unless the recipe
spells it out. See
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
