# `recipe.yaml` fields

Every accepted top-level key. Anything else is rejected in strict mode (`KNOWN_RECIPE_FIELDS` in
`src/harnessed/schema.py`, which is the authority):

```text
name description mcp skills commands rules expect persist init conflicts hooks setup
install egress tools env services            plugins deps scripts   (forward-parsed only)
```

Only `name` is required. A recipe may deliver nothing and exist purely to declare a contract.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/recipe.schema.json
name: my-recipe                  # required; must match the directory name
description: one line
```

## MCP servers — three shapes, pick by where the server runs

```yaml
mcp:
  servers:
    # 1. stdio child — hatago spawns it and wraps stdio→HTTP. Light, dependency-free servers.
    - name: time
      command: uvx
      args: [mcp-server-time==2026.7.10]   # PIN the package. Nothing validates `args:` —
      transport: stdio                     # validate_pin reads Dockerfile text only — so an
                                           # unpinned server here is on you. `transport` is the
                                           # default, but write it: the shape is load-bearing

    # 2. local sidecar — resolved from catalog/services/<name>/service.yaml to a URL
    - name: ping
      service: ping
      transport: http

    # 3. remote URL — hatago proxies it verbatim
    - name: openbrain
      url: https://host/functions/v1/mcp?key=...
      transport: http
      headers: {Authorization: "Bearer ..."}   # written verbatim into hatago.config.json
      env: {FOO: bar}
```

`localhost` inside a pod is the pod, not your machine. A server running on the **host** must be
addressed as `http://host.containers.internal:<port>/mcp`.

`url:` and `headers:` land in the generated `hatago.config.json` in plaintext (host-local, never an
image layer, never committed) — a recipe carrying a real key belongs in the overlay only.

## File-extension layer

```yaml
skills:                     # DIRECTORIES only; leaf name becomes the profile target
  - path: skills/my-skill   #   → .claude/skills/my-skill
commands:                   # DIRECTORIES only — a namespace dir is the unit
  - path: commands/mine     #   → .claude/commands/mine/*.md, invoked as /mine:<cmd>
rules:                      # the one field that accepts a FILE as well as a directory
  - path: rules/react.md    #   → .claude/rules/react.md          (preferred, flat)
  - path: rules/my-rule     #   → .claude/rules/my-rule/RULE.md   (both are loaded)
```

Each skill, command, or rule entry also takes `only_harnesses:`, an allow-list. Every other harness
skips it. No other recipe field accepts it.

```yaml
rules:
  - path: rules/ctx-routing
    only_harnesses: [omp]   # ships to omp only
```

Use it when a rule exists to cover a hook that cannot fire on one harness. It is the complement of
`hooks.<Event>[].skip_harnesses`: skip the hook where it cannot run, ship the rule there instead.
Keep the pair in lockstep, or the same steering arrives twice.

It is an allow-list, not a skip-list, on purpose. Content that patches one harness must never ship
to a harness added later.

Leaf names are global across the stack — the assembler **fails fast** if two recipes contribute the
same skill or command name. Design complementary recipes with zero name overlap.

A rule with no `paths:` frontmatter loads at launch; `paths: ["src/**/*.ts"]` scopes it.

## `expect:` — what the assembler cannot see

The assembler knows about `skills:`/`commands:`/`mcp.servers`. It cannot see what an
`install.script` writes into `$HARNESSED_CONFIG_DIR`, or what `tools:` puts on `PATH`. Declare those
so `harnessed test` probes for them:

(A recipe **Dockerfile** is not on this list because it may not deliver `~/.claude` content at all —
`validate_no_claude_writes` rejects any `.claude` mention in a recipe Dockerfile body. Content goes
through `install.script`, which lands in both modes.)

```yaml
expect:
  skills:   [gstack, review]
  commands: [some-cmd]
  plugins:  [some-plugin]
  mcp:      [some-server]
```

A stable handful is enough to prove an install worked.

## `persist:` — data that survives `--fresh`

Two axes. Scope = what identifies the owner; location = where the bytes live.

```yaml
persist:
  - name: .context-mode      # harnessed-managed dir, bind-mounted at ~/.context-mode
    scope: workspace         # workspace (launch path) | project (git-common-dir) | global
    location: host           # host | in_repo
  - name: .mydata
    scope: workspace
    location: in_repo        # inside the already-mounted workspace; no extra mount
    vcs: tracked             # REQUIRED for in_repo: tracked | ignored (ignored → .gitignore entry)
  - path: /home/USER/.pulumi # scope: global uses a real host path instead of name:
    scope: global            #   must be pre-registered in ~/.config/harnessed/persist-allowlist
```

`workspace` is the right default. `project` when the data is per-repository and should be identical
across worktrees. `global` only for one shared knowledge base across every project.

`scope: repo` and `location: external` are reserved and rejected today.

Inspect and prune: `harnessed-tools persist-list`, `harnessed-tools persist-prune --recipe <r>
--project <p> --yes`.

## Three ways to do work, split by phase

Pick by **what the phase can see**. This is forced, not stylistic.

| Field | Runs | Sees a project? | For |
| --- | --- | --- | --- |
| `install:` | first launch (container: in a container writing the per-stack volumes, fingerprint-gated; host: right after the home is materialized) | no | fetching/installing content into the config dir |
| `setup.script` | after the container starts, before the egress firewall closes; host: after install | yes | anything needing `PROJECT_DIR` |
| `init.run` | sourced inline in the attach shell on **every** attach | yes | cheap, self-gating, idempotent one-liners |

```yaml
install:
  script: install.sh     # one bash file, run in BOTH modes
  cache: v6.0.3          # pinned ref → enables $HARNESSED_INSTALL_CACHE. Floating refs rejected.
  system: "apt package X needs root"   # prose reason for a container-only Dockerfile step;
                                       # printed verbatim and skipped on a host launch
  hold: "upstream has no tags"         # `harnessed update` lists but never bumps these pins

setup:
  summary: Run `bd init …` once per workspace, then restart the agent.   # required
  reference: https://example/docs                                         # required
  condition: '! bd list >/dev/null 2>&1'   # exits 0 while STILL needed → synthesizes a self-gating
                                           # Claude SessionStart hook and drops the static bullet
  script: setup.sh
  confirm: "This will commit files into the repo. Proceed?"

init:
  run: bd list >/dev/null 2>&1 || bd init --quiet   # sourced → no `exit` (rejected at parse time);
                                                    # non-zero aborts the attach
```

**Install-script env** (identical in both modes — a deliberate *subset*; `PROJECT_DIR` is absent
because a build has no project):

| Variable | Value |
| --- | --- |
| `HARNESS` | `claude`, `omp`, … |
| `HARNESSED_MODE` | `host` \| `container` |
| `HARNESSED_RECIPE_DIR` | the recipe's own dir — `cp` from here instead of `COPY` |
| `HARNESSED_CONFIG_DIR` | the config dir to install **into** |
| `HARNESSED_INSTALL_CACHE` | cache dir, or empty when no `cache:`. Miss = the dir does not exist. |
| `HARNESSED_BIN_DIR` | where an executable goes. Use this, never `$UV_TOOL_BIN_DIR`. |
| `HARNESSED_HOME_SHIM` | a dir whose `.claude` **is** `$HARNESSED_CONFIG_DIR`, for installers that only know how to install globally: `HOME="$HARNESSED_HOME_SHIM" <installer>`. Never roll your own with `mktemp -d` — that shape is rejected. |

An `install.sh` that fetches a binary **must verify a checksum**. Nothing enforces this
syntactically; it is an authoring obligation. If the install writes outside harnessed-owned dirs,
document the removal procedure.

Declare `install.system:` for any root-level Dockerfile step. A recipe with an `install:` whose
Dockerfile still has a `RUN` but declares no `system:` fails validation — that shape silently
delivers less on a host launch than the recipe promises.

## `env:` — variables the running agent gets

```yaml
env:
  SOME_FLAG: "1"
  CONTEXT_MODE_DIR: "{persist:.context-mode}"   # resolves per mode: mount target in a container,
                                                # the real host path on a host launch
```

The one recipe deliverable that survives into the agent process — a script `export` dies with the
script. Distinct from `mcp.servers[].env`. Precedence: inherited env → recipe `env:` → the
harnessed install contract (the contract always wins).

## The cheap escape hatches

```yaml
tools: [pulumi@3.140.0]     # pinned mise tools, installed as a `mise use -g` layer. No Dockerfile.
egress: [api.pulumi.com]    # opens the default-DROP egress firewall for these hosts, ONLY when this
                            # recipe is in the stack. Bare hostnames — no scheme, path, or port.
services: [my-server]      # sidecars this recipe needs that have NO MCP surface, so they cannot be
                            # declared through mcp.servers[].service. Unioned with the stack's list.
conflicts: [other-recipe]   # mutually exclusive recipes; checked symmetrically at parse time
hooks:                      # native Claude Code hook shape, merged into the profile settings.json
  SessionStart: [{command: "echo hi"}]
```

Together `tools:` + `egress:` let a recipe expose a whole cloud CLI as pure YAML with no Dockerfile.

## When you do need a Dockerfile

Ship `Dockerfile` next to `recipe.yaml`. The assembler concatenates every recipe's body in stack
order under a prepended `FROM harnessed-${HARNESS}:latest`.

```dockerfile
USER root
RUN apt-get update && apt-get install -y --no-install-recommends some-lib && rm -rf /var/lib/apt/lists/*
USER harnessed
ARG GSTACK_REF=11de390be1be6849eb9a15f91ff4922dd16c589a
RUN git init -q ~/x && cd ~/x && git remote add origin https://github.com/o/r.git \
    && git fetch --depth 1 origin ${GSTACK_REF} && git checkout -q FETCH_HEAD && ./setup
```

- No `FROM`, no `ARG HARNESS` — both are prepended. Adding your own produces a malformed body.
- `USER root` for system installs, then back to `USER harnessed` before the body ends. Fix up
  ownership of any cache an earlier root step created.
- **Replicate the upstream installer.** If the project's docs say "clone and run `./setup`", run
  exactly that. Do not hand-copy files or reverse-engineer a layout.
- Watch for OS libraries an installer pulls an app but not its deps for.
- Pin everything. Prefer a release tag; fetch-by-SHA when upstream publishes none.

## Recipe varieties

`catalog/recipes/<family>/<variety>/recipe.yaml` is referenced as `family/variety` (e.g.
`fam/a`, `fam/b`). Sibling varieties of one family are implicitly exclusive — a stack
cannot carry two.
