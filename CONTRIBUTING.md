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

The CLI runs on the host. Edits under `src/harnessed/` take effect immediately (no image rebuild).

### Git hooks

**harnessed ships hook logic, never hook wiring.** A git hook is one executable per event with no
chaining, so any tool that claims `.git/hooks/pre-commit` is at war with every other tool that wants
it. A recipe needing a host git hook ships a plain script and leaves the wiring to you.

For the whole picture — how git resolves hooks, and why worktrees share one hooks dir — see the
[Git hooks guide](https://github.com/drmikecrowe/harnessed/wiki/guides/git-hooks).

**Do not set `core.hooksPath`.** Set locally *or* globally, it makes the repo's own `.git/hooks` be
ignored entirely — which is how tools silently disable each other. Nothing in harnessed sets it; if
something on your host did: `git config --unset core.hooksPath`, adding `--global` if needed.

## `catalog/` is a published artifact

`catalog/` is **shipped inside the wheel** (via the `src/harnessed/catalog` symlink + package-data), so
an installed `harnessed` needs no repo on disk — see [ARCHITECTURE.md](ARCHITECTURE.md) §harnessed home.
Two things follow when you touch it:

- **Never put host-local content in `catalog/`**, and never point a symlink out of it. setuptools
  follows symlinks, so anything you park there can be published. Your overlay symlinks live in
  `catalog-local/` (created by `harnessed build`, gitignored). Build artifacts go in a staged temp
  context, not back into `catalog/`. `tests/test_wheel_packaging.py` builds a real wheel and fails if
  host-local content shows up in it.
- **Never key build/assembly off the CWD.** Anchor to `paths.harnessed_home()` — the directory that
  contains `catalog/` — so `harnessed build <stack>` works from any directory.

Do not delete the `src/harnessed/catalog` symlink. Without it an installed harnessed has no catalog.

## Add a recipe (the common case)

A recipe lives at `catalog/recipes/<name>/recipe.yaml`. Recipes are **harness-independent** — never
add a `harnesses:` field. If you need harness-specific install steps, branch on `${HARNESS}` inside
the recipe's Dockerfile. Three ways a recipe delivers capability:

- **MCP server** — `mcp.servers:` (stdio child via `command:`, or network-native via `url:`/`service:`).
- **Skill / command** — ship a `skills/<leaf>/` or `commands/<leaf>/` dir. The assembler fans it into
  the profile's `.claude/`.
- **Rules** — ship a `rules/<leaf>/` dir; the assembler fans it into the profile's `.claude/rules/` (system-prompt-equivalent guidance for Claude Code).
- **`install:` script** — one bash file run by **both** executors, so it delivers identically in a
  container build and a `harnessed host-run` launch. Write content into `"$HARNESSED_CONFIG_DIR"`,
  executables into `"$HARNESSED_BIN_DIR"`, and run an installer that only understands "global" as
  `HOME="$HARNESSED_HOME_SHIM" <installer>`. A recipe Dockerfile must **not** write into `~/.claude`:
  that content is invisible to a host-native launch and hidden by the profile bind-mount in a
  container. Anything genuinely container-only (root, `apt-get`) stays in the Dockerfile and is
  declared in `install.system`, whose prose reason is printed at host launch so the shortfall is
  never silent.

Because the assembler cannot see what a script or Dockerfile installs, **declare it** so the
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

Recipe Dockerfiles: **no `FROM`**, **no `ARG HARNESS`** (the assembler supplies both). **Pin every
download** (no `@latest` / `--branch main` — the build rejects floating refs).

**A `setup.config` item with a `prompt:` must refuse to run without a TTY.** Today every config
item in the catalog is `derive:`-only, which resolves fine headlessly — so no guard exists yet. If
you add a *prompted* item, add the refusal with it: a headless launch (`CI`, a script) takes the
default silently, and some defaults are forever-values. The motivating case was a tracker's issue-ID
prefix — it appears in every ID minted and is expensive to change, so it must never be set by silence.
Abort with the recipe name and the interactive command to run once. A `setup.condition` then keeps
later headless launches unaffected.

**Write outside harnessed-owned dirs → document removal in the recipe's README.** A recipe that
touches anything beyond `$HARNESSED_CONFIG_DIR`, `$HARNESSED_BIN_DIR`, and its own persist dirs —
a global package, a file in the user's home, a system service — must say in its README exactly what
it leaves behind and how to remove it. A host launch runs against the user's real machine, where
there is no image to throw away, so "uninstall the stack" cannot mean anything unless the recipe
spells it out. See
[docs/guides/recipe-authoring.md](docs/guides/recipe-authoring.md). Worked examples: `catalog/recipes/time`
(stdio MCP + skill), `catalog/recipes/ping` (service ref), `catalog/recipes/gstack` (Dockerfile).

### Recipe varieties (one tool, several wirings)

When the same tool needs several mutually-exclusive wirings, ship them as a recipe **family**: a dir
whose children are each a complete recipe. A stack names one with a ref.

```
catalog/recipes/<family>/       # family — no recipe.yaml of its own, NOT a usable ref
  README.md                     # shared docs: how to choose, shared setup
  <variety-a>/{recipe.yaml,Dockerfile,README.md}    # → `<family>/<variety-a>`
  <variety-b>/{recipe.yaml,Dockerfile,README.md}    # → `<family>/<variety-b>`
```

```yaml
# catalog/stacks/<stack>/stack.yaml
recipes: [<family>/<variety-a>]
```

The ref is the variety's path under `catalog/recipes/`. A family is exactly one dir deep. Each variety is
self-contained (own `recipe.yaml`, `Dockerfile`, `tests/`) and is hashed independently — editing one
variety does not rebuild stacks using another. Sibling varieties are **implicitly mutually
exclusive**: a stack listing two of them fails at assemble time, so do not list them in each other's
`conflicts:`.

The catalog currently ships **no** family — `catalog/recipes/beads/{team,stealth}` was the worked
example until beads was retired (2026-08-08). The variety-ref resolution in `paths.py` is unchanged
and still supported; there is simply nothing shipped to point at.

### The `default` recipe and stack (the shipped baseline)

`catalog/stacks/default` is the stack `--extends` resolves to for every dynamic (`--recipe`) launch,
and it composes exactly one recipe, `catalog/recipes/default`. Together they are the baseline every
install inherits without configuring anything.

Two rules follow:

- **Keep the default recipe small and universal.** Everyone pays for what it carries. No MCP servers
  (each costs a hatago child or a proxied endpoint), no Dockerfile (it forces a derived-image build
  on stacks that would otherwise need none), no `persist:`, no `egress:`. A capability only some
  projects want gets its own recipe, opted into by name.
- **Keep the default stack policy-free.** A shipped baseline that set `permissions:` or turned on
  credential forwarding would silently apply that policy to every dynamic stack on every install.

harnessed **seeds a copy** of the default recipe into `~/.config/harnessed/catalog/recipes/default`
on first run (`launcher._seed_user_default_recipe`) so the baseline is the user's to edit. The
overlay wins on a name clash, which is the feature and also the cost: once seeded, changes you make
to the shipped recipe do not reach that user until they delete their copy. Say so in the PR when you
change it.

## Add an agent or a service

- **agent** → `catalog/agents/<name>/agent.yaml` (`harness`, `image`, `dockerfile`) + the Dockerfile
  it points at. Agents are not recipes.
- **service** → `catalog/services/<name>/` (`service.yaml` + `Dockerfile` + server). See
  [docs/guides/service-authoring.md](docs/guides/service-authoring.md).

## Compose + test a stack

Stacks are **harness-free**, named after their recipes **`<recipe>[_<recipe>…]`** (underscores
between fields, hyphens within a name — not after a harness). The harness is a run-time positional.
Scaffold + run the loop:

```bash
harnessed new <recipes>… --recipes a,b,c
harnessed build <stack> <harness>  # assemble + build images for that harness (host-native)
harnessed test  <stack> <harness>  # capability report — every declared capability present?  (auth-free)
```

Personal/experimental catalog entries can live in `~/.config/harnessed/catalog/` instead of the repo
— they overlay the repo catalog (yours wins on a name clash).

## Tests

- `uv run pytest -q` — fast unit + assembly oracle (no containers). Run before every PR.
- `HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py` — live: builds each stack and
  asserts every declared skill/command/plugin/MCP is present in the running container. Add your stack
  to the catalog and it is covered automatically.

A contribution is done when `harnessed test <your-stack>` is green and the live integration test passes.
