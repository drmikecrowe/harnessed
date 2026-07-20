# harnessed — architecture

The authoritative description of *what lives where* and *what the words mean*. Read this first.
The deeper "why" is in [docs/harnessed-design.md](docs/harnessed-design.md); how to add things is in
[CONTRIBUTING.md](CONTRIBUTING.md).

## What harnessed is

A **host Python CLI** that composes and launches containerized AI-coding-harness stacks. It runs on
the host (installed via pipx/uvx) and drives **podman** directly — there is no tool container and no
daemon socket. A launched stack is a podman **pod**: the chosen agent container — which also runs the
**hatago** MCP hub as an in-container process (hatago-consolidation) — plus any referenced service
sidecars.

## Repository layout

```
harnessed/
├── pyproject.toml            # the Python project (name: harnessed)
├── src/harnessed/            # the application — ALL assembly + launch logic
│   ├── launcher.py           #   `harnessed` CLI (Typer): build / launch / test / new / svc / …
│   ├── cli.py                #   `harnessed-tools` (assemble/scan/test entrypoints)
│   ├── assemble.py  emit.py  #   emit-only assembler: stack + recipes → a committed profile
│   ├── schema.py             #   typed models + catalog resolution (Agent/Recipe/Service/Stack)
│   ├── capability.py report.py  # the capability test (the integration oracle)
│   ├── paths.py              #   single source of truth for host/container paths + catalog roots
│   ├── scan.py  synclinks.py
├── tests/                    # pytest (unit + podman-gated integration); tests/fixtures/
├── catalog/                  # everything contributors author (see Vocabulary) — SHIPPED IN THE WHEEL
│   ├── agents/<name>/agent.yaml      # an AI harness (claude, omp, …) + its image/Dockerfile
│   ├── base/                         # shared base + per-agent Dockerfiles (hatago baked into base), pnpm policy, egress script
│   ├── recipes/<name>/               # recipe.yaml [+ skills/ commands/ Dockerfile]
│   ├── services/<name>/              # service.yaml + Dockerfile + server (shared sidecars)
│   └── stacks/<recipe>…/stack.yaml       # harness-free; harness chosen at run time
├── catalog-local/            # gitignored DX symlinks → your ~/.config/harnessed/catalog overlay
└── docs/
```

Generated profiles are **not** in the repo — they are emitted to `$XDG_DATA_HOME/harnessed/profiles/`
(the clone stays immutable source).

## harnessed home (why `build` works from any directory)

`harnessed build <stack>` never looks at your CWD. Everything — catalog lookup and the podman build
context — is anchored to **harnessed's home**: the directory that contains `catalog/`
(`paths.harnessed_home`). It resolves to:

| | home | `catalog/` |
|---|---|---|
| source checkout | the repo root | the authored dir |
| installed wheel | `site-packages/harnessed/` | shipped inside the wheel |

`src/harnessed/catalog` is a **symlink** to the repo-root `catalog/`. setuptools follows it and
materializes the catalog as real files inside the wheel, so an installed `harnessed` (uv tool / pipx /
PyPI) carries its own recipes, agents, services, stacks and base Dockerfiles and needs **no repo on
disk**. `harnessed_home()` resolves *through* that symlink, so home is always a real directory holding
a real `catalog/` — podman rejects a context symlink that escapes the context. `HARNESSED_DIR`
overrides it. **Do not delete the `src/harnessed/catalog` symlink** — without it an installed
harnessed has no catalog and every stack reads as "unknown".

Two consequences worth knowing:

- **Nothing host-local may live inside `catalog/`.** It is a published artifact, and setuptools
  follows symlinks. That is why the overlay symlinks sit in `catalog-local/` (not
  `catalog/<kind>.local`, their pre-move home) — a link to your private
  `~/.config/harnessed/catalog` parked inside `catalog/` would be packaged into the wheel.
- **Builds run from a staged context** (`launcher._staged_build_context`): a temp copy of `catalog/`
  plus your resolved `extra-tools.txt`. Building straight from home would write into site-packages on
  an installed harnessed, and would ship the entire repo (`.git`, `.venv`, `node_modules`) to podman
  in a checkout. The Dockerfiles' context-relative `COPY catalog/…` paths are identical either way.

## Vocabulary (precise — these are not interchangeable)

- **agent** — an AI coding harness (`claude`, `omp`, …). Defined in `catalog/agents/<name>/agent.yaml`
  (its image + Dockerfile, and any agent-specific runtime contract such as omp's claude-hooks-bridge).
  An agent is **not** a recipe.
- **recipe** — a composable capability bundle (MCP servers / skills / commands / plugins, with an
  optional Dockerfile) that is added **onto** an agent. Recipes are **harness-independent**: they
  carry no `harnesses:` field. Any harness-specific step branches on the `${HARNESS}` build arg
  *inside* the recipe's Dockerfile.
- **service** — a sidecar with its own image + `service.yaml`, referenced by a recipe via `service:`
  (an MCP server) or attached by a stack via `services:` (no MCP surface). Two scopes:
  - `scope: global` (default) — ONE shared container, host-published on a static port, reached at
    `host.containers.internal:<port>`; outlives any instance.
  - `scope: project` — ONE container **per project** (git-common-dir keyed), for a service that holds
    an **exclusive lock over per-project data** and so cannot be shared (a `dolt sql-server` is the
    motivating case — see `catalog/services/beads-server/`). Its data dir is a bind mount of a
    persist entry declared by a recipe in the stack (`data.persist`), so the **service follows the
    recipe's placement** (`in_repo` vs `host`) instead of owning a named volume. It is reached
    through a **unix socket** inside that same dir (`socket:`), which publishes no port at all: a
    socket is a filesystem object, so it crosses containers via the bind mount with no network
    namespace and no port allocation. (`127.0.0.1` differs per netns, so TCP cannot reach another
    container's server regardless of port.) The launcher exports the container-side path as
    `$HARNESSED_<NAME>_SOCKET`.
- **stack** — a **harness-free** chosen set of recipes, named after the recipes (e.g.
  `review-harness`, `gsd-core_repowise`; underscores between fields, hyphens within a name; a stack
  may **not** be named after a harness). The harness is **not** a stack property — it is a required
  positional chosen at run/build time: `harnessed <stack> <harness>`. The same stack runs on any
  harness; claude+it and omp+it are the same stack, materialized into per-harness images/pods.
  A stack may **inherit** from another with `extends: <stack>` (resolved in its own catalog root
  first, then the catalog search path — so an overlay stack can extend one shipped in the repo):
  `recipes` / `services` / `harnesses` / `ssh_keys` **union** with the parent's (parent's entries
  first, then the child's, de-duped), every other field the child declares **overrides**, and any it
  omits is **inherited**. Chains are allowed; cycles are an error. Unknown stack fields are
  **rejected** — a stack manifest has no forward-field case, and silently-ignored keys are how an
  `extends:` written before the feature existed went unnoticed while inheriting nothing.
- **catalog** — the collection of agents/recipes/services/stacks. Two roots, searched in order:
  the user overlay **`~/.config/harnessed/catalog`** (wins on a name clash) then the repo `catalog/`.

## How a build works (host-native)

`harnessed build <stack> <harness>`:
1. **assemble** (in-process, emit-only — no container): resolve the stack + its recipes across the
   catalog roots; fan each recipe's `skills/`+`commands/` into the profile's `.claude/`; merge MCP
   servers into one `hatago.config.json`; emit the harness `.mcp.json` (one entry → the hatago hub);
   emit `Dockerfile.harnessed-<stack>` (base agent image + concatenated recipe Dockerfile bodies).
   The profile is written under the **per-harness** dir `profiles/<stack>/<harness>/`, so the same
   stack's claude and omp builds never clobber each other.
2. build the shared **base** image, which bakes the **hatago** hub (and the time server) in-process
   (hatago-consolidation) — there is no separate hatago image.
3. if any recipe ships a Dockerfile, build the **derived** `harnessed-<harness>-<stack>` image and
   **merge** its baked `~/.claude/{skills,commands,plugins,…}` back into the profile (so
   image-delivered and recipe-fanned extensions coexist — the profile mount would otherwise shadow
   the baked ones).

`harnessed <stack> <harness>` then launches the pod (derived image if present, else the agent image), starts
**hatago** as a process *inside* that container (hatago-consolidation), and brings up any referenced
services (started host-published, idempotently).

## Folder-env contract

The **one** set of environment variables a recipe may rely on. Same names, same meanings, on every
surface — container and `--host` alike. Single definition: `launcher.harnessed_env()`.

| Variable | Value |
| --- | --- |
| `HARNESS` | The harness being launched (`claude`, `omp`, …). Unprefixed on purpose: it is already the token a recipe Dockerfile branches on (`ARG HARNESS`), so `$HARNESS` in a setup script means the same thing. |
| `PROJECT_DIR` | The project directory the agent starts in. |
| `MAIN_REPO_DIR` | The git **common dir** — in a bare + linked-worktree layout that is the bare repo dir, not the default-branch work tree. Falls back to `PROJECT_DIR` outside a repo. |
| `HARNESSED_GIT_COMMON_DIR` | Same value as `MAIN_REPO_DIR`, under an explicit name. A bare `GIT_COMMON_DIR` is **never** exported: git itself consumes that variable and it would hijack common-dir resolution the moment the agent `cd`s into another repo. |
| `HOST_WORKSPACE_DIR` / `CONTAINER_WORKSPACE_DIR` | The mounted workspace root (auto-widened to the bare-repo container so sibling worktrees are visible). Identical strings — the project is bind-mounted at its own host path. |
| `HOST_HOME` | The **host** `$HOME`, which is not the container's (`/home/harnessed`). A `scope: global` persist entry is mounted path-preserving, so a recipe pointing a tool at e.g. `~/.pulumi` must write `$HOST_HOME/.pulumi`. |
| `HARNESSED_RECIPE_DIR` | *(recipe-scoped surfaces only)* The recipe's own source dir — a setup script does `cp` where a Dockerfile did `COPY`. Host: the catalog dir. Container: `/opt/harnessed/recipes/<recipe>` (bind-mounted `:ro`). |
| `HARNESSED_<SERVICE>_SOCKET` | *(container only)* Container-side socket path for each socket-backed project-scoped service (e.g. `HARNESSED_BEADS_SERVER_SOCKET`). Omitted host-side: `--host` runs no service sidecars, so the path would not exist. |

Injected at every place catalog-authored content runs: the container attach shell
(`_init_shell_prologue`), the container itself (`podman run -e`, so hooks and later `podman exec`s
agree), **both** `setup.condition` eval sites (`_collect_setup_notices`, `_host_run_setups`),
`setup.run` / `setup.script` (`_script_env`, which additionally carries the `HARNESSED_MODE` /
`HARNESSED_CFG_*` / repo-identity vars), and the **host agent process** (`os.environ` in
`_launch_host` — on the host there is no container to set env on, so `os.environ` is the box).

This is why a condition may be written against a real path — `[ ! -f
"${MAIN_REPO_DIR}/.beads/metadata.json" ]`. Under an env-less eval that expanded to the empty string
and the test passed falsely.

## The capability test is the oracle

`harnessed test <stack>` launches the stack `--fresh` headless and diffs the **manifest oracle**
(`schema.expected_capabilities`) against the live instance. The oracle unions (a) what the assembler
can see — `mcp.servers`, the fanned `skills:`/`commands:` — and (b) what a recipe **declares** via its
`expect:` block for capabilities delivered through its Dockerfile. Each is probed *in the right place*
in the running container: skills → `~/.claude/skills`, commands → `~/.claude/commands`, plugins →
`~/.claude/plugins`, MCP → connected through hatago. The primary checks are **auth-free** (no Claude
credentials needed for a green report).

## Constraints (unchanged)

Claude format is canonical (every other agent adapts out of it); pnpm everywhere (no npm/npx); `uvx`
for light Python MCP servers; credentials referenced from the host, never baked; Streamable-HTTP MCP
(SSE is deprecated).

**Auth is per-harness.** claude seeds a read-only credential mount + a token-free onboarding stub
(isolated). **omp is a deliberate exception**: it stores auth/usage/sessions together in
`~/.omp/agent`, so the launcher **bind-mounts that host dir read-write** (shared host state, not
isolated) and runs plain `omp` (never `--profile`). This is intentional — do not "fix" it back to
isolation; see [design §4c](docs/harnessed-design.md) for the full rationale.
