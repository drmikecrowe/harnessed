# harnessed — architecture

The authoritative description of *what lives where* and *what the words mean*. Read this first.
The deeper "why" is in [docs/harnessed-design.md](docs/harnessed-design.md). *Where* a composed
stack runs — the execution-backend seam behind both launch verbs — is [BACKENDS.md](BACKENDS.md).
For how to add things, see [CONTRIBUTING.md](CONTRIBUTING.md).

## What harnessed is

A **host Python CLI** that composes and launches containerized AI-coding-harness stacks. It runs on
the host (installed via pipx/uvx) and drives **podman** directly — there is no tool container and no
daemon socket. A launched stack is a podman **pod**: the chosen agent container plus any referenced service
sidecars. The agent container also runs the **hatago** MCP hub as an in-process hub
(hatago-consolidation).

## Repository layout

```
harnessed/
├── pyproject.toml            # the Python project (name: harnessed)
├── src/harnessed/            # the application — ALL assembly + launch logic
│   ├── launcher.py           #   `harnessed` CLI (Typer): build / launch / test / new / svc / …
│   │                         #   AND both backends: HostBackend + ContainerBackend live here
│   │                         #   (see BACKENDS.md), beside the private helpers they call
│   ├── backend.py            #   the ExecutionBackend contract + LaunchSpec + registry — see BACKENDS.md
│   ├── capmatrix.py          #   which recipe primitive each backend honors (the matrix tests read)
│   ├── cli.py                #   `harnessed-tools` (assemble/scan/test entrypoints)
│   ├── assemble.py  emit.py  #   emit-only assembler: stack + recipes → a committed profile
│   ├── schema.py             #   typed models + catalog resolution (Agent/Recipe/Service/Stack)
│   ├── capability.py report.py  # the capability test (the integration oracle)
│   ├── paths.py              #   single source of truth for host/container paths + catalog roots
│   ├── hostrun.py  hosthome.py   # host-native execution: per-stack home, installs/setups
│   ├── mounts.py  volumes.py  credmounts.py   # container mount set, per-stack volumes, auth mounts
│   ├── svcstate.py  svcguards.py              # service lifecycle + the guards around it
│   ├── launchenv.py  setupenv.py              # the folder-env contract, resolved per surface
│   ├── dynstack.py  lastrun.py  persist.py    # `--recipe` minting, `--last`, persist entries
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

The module list above is the **orientation subset, not the inventory** — `src/harnessed/` holds 37
modules. `docs/codebase/STRUCTURE.md` has the generated full map; treat this tree as the answer to
"where do I start reading", and that one as the answer to "does a module for X already exist".

## harnessed home (why `build` works from any directory)

`harnessed build <stack>` never looks at your CWD. Everything — catalog lookup and the podman build
context — is anchored to **harnessed's home**: the directory that contains `catalog/`
(`paths.harnessed_home`). It resolves to:

| | home | `catalog/` |
|---|---|---|
| source checkout | the repo root | the authored dir |
| installed wheel | `site-packages/harnessed/` | shipped inside the wheel |

`src/harnessed/catalog` is a **symlink** to the repo-root `catalog/`. setuptools follows it and
materializes the catalog as real files inside the wheel. An installed `harnessed` (uv tool / pipx /
PyPI) carries its own recipes, agents, services, stacks, and base Dockerfiles. It needs **no repo on
disk**. `harnessed_home()` resolves *through* that symlink, so home is always a real directory holding
a real `catalog/` — podman rejects a context symlink that escapes the context. `HARNESSED_DIR`
overrides it. **Do not delete the `src/harnessed/catalog` symlink** — without it an installed
harnessed has no catalog and every stack reads as "unknown".

Two consequences worth knowing:

- **Nothing host-local may live inside `catalog/`.** It is a published artifact, and setuptools
  follows symlinks. That is why the overlay symlinks sit in `catalog-local/` (not
  `catalog/<kind>.local`, their pre-move home). A link to your private
  `~/.config/harnessed/catalog` parked inside `catalog/` is packaged into the wheel.
- **Builds run from a staged context** (`launcher._staged_build_context`): a temp copy of `catalog/`
  plus your resolved `extra-tools.txt`. If you build straight from home, you write into site-packages
  on an installed harnessed. The same build also ships the entire repo (`.git`, `.venv`,
  `node_modules`) to podman. The Dockerfiles' context-relative `COPY catalog/…` paths are identical either way.

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
    motivating case). Its data dir is a bind mount of a
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
  argument chosen at run/build time: `harnessed container-run <harness> --stack <name>`. The same stack runs on any
  harness; claude+it and omp+it are the same stack, materialized into per-harness images/pods.
  A stack may **inherit** from another with `extends: <stack>`. The field resolves against the
  stack's own catalog root first, then the catalog search path — so an overlay stack can extend one
  shipped in the repo. The fields `recipes`, `services`, `harnesses`, and `ssh_keys` **union** with
  the parent's (parent's entries first, then the child's, de-duped). Every other field the child
  declares **overrides** the parent's. Any field the child omits is **inherited**. Chains are
  allowed. Cycles are an error. Unknown stack fields are **rejected** — a stack manifest has no
  forward-field case. Silently-ignored keys are how an `extends:` written before the feature existed
  went unnoticed while inheriting nothing.
- **catalog** — the collection of agents/recipes/services/stacks. Three roots, searched in order:
  the user overlay **`~/.config/harnessed/catalog`** (wins on a name clash), the repo `catalog/`,
  and last the **generated** root `$XDG_DATA_HOME/harnessed/generated/` holding machine-minted stacks
  (`--recipe`). Generated is last so it can never shadow a stack you authored, and it is kept
  out of the overlay so `harnessed list` can tell authored from generated and a regenerated
  manifest can never clobber a hand edit. It is included only when it exists.

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
3. if any recipe ships a Dockerfile, build the **derived** `harnessed-<harness>-<stack>` image —
   **system layers only** (`USER root` / `apt-get` / writes to `/usr`), plus recipe `env:` as real
   image `ENV`.
4. **populate the per-stack volumes** (`_ensure_stack_volumes`): `tools:` and every
   `install.script` run in a container writing to `harnessed-cfg-<harness>-<stack>` (`~/.claude`)
   and `harnessed-tools-<harness>-<stack>` (`~/.local`). Fingerprint-gated, so an unchanged stack
   pays nothing. `container-run` calls the same function, which is what keeps the two paths in step.
5. scan the populated volumes and merge the installer-written `settings.json` back into the profile.

The volume is **composed**, never layered: podman's copy-up lifts the image's own content in, then
the fanned profile content goes on top. One tree means nothing is left for a mount to shadow.
**Never mount a profile directory over a config subtree** — a mount hides everything the image put
there, so a profile dir over `~/.claude/skills` leaves only the skills the profile itself ships.

`harnessed container-run <harness> --stack <name>` then launches the pod (derived image if present, else the agent image), starts
**hatago** as a process *inside* that container, and brings up any referenced
services (started host-published, idempotently).

## Two launch verbs, one per backend

| verb | backend | what it isolates |
| --- | --- | --- |
| `harnessed container-run <harness> [path]` | container (podman pod + hatago + services) | the filesystem, the network, **and** the configuration |
| `harnessed host-run claude [path]` | host-native — no podman, no MCP hub | the **configuration only** |

Both verbs run the same composed stack through the **execution-backend seam**,
`harnessed.backend.ExecutionBackend` — six capabilities (materialize config / provision tools /
wire MCP / seed auth / wire services / apply isolation) that a backend implements and *sequences
itself*. There is deliberately no shared driver: the host backend materializes before it
provisions, the container backend provisions first because podman's copy-up is what populates the
volume the mount set then delivers. `HostBackend` and `ContainerBackend` are the two conforming
implementations and **both live in `launcher.py`**, next to the private helpers they call, so the
dependency points into `backend.py` and never back out (`tests/test_module_boundaries.py`).
Isolation is therefore a backend *capability*, not a property of the product — which is what makes
a third backend (bwrap, devcontainer, microVM) a class to write rather than a fork of the launch
path. **[BACKENDS.md](BACKENDS.md) is the full treatment**: the isolation spectrum, the capability
contract, and `harnessed.capmatrix` as the machine-checked record of which primitive each backend
honors.

**The verb picks the BACKEND; a flag picks the STACK.** Both take the same options — `--stack/-s`
for a stack you authored, `--recipe/-r` (repeatable) to compose one on the fly. The two are mutually
exclusive, and giving neither runs the `--extends` baseline (`default`) as-is: composing nothing on
top of the baseline is a legitimate launch, so the bare form needs no flags at all.

```bash
harnessed host-run      claude .                    # the `default` baseline, nothing composed
harnessed container-run claude .       --stack gsd-core
harnessed container-run omp   ~/proj   --recipe superpowers --recipe serena
harnessed host-run      claude .       --recipe superpowers
```

`--no-extends` is the one shape a bare invocation cannot be read as — it inherits nothing, so
without a `--recipe` list there is nothing left to run, and it is rejected.

The stack is named by a flag rather than a leading positional because with the stack in front,
Typer — which binds positionals by DECLARATION order, not by meaning — could not tell a stack name
from a project path under `--recipe`. That cost the recipe form a rejects-all-positionals rule, a
separate `--path` option, and it still let `host-run <stack> --recipe X` silently launch the
generated stack with the authored name demoted to a path, exit 0.

The harness is required on both verbs, including `host-run` where **`claude` is currently the only
accepted value** (`_HOST_HARNESS`; the other harnesses do not consume `CLAUDE_CONFIG_DIR`
directly). It is spelled out rather than defaulted because `path` is
the second positional: a defaulted harness would make `host-run .` bind `.` as the harness.

`host-run` materializes the stack's assembled profile into a per-stack `CLAUDE_CONFIG_DIR`
(`<stack>/<harness>`, see `paths.host_home`) and execs the harness against your real machine, real
project, and real credentials. Configuration isolation *is* the host backend's boundary — which
skills, rules, commands and hooks are live — so a stack's hooks fire only in that stack rather than
in every session, the way a global `~/.claude` does.

The two verbs share no flags except `--rm` (host-side: stop daemons this launch started). They are
separate commands rather than one command with a mode switch. The flags `--fresh`, `--no-firewall`,
`--shell`, `--mount-folder`, and `--agent-start-folder` all describe a pod. A host launch has none
of them, so a single combined verb can only accept them and do nothing.

`--recipe` is how you run without a hand-written stack. It normalizes the recipe set, derives a name
from its CONTENT, and mints a `stack.yaml` under the generated catalog root — which the container
backend then builds, and the host backend does not need to (it assembles in-process every launch).
Because the name is content-derived, the same recipe set in five repos is one stack — one image, one
pair of volumes. `--extends` defaults to `default` — the baseline stack the repo ships (`catalog/stacks/default`,
composing `catalog/recipes/default`), so the documented default resolves on a bare install rather
than only for users who happened to author a `default` stack of their own. Overlay a stack of that
name to replace it wholesale. `--no-extends` makes the recipe set stand alone, and therefore requires
at least one `--recipe` — with nothing inherited and nothing composed there is no stack to run.

A generated stack cannot use `ssh_keys:` — the private-key gate honors that field only from the
user's own overlay. That is correct rather than unfortunate: `ssh_keys` is per-stack and a generated
stack is shared across repos, so it cannot express "the key for *this* repo". Per-repo SSH
identity comes from the forwarded agent plus your own `~/.ssh/config`.

**Per-repo binding.** A launch records its resolved stack in harnessed's own state, and `--last`
replays it:

```console
$ harnessed container-run claude --recipe superpowers --recipe serena   # once
$ harnessed container-run claude --last                                 # thereafter
```

No env var, no discovery, no precedence rules, and nothing written into the repo. `--last` is a
flag rather than the bare verb because bare is already the `default` baseline; with no record it
fails loudly instead of falling back to one.

**The record belongs in harnessed's own state, never in a mise config.** mise keys trust per config
*file* and trust does not cascade from a trusted ancestor, so a file written into each project
re-prompts in every new worktree — and automating that trust is not an option, because a mise config
can carry `_.source`, so trusting one grants code execution. The two shapes that look like a way
around it are both worse: an unknown top-level `[harnessed]` table warns on every mise invocation,
and `[env] HARNESSED_RECIPES` is live only when mise is activated, so it fails silently and
expensively when it is not.

## Agent of Empires mirror (optional)

Agent of Empires (`aoe`) is a tmux session coordinator some users run in front of their agents. harnessed neither requires nor installs it. When `aoe` is installed (`aoe` on PATH and `~/.config/agent-of-empires/` present), every launch
mirrors itself into a dedicated `harnessed` aoe profile. The profile has a group per git repo and a
session per launch. `src/harnessed/aoe.py` is the whole bridge. `HARNESSED_NO_AOE=1` turns it off.

**Register-only, one-way.** harnessed still owns the process — `container-run` ends in an `os.execvp` that
hands your terminal to the agent. The row is a bookmark that can be started or attached from the
dashboard later; aoe never drives harnessed. Sessions stay in aoe's terminal (raw tmux/PTY) view. This is what `aoe add` already defaults to —
the structured view's ACP transport cannot reach through the `podman exec -it` attach that the
container backend uses. The `add` command therefore passes only `-p`, `-g`, `-t`, and
`--cmd-override`. `aoe add` rejects an unknown flag with exit 2 before adding anything. On the
detached write path, that failure is invisible.

| property | value | why |
| --- | --- | --- |
| identity | (project path, stack, harness, verb, MCP mode) | a stack has an assembled profile **per harness**, the same stack host-native vs containerized is two different things to run, and `--no-strict-mcp-config` changes the agent's MCP surface |
| identity, overridden | (group, title), with `--aoe-group` **and** `--aoe-title` | the only key that can adopt a row harnessed did not write |
| group | the git **common** dir's repo, or `--aoe-group` | every worktree of one checkout shares a group instead of each spawning its own |
| skipped | the `default` stack | the baseline every dynamic stack extends, not something the user composed |
| removed by | `harnessed rm <stack>` | container rows only — `rm` tears down containers, and a host-native session owns none |

**A row never outlives its launch.** Each backend registers only after its last validation gate —
`is_built` plus the staleness check for the container path, in-process assembly for the host path.
If registration happens earlier, the row becomes a bookmark for a launch that died on a renamed
recipe. That row fails identically every time it is started from the dashboard.

Two aoe behaviours the code is shaped around, neither documented by aoe:

1. **`--cmd` is not stored verbatim.** It is validated against aoe's own tool list and silently
   substituted with the configured default, so a harnessed invocation came back as
   `claude-with-env`. `--cmd-override` stores the string as given, and accepts harnesses aoe has no
   notion of (`omp`). The recorded command is both the replay and the identity key, so this matters
   twice.
2. **`add` deduplicates on (title, path) and exits 0.** A collision is not an error, it is a row
   that never appears. The title is therefore part of identity whether or not it looks cosmetic,
   and must separate backend as well as harness and stack.

**`--aoe-group` / `--aoe-title`** name the row instead of deriving it, on both run verbs. Given
together they also replace the identity key with (group, title), which is the only match that finds
a row harnessed did not write: a hand-placed or hand-edited one records the path as typed and
carries flags `command_for` does not emit, so by command it is invisible and a duplicate lands
beside it under the derived group. Either flag alone still overrides its half but leaves matching on
the command — a group holds many sessions and a title is unique only within one, so neither alone
identifies a row. Both are echoed back into the recorded command, or a restart from the dashboard
would re-derive the placement and produce that duplicate anyway.

**The recorded command replays the launch, so `--no-strict-mcp-config` is recorded too.** It is the
one launch flag that changes the *session*, not the invocation: dropped, claude also loads the
project's `.mcp.json` and the user's config, so a row that forgets it restarts with a different MCP
surface than the one registered. `--rm`, `--fresh` and the pod flags describe this invocation's
lifecycle and are correctly re-decided by a restart.

Recording it makes it identity, and identity the title cannot express is identity aoe discards — so
the derived title gains a ` +open-mcp` suffix in that mode. Without it the strict and open variants
of one stack share a title, the second `add` is refused at exit 0, and the row keeps replaying the
command it was first registered with. Strict titles are unchanged.

aoe has no verb that rewrites a session's stored command (`session rename` changes only the title),
so this fixes rows created from here on. A row registered before the flag was echoed keeps its old
command and re-registers once under the new identity; one adopted by `--aoe-group` + `--aoe-title`
is left exactly as it is, and must be removed and relaunched to pick the flag up.

`aoe add` takes ~12s (it starts aoe's daemon) while every read is ~0.01s. So the reads that decide
*whether* to write run inline, and the writes are fired into a `start_new_session` child that
outlives the `execvp`. A dashboard is not worth twelve seconds of a launch.

`--create-aoe-only` is the exception: on `container-run` and `host-run` it registers the session and
exits without launching. There registering *is* the command, so it blocks, prints what it wrote, and
exits non-zero if registration fails. On `container-run` a `--recipe` set is still minted AND
built — the row replays `container-run`, which hard-errors without an assembled profile. Skipping
the build creates a row that is dead on arrival. `host-run` needs no build: it assembles
in-process on every launch.

## Folder-env contract

The **one** set of environment variables a recipe may rely on. Same names, same meanings, on every
surface — container and `--host` alike. Single definition: `launcher.harnessed_env()`.

| Variable | Value |
| --- | --- |
| `HARNESS` | The harness being launched (`claude`, `omp`, …). Unprefixed on purpose: it is already the token a recipe Dockerfile branches on (`ARG HARNESS`), so `$HARNESS` in a setup script means the same thing. |
| `PROJECT_DIR` | The project directory the agent starts in. |
| `MAIN_REPO_DIR` | The git **common dir** — in a bare + linked-worktree layout that is the bare repo dir, not the default-branch work tree. Falls back to `PROJECT_DIR` outside a repo. |
| `HARNESSED_GIT_COMMON_DIR` | Same value as `MAIN_REPO_DIR`, under an explicit name. A bare `GIT_COMMON_DIR` is **never** exported: git itself consumes that variable and it hijacks common-dir resolution the moment the agent `cd`s into another repo. |
| `HOST_WORKSPACE_DIR` / `CONTAINER_WORKSPACE_DIR` | The mounted workspace root (auto-widened to the bare-repo container so sibling worktrees are visible). Identical strings — the project is bind-mounted at its own host path. |
| `HOST_HOME` | The **host** `$HOME`, which is not the container's (`/home/harnessed`). A `scope: global` persist entry is mounted path-preserving, so a recipe pointing a tool at e.g. `~/.pulumi` must write `$HOST_HOME/.pulumi`. |
| `HARNESSED_BIN_DIR` | The dir an `install.script` lands executables in — the same value the install contract hands that script, so a recipe can install a wrapper at build time and put it on PATH at attach time (`init: run: export PATH="${HARNESSED_BIN_DIR:?}/…:$PATH"`, e.g. a CLI shim). Container: `/home/harnessed/.local/bin`. Host: the stack's own `tools/<stack>/bin`. |
| `HARNESSED_RECIPE_DIR` | *(recipe-scoped surfaces only)* The recipe's own source dir — a setup script does `cp` where a Dockerfile did `COPY`. Host: the catalog dir. Container: `/opt/harnessed/recipes/<recipe>` (bind-mounted `:ro`). |
| `HARNESSED_<SERVICE>_SOCKET` | Agent-side socket path for each socket-backed project-scoped service (`HARNESSED_<NAME>_SOCKET`). Resolved per mode, so a host launch gets the host path, not the container's. |
| *(a service's own `client_env`)* | Whatever a project-scoped service declares its clients need — resolved per launch and injected under the service's chosen names, not a `HARNESSED_*` one. This is how a `publish: ephemeral` service hands over a host/port that does not exist until the container is running; `{host}` resolves to `127.0.0.1` on the host and `host.containers.internal` in a container. |

Injected at every place catalog-authored content runs: the container attach shell
(`_init_shell_prologue`), the container itself (`podman run -e`, so hooks and later `podman exec`s
agree), **both** `setup.condition` eval sites (`_collect_setup_notices`, `_confirm_setup`),
`setup.script` (`_script_env`, which additionally carries the `HARNESSED_MODE` /
`HARNESSED_CFG_*` / repo-identity vars), and the **host agent process** (`os.environ` in
`_launch_host` — on the host there is no container to set env on, so `os.environ` is the box).

This is why a condition may be written against a real path — `[ ! -f
"${MAIN_REPO_DIR}/.sometool/metadata.json" ]`. Under an env-less eval that expanded to the empty string
and the test passed falsely.

## Recipe scripts: `install:` vs `setup.script`

Both are a bash file in the recipe dir (an `install:` may instead be a bare `system:` reason with no
script at all — see **Shape** below), run by **both** executors (container and `--host`), linted
identically (raw `npm`/`npx` and floating refs rejected inside the `.sh` — `validate_install_script`
/ `validate_setup_script`, because `validate_pin` only ever reads Dockerfile *text*). They differ in
exactly one thing: **the phase**.

| | container | host |
| --- | --- | --- |
| `install:` | **first start** — `bash <script>` in a container writing to the per-stack volumes, with the recipe dir bind-mounted `:ro` at `/opt/harnessed/recipes/<recipe>`. Fingerprint-gated | immediately **after** `_materialize_host_home` |
| `setup.script` | **runtime** — `podman exec` after start, before the egress firewall closes | after `install` |

The split is forced, not stylistic. `setup` cannot run at build: no project is bind-mounted, so
`HARNESSED_PROJECT_DIR` is unresolvable. `install` used to be barred from container runtime for the
mirror-image reason — re-running it per start re-pays the clone every launch — but that assumed
**no persistence**. A fingerprint-gated per-stack volume removes the assumption: you pay once per
stack *change*, not per start, exactly as the host path already did. Moving it there is bd
harnessed-8px.21, and the reason is cost: a one-line edit to a recipe's `install.sh` cost **307s** as
a layer rebuild against **4.3s** for the same install executed natively. Almost none of that gap was
download — the build already had cache mounts — it was podman committing layers over a large tree.

Host installs run **after** the materialize because `_materialize_host_home` does
`shutil.rmtree(home)` on **every** launch (so a removed recipe's files never linger). Run before it,
the install's output is deleted milliseconds later, silently — which is exactly the shape of the bug
this mechanism fixes. That same wipe makes "run once on first launch" structurally impossible, so
the install runs every launch; `install.cache` is what makes that affordable (the *output* cannot
persist, but the pinned *source* can).

**Install env** — deliberately a *subset* of the folder-env contract above, not a superset:

| Variable | Value |
| --- | --- |
| `HARNESS` | as above |
| `HARNESSED_MODE` | `host` \| `container` |
| `HARNESSED_RECIPE_DIR` | the recipe's own dir — `cp` where a Dockerfile did `COPY` |
| `HARNESSED_CONFIG_DIR` | the agent config dir to install **into**: image `~/.claude` at build, the materialized host home on a host launch |
| `HARNESSED_INSTALL_CACHE` | `$XDG_CACHE_HOME/harnessed/install/<recipe>/<install.cache>`, or empty when no `cache:` is declared. Cache **miss** is "the directory does not exist" — harnessed creates only its parent. **The same host dir in both modes**: container-side it is bind-mounted into the install container, so the cache is finally shared *across stacks*. It used to be `/tmp` scratch discarded in the same layer. Keeping the clone ships it inside the image. |
| `HARNESSED_BIN_DIR` | where to land an **executable**: the base image's `~/.local/bin` (already on `PATH`) at build, the stack's own bin dir on a host launch. Without it a script has no portable destination for a binary and must either go root-only or guess at `$UV_TOOL_BIN_DIR`. |
| `HARNESSED_HOME_SHIM` | a dir whose `.claude` **is** `$HARNESSED_CONFIG_DIR`, for upstream installers that only know how to install "globally" into `$HOME/.claude`: run them as `HOME="$HARNESSED_HOME_SHIM" <installer>`. The image home at build (where that is already true); a **stable** per-project sibling of the config dir on a host launch. Stability is the point — a recipe rolling its own with `mktemp -d` gets a shim deleted on exit, so any absolute path the installer *recorded* dies with it. `install.sh` must not build its own shim; a catalog test enforces this. |

`PROJECT_DIR` and friends are **absent on purpose**. A build cannot know them. If you export them
host-side only, authors get a variable that works on the host and silently expands to empty in a
build. Anything needing project context belongs in `setup.script`, whose phase has a project.

**Host-only extras.** Alongside the contract above, `_host_run_installs` also redirects the package
managers so a tool installed by an install script lands in the *stack's* tree rather than the user's
global one — there is no image to contain it host-side:

| Variable | Value |
| --- | --- |
| `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` | the stack's uv tool dir and bin dir, so `uv tool install` stays inside the stack |
| `npm_config_prefix` | the stack tools dir, so `pnpm add -g` does not write the user's global prefix |
| `PATH` | `$HARNESSED_BIN_DIR` **first**, so a tool an install just landed is resolvable by the next line of the same script |

These are host-only *by design*: container-side the image already provides the containment they
recreate. They are NOT part of the both-modes contract, so a script must not depend on their values
— use `$HARNESSED_BIN_DIR` for a path you need to name.

**Shape.** `install:` is usually one bash file, but not always:

- `script:` only — the common case; runs in both modes.
- `script:` **and** `system:` — a partial migration. The script runs in both modes; the recipe's
  Dockerfile keeps a container-only step (root, or a write outside harnessed-owned dirs). `system:`
  is a prose reason, printed verbatim at host launch to say what that launch does *not* get.
- `system:` only, **no script** — a root-only install. The whole step lives in the recipe's
  Dockerfile; nothing is emitted at build and the host behaviour is the warning and nothing else.

`validate_container_only_declared` rejects the fourth combination — a recipe with an `install:` whose
Dockerfile still has a `RUN` but which declares no `system:`. That shape delivers less on a host
launch than the recipe promises, silently. Relatedly, a recipe Dockerfile may not reference
`~/.claude` at all (`validate_no_claude_writes`): content written there is invisible to a host launch
and hidden by the profile bind-mount in a container, so it belongs in `install.script` writing to
`$HARNESSED_CONFIG_DIR`.

**Precedence, identical in both modes**: inherited environment → recipe `env:` → harnessed-owned
install contract. The contract wins. Container gets that from inline `VAR=… bash install.sh`
assignments beating the preceding `ENV` lines; host from `env.update(install_env(...))` running last.
Asserted as *order*, not values, in `tests/test_install_script.py::TestPrecedence`.

**System-level steps** (`USER root`, `apt-get`, `COPY` into `/usr/local/bin`) stay in the recipe
Dockerfile — harnessed never sudos or mutates the user's system. A recipe with such a step declares
`install.system: "<reason>"`; a host launch then **skips it and says so**, naming the recipe and
printing the reason verbatim. Documented skip, not hard failure (a hard failure makes `--host`
unusable for stacks in the default set) — and never a *silent* skip.

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
for light Python MCP servers; credentials referenced, never replicated; MCP transports are `stdio`
and Streamable-HTTP (SSE is rejected at validation).

**Credentials are referenced, never replicated (SOP).** harnessed never copies, seeds, or snapshots
a harness's credential store into a per-stack home — container or host. The reason is structural,
not stylistic: a harness **rewrites its own credential store on token refresh**. Any copy harnessed
makes therefore rots the moment a token refreshes, and the next launch restores the stale one — a
silent logout the user experiences as "it keeps asking me to log in". Two mechanisms are sanctioned:

1. **Reference the live store** — a mount or a symlink at the real path (ro where the harness only
   reads it, rw where it owns the whole dir). Always current by construction.
2. **Reference a token or broker URL** — an env token, or omp's `auth.broker.url` +
   `auth.broker.token`. No file involved at all.

Everything else is replication and is out of bounds, however carefully guarded. "Copy it back if
it is newer" is still replication — it just moves the race rather than removing it.

**A symlink is a reference only while the harness writes in place.** This is the property that
decides whether mechanism 1 is available for a given harness, so establish it before designing:

- **Writes in place → the link holds.** SQLite is the worked example: it resolves the symlink, so
  `-wal`/`-shm` are created beside the **target**, and concurrent openers through different links
  share one database rather than diverging. Verified against omp's `agent.db` (two links, two live
  connections, one consistent row set; both links intact afterwards).
- **Replaces the file → the link silently becomes a copy.** Claude Code rewrites
  `.credentials.json` by replacement, converting the link into a regular file whose refreshed token
  never reaches the shared store. That is harnessed-8px.10, and it is a property of the harness, not
  a flaw in symlinks.

**This SOP governs credentials only.** Symlinking *history, sessions, memory and usage state* up to
one shared location is deliberate design, not a violation — a universal rolled-up view across every
stack is the point, and those files are not subject to the replace-on-refresh hazard above.

**Auth is per-harness.** For **claude** there are two paths, in order of preference:

1. **`CLAUDE_CODE_OAUTH_TOKEN` (primary — mechanism 2).** A long-lived subscription token issued
   by `claude setup-token` (~1-year lifetime). Forwarded from the host environment or a resolved
   `--env-file` (varlock / 1Password). When present, no credential file is mounted at all — the
   copy-divergence problem does not arise. Also mounted in all cases: a token-free `~/.claude.json`
   onboarding stub so Claude skips the interactive setup screen.
   **A token from an `--env-file` outranks one exported in the shell**, in both backends: `podman
   run -e` beats `--env-file`, so the launcher withholds the host forward when a resolved env-file
   already declares the variable. Without that, a stale export outranks every declared source and a
   per-project token can never take effect.
   Among the declared sources the **last** one wins, matching the global → project order the
   env-files are built in — and an explicit empty value is a declaration meaning *off*, not an
   absence. A project-level `CLAUDE_CODE_OAUTH_TOKEN=` therefore disables a user-global token and
   correctly falls back to the credential file; answering from the first source instead left the
   container with no token *and* no credentials (harnessed-7bk).
2. **Per-instance credential seed (legacy fallback — NOT mechanism 1).** When no OAuth token is
   configured, the launcher seeds a per-instance copy of `~/.claude/.credentials.json`, mounted
   **rw** so the container can refresh it. This is acknowledged replication — it violates the SOP
   above — and is tolerated only so that hosts which have not yet run `claude setup-token` keep
   working. The container's copy diverges from the host's on the first token refresh, and concurrent
   rotation is undocumented. The launcher re-seeds from the host file when the copy has expired,
   which addresses the "permanently logged out" failure mode of the original design; the underlying
   race remains. Migrate with `claude setup-token`.

**A third path exists for a different *identity*, not a different mechanism: `isolated_auth: true`
(stack).** Both paths above answer "how does the container get **your** login". This one answers
"how does a stack run as **someone else's**" — a client's account. The host token is withheld (env
forward *and* `--env-file`, so a user-global declaration cannot leak in), no host credential file is
seeded, and the stack gets a per-instance `.credentials.json` it logs into itself. Persisted across
recreates, cleared by `--fresh`; container backend, claude only.

It is **not** a fourth violation of the SOP. The rule bans *copying* the host store, because a copy
rots the moment either side refreshes. Nothing is copied here: the store is minted in-container by
its own login and is the only copy of that credential in existence, so there is no second copy to
diverge from. The store lives on the host rather than in the `~/.claude` config volume because
`_ensure_config_volume` destroys that volume whenever the profile fingerprint changes — its own
"safe to destroy: credentials are bind-mounted over it" invariant is what this relies on.

**`host-run` applies the same order.** Without a token it symlinks the per-stack `.credentials.json`
at the host `CLAUDE_CONFIG_DIR`'s (default `~/.claude`; mechanism 1, subject to the replace-on-refresh hazard above — hence the rescue
that promotes a refreshed token back before the next launch wipes the home). With one configured it
does neither: no link is made, the rescue is skipped, and a copy an earlier token-free launch left
behind is removed, so the stale file cannot outlive the switch. The shared `~/.claude` copy is never
deleted — or, when configured, the shared `CLAUDE_CONFIG_DIR` copy is never deleted — because it is the user's own login, outside any stack.

**omp** stores auth/usage/sessions together in `~/.omp/agent` with no separately-mountable
credential file, so the launcher **bind-mounts that host dir read-write** and runs plain `omp`
(never `--profile`, which points omp at an isolated *empty* store — a credential-only seed lands on
the login screen). That is mechanism 1 (reference the live store, at dir granularity): shared host
state, deliberately not isolated. Do not "fix" it back to isolation by snapshotting the dir — that
was built, tried, and rejected; see [design §4c](docs/harnessed-design.md).

Both host backends inherit the same shape, because `CLAUDE_CONFIG_DIR` and `PI_CODING_AGENT_DIR`
each move config **and** credentials together. The per-stack home therefore holds content
(`skills`/`rules`/`commands`/`mcp.json`/`config.yml`) while state — `agent.db`, `history.db`,
`sessions/`, `memories/` — is symlinked back to the one shared store, which keeps history universal
and, for omp, makes auth shared as a side effect of mechanism 1. claude is the harness where that
does not hold, per the replace-on-refresh case above.
