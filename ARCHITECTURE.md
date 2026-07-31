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
- **catalog** — the collection of agents/recipes/services/stacks. Three roots, searched in order:
  the user overlay **`~/.config/harnessed/catalog`** (wins on a name clash), the repo `catalog/`,
  and last the **generated** root `$XDG_DATA_HOME/harnessed/generated/` holding machine-minted stacks
  (`harnessed run`). Generated is last so it can never shadow a stack you authored, and it is kept
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
   pays nothing. `launch` calls the same function, which is what keeps the two paths in step.
5. scan the populated volumes and merge the installer-written `settings.json` back into the profile.

The volume is **composed**, never layered: podman's copy-up lifts the image's own content in, then
the fanned profile content goes on top. That is what retired the old copy-the-baked-content-back-out
pass — with one tree there is nothing left for a mount to shadow (bd harnessed-8px.22, where a
profile dir mounted over `~/.claude/skills` hid 70 of 75 skills).

`harnessed <stack> <harness>` then launches the pod (derived image if present, else the agent image), starts
**hatago** as a process *inside* that container (hatago-consolidation), and brings up any referenced
services (started host-published, idempotently).

## Two launch verbs, one per backend

| verb | backend | what it isolates |
| --- | --- | --- |
| `harnessed launch <stack> <harness>` | container (podman pod + hatago + services) | the filesystem, the network, **and** the configuration |
| `harnessed host-run <stack> [harness]` | host-native — no podman, no MCP hub | the **configuration only** |
| `harnessed run --recipe <r> … <harness>` | container, composed at launch | same as `launch` |

`host-run` materializes the stack's assembled profile into a per-stack `CLAUDE_CONFIG_DIR`
(`<stack>/<harness>`, see `paths.host_home`) and execs the harness against your real machine, real
project, and real credentials. Configuration isolation *is* the host backend's boundary — which
skills, rules, commands and hooks are live — so a stack's hooks fire only in that stack rather than
in every session, the way a global `~/.claude` would.

The two verbs share no flags but `--rm` (host-side: stop daemons this launch started). That is the
reason they are separate commands rather than one command with a mode switch — `--fresh`,
`--no-firewall`, `--shell`, `--mount-folder` and `--agent-start-folder` all describe a pod, and a
host launch has none, so a combined verb could only accept them and do nothing.

`run` is `launch` without a hand-written stack. It normalizes the recipe set, derives a name from
its CONTENT, mints a `stack.yaml` under the generated catalog root, builds it, and hands off to
`launch`. Because the name is content-derived, the same recipe set in five repos is one stack — one
image, one pair of volumes. `--extends` defaults to `default`; `--no-extends` stands alone.

A generated stack cannot use `ssh_keys:` — the private-key gate honors that field only from the
user's own overlay. That is correct rather than unfortunate: `ssh_keys` is per-stack and a generated
stack is shared across repos, so it could never express "the key for *this* repo". Per-repo SSH
identity comes from the forwarded agent plus your own `~/.ssh/config` (bd harnessed-ji6).

**Per-repo binding.** A project records its recipe set as a mise task:

```toml
[tasks.start-harness]
run = "harnessed run --recipe superpowers --recipe serena claude"
```

No env var, no discovery, no precedence rules — and the trust question answers itself, because
`mise run` refuses an untrusted config, so a cloned repo's task cannot select anything until you
`mise trust` it. Rejected alternatives are recorded in bd harnessed-7rx: an unknown top-level
`[harnessed]` table warns on every mise invocation, and `[env] HARNESSED_RECIPES` is live only when
mise is activated, failing silently and expensively when it is not.

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
| `HARNESSED_BIN_DIR` | The dir an `install.script` lands executables in — the same value the install contract hands that script, so a recipe can install a wrapper at build time and put it on PATH at attach time (`init: run: export PATH="${HARNESSED_BIN_DIR:?}/…:$PATH"`, beads' `bd-shim`). Container: `/home/harnessed/.local/bin`. Host: the stack's own `tools/<stack>/bin`. |
| `HARNESSED_RECIPE_DIR` | *(recipe-scoped surfaces only)* The recipe's own source dir — a setup script does `cp` where a Dockerfile did `COPY`. Host: the catalog dir. Container: `/opt/harnessed/recipes/<recipe>` (bind-mounted `:ro`). |
| `HARNESSED_<SERVICE>_SOCKET` | Agent-side socket path for each socket-backed project-scoped service (e.g. `HARNESSED_BEADS_SERVER_SOCKET`). Resolved per mode, so a host launch gets the host path, not the container's. |
| *(a service's own `client_env`)* | Whatever a project-scoped service declares its clients need — resolved per launch and injected under the service's chosen names, not a `HARNESSED_*` one. This is how a `publish: ephemeral` service hands over a host/port that does not exist until the container is running; `{host}` resolves to `127.0.0.1` on the host and `host.containers.internal` in a container. See `services/beads-server/service.yaml`. |

Injected at every place catalog-authored content runs: the container attach shell
(`_init_shell_prologue`), the container itself (`podman run -e`, so hooks and later `podman exec`s
agree), **both** `setup.condition` eval sites (`_collect_setup_notices`, `_host_run_setups`),
`setup.run` / `setup.script` (`_script_env`, which additionally carries the `HARNESSED_MODE` /
`HARNESSED_CFG_*` / repo-identity vars), and the **host agent process** (`os.environ` in
`_launch_host` — on the host there is no container to set env on, so `os.environ` is the box).

This is why a condition may be written against a real path — `[ ! -f
"${MAIN_REPO_DIR}/.beads/metadata.json" ]`. Under an env-less eval that expanded to the empty string
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
mirror-image reason — re-running it per start would re-pay the clone every launch — but that assumed
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
| `HARNESSED_INSTALL_CACHE` | `$XDG_CACHE_HOME/harnessed/install/<recipe>/<install.cache>`, or empty when no `cache:` is declared. Cache **miss** is "the directory does not exist" — harnessed creates only its parent. **The same host dir in both modes**: container-side it is bind-mounted into the install container, so the cache is finally shared *across stacks*. It used to be `/tmp` scratch discarded in the same layer, because a build that kept the clone would have shipped it inside the image. |
| `HARNESSED_BIN_DIR` | where to land an **executable**: the base image's `~/.local/bin` (already on `PATH`) at build, the stack's own bin dir on a host launch. Without it a script has no portable destination for a binary and must either go root-only or guess at `$UV_TOOL_BIN_DIR`. |
| `HARNESSED_HOME_SHIM` | a dir whose `.claude` **is** `$HARNESSED_CONFIG_DIR`, for upstream installers that only know how to install "globally" into `$HOME/.claude`: run them as `HOME="$HARNESSED_HOME_SHIM" <installer>`. The image home at build (where that is already true); a **stable** per-project sibling of the config dir on a host launch. Stability is the point — a recipe rolling its own with `mktemp -d` gets a shim deleted on exit, so any absolute path the installer *recorded* dies with it. `install.sh` must not build its own shim; a catalog test enforces this. |

`PROJECT_DIR` and friends are **absent on purpose**. A build cannot know them; exporting them
host-side only would hand authors a variable that works on host and silently expands to empty in a
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
printing the reason verbatim. Documented skip, not hard failure (a hard failure would make `--host`
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
for light Python MCP servers; credentials referenced from the host, never baked; Streamable-HTTP MCP
(SSE is deprecated).

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
it's newer" is still replication — it just moves the race rather than removing it.

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
2. **Per-instance credential seed (legacy fallback — NOT mechanism 1).** When no OAuth token is
   configured, the launcher seeds a per-instance copy of `~/.claude/.credentials.json`, mounted
   **rw** so the container can refresh it. This is acknowledged replication — it violates the SOP
   above — and is tolerated only so that hosts which have not yet run `claude setup-token` keep
   working. The container's copy diverges from the host's on the first token refresh, and concurrent
   rotation is undocumented. The launcher re-seeds from the host file when the copy has expired,
   which addresses the "permanently logged out" failure mode of the original design; the underlying
   race remains. Migrate with `claude setup-token`.

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
