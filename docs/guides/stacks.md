# Composing stacks

A **stack** is a manifest (`stacks/<name>/stack.yaml`) that composes **one** harness with a chosen
set of recipes (and optional shared services). A running `isolated` stack is a podman pod — harness
container + hatago + any declared services — composed at runtime, not baked at build time (`FROM`
can't union sibling systems; design §3, §6). `transparent` is the degenerate, host-mirror case.

For the *why* (why one harness per stack, why transparent vs isolated, the runtime-pod model), read
[docs/harnessed-design.md §2 & §12](../harnessed-design.md). This guide shows the *how* with worked
examples from this repo's `stacks/`.

## What a stack is

```
stacks/<name>/stack.yaml        # the manifest (you author or scaffold)
  ↓ harnessed build <stack>     # assemble (emit-only) + scan + host podman build
profiles/<name>/                # GENERATED + committed; mounted into the harness container
  .claude/{skills,commands,...} # the assembled, version-controlled profile
  hatago.config.json
```

Recipes are resolved **ahead of time** into a committed profile plus pinned images; the host runs
`podman build`, and nothing is assembled at container start (design §15).

## The `stack.yaml` schema

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`Stack`).
Key fields:

```yaml
name: <stack>                     # required
config: isolated                  # isolated (default) | transparent
harness: claude                   # claude | omp  (exactly one)
recipes: [a, b, c]                # list of recipes/ to compose (transparent stacks omit this)
services: [ping]                  # optional — shared sidecars to attach (auto-started on launch)
permissions: yolo                 # optional — prompt (default) | yolo (writes skip-permission config)
state:                            # optional
  persist: true                   # default; `--fresh` overrides at runtime
  session_state: host             # host (default — sessions persist, inspectable) | volume
```

Notes:

- **One harness per stack** (design §8). `claude` mounts the profile natively; `omp` consumes the
  *same* Claude-canonical profile via `claude-hooks-bridge` — no re-authoring.
- `transparent` omits `harness`, `recipes`, and `services`: it mirrors **all** host harness configs
  live and you pick one in the shell.
- Only the fields you exercise are required; the assembler parses the rest forward.

## Worked example 1: `tracer-time` (isolated, claude, one recipe)

[`stacks/tracer-time/stack.yaml`](../../stacks/tracer-time/stack.yaml) is the Phase 2 tracer bullet —
the smallest end-to-end isolated slice:

```yaml
name: tracer-time
config: isolated      # isolated (default) | transparent
harness: claude       # claude | omp  (exactly one)
recipes: [time]
```

The full lifecycle:

```bash
harnessed build tracer-time      # assemble → scan → build hatago → image scan
harnessed tracer-time            # launch the pod (harness + hatago), attach
harnessed test tracer-time       # capability report: ✓ time (mcp), ✓ time-helper (skill)
```

`harnessed build` emits the `profiles/tracer-time/` tree (assembled from `recipes/time`) and builds
the hatago image. `harnessed tracer-time` composes the pod and attaches; `harnessed test` brings the
instance up `--fresh` headless and asserts the manifest's declared capabilities are live (design
§18). Running an unbuilt isolated stack errors and tells you to `harnessed build` first.

## Worked example 2: `transparent` (the degenerate host-mirror stack)

[`stacks/transparent/stack.yaml`](../../stacks/transparent/stack.yaml) is the built-in transparent
stack — today's `container`:

```yaml
name: transparent
config: transparent
# harness omitted: transparent mirrors all host harness configs; pick one in the shell
```

No recipes, no services, no hatago, no assembler. The harness container runs with the host's
`~/.claude` (+ `.codex`/`.config/opencode`/`.gemini`) mounted live (with a copy-on-start
`.claude.json` so the host file is never rw-raced). Launch it from any project:

```bash
cd /path/to/project
harnessed transparent      # or just: container
```

Contrast with `isolated`: `transparent` carries **all** host defaults; `isolated` carries **only**
what the profile declares (auth seeded, no host config).

## Worked example 3: `ping-time` (a stack with a shared service)

[`stacks/ping-time/stack.yaml`](../../stacks/ping-time/stack.yaml) composes a stdio recipe (`time`)
with a service-ref recipe (`ping`) and attaches a shared sidecar:

```yaml
name: ping-time
config: isolated
harness: claude
recipes: [time, ping]
services: [ping]
```

- `recipes: [time, ping]` — the assembler composes **two** recipes into one profile: the `time` stdio
  server (hatago child) **and** the `ping` network-native server (hatago URL-proxy). The capability
  test asserts both.
- `services: [ping]` — the isolated launcher **auto-starts** the `ping` sidecar on launch
  (`ensure_service_up`) if it isn't already running. The service is a standalone container (own
  image + volume), **not** a pod member; its lifecycle is independent of any instance.

Authoring the sidecar itself is covered in the [service-authoring guide](service-authoring.md).

> Other stacks in this repo follow the same shape: [`stacks/claude-multi`](../../stacks/claude-multi/stack.yaml)
> (two recipes on claude — proves multi-recipe composition) and [`stacks/omp-time`](../../stacks/omp-time/stack.yaml)
> (the same `time` recipe on the `omp` harness via the bridge — proves one canonical profile runs on
> either harness).

## Scaffolding a new stack

`harnessed new` (CLI-02) writes a manifest for you — validating the harness and refusing to
overwrite an existing stack:

```bash
harnessed new my-stack --harness claude --recipes time,greet
# → writes stacks/my-stack/stack.yaml:
#   name: my-stack
#   config: isolated
#   harness: claude
#   recipes: [time, greet]
```

`--harness` must be `claude` or `omp` (hard error otherwise). Recipes need not pre-exist yet —
`harnessed new` **warns** (not fails) if a recipe dir is missing, so you can author the stack first
and the recipes after.

## Build + run lifecycle

| Step | Command | Notes |
| --- | --- | --- |
| Build | `harnessed build <stack>` | Assemble (emit-only) + scoped source scan + host hatago build + image scan. Fails on HIGH. |
| Run | `harnessed <stack> [path]` | Compose the pod (harness + hatago), attach. Auto-builds missing images. |
| Clean-room run | `harnessed <stack> --fresh` | Tear down any existing pod/instance first; reseed state from the profile. |
| Capability test | `harnessed test <stack>` | Launch `--fresh` headless + assert declared capabilities (markdown report). |
| List | `harnessed list` | Authored stacks + running instances. |
| Stop / remove | `harnessed stop \| rm <stack>` | Stop or remove every instance of a stack (across projects). |
| Install | `harnessed install <stack>` | Write a `~/.local/bin/<stack>` launcher shim (launch by name from any cwd). |

State persists by default: an isolated instance writes `projects/` + `history.jsonl` to a
harnessed-owned host dir with a legible project slug (STA-02). `--fresh` is the throwaway path. See
the [troubleshooting guide](troubleshooting.md) for the state-dir layout and `--fresh` semantics.

## See also

- [docs/harnessed-design.md §2 & §12](../harnessed-design.md) — the *why* (modes, the stack manifest, state).
- [Recipe-authoring guide](recipe-authoring.md) — author the recipes a stack composes.
- [Service-authoring guide](service-authoring.md) — author the sidecars a stack attaches.
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `Stack` model.
