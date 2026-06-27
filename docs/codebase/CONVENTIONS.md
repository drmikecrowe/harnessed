# Coding Conventions

**Analysis Date:** 2026-06-27

## Naming Patterns

**Files:**
- Module files: `snake_case.py` (e.g., `assemble.py`, `synclinks.py`, `capability.py`)
- Test files: `test_<module>.py` (e.g., `test_emit.py`, `test_schema.py`)

**Functions:**
- Public API: `snake_case` (e.g., `assemble()`, `run_source_scan()`, `load_stack_with_recipes()`)
- Private/internal: `_snake_case` with leading underscore (e.g., `_build_parser()`, `_merge_servers()`, `_cvss3_base()`)
- CLI dispatch functions: `_run_<subcommand>` (e.g., `_run_assemble()`, `_run_scan()`)

**Variables:**
- `snake_case` throughout
- Constants: `UPPER_CASE` (e.g., `HIGH = 7.0`, `HATAGO_PORT = 3535`, `HATAGO_ENDPOINT`, `HATAGO_MCP_KEY`)

**Types/Classes:**
- PascalCase for all classes (e.g., `AssembleResult`, `ScanError`, `LinkSyncer`, `CollisionError`)
- Exception classes end in `Error` (e.g., `ScanError`, `SchemaError`, `RecipeLintError`, `PinValidationError`, `CapabilityError`, `CollisionError`)
- Dataclasses end in descriptive noun (e.g., `ScanResult`, `CapabilityResult`, `CapabilityReport`)

## Code Style

**Formatting:**
- No formatter config detected (no `.ruff.toml`, `.black`, `.flake8`); consistent PEP 8 style applied manually
- Line length appears 100-120 chars in practice (long inline comments on same line as code)

**Type Hints:**
- Required on all function signatures: parameters AND return types
- `from __future__ import annotations` at the top of every module (deferred evaluation)
- Use `|` union syntax (`float | None`, `list[str] | None`, `Path | None`) — NOT `Optional[...]`
- Built-in generics used directly (`list[str]`, `dict[str, str]`) — NOT `List`, `Dict` from `typing`

**Data Models:**
- `@dataclass` for structured results (e.g., `AssembleResult`, `ScanResult`, `CapabilityReport`)
- `field(default_factory=list)` for mutable defaults
- `@dataclass` preferred over plain dicts or TypedDicts for public API boundaries

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first when present)
2. stdlib imports (alphabetical within group: `argparse`, `json`, `math`, `os`, `pathlib`, `re`, `shutil`, `subprocess`)
3. Third-party imports (`rich`, `ruamel.yaml`)
4. Local imports from same package (`from . import paths`, `from .schema import ...`, `from .emit import ...`)

**Pattern:**
```python
from __future__ import annotations

import json
import os
from pathlib import Path

from rich.console import Console

from . import report
from .assemble import assemble
from .schema import RecipeLintError, SchemaError
```

**No path aliases** — all local imports use relative `.` or `..` notation.

## Error Handling

**Strategy:** Domain-specific exception classes raised deep, caught at the CLI boundary.

**Exception hierarchy:**
- `ScanError` (`src/harnessed/scan.py`) — HIGH+ CVE found; aborts build
- `CapabilityError` (`src/harnessed/capability.py`) — capability test infrastructure failed
- `SchemaError` (`src/harnessed/schema.py`) — malformed recipe/stack/service YAML
- `RecipeLintError` (`src/harnessed/schema.py`) — recipe policy violation (e.g., raw npm/npx)
- `PinValidationError` (`src/harnessed/schema.py`) — floating Dockerfile reference (`:latest` or no pin)
- `CollisionError` (`src/harnessed/synclinks.py`) — duplicate skill/command name across recipes

**CLI boundary pattern** (in `src/harnessed/cli.py`):
```python
try:
    result = run_source_scan(root, args.stack, Path(args.build_dir))
except ScanError as exc:
    err.print(f"[bold red]supply-chain scan failed:[/bold red] {exc}", highlight=False)
    return 1
```

**Internal helpers:** Return `None` or empty collections on unrecoverable non-fatal cases (e.g., `_cvss3_base()` returns `None` on unparseable input); never swallow errors silently.

**Subprocess error handling:** Capture `stdout`/`stderr`, inspect return code, parse JSON output — never trust subprocess exit code alone (see `scan.py` module docstring: "Pitfall 3").

## Logging / Output

**Framework:** `rich.console.Console` — NOT `print()` or `logging`.

**Pattern:**
- `out = Console()` for stdout, `err = Console(stderr=True)` for stderr
- Both passed as parameters to all `_run_*` dispatch functions
- Rich markup used for color: `[bold green]...[/bold green]`, `[bold red]...[/bold red]`, `[yellow]warning:[/yellow]`
- `highlight=False` on error prints to avoid unexpected rich parsing

**No structured logging** — output is human-readable terminal text only.

## Comments and Documentation

**Module docstrings:**
- Every module has a leading triple-quoted docstring
- Docstrings reference design section numbers (e.g., `design §7`, `§15`, `D-04`, `B6`)
- State what the module does NOT do (e.g., "EMIT ONLY: nothing here invokes podman/docker")
- Call out security classification: `# C1 — security-critical code`

**Function docstrings:**
- All public functions documented with purpose, key constraints, and cross-references
- Reference design decisions inline: `# design D-04; default port 3535`
- Document non-obvious behavior: why `highlight=False`, why `type: http` is required

**Inline comments:**
- Explain the "why" for non-obvious choices (e.g., CVSS parsing pitfalls, podman rootless constraints)
- Tag design rationale: `# BLD-02`, `# ASM-02 (T-08-01)`, `# SEC-04`
- Mark inferences: `# [INFERENCE: ...]` for unverified assumptions needing confirmation

## Module Design

**Emit-only principle:** Modules tagged `EMIT ONLY` in docstring must never invoke `podman`, `docker`, or any subprocess that talks to a daemon. This constraint is enforced by code review, not tooling.

**Exports:**
- No `__all__` defined; public API is by convention (no leading underscore)
- Private helpers are prefixed `_` and consumed only within their own module

**Single responsibility:** Each module owns one concern:
- `schema.py` — parse + validate YAML into typed objects
- `assemble.py` — orchestrate recipe assembly
- `emit.py` — write profile artifacts to disk
- `synclinks.py` — fan skills/commands into profile, detect collisions
- `scan.py` — supply-chain scanning and severity gate
- `capability.py` — capability test introspection
- `paths.py` — all path resolution (XDG, catalog, container paths)
- `cli.py` — argparse wiring, dispatch to above modules
- `launcher.py` — host-side podman invocation (the only module that calls podman)
- `report.py` — rich rendering of capability test results

**Tolerance:** Parsers accept unknown fields (forward-compat design D-14); unknown YAML keys preserved on `.raw`, not rejected.

## Constants

Module-level constants defined at top of file after imports:
```python
HIGH = 7.0          # CVSS threshold
HATAGO_PORT = 3535
HATAGO_ENDPOINT = f"http://localhost:{HATAGO_PORT}/mcp"
HATAGO_MCP_KEY = "hatago"
```

---

*Convention analysis: 2026-06-27*
