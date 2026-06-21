# Coding Conventions

**Analysis Date:** 2026-06-16

This repo runs **two engines in two dialects**, and the boundary between them is the
single most important convention to internalize:

- **Host BASH launcher** — `harnessed` + `lib/*.sh`. Runs *on the host*. Owns every
  `podman`/`docker` call (image build, pod compose, `exec`, lifecycle). Host-native:
  **no daemon-in-container, no API socket, no Docker-out-of-Docker** (design §15).
- **EMIT-ONLY Python assembler** — `tools/harnessed/*.py`, packaged as the
  `harnessed-tools` image (`tools/Dockerfile`). Runs *inside a container*, mounted
  read-write on the build dir only. It **reads `recipes/` + `stacks/`, writes
  `profiles/<stack>/` + `hatago.config.json`** — and that is all. It never invokes a
  container runtime. Emit-only is enforced by discipline, not by a sandbox.

The contract between them is a one-way handoff: the launcher asks the assembler to
emit artifacts, then the *host* builds images from those artifacts
(`build_stack` in `lib/harnessed-common.sh`). Neither calls into the other's domain.

## Tooling: there is intentionally almost none

There is **no `.editorconfig`, no `.shellcheckrc`, no ruff/black/isort config, no
prettier**. `tools/pyproject.toml` declares dependencies and a `[project.scripts]`
entry only — there is no `[tool.ruff]` / `[tool.black]` block.

This is deliberate: the persistent host dependency surface is meant to stay at
"podman only" (design §15). The conventions below are therefore enforced by **shared
style + code review**, plus two structural guardrails:

1. **`# shellcheck source=…` directives** annotate every `. lib/…` so shellcheck can
   follow sourced files. Example from `harnessed`:
   ```bash
   # shellcheck source=lib/harnessed-common.sh
   . "$HARNESSED_DIR/lib/harnessed-common.sh"
   ```
2. **The emit-only image boundary** is the assembler's hard guardrail: a module that
   cannot reach `subprocess`/`podman` cannot violate host-nativeness. The podman
   *introspection* code lives in `tools/harnessed/capability.py`, but it is the one
   exception — it runs **host-native python** (driven by `harnessed test`), never
   inside the tools image.

Python targets **`requires-python = ">=3.12"`** (`tools/pyproject.toml`), so use PEP
604 `X | Y` unions, `list[str]`, and `from __future__ import annotations` (every
module — it is the first import after the docstring).

---

## Bash conventions

### Strict mode — always

Every executable bash file opens with:

```bash
#!/usr/bin/env bash
set -euo pipefail
```

`harnessed` sets it at line 25. Sourced libraries (`lib/*.sh`) do **not** re-set it —
they inherit the caller's shell. Because `errexit` is on, a bare failing pipeline
aborts the script; where a non-zero exit is expected and meaningful, **capture it
explicitly** rather than suppress it (see "Capturing a meaningful exit" below).

### Logging: the four `print_*` helpers

All user-facing output goes through exactly four helpers, defined once in
`lib/harnessed-common.sh` and reused by every library:

```bash
# lib/harnessed-common.sh:9-13
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }
```

Conventions:
- **`print_error` writes to stderr** (note `>&2`); the other three write to stdout.
  Any capture of `harnessed` output for the capability test parses stdout, so keep
  errors off stdout.
- Each helper takes **exactly one `$1` argument** — a single message string. Do not
  pass structured data; build the string at the call site.
- Prefix every side-effecting step with `print_info` ("Assembling stack…", "Building
  $IMAGE…"), every success with `print_success`, every recoverable miss with
  `print_warning`. This makes a build log read like a narrative.

### Error handling: `print_error` + `exit 1` (or `return 1`)

There is no `trap ERR` handler and no exception-like machinery. The pattern is
uniform across the launcher and libraries — **name the problem, then stop**:

```bash
# harnessed (the launcher), repeated pattern
[ $# -gt 0 ] || { print_error "stop requires a stack name"; usage; exit 1; }
```
```bash
# lib/harnessed-common.sh — a library returns non-zero so the caller's errexit fires
build_stack() {
    local stack="$1"
    if [ -z "$stack" ]; then print_error "build_stack: stack name required"; return 1; fi
    if [ ! -f "$ROOT/stacks/$stack/stack.yaml" ]; then
        print_error "Unknown stack: $stack (no $ROOT/stacks/$stack/stack.yaml)"; return 1
    fi
    ...
}
```

Rule of thumb: in `harnessed` and the per-command libraries, a bad invocation calls
`usage` then `exit 1`; in `lib/harnessed-common.sh` helpers that may be reused, `return 1`
and let the caller's `set -e` abort.

### Capturing a meaningful exit under `errexit`

`set -e` aborts on non-zero, so when a non-zero exit is **the signal** (a scanner
found a HIGH vuln; an image scan failed), capture the status into a local and branch:

```bash
# lib/harnessed-common.sh:115-122 — the BLD-02a source scan
local src_rc=0
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT" || src_rc=$?
if [ "$src_rc" -ne 0 ]; then
    print_error "supply-chain source scan failed for stack '$stack' (HIGH+ finding)"
    return 1
fi
```

The same `|| var=$?` idiom is used for the image scan (`img_rc`) and for the
capability test's python invocation (`test_rc`). Never silence with `|| true` when
the exit code matters; never let a bare pipeline abort when it doesn't.

### The source-then-call structure

`harnessed` is a **thin dispatcher**: it parses argv, then sources exactly the
library it needs and calls one function, then exits. No library is sourced
unconditionally — that keeps the common case (launch a stack) from pulling in the
service/CLI machinery:

```bash
# harnessed — top-level subcommands dispatch with `. … ; fn ; exit 0`
if [ "$SUB_LIST" = true ]; then
    . "$HARNESSED_DIR/lib/harnessed-cli.sh"; list_all; exit 0
fi
...
case "$STACK" in
    transparent)
        # shellcheck source=lib/harnessed-transparent.sh
        . "$HARNESSED_DIR/lib/harnessed-transparent.sh"
        harnessed_transparent "$PROJECT_PATH" "$CLAUDE" "$ZAI" ;;
    *)
        # shellcheck source=lib/harnessed-isolated.sh
        . "$HARNESSED_DIR/lib/harnessed-isolated.sh"
        harnessed_isolated "$STACK" "$PROJECT_PATH" "$FRESH" ;;
esac
```

And the isolated launcher itself sources its helpers at the top of the function that
needs them (`lib/harnessed-isolated.sh:46-48`), not at script load. Match this: source
lazily, annotate every `. ` with a `# shellcheck source=` comment, and dispatch with a
trailing `exit 0`.

### `local` for every function-scoped variable

There are no global mutable work variables in functions. Every helper declares its
inputs and scratch on the first line:

```bash
# lib/harnessed-common.sh
generate_instance_name() {
    local stack="$1" project_path="${2%/}" hash
    ...
}
build_stack() {
    local stack="$1"
    local ROOT="${HARNESSED_ROOT:-$HARNESSED_DIR}"
    ...
}
```

The only "globals" are module-level **constants** (`HARNESSED_BASE_IMAGE`,
`CONTAINER_HOME`, `NO_FIREWALL`) declared at the top of `lib/harnessed-common.sh`,
and a small set of parse-state flags (`BUILD`, `STACK`, `FRESH`, …) in the launcher.
Use `${VAR:-default}` at the point of read for optional values (e.g.
`fresh="${3:-false}"`, `headless="${HARNESSED_HEADLESS:-false}"`).

### The `MOUNT_ARGS` array pattern (caller declares, helpers append)

This is the central composition idiom for building a `podman run` invocation. The
**caller declares an empty array**; a chain of helper functions each **append**
`-v`/`-e`/`--cap-add`/`--device` entries to it; the caller finally splats it into the
run command:

```bash
# lib/harnessed-isolated.sh:90-109 — the isolated launcher
local MOUNT_ARGS=()
harnessed_host_integration_mounts "$project_path" "$relpath"   # §4a host-integration layer
harnessed_isolated_auth_mounts "$instance"                      # §4b isolated auth
...
MOUNT_ARGS+=( -v "$run_claude:$CONTAINER_HOME/.claude:rw" )     # profile (config source)
```

Each helper (`lib/harnessed-mounts.sh`, `lib/harnessed-isolated-config.sh`) documents
that it appends to `MOUNT_ARGS` in its header comment:

```bash
# lib/harnessed-mounts.sh:4-5
# Appends podman/docker run args to the MOUNT_ARGS array (the caller declares `MOUNT_ARGS=()`).
```

The final invocation splats the array. Where a pod-level property must be stripped
from a member (`--userns=keep-id` is illegal on a pod member), filter explicitly:

```bash
# lib/harnessed-isolated.sh:152-158
local member_args=() _arg
for _arg in "${MOUNT_ARGS[@]}"; do
    [ "$_arg" = "--userns=keep-id" ] && continue
    member_args+=( "$_arg" )
done
"$CONTAINER_RUNTIME" run -d --pod "$pod" --name "$instance" "${member_args[@]}" \
    "$harness_image" sleep infinity >/dev/null
```

**When adding a new mount layer**, write a function that appends to `MOUNT_ARGS` and
document the `:ro`/`:rw` suffix in the comment — read-only is the default for host
secrets, read-write only for state the instance owns.

### Runtime detection: podman-first, docker-fallback

Exactly one function decides the runtime, called once at launcher boot:

```bash
# lib/harnessed-common.sh:31-40
detect_runtime() {
    if command -v podman >/dev/null 2>&1; then
        CONTAINER_RUNTIME="podman"
    elif command -v docker >/dev/null 2>&1; then
        CONTAINER_RUNTIME="docker"
    else
        print_error "Neither podman nor docker found on PATH. Install podman (recommended) or docker."
        exit 1
    fi
}
```

After that, **always** invoke through `"$CONTAINER_RUNTIME"` — never call `podman` or
`docker` directly. The capability test mirrors this in Python
(`_runtime()` in `capability.py`) so the two engines agree.

### Reading manifests in bash: flat `sed`, no YAML lib

The host must stay dependency-free (no YAML library on the host). Manifests are
authored as **flat scalars**, so the launcher parses them with targeted `sed`/`grep`
rather than a real parser. Only the Python assembler loads YAML for real.

```bash
# lib/harnessed-isolated.sh:38 — read a stack's harness (one scalar)
harness="$(sed -n 's/^harness:[[:space:]]*//p' "$HARNESSED_DIR/stacks/$stack/stack.yaml" | tr -d '[:space:]')"
harness="${harness:-claude}"
```
```bash
# lib/harnessed-services.sh — the service library reads flat scalars the same way
# _svc_yaml_val reads a single `key: value` line from services/<name>/service.yaml
```

If you need a *structured* manifest read, that code belongs in Python (under
`tools/harnessed/`), not bash.

---

## Python conventions

Every module under `tools/harnessed/` follows the same shape. Use these as the
template for new code.

### Module header: docstring, future annotations, stdlib, local

```python
# tools/harnessed/capability.py:1, 26-39
"""Per-stack capability test — manifest oracle vs live --fresh introspection (design §18).

The stack manifest is the **oracle**: ... [paragraphs explaining the module's role]
"""

from __future__ import annotations

import json
import shlex
import os
...

from . import schema
```

Conventions:
- **Module docstring first**, always — it states the module's responsibility and
  cites the design section (e.g. `(design §18)`). Read these before editing; they are
  the local spec.
- **`from __future__ import annotations`** is the first statement after the docstring,
  in every module. It makes `X | Y` and `list[str]` annotations lazy strings.
- **Import order**: stdlib, blank line, third-party (`ruamel.yaml`, `rich`), blank
  line, intra-package relative imports (`from . import schema`).

### `@dataclass` for every typed record

Domain objects are frozen-shape `@dataclass`es with `field(default_factory=…)` for
mutable defaults. This is the only data modeling style in the package:

```python
# tools/harnessed/schema.py:54-77
@dataclass
class McpServer:
    """One MCP server declared by a recipe (design §11 MCP layer).

    `transport` is explicit (RESEARCH Pitfall B). A `stdio` server (with `command`)
    is run by hatago as a child (stdio→HTTP) and must be baked into the hatago image;
    a network-native server (`url`, transport http/sse) is proxied by hatago by URL.
    """

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    transport: str = "stdio"
    url: str | None = None
    service: str | None = None
    ...

    @property
    def is_stdio_child(self) -> bool:
        """A stdio server hatago must bake + spawn (vs a network-native URL proxy)."""
        return self.transport == "stdio" and self.command is not None
```

Rules:
- **Required fields first, defaulted fields after** (dataclass requirement). Put the
  discriminator/identity (`name`) first.
- **Mutable defaults use `field(default_factory=list)` / `dict` / `set`** — never a
  bare `[]` or `{}`.
- **Derive computed shape from `@property`**, not a method (`is_stdio_child`,
  `FileExt.name`, `Stack.harness_config_dir`, `CapabilityReport.ok`,
  `CapabilityReport.exit_code`). A read-only property signals "this is shape, not an
  action."
- Keep a `raw: dict = field(default_factory=dict)` tail field on manifest-loaded
  dataclasses (`McpServer`, `Recipe`, `Stack`, `ServiceDef`) — the assembler parses
  **forward** (design D-14), carrying unknown keys for future phases rather than
  rejecting them.

### Type hints everywhere, PEP 604 unions

Every function signature is fully annotated, including `-> None` on procedures.
Use `X | Y` (not `Union[X, Y]`) and `list[T]` / `dict[K, V]` / `set[T]` (not
`List`/`Dict`/`Set`). Optional-with-default reads `x: T | None = None`:

```python
# tools/harnessed/capability.py:518-525
def run_capability_test(
    root: Path | str,
    stack_name: str,
    *,
    project_path: str | None = None,
    harnessed_bin: str | None = None,
    keep: bool = False,
) -> CapabilityReport:
```

Keyword-only args (the `*,` separator) are used for optional/configuration
parameters — call sites must name them, which keeps the positional core readable.

### Docstrings on every public function

Triple-quoted, imperative mood, explaining **what + why**, citing the design
decision where relevant. The docstring is where the "why this exists" lives:

```python
# tools/harnessed/synclinks.py:1-10 (module) and the collision contract
"""Fan recipe skills/commands into harness-native profile paths, fail-fast on collision.
...
Two recipes shipping the same skill/command name is a **fail-fast** error that names
BOTH source paths — never a silent last-wins overwrite.
"""
```

### The exception hierarchy: one base per concern

Exceptions are domain-specific and named after the *failure*, not a generic
`RuntimeError`. The hierarchy is shallow and each class carries a one-line docstring
stating when it fires:

```python
# tools/harnessed/schema.py
class SchemaError(Exception):
    """A recipe/stack manifest is missing a required field or is malformed."""

class RecipeLintError(SchemaError):
    """A recipe uses raw npm/npx instead of the pnpm equivalent (BLD-03 supply-chain lint)."""
```
```python
# tools/harnessed/synclinks.py
class CollisionError(Exception):
    """Two recipes ship a skill/command with the same harness-native name."""
```
```python
# tools/harnessed/scan.py
class ScanError(Exception):
    """A supply-chain scan found a HIGH+ finding (CVSS >= HIGH) — the build must abort."""
```
```python
# tools/harnessed/capability.py
class CapabilityError(Exception):
    """The capability test could not be run (launch failed, instance not found, etc.)."""
```

Note that `RecipeLintError` **extends `SchemaError`** — a lint failure *is* a manifest
malformation, so the CLI can catch the whole family in one `except`:

```python
# tools/harnessed/cli.py:108-114
def _run_assemble(args, out, err):
    ...
    try:
        result = assemble(root, args.stack, Path(args.build_dir))
    except (CollisionError, SchemaError, RecipeLintError) as exc:
        err.print(f"[bold red]assemble failed:[/bold red] {exc}", highlight=False)
        return 1
```

**When adding a new failure mode**, add a named exception class with a docstring
rather than raising `ValueError`/`RuntimeError`. The CLI's error rendering and the
exit-code mapping both key off the exception type.

### Fail-fast validation: check before any file is written

Validation runs **before** emission so a failed build leaves no half-written
profile. The assembler's `assemble()` is the canonical example — every gate fires
before `emit.reset_profile`:

```python
# tools/harnessed/assemble.py:73-99
def assemble(root, stack_name, build_dir):
    stack, recipes = load_stack_with_recipes(root, stack_name)

    # Fail-fast recipe validation (BLD-03): reject raw npm/npx BEFORE any file is emitted.
    for recipe in recipes:
        validate_no_raw_npm(recipe)

    # Fan skills/commands (registers + collision-checks before any file is written).
    syncer = LinkSyncer()
    for recipe in recipes:
        syncer.add_recipe(recipe)
    ...
    emit.reset_profile(profile_dir)   # <-- first write happens HERE, after all checks
```

And the collision check registers-and-checks as recipes are added, so the error names
**both** offenders with full source paths — never a silent last-wins overwrite:

```python
# tools/harnessed/synclinks.py:48-64
for entry in entries:
    src = (recipe.root / entry.path).resolve()
    if not src.is_dir():
        raise CollisionError(
            f"recipe '{recipe.name}' declares {kind} '{entry.path}' "
            f"but the source dir does not exist: {src}"
        )
    name = entry.name
    if name in registry:
        prev_src, prev_recipe = registry[name]
        raise CollisionError(
            f"{kind} name collision: '{name}' is shipped by two recipes.\n"
            f"  recipe '{prev_recipe}': {prev_src}\n"
            f"  recipe '{recipe.name}': {src}\n"
            f"Rename one of them or drop a recipe from the stack."
        )
```

**When adding a new validation rule**, put it before the first `emit.*` call and raise
your named exception with an actionable message (name the offending value and the fix).

### Emit-only discipline: no runtime calls in `tools/harnessed/`

The assembler modules (`schema.py`, `assemble.py`, `emit.py`, `synclinks.py`,
`scan.py`) may not invoke a container runtime. They read the mounted build dir and
write to it — nothing else. The header of `emit.py` states the contract:

```python
# tools/harnessed/emit.py:1
"""Write the assembled artifacts into the mounted build dir (EMIT ONLY).
...
"""
```
```python
# tools/harnessed/assemble.py:11-12
EMIT ONLY: nothing here invokes podman/docker or mounts a daemon socket.
```

The **one** module that *does* shell out is `capability.py` — and it is never run
inside the tools image. `harnessed test` runs it host-native (see `harnessed:306-325`
for the `HARNESSED_PYTHON` → `uv run --with …` → host `python3` resolution chain).
Keep this split absolute: emit-time code = pure filesystem; test-time code =
subprocess + `podman exec`.

### Separate pure functions from podman-touching functions

Even within `capability.py`, the pure logic is isolated so it can be reasoned about
(and unit-tested in principle) without a container runtime. Each such function's
docstring says so explicitly:

```python
# tools/harnessed/capability.py:115-121
def expected_capabilities(root: Path | str, stack_name: str) -> schema.Capabilities:
    """Derive the EXPECTED capabilities from the manifest oracle (reuses 02-01's schema API).

    Pure: reads `stacks/<stack>/stack.yaml` + its recipes under `root`; touches no container runtime.
    """
```
```python
# tools/harnessed/capability.py:124-127
def build_report(stack_name, expected, live) -> CapabilityReport:
    """Pure expected-vs-live diff → the structured result. No podman; unit-testable.
    ...
    """
```

The podman-touching functions (`launch_headless`, `wait_ready`, `introspect`,
`teardown`, `run_capability_test`) live under a clearly-marked section header
(`# --- Live introspection (podman-touching; …)`). Match this layout: a
`# --- Pure: … (no podman)` section, then a `# --- Live introspection …` section.

---

## Manifest conventions

Manifests are hand-authored YAML loaded by the Python assembler
(`schema.load_recipe` / `load_stack` / `load_service`). Three shapes:

### `recipes/<name>/recipe.yaml`

A recipe is an integration definition for **one** project. It contributes to two
layers: an **MCP layer** (`mcp.servers`) and a **file-extension layer** (`skills` /
`commands`). The tracer recipe (`recipes/time/recipe.yaml`) is the minimal
reference:

```yaml
name: time
description: Time and timezone queries via the network-free uvx mcp-server-time stdio MCP server.

mcp:
  servers:
    - name: time
      command: uvx
      args: [mcp-server-time]
      transport: stdio        # explicit; stdio → hatago runs it as a child (stdio→HTTP)

skills:
  - path: skills/time-helper   # standalone skill dir; fanned to .claude/skills/time-helper
```

Conventions:
- `name` matches the recipe directory. `description` is one sentence.
- **`transport` is always explicit** (RESEARCH Pitfall B). `stdio` + `command` →
  hatago bakes + spawns it as a child; a network-native server uses `url` (or
  `service:` to reference a shared sidecar) with `transport: http`.
- `skills`/`commands` entries are **relative paths** whose leaf dir is the
  harness-native name (`FileExt.name` = `Path(path).name`). Two recipes with the same
  leaf name is a `CollisionError`.
- Forward fields (`plugins`, `deps`, `hooks`) are parsed-but-unused in later phases;
  the assembler carries them on `raw` (design D-14). Do not reject unknown keys.

### `stacks/<name>/stack.yaml`

A stack composes one harness + a set of recipes (+ optional shared services). The
tracer stack is the minimal reference:

```yaml
# stacks/tracer-time/stack.yaml
name: tracer-time
config: isolated      # isolated (default) | transparent
harness: claude       # claude | omp  (exactly one)
recipes: [time]
```

Conventions:
- `config: isolated` (default) means the config layer comes from an assembled profile;
  `config: transparent` means it comes from live host config (the built-in
  `transparent` stack omits `harness` and mounts host configs wholesale).
- `harness` is **exactly one** of `claude` | `omp` (validated by `Stack.harness_config_dir`
  → `SchemaError` on an unknown value). omp consumes the *same* Claude-canonical
  profile via the bridge — no separate config dir, no re-authoring (design §8).
- `services: [name, …]` references `services/<name>/service.yaml`; the launcher
  auto-starts each via `ensure_service_up` (design §9). Optional.
- `permissions` / `state` are parsed forward and currently use defaults.

### `services/<name>/service.yaml`

A shared service is its **own** image/container/volume on `harnessed-net`, with a
lifecycle independent of any instance. Flat scalars only (the bash service library
reads them with `sed`):

```yaml
# services/ping/service.yaml
name: ping
image: harnessed-ping:latest
volume: ping-data                                    # service-scoped; survives `svc down`
port: 8080
healthcheck: "curl -sf http://localhost:8080/health || exit 1"
```

Conventions:
- `volume` is **service-scoped** (`ping-data`, never `harnessed-data-<stack>`) — this
  is what lets a `claude` instance and an `omp` instance share one memory.
- `healthcheck` is a shell command run inside the service container; `svc up` polls it.
- A recipe references a service via `mcp.servers[].service: <name>`; the assembler
  resolves it to a hatago URL-proxy entry (`_resolve_service_servers` in `assemble.py`).

### Claude-canonical layout is the single source of truth

Skills/commands/hooks/agents/rules are authored in **Claude Code format**. omp adapts
*out* of it via `claude-hooks-bridge` — there is no omp-native format and no
re-authoring (design §8). The emitted profile is always
`profiles/<stack>/.claude/{skills,commands,agents,hooks,rules}/` + `.mcp.json` +
`settings.json`.

---

## The pnpm supply-chain rule (BLD-03)

**All JavaScript installs — global, per-recipe, and hatago's bundled servers — use
pnpm, never npm/npx.** This is a hard, enforced policy, not a style preference, and
it has three enforcement points:

### 1. The managed global config (`lib/pnpm/config.yaml`)

Shipped into `~/.config/pnpm/config.yaml` in every image that runs pnpm. The keys
that matter:

```yaml
# lib/pnpm/config.yaml
minimumReleaseAge: 1440          # 1-day cooldown; a compromised release isn't installed on landing
minimumReleaseAgeStrict: true    # fail-closed rather than silently falling back
blockExoticSubdeps: true         # block git/tarball/non-registry subdeps
verifyStoreIntegrity: true       # content-addressed store integrity on link
strictDepBuilds: true            # lifecycle default-deny: non-zero on any unreviewed build/postinstall
```

Policy lives here, **not** `.npmrc` (which is auth/registry-only in pnpm v11). The
one exception is `allowBuilds` — v11 rejects it from the global config, so it is
deferred to a project's `pnpm-workspace.yaml` when a build-script package (e.g.
esbuild) actually needs to run.

### 2. Recipe lint: `validate_no_raw_npm` (fail-fast at assemble time)

`tools/harnessed/schema.py:296` rejects raw `npm`/`npx` in a recipe's MCP commands,
scripts, deps, or vendored `package.json` scripts — and **names the pnpm
equivalent** in the error. Detection is word-boundaried (`\bnpx\b`,
`\bnpm\s+(install|ci|run|exec|i)\b`) so a package named `npmlog` is not flagged:

```python
# tools/harnessed/schema.py:296-310
def validate_no_raw_npm(recipe: Recipe) -> None:
    """Reject recipes that reach for raw npm/npx; name the pnpm equivalent (BLD-03, fail-fast)."""
    for server in recipe.servers:
        if server.command in ("npm", "npx"):
            raise RecipeLintError(
                f"recipe '{recipe.name}': MCP server '{server.name}' uses raw '{server.command}'. "
                "Use the pnpm equivalent 'pnpm dlx' "
                "(e.g. command: pnpm, args: [dlx, <pkg>])."
            )
    ...
```

### 3. The substitution map (what to write instead)

| Forbidden token | pnpm equivalent |
|---|---|
| `npx <pkg>` | `pnpm dlx <pkg>` |
| `npm install` | `pnpm install` |
| `npm ci` | `pnpm install --frozen-lockfile` |
| `npm run <s>` | `pnpm run <s>` |
| `npm exec` | `pnpm exec` |

When writing a recipe MCP server that needs a JS package, use
`command: pnpm, args: [dlx, <pkg>]`. The `_NPM_TO_PNPM` map in `schema.py` is the
authoritative list of substitutions the linter suggests.

---

## Quick reference — where new code goes

| You are adding… | Put it in… | Style |
|---|---|---|
| A host-side podman step (mount, lifecycle, scan) | a `lib/harnessed-*.sh` helper | bash: `print_*`, `local`, append to `MOUNT_ARGS`, `"$CONTAINER_RUNTIME"` |
| A new CLI subcommand | parse in `harnessed`, dispatch with `. lib/… ; fn ; exit 0` | bash dispatcher |
| A new manifest field | parse it in `tools/harnessed/schema.py` (carry unknowns on `raw`) | `@dataclass` + `field(default_factory=…)` |
| A new assembly step | `tools/harnessed/assemble.py` (before `emit.*`) or `emit.py` | pure, emit-only, fail-fast |
| A new validation rule | a named `Exception` subclass, raised before any `emit.*` | fail-fast with an actionable message |
| A new capability (MCP/skill/command) | declare it in a `recipe.yaml` — it becomes an assertion automatically | manifest-driven, no test code |
