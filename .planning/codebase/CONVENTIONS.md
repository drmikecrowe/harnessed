# Coding Conventions

**Analysis Date:** 2026-06-24

## Languages

Two primary languages co-exist with distinct conventions:

1. **Bash** — host bootstrap, CLI launcher, lib helpers (`harnessed`, `lib/*.sh`, `install.sh`, `tools/uat/*.sh`)
2. **Python** — build-time assembler tools (`tools/harnessed/*.py`, `services/ping/server.py`)

## Naming Patterns

### Files

**Bash:**
- Library files: `harnessed-<domain>.sh` (e.g., `lib/harnessed-cli.sh`, `lib/harnessed-mounts.sh`)
- UAT phase suites: `phase-<NN>.sh` (zero-padded, e.g., `tools/uat/phase-04.sh`)
- Shared helpers: `uat-common.sh`, `harnessed-common.sh`

**Python:**
- Module files: `<noun>.py` — single responsibility, lowercase (e.g., `schema.py`, `assemble.py`, `emit.py`, `scan.py`, `capability.py`)
- Package init: `tools/harnessed/__init__.py`

**YAML manifests:**
- Recipes: `recipes/<name>/recipe.yaml`
- Stacks: `stacks/<name>/stack.yaml`
- Services: `services/<name>/service.yaml`

### Functions

**Bash:**
- Public helpers: `snake_case` (e.g., `detect_runtime`, `build_images`, `list_all`, `stop_stack`)
- Private/internal helpers: `_snake_case` prefixed (e.g., `_uat_pass`, `_uat_fail`)
- UAT test functions: `test_<id>` prefix (e.g., `test_svc_up`, `test_svc_up_idempotent`)
- UAT helper functions: `uat_<verb>` prefix (e.g., `uat_run`, `uat_show`, `uat_summary`, `uat_vol_exists`)
- Logging helpers: `print_<level>` (e.g., `print_info`, `print_success`, `print_warning`, `print_error`)

**Python:**
- Public functions: `snake_case` (e.g., `load_recipe`, `load_stack`, `assemble`, `run_source_scan`)
- Private module-level functions: `_snake_case` prefix (e.g., `_load_yaml`, `_parse_servers`, `_merge_servers`, `_cvss3_base`, `_roundup`)
- CLI entry points: `main()`
- CLI sub-handler functions: `_run_<command>` prefix (e.g., `_run_assemble`, `_run_test`, `_run_scan`)

### Variables

**Bash:**
- Global constants/image names: `UPPER_SNAKE_CASE` (e.g., `HARNESSED_BASE_IMAGE`, `CONTAINER_HOME`, `RED`, `NC`)
- Local variables inside functions: `lower_snake_case` with `local` keyword
- UAT capture variables: `UAT_OUT`, `UAT_RC`, `UAT_PASS`, `UAT_FAIL`

**Python:**
- Module-level constants: `UPPER_SNAKE_CASE` (e.g., `HIGH`, `HATAGO_PORT`, `HATAGO_ENDPOINT`, `MCP`, `SKILL`, `COMMAND`)
- Private module-level regex/table constants: `_UPPER_SNAKE_CASE` (e.g., `_RAW_NPM_RE`, `_FLOATING_REF_RE`, `_NPM_TO_PNPM`, `_AV`, `_AC`)
- Local variables: `snake_case`
- Dataclass fields: `snake_case`

### Types / Classes

**Python:**
- Exception classes: `<Noun>Error` suffix (e.g., `SchemaError`, `RecipeLintError`, `ScanError`, `CapabilityError`, `CollisionError`, `HarnessCompatError`, `PinValidationError`)
- Data containers: `PascalCase` dataclasses (e.g., `McpServer`, `Recipe`, `Stack`, `ServiceDef`, `AssembleResult`, `ScanResult`, `Capabilities`)

## Code Style

### Bash

**Set flags:** Every executable script starts with `set -euo pipefail` (`set -uo pipefail` in sourced files). Sourced library files omit `set -e` to avoid aborting the caller's shell.

**ShellCheck:** Files carry `# shellcheck source=<path>` directives for sourced files and `# shellcheck shell=bash` on files that need it. Intentional workarounds are annotated with `# shellcheck disable=SC<code> # reason`.

**Local variables:** Always declare with `local` inside functions to prevent global namespace pollution.

**Quoting:** Variables are always double-quoted; word-split is only intentional when explicitly noted with a ShellCheck disable comment.

**Here-docs:** Used for multi-line output (usage strings, scaffolded files). Always delimited with `EOF`.

**Colors:** Defined as module-level constants (`RED`, `GREEN`, `YELLOW`, `BLUE`, `NC`) in `lib/harnessed-common.sh` and used via the `print_*` helpers — raw color codes are never embedded in output strings.

### Python

**`from __future__ import annotations`:** Present in every module — enables forward-reference type hints.

**Type hints:** Used throughout. Function signatures have full parameter and return type annotations (e.g., `def _load_yaml(path: Path) -> dict`, `def load_stack(stack_dir: Path) -> Stack`).

**Dataclasses:** Used for all data containers (`@dataclass`). `field(default_factory=...)` used for mutable defaults. `raw: dict` field pattern carried on every dataclass as a forward-compatibility slot for unrecognized YAML fields (design D-14).

**Imports:** Standard library first, then third-party, then local package imports (`from . import ...`). Relative imports (`from .schema import ...`) used for intra-package references.

**Module docstrings:** Every module has a top-level docstring explaining the component's responsibility, what it does NOT do (e.g., "never invokes podman/docker"), and key design references (e.g., "design §15 / D-12").

**Function docstrings:** Public functions carry a one-line or multi-line docstring. Private helper functions document the "why" for non-obvious logic. Cross-references to design sections and requirement IDs (e.g., `BLD-02`, `BLD-03`, `SEC-04`, `ASM-01`) are embedded directly in code comments.

## Import Organization

**Python:**
1. `from __future__ import annotations`
2. Standard library (alphabetical)
3. Third-party (`rich`, `ruamel.yaml`)
4. Local package (`from . import ...` or `from .module import ...`)

**Bash:**
- Library files are sourced at the top with `# shellcheck source=` directives
- Source order matters: `harnessed-common.sh` sources `harnessed-runtime.sh` internally

## Error Handling

### Bash

- `set -euo pipefail` ensures unhandled errors abort the script
- Explicit error messages via `print_error "..." >&2; exit 1` for user-facing failures
- Non-fatal cleanup commands are `|| true` or `>/dev/null 2>&1 || true` to tolerate absence
- Return codes are propagated — no silent swallowing

### Python

- Custom exception hierarchy (all extend `Exception`) for structured error reporting:
  - `SchemaError` — malformed/missing manifest fields
  - `RecipeLintError`, `HarnessCompatError`, `PinValidationError` (extend `SchemaError`)
  - `ScanError` — HIGH+ CVE finding
  - `CapabilityError` — capability test launch/introspection failure
- Exceptions are caught at the CLI layer in `_run_*` handlers, rendered with `[bold red]...[/bold red]` rich markup to stderr, and converted to exit code 1
- `err.print(f"...", highlight=False)` used for error output (separate `Console(stderr=True)`)
- Fail-fast design: validation runs before any file emission in `assemble()` so no partial output is produced on error

## Logging

**Bash:**
- `print_info "..."` — blue `[INFO]` prefix
- `print_success "..."` — green `[SUCCESS]` prefix
- `print_warning "..."` — yellow `[WARNING]` prefix
- `print_error "..." >&2` — red `[ERROR]` prefix, stderr

**Python:**
- `rich.console.Console` for stdout, `Console(stderr=True)` for errors
- Rich markup used for colored output: `[bold green]`, `[bold red]`, `[yellow]`, `[bold]`
- `highlight=False` passed for error messages to prevent rich's auto-highlighting from mangling output

## Comments

**Bash:**
- File-level header comment block on every `.sh` file explaining purpose, what it expects, and cross-references (design section, plan ID)
- Inline `# ---` section separators with section names for logical grouping
- Design decision comments inline with the code they affect (e.g., `# Rootless model (plan 04-01 fix): ...`)
- `# shellcheck ...` directives with justification comments

**Python:**
- Module docstrings: authoritative statement of responsibility, scope constraints ("EMIT ONLY: nothing here invokes podman/docker"), and design references
- Function docstrings on all public functions; private helpers use `#` comments for non-obvious logic
- Design/requirement references embedded as inline comments: `# design §15 / D-12`, `# BLD-03`, `# RESEARCH Pitfall 3`

## Module Design

**Python package layout:**
- `tools/harnessed/` is the single package
- Responsibility split: `schema.py` (parse/validate), `assemble.py` (orchestrate), `emit.py` (write artifacts), `scan.py` (CVE scanning), `capability.py` (test oracle), `report.py` (rich rendering), `synclinks.py` (skill/command fan-out)
- `cli.py` is the thin CLI shell — dispatches to module functions, never contains business logic
- Modules that are "pure" (no subprocess/podman) document this explicitly

**EMIT-ONLY constraint:** `tools/harnessed/` modules never invoke podman/docker. This constraint is stated in every relevant module docstring and enforced by design (the host runs `podman build` on emitted artifacts).

---

*Convention analysis: 2026-06-24*
