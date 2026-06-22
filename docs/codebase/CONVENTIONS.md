# Conventions

> Coding conventions and patterns for the `harnessed` codebase.
> Grounded in actual source as of 2026-06-22. The repo's `CLAUDE.md`
> "Conventions" section is intentionally empty ("Conventions not yet established"),
> so this document is the prescriptive distillation of the patterns the code
> already follows. Follow them when adding or editing code.

The codebase is **bash-first on the host, Python in a containerized tools image**.
Two languages, one discipline: the host bootstrap stays dependency-free (only
podman/docker required); all parsing/emit/scan/capability logic lives in
`tools/harnessed/*.py`, run inside the `harnessed-tools` image. YAML manifests
(`recipe.yaml` / `stack.yaml` / `service.yaml`) are a third, authored format.

---

## 1. Bash — host bootstrap & library modules

### 1.1 Shebang and `set` policy

Every executable bash script begins with `#!/usr/bin/env bash`. The `set` policy
is **role-dependent** — match the role, do not copy-paste:

- **Entry-point launcher** (`harnessed:27`) uses the strict trinity:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  ```
  The launcher owns process-level correctness; one uncaught failure should abort.

- **Library modules** (`lib/harnessed-common.sh`, `lib/harnessed-isolated.sh`,
  `lib/harnessed-mounts.sh`, …) are **sourced**, so they MUST NOT set their own
  `set` — they inherit the launcher's options. Setting `set -e` in a sourced
  library would silently change every caller's failure semantics.

- **UAT runner** (`tools/uat/run-uat.sh:11`) deliberately drops `-e`:
  ```bash
  set -uo pipefail     # NO -e: a failing command must NOT abort the suite
  ```
  The UAT harness records pass/fail per assertion and continues; `set -e` would
  kill the run on the first non-zero command. Use `set -uo pipefail` (never bare
  `set -e`) for any script that needs to survive individual command failures.

### 1.2 Module sourcing — lazy, with shellcheck directives

Modules are sourced lazily — only when the dispatching subcommand actually needs
them — and every `. ` source is preceded by a `# shellcheck source=` directive
so editors/shellcheck can resolve the file:

```bash
# harnessed (the launcher)
# shellcheck source=lib/harnessed-common.sh
. "$HARNESSED_DIR/lib/harnessed-common.sh"
...
case "$STACK" in
    transparent)
        # shellcheck source=lib/harnessed-transparent.sh
        . "$HARNESSED_DIR/lib/harnessed-transparent.sh"
        harnessed_transparent "$PROJECT_PATH" "$CLAUDE" "$ZAI"
        ;;
    *)
        # shellcheck source=lib/harnessed-isolated.sh
        . "$HARNESSED_DIR/lib/harnessed-isolated.sh"
        harnessed_isolated "$STACK" "$PROJECT_PATH" "$FRESH"
        ;;
esac
```

`HARNESSED_DIR` is resolved once in the bootstrap by following symlinks (so a
PATH symlink works) and exported (`harnessed:30-33`); every library assumes it is
already set. `lib/harnessed-common.sh` itself sources the runtime abstraction in
turn (`harnessed-runtime.sh`), so sourcing `common.sh` is the one-stop entry to
the full helper set.

**Rule:** when adding a subcommand that needs a new module, source it in that
subcommand's dispatch block — not at the top of the launcher. This keeps the
no-op paths (e.g. `harnessed list`) cheap and keeps unrelated failures out of
unrelated commands.

### 1.3 Logging — the four colored helpers

`lib/harnessed-common.sh:8-13` defines exactly four logging helpers. **Use these;
do not invent `log()`/`die()`/`err()` wrappers — none exist and the codebase has
deliberately not grown them:**

```bash
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }   # ← stderr only
```

- `print_info` / `print_success` / `print_warning` → stdout.
- `print_error` → **stderr** (`>&2`), so it does not pollute piped stdout.

### 1.4 Error handling — inline `print_error` + exit/return, never a `die` helper

There is no `die`, `err`, `fail`, or `fatal` function (verified across `lib/`).
The error idiom is a **literal two-line `print_error "msg"; exit 1`** (or
`return 1` from a function):

```bash
[ -d "$project_path" ] || { print_error "Project directory does not exist: $project_path"; exit 1; }

local profile_dir="$HARNESSED_DIR/profiles/$stack"
[ -d "$profile_dir/.claude" ] || {
    print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }
```

Error messages name the offending value AND the remedy (`run: harnessed build $stack`),
so the user can recover without reading source.

**Propagating an already-known non-zero exit** (rather than re-printing) relies on
`set -e`: a bare failing command aborts the launcher. Capture the status only when
you need to render or branch on it (next section).

### 1.5 Fail-safe subprocess capture under `set -e` — the `rc=$?` idiom

Scanners and container probes exit non-zero for ordinary "finding present" /
"not ready" signals. Under `set -euo pipefail`, a bare such command would abort
the whole launch. The established idiom captures the exit into a `local rc` and
branches:

```bash
# lib/harnessed-common.sh (build_stack) — the source scan
local src_rc=0
"$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
    "${build_env_args[@]}" "${TOKEN_ARGS[@]}" \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT" || src_rc=$?
if [ "$src_rc" -ne 0 ]; then
    print_error "supply-chain source scan failed for stack '$stack' (HIGH+ finding)"
    return 1
fi
```

The `.planning` research codifies this: *"Every fallible probe (`resolve_secret_env`,
`auth_scanner`, `harnessed_rescan_images`) MUST use the `local rc=0; cmd || rc=$?`
shape."* See also the secret-resolution capture in `lib/harnessed-isolated.sh:178-184`.

### 1.6 Quoting and variables

- **Always double-quote expansions:** `"$CONTAINER_RUNTIME"`, `"$1"`, `"$ROOT"`.
- **Unset-safe reads use `"${VAR:-}"`** — critical under `set -u`. Bare `$SNYK_TOKEN`
  aborts; `${SNYK_TOKEN:-}` does not:
  ```bash
  [ -n "${SNYK_TOKEN:-}" ] && TOKEN_ARGS+=( -e "SNYK_TOKEN=$SNYK_TOKEN" )
  ```
- **Arrays for variable-length arg lists.** Declare `local -a env_args=()` (or a
  non-local `MOUNT_ARGS=()` the caller seeds), append conditionally, expand with
  the double-quoted splat `"${env_args[@]}"`:
  ```bash
  local -a env_args=()
  [ -n "$secret_env" ] && env_args=( --env-file "$secret_env" )
  ...
  "$CONTAINER_RUNTIME" run -d ... "${env_args[@]}" ...
  ```
- **`local` for everything function-scoped.** Module-level constants are
  `UPPER_SNAKE` and usually `HARNESSED_`-prefixed (`HARNESSED_BASE_IMAGE`,
  `CONTAINER_HOME`, `HATAGO_PORT`).

### 1.7 Comments — explain WHY, cite the design

Comments are dense and load-bearing. They reference design sections (`§15`, `§18`),
decision IDs (`D-04`, `D-06`, `D-12`), plan/requirement IDs (`HRN-01`, `T-05-06`,
`BLD-02a`, `PORT-01`), and threat IDs (`T-02-07`), and they explain the *reason*,
not the *mechanism*:

```bash
# Copy-on-start into a per-instance state dir and mount THAT rw: the committed profile is the
# immutable template, so the running harness never writes runtime state (projects/, backups/,
# caches) ... back into the version-controlled tree (reproducibility + credential hygiene, T-02-07).
```

Section comments use a banner form:

```bash
# --- Images (built and run on the HOST) ------------------------------------
```

When you leave a line that looks unused on purpose, say why (the codebase's own
rule, quoted in `lib/harnessed-isolated.sh:75-76`: *"KEPT per D-04 ('if unsure,
leave it and add a clarifying comment')"*):

```bash
local net="${HARNESSED_NET:-harnessed-net}"   # assigned-but-unused on this path; KEPT per D-04
```

### 1.8 Bash naming

| Kind | Convention | Example |
|------|-----------|---------|
| Functions | `snake_case` | `harnessed_isolated`, `ensure_omp_image`, `build_stack` |
| Constants (module/global) | `UPPER_SNAKE`, often `HARNESSED_`-prefixed | `HARNESSED_HATAGO_IMAGE`, `CONTAINER_HOME` |
| Local vars | `snake_case` | `profile_dir`, `state_project` |
| Boolean sentinels | `UPPER_SNAKE`, compared to `true`/`false` | `FRESH=false; [ "$fresh" = "true" ]` |

---

## 2. Python — `tools/harnessed/*.py`

The package (`tools/harnessed/`, entry `harnessed-tools = harnessed.cli:main` in
`tools/pyproject.toml`) is the build-time assembler + scanner + capability tester.
Target Python `>=3.12`. Pinned deps: `ruamel.yaml`, `rich`, `pip-audit==2.10.1`.

### 2.1 Module header — `from __future__` + docstring + imports

Every module opens with the same shape (`tools/harnessed/schema.py`,
`capability.py`, `scan.py`, `assemble.py`, `emit.py`, `synclinks.py`, `report.py`,
`cli.py`):

```python
"""<one-line summary>.

<prose: what the module does, the invariant (EMIT-ONLY / pure / no podman),
and design references — §/D-/HRN-/BLD- as in the bash comments>.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
```

- `from __future__ import annotations` is **always present** — it unlocks PEP 604
  unions (`Path | str`, `dict[str, str]`) and `list[T]` / `tuple[…]` builtin
  generics in annotations on 3.12.
- The docstring prose carries the same design-citation discipline as the bash
  comments (e.g. `capability.py`: *"manifest oracle vs live --fresh
  introspection (design §18)"*).

### 2.2 Dataclasses for all typed data; module constants up top

Schema and result types are `@dataclass`. Mutables default via
`field(default_factory=...)`. Every dataclass and field carries a docstring:

```python
@dataclass
class CapabilityResult:
    """One expected capability and whether the live instance actually exposed it."""

    name: str
    kind: str  # MCP | SKILL | COMMAND
    present: bool
    detail: str = ""  # short status reason (NEVER a config value / token — threat T-02-07)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "present": self.present, "detail": self.detail}
```

Module-level constants sit just after imports, each with an explanatory comment,
often with a CVSS/spec citation:

```python
# CVSS HIGH threshold (RESEARCH A2). The build ABORTS at >= HIGH; below is a warning.
HIGH = 7.0
# hatago's single Streamable-HTTP endpoint inside the shared pod netns (design D-04).
HATAGO_ENDPOINT = "http://localhost:3535/mcp"
```

### 2.3 One exception base per module, with a docstring

Each module defines its own exception, subclassing a sibling base when related.
The class docstring states the trigger, not the type:

```python
class SchemaError(Exception):
    """A recipe/stack manifest is missing a required field or is malformed."""

class RecipeLintError(SchemaError):
    """A recipe uses raw npm/npx instead of the pnpm equivalent (BLD-03 supply-chain lint)."""
```

The pattern repeats: `ScanError` (`scan.py`), `CapabilityError` (`capability.py`),
`CollisionError` (`synclinks.py`). Callers (`cli.py`) catch these and render them
as clean exit-1 messages.

### 2.4 Pure / subprocess separation — label it

Functions that do no I/O are grouped under a banner and marked "unit-testable"
(even though no unit tests ship — see TESTING.md). Subprocess wrappers are
grouped separately and "mirror" each other:

```python
# --- Pure: CVSS / severity gate (no subprocess; unit-testable) -----------------

def gate(osv_json: dict) -> list[str]:
    """Return HIGH+ finding ids (CVSS >= HIGH); empty list ⇒ pass. The ONLY HIGH decision point."""


# --- Subprocess invokers (mirror capability._exec: capture, text, swallow ...) --

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a scanner, capturing output. Never raise on a non-zero scanner exit (gated in Python)."""
```

Private helpers are `_`-prefixed (`_load_yaml`, `_parse_servers`, `_hatago_entry`,
`_runtime`). The public surface (`load_recipe`, `assemble`, `run_capability_test`,
`gate`) is small and documented.

### 2.5 Signatures, types, and the `main() -> int` entrypoint

- Annotate everything: `Path | str`, `list[str]`, `dict[str, str]`, `-> int`.
- Prefer `keyword-only` args (`*,`) for options so call sites are self-documenting
  (`run_capability_test(root, stack_name, *, project_path=None, keep=False)`).
- `main(argv: list[str] | None = None) -> int` returns the process exit code;
  the module footer wires it:
  ```python
  if __name__ == "__main__":
      sys.exit(main())
  ```
- Each argparse handler is a `_run_*` function returning `int` (`_run_assemble`,
  `_run_test`, `_run_scan`, `_run_scan_image`). Handlers catch the module's
  domain exceptions and print + return `1`; unknown errors print a traceback and
  return `2` (`tools/harnessed/cli.py:201-217`).

### 2.6 YAML/JSON

- Parse manifests with a single module-level safe loader:
  `_yaml = YAML(typ="safe", pure=True)` (`schema.py:25`). Never use round-trip
  loading — manifests are read-only inputs.
- Emit JSON with `json.dumps(data, indent=2) + "\n"` and `encoding="utf-8"`
  (`emit.py:46-48`).
- The harness output uses **rich** for terminal rendering (`report.py`:
  `Console()` + `Markdown`), but CI-consumable output (`--json`) prints plain
  stdout with no styling.

### 2.7 Python naming

| Kind | Convention | Example |
|------|-----------|---------|
| Modules/files | `snake_case.py` | `capability.py`, `synclinks.py` |
| Classes/exceptions | `PascalCase` | `CapabilityReport`, `CollisionError` |
| Functions/vars | `snake_case` | `expected_capabilities`, `run_source_scan` |
| Private helpers | `_snake_case` | `_merge_servers`, `_llm_cmd` |
| Module constants | `UPPER_SNAKE` | `HATAGO_PORT`, `HIGH` |

---

## 3. YAML manifests — `recipe.yaml` / `stack.yaml` / `service.yaml`

All three are **authored by hand** (the assembler parses them; it does not
generate them), so a leading comment header naming the manifest and citing the
design/plan refs is the convention. Bash is allowed to read them with flat
scalar greps (`sed -n 's/^harness:[[:space:]]*//p'`) precisely because they are
hand-authored and stable.

### 3.1 `recipe.yaml` (`recipes/<name>/recipe.yaml`)

```yaml
# Recipe: time — a network-free, credential-free time/timezone MCP server + a no-dep skill.
#
# <prose: tracer-bullet rationale; which design section / decision this exercises>
name: time
description: Time and timezone queries via the network-free uvx mcp-server-time stdio MCP server.

mcp:
  servers:
    - name: time
      command: uvx
      args: [mcp-server-time]
      transport: stdio

skills:
  - path: skills/time-helper
```

Conventions:

- **`name`** matches the directory (`recipes/time/recipe.yaml` → `name: time`).
- **`description`** is one sentence, human-facing.
- **MCP servers** declare `transport` **explicitly** (`stdio` | `http`). A stdio
  server carries `command` + `args` (hatago wraps it as a child); a
  **service-referenced** server carries `service: <name>` + `transport: http`
  (resolved to a URL at assemble time — see `recipes/ping/recipe.yaml`).
- **`skills` / `commands`** are standalone file-extension dirs (`path:
  skills/<name>`); the assembler fans them into `.claude/skills/<name>` and
  **fails fast on a name collision** across recipes (`CollisionError`).
- Forward fields (`plugins`, `deps`, `hooks`) are parsed-but-optional ("D-14"):
  add them only when a recipe needs them; the assembler carries the raw values
  through. **Never use raw `npm`/`npx`** anywhere in a recipe —
  `validate_no_raw_npm()` aborts the build naming the pnpm equivalent (`npx` →
  `pnpm dlx`, `npm install` → `pnpm install`). Use `uvx`/`pnpm dlx`.

### 3.2 `stack.yaml` (`stacks/<name>/stack.yaml`)

```yaml
name: tracer-time
config: isolated      # isolated (default) | transparent
harness: claude       # claude | omp | opencode | gemini | antigravity | codex
recipes: [time]
```

- **`config`**: `isolated` (runtime-composed pod) or `transparent` (host-mirror).
- **`harness`**: **exactly one** of the six supported harnesses — never two. The
  scaffolder (`lib/harnessed-cli.sh` `new_stack`) validates this and hard-errors
  on an unknown value.
- **`recipes`**: an inline-array `[a, b]` of recipe names. Recipes need not
  pre-exist (a missing recipe is a warning, not an error).
- **`services`** (optional): inline-array of shared sidecar service names.

### 3.3 `service.yaml` (`services/<name>/service.yaml`)

```yaml
name: ping
image: harnessed-ping:latest
volume: ping-data
port: 8080
healthcheck: "curl -sf http://localhost:8080/health || exit 1"
```

Minimal and flat: `name`, `image`, `volume`, `port`, `healthcheck`. The service
has its own `Dockerfile` + server under `services/<name>/`.

---

## 4. Dockerfiles (`base/Dockerfile.harnessed-*`, `tools/Dockerfile`)

Each `Dockerfile.*` opens with a comment header naming the image and citing the
design section it realizes (e.g. *"hatago MCP hub image (baked hub + light stdio
servers; design §6 / D-06)"*). Per-harness images are **lazy-built** —
`ensure_<harness>_image` runs only when a stack with that harness launches, so
claude-only users are never forced to build omp/opencode/gemini/antigravity/codex.
When adding a harness image, mirror the `ensure_omp_image` shape in
`lib/harnessed-common.sh` and wire a `[ "$harness" = "…" ] && ensure_…_image`
line in `lib/harnessed-isolated.sh`.

---

## 5. Commit messages — Conventional Commits

The history uses **Conventional Commits** with optional scopes tied to the
planning phases:

```
feat: provider-agnostic multi-harness support + harness-matrix UAT
fix(06-01): correct stale bridge-model comments to publish + host-gateway (B1-B7)
docs(06): regenerate docs/codebase via map-codebase — clear stale harnessed-net refs
test(06): complete UAT — 6 passed, 0 issues (static + deferred live gate)
docs(phase-06): complete phase execution — SC-1/SC-2/SC-3 passed; milestone v1.0 complete
```

Rules observed in the log:

- **Type prefix:** `feat` / `fix` / `docs` / `test` (lowercase, imperative subject).
- **Scope** (optional, no space before colon): a phase or plan id — `(06)`,
  `(06-01)`, `(phase-06)`, `(requirements)`.
- **Subject:** imperative mood, lowercase, no trailing period.
- **Body** (feature/fix commits): a short prose summary, then bullets naming the
  files/subsystems touched, referencing phase/plan IDs and decisions. Housekeeping
  commits (SUMMARY/plan updates) may be subject-only.
- Reference in-repo IDs the same way the code comments do (`SC-1`, `HRN-01`,
  `BLD-02`, `D-12`).

---

## 6. When conventions conflict with existing code

The codebase is explicit that ambiguity is resolved by *leaving the existing
pattern and adding a clarifying comment* rather than refactoring silently (the
D-04 rule quoted in `lib/harnessed-isolated.sh`). If you introduce a second
convention beside an existing one for the same concern, that is prohibited —
reuse the established helper/idiom. When in doubt, grep for the pattern first
(`print_error`, `local rc=0; … || rc=$?`, `@dataclass`, `from __future__ import
annotations`) and match it exactly.
