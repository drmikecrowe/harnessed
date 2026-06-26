# harnessed — architecture

The authoritative description of *what lives where* and *what the words mean*. Read this first.
The deeper "why" is in [docs/harnessed-design.md](docs/harnessed-design.md); how to add things is in
[CONTRIBUTING.md](CONTRIBUTING.md).

## What harnessed is

A **host Python CLI** that composes and launches containerized AI-coding-harness stacks. It runs on
the host (installed via pipx/uvx) and drives **podman** directly — there is no tool container and no
daemon socket. A launched stack is a podman **pod**: the chosen agent + the **hatago** MCP hub (+ any
referenced service sidecars).

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
├── catalog/                  # everything contributors author (see Vocabulary)
│   ├── agents/<name>/agent.yaml      # an AI harness (claude, omp, …) + its image/Dockerfile
│   ├── base/                         # shared base + hatago Dockerfiles, pnpm policy, egress script
│   ├── recipes/<name>/               # recipe.yaml [+ skills/ commands/ Dockerfile]
│   ├── services/<name>/              # service.yaml + Dockerfile + server (shared sidecars)
│   └── stacks/<agent>_<recipe>…/stack.yaml
└── docs/
```

Generated profiles are **not** in the repo — they are emitted to `$XDG_DATA_HOME/harnessed/profiles/`
(the clone stays immutable source).

## Vocabulary (precise — these are not interchangeable)

- **agent** — an AI coding harness (`claude`, `omp`, …). Defined in `catalog/agents/<name>/agent.yaml`
  (its image + Dockerfile, and any agent-specific runtime contract such as omp's claude-hooks-bridge).
  An agent is **not** a recipe.
- **recipe** — a composable capability bundle (MCP servers / skills / commands / plugins, with an
  optional Dockerfile) that is added **onto** an agent. Recipes are **harness-independent**: they
  carry no `harnesses:` field. Any harness-specific step branches on the `${HARNESS}` build arg
  *inside* the recipe's Dockerfile.
- **service** — a shared sidecar (its own image + `service.yaml`) that a recipe references via
  `service:`. Host-published; outlives any instance.
- **stack** — one agent + a chosen set of recipes, named **`<agent>_<recipe>[_<recipe>…]`**
  (underscores between fields; hyphens allowed within a name).
- **catalog** — the collection of agents/recipes/services/stacks. Two roots, searched in order:
  the user overlay **`~/.config/harnessed/catalog`** (wins on a name clash) then the repo `catalog/`.

## How a build works (host-native)

`harnessed build <stack>`:
1. **assemble** (in-process, emit-only — no container): resolve the stack + its recipes across the
   catalog roots; fan each recipe's `skills/`+`commands/` into the profile's `.claude/`; merge MCP
   servers into one `hatago.config.json`; emit the harness `.mcp.json` (one entry → the hatago hub);
   emit `Dockerfile.harnessed-<stack>` (base agent image + concatenated recipe Dockerfile bodies).
2. build the **hatago** image.
3. if any recipe ships a Dockerfile, build the **derived** `harnessed-<stack>` image and **merge**
   its baked `~/.claude/{skills,commands,plugins,…}` back into the profile (so image-delivered and
   recipe-fanned extensions coexist — the profile mount would otherwise shadow the baked ones).

`harnessed <stack>` then launches the pod (derived image if present, else the agent image) + hatago
+ any referenced services (started host-published, idempotently).

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
