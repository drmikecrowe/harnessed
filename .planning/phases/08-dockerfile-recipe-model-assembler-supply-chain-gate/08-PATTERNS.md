# Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate — Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 9 new/modified files
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tools/harnessed/schema.py` (modify) | model/validator | transform | `tools/harnessed/schema.py` (existing) | exact — adding fields + error classes |
| `tools/harnessed/emit.py` (modify) | utility | file-I/O | `tools/harnessed/emit.py` (existing) | exact — adding one write function |
| `tools/harnessed/scan.py` (modify) | service | request-response | `tools/harnessed/scan.py` (existing) | exact — adding `_scan_snyk_container_image` + `run_snyk_container_scan` |
| `tools/harnessed/assemble.py` (modify) | service | transform | `tools/harnessed/assemble.py` (existing) | exact — inserting two validation calls |
| `lib/harnessed-common.sh` (modify) | utility | event-driven | `lib/harnessed-common.sh` (existing) | exact — extending `build_stack()` |
| `recipes/gstack/recipe.yaml` (new) | config | — | `recipes/time/recipe.yaml` | exact |
| `recipes/gstack/Dockerfile` (new) | config | file-I/O | none in codebase | no analog — use RESEARCH Pattern 1 |
| `stacks/gstack-time/stack.yaml` (new) | config | — | `tools/test-fixtures/stacks/tracer-time/stack.yaml` | exact |
| `tools/uat/phase-08.sh` (new) | test | event-driven | `tools/uat/phase-06.sh` | exact |

---

## Pattern Assignments

### `tools/harnessed/schema.py` — Add `harnesses`, `expect`, `HarnessCompatError`, `PinValidationError`, `validate_harness_compat`, `validate_pin`

**Analog:** `tools/harnessed/schema.py` (existing content)

**Imports pattern** (lines 1–20 of existing file):
```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
```

**Existing error class pattern** (lines 51–57) — new error classes follow this shape:
```python
class SchemaError(Exception):
    """A recipe/stack manifest is missing a required field or is malformed."""


class RecipeLintError(SchemaError):
    """A recipe uses raw npm/npx instead of the pnpm equivalent (BLD-03 supply-chain lint)."""
```

New classes to add after `RecipeLintError` — mirror the same docstring convention:
```python
class HarnessCompatError(SchemaError):
    """A recipe's declared harnesses list does not include the stack's harness."""


class PinValidationError(SchemaError):
    """A recipe Dockerfile contains a floating ref (--branch main/master, :latest, @latest)."""
```

**Existing `Recipe` dataclass** (lines 108–116) — new fields added inside:
```python
@dataclass
class Recipe:
    name: str
    description: str = ""
    servers: list[McpServer] = field(default_factory=list)
    skills: list[FileExt] = field(default_factory=list)
    commands: list[FileExt] = field(default_factory=list)
    root: Path = field(default_factory=Path)
    raw: dict = field(default_factory=dict)
```

Add two new fields (after `commands`, before `root`):
```python
    harnesses: list[str] = field(default_factory=lambda: list(HARNESS_CONFIG_DIR.keys()))
    expect: list[str] = field(default_factory=list)
```

**Existing regex pattern** (lines 269–278) — `validate_pin` regex follows the same `_RAW_NPM_RE` style:
```python
_RAW_NPM_RE = re.compile(r"\bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b")
```

New regex (add near `_RAW_NPM_RE`):
```python
_FLOATING_REF_RE = re.compile(
    r'--branch\s+(main|master|HEAD)\b'
    r'|(?<!\w):latest\b'
    r'|@latest\b',
    re.IGNORECASE,
)
```

**Existing validation function pattern** (lines 311–342) — `validate_pin` and `validate_harness_compat` follow the `validate_no_raw_npm` shape (raises a `SchemaError` subclass, never returns data):
```python
def validate_no_raw_npm(recipe: Recipe) -> None:
    """Reject recipes that reach for raw npm/npx; name the pnpm equivalent (BLD-03, fail-fast).
    ...
    """
    for server in recipe.servers:
        if server.command in ("npm", "npx"):
            raise RecipeLintError(
                f"recipe '{recipe.name}': MCP server '{server.name}' uses raw '{server.command}'. "
                "Use the pnpm equivalent 'pnpm dlx' "
                "(e.g. command: pnpm, args: [dlx, <pkg>])."
            )
    ...
    match = _RAW_NPM_RE.search(" ".join(haystack))
    if match:
        token = match.group(0)
        ...
        raise RecipeLintError(...)
```

New validation functions follow this exact signature and raise-on-failure shape:
```python
def validate_pin(recipe_name: str, dockerfile_body: str) -> None:
    """Raises PinValidationError if the Dockerfile body contains a floating ref (ASM-02)."""
    match = _FLOATING_REF_RE.search(dockerfile_body)
    if match:
        raise PinValidationError(
            f"recipe '{recipe_name}': Dockerfile contains a floating ref '{match.group(0).strip()}'. "
            "Pin to a tag (e.g. v1.2.3) or SHA (e.g. @sha256:...) instead of floating branches or :latest."
        )


def validate_harness_compat(recipe: "Recipe", stack_harness: str) -> None:
    """Raises HarnessCompatError before any Dockerfile is emitted (ASM-01)."""
    if recipe.harnesses and stack_harness not in recipe.harnesses:
        raise HarnessCompatError(
            f"recipe '{recipe.name}' does not support harness '{stack_harness}'. "
            f"Supported harnesses: {', '.join(sorted(recipe.harnesses))}. "
            f"Either update the recipe's harnesses: field or use a compatible stack harness."
        )
```

**`load_recipe` extension** (lines 192–208) — add `harnesses` and `expect` parsing inside `load_recipe` following the existing pattern for optional fields:
```python
def load_recipe(recipe_dir: Path) -> Recipe:
    ...
    return Recipe(
        name=raw["name"],
        description=raw.get("description", ""),
        servers=_parse_servers(raw.get("mcp", {}) or {}),
        skills=_parse_fileext(raw.get("skills")),
        commands=_parse_fileext(raw.get("commands")),
        root=recipe_dir,
        raw=raw,
    )
```

Add `harnesses` and `expect` to the `Recipe(...)` call:
```python
        harnesses=list(raw.get("harnesses") or list(HARNESS_CONFIG_DIR.keys())),
        expect=list(raw.get("expect") or []),
```

---

### `tools/harnessed/emit.py` — Add `write_derived_dockerfile()`

**Analog:** `tools/harnessed/emit.py` (existing content)

**Imports pattern** (lines 1–22 of existing file):
```python
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .schema import McpServer, Stack
```

Add `Recipe` to the schema import (needed by `write_derived_dockerfile`):
```python
from .schema import McpServer, Recipe, Stack
```

**Existing file-write pattern** (lines 46–48, 58–61) — all emit functions write text via `Path.write_text`; `write_derived_dockerfile` follows the same convention:
```python
def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
```

```python
def write_mcp_json(harness_dir: Path) -> Path:
    out = harness_dir / ".mcp.json"
    _write_json(out, {...})
    return out
```

New function — place at end of file, returning `Path` (same convention as all other `write_*` functions):
```python
def write_derived_dockerfile(profile_dir: Path, stack: Stack, recipes: list[Recipe]) -> Path:
    """Emit profiles/<stack>/Dockerfile.harnessed-<stack> for host `podman build` (ASM-03)."""
    lines: list[str] = [
        f"# Generated by harnessed assembler for stack '{stack.name}'",
        "# DO NOT EDIT — regenerated by `harnessed build " + stack.name + "`",
        f"ARG HARNESS={stack.harness}",
        f"FROM harnessed-${{HARNESS}}:latest",
        "ARG HARNESS",  # re-declare in post-FROM stage so RUN instructions see it
        "",
    ]
    for recipe in recipes:
        dockerfile = recipe.root / "Dockerfile"
        if not dockerfile.is_file():
            continue  # backward-compat: recipes without Dockerfiles contribute no layer
        body_lines = dockerfile.read_text(encoding="utf-8").splitlines()
        filtered = [
            ln for ln in body_lines
            if not ln.strip().upper().startswith("FROM ")
            and not ln.strip().upper().startswith("ARG HARNESS")
        ]
        lines.append(f"# --- recipe: {recipe.name} ---")
        lines.extend(filtered)
        lines.append("")

    out = profile_dir / f"Dockerfile.harnessed-{stack.name}"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
```

---

### `tools/harnessed/scan.py` — Add `_scan_snyk_container_image()` + `run_snyk_container_scan()`

**Analog:** `tools/harnessed/scan.py` (existing content)

**Existing env-gated snyk pattern** (lines 226–258) — `_scan_snyk_container_image` mirrors `_scan_snyk` exactly; copy the env-gate, the `_run` call, and the exit-code dispatch:
```python
def _scan_snyk(target: Path, highs: list[str], warnings: list[str]) -> None:
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append("snyk skipped (no SNYK_TOKEN) — credential-free baseline remains the gate")
        return
    manifest = target / "package.json"
    if not manifest.is_file():
        return
    proc = _run(["snyk", "test", "--severity-threshold=high", "--json", "--file", str(manifest)])
    if proc.returncode == 1:
        data = _parse_json(proc.stdout)
        ids = _snyk_vuln_ids(data) if data is not None else []
        if ids:
            highs.extend(ids)
        else:
            highs.append(f"snyk: HIGH+ finding in {target.name} (exit 1; parse JSON output)")
    elif proc.returncode in (2, 3):
        warnings.append(
            f"snyk: exit {proc.returncode} for {target.name} (failure / no supported projects) — investigate"
        )
```

New private function (no `manifest.is_file()` guard — container scan takes the image name, not a dir):
```python
def _scan_snyk_container_image(image_name: str, highs: list[str], warnings: list[str]) -> None:
    """snyk container test <image> --severity-threshold=high (SC-03).

    Env-gated on SNYK_TOKEN (same warn-and-skip contract as _scan_snyk). Never prompts.
    Exit code 1 = HIGH+ vuln found → abort. 2/3 = failure → warn.
    """
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append(
            "snyk container test skipped (no SNYK_TOKEN) — credential-free osv-scanner baseline remains the gate"
        )
        return
    proc = _run(["snyk", "container", "test", image_name, "--severity-threshold=high", "--json"])
    if proc.returncode == 1:
        data = _parse_json(proc.stdout)
        ids = _snyk_vuln_ids(data) if data is not None else []
        if ids:
            highs.extend(ids)
        else:
            highs.append(f"snyk container test: HIGH+ finding in {image_name} (exit 1; parse JSON for details)")
    elif proc.returncode in (2, 3):
        warnings.append(
            f"snyk container test: exit {proc.returncode} for {image_name} (failure / no supported projects) — investigate"
        )
```

**Existing top-level scan function pattern** (lines 319–339) — `run_snyk_container_scan` mirrors `run_image_scan`: calls private scanner, gates on highs, raises `ScanError`:
```python
def run_image_scan(archive_tar: Path | str) -> ScanResult:
    ...
    highs = gate(data)
    if highs:
        unique = sorted(set(highs))
        raise ScanError(
            f"supply-chain image scan found {len(unique)} HIGH+ finding(s) "
            f"(CVSS >= {HIGH}): {', '.join(unique)}"
        )
    ...
    return ScanResult(scope="image", highs=[], warnings=warnings)
```

New top-level function:
```python
def run_snyk_container_scan(image_name: str) -> ScanResult:
    """Top-level: snyk container test on a built image (SC-03). Raises ScanError on HIGH+."""
    highs: list[str] = []
    warnings: list[str] = []
    _scan_snyk_container_image(image_name, highs, warnings)
    if highs:
        raise ScanError(
            f"snyk container test found {len(highs)} HIGH+ finding(s) in {image_name}: {', '.join(sorted(set(highs)))}"
        )
    return ScanResult(scope=f"snyk-container:{image_name}", highs=[], warnings=warnings)
```

**cli.py import** (line 23) — add `run_snyk_container_scan` to the existing scan import:
```python
from .scan import ScanError, run_image_scan, run_image_scan_online, run_source_scan, run_snyk_container_scan
```

Add a `scan-snyk-container` subcommand in `_build_parser()` following the same pattern as `scan-image`.

---

### `tools/harnessed/assemble.py` — Insert validation calls in `assemble()`

**Analog:** `tools/harnessed/assemble.py` (existing content)

**Existing import line** (line 20) — add new validators to the schema import:
```python
from .schema import McpServer, Recipe, Stack, load_service, load_stack_with_recipes, validate_no_raw_npm
```

Add `validate_harness_compat`, `validate_pin`, `HarnessCompatError`, `PinValidationError`:
```python
from .schema import (
    HarnessCompatError,
    McpServer,
    PinValidationError,
    Recipe,
    Stack,
    load_service,
    load_stack_with_recipes,
    validate_harness_compat,
    validate_no_raw_npm,
    validate_pin,
)
```

**Existing fail-fast gate in `assemble()`** (lines 79–82) — new gates are inserted in the same loop, before any file is written:
```python
    # Fail-fast recipe validation (BLD-03): reject raw npm/npx BEFORE any file is emitted
    for recipe in recipes:
        validate_no_raw_npm(recipe)
```

Extend the loop to add ASM-01 (compat) and ASM-02 (pin):
```python
    for recipe in recipes:
        validate_no_raw_npm(recipe)
        validate_harness_compat(recipe, stack.harness)   # ASM-01: before any emission
        dockerfile = recipe.root / "Dockerfile"
        if dockerfile.is_file():
            validate_pin(recipe.name, dockerfile.read_text(encoding="utf-8"))  # ASM-02
```

**Emit call insertion** — add `write_derived_dockerfile` after existing emit calls (lines 94–101):
```python
    emit.reset_profile(profile_dir)
    emit.ensure_profile_tree(harness_dir)
    syncer.fan(harness_dir)
    emit.write_mcp_json(harness_dir)
    emit.write_settings_json(harness_dir, servers)
    emit.write_hatago_config(profile_dir, servers)
    emit.write_derived_dockerfile(profile_dir, stack, recipes)  # ASM-03 — NEW
```

Add `write_derived_dockerfile` to the emit import at line 19:
```python
from . import emit
```
(no change needed — `emit.write_derived_dockerfile` is accessed via the module reference).

---

### `lib/harnessed-common.sh` — Extend `build_stack()` with IMG-03 + SC-01 + SC-03

**Analog:** `lib/harnessed-common.sh` (existing content)

**Existing BLD-02b image scan pattern** (lines 177–188) — IMG-03 / SC-01 derive image name and tar path, then follow the exact same `mktemp → save → scan → rm → rc-check` pattern:
```bash
    print_info "Running supply-chain image scan for $HARNESSED_HATAGO_IMAGE ..."
    local img_tar img_rc=0
    img_tar="$(mktemp --suffix=.tar)"
    "$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"
    "$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro \
        "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar" || img_rc=$?
    rm -f "$img_tar"
    if [ "$img_rc" -ne 0 ]; then
        print_error "supply-chain image scan failed for $HARNESSED_HATAGO_IMAGE (HIGH+ finding)"
        return 1
    fi
```

**Existing TOKEN_ARGS pattern** (lines 156–158) — SC-03 reuses the same `TOKEN_ARGS` array already constructed for the source scan:
```bash
    local TOKEN_ARGS=()
    [ -n "${SNYK_TOKEN:-}" ] && TOKEN_ARGS+=( -e "SNYK_TOKEN=$SNYK_TOKEN" )
    [ -n "${SOCKET_SECURITY_API_KEY:-}" ] && TOKEN_ARGS+=( -e "SOCKET_SECURITY_API_KEY=$SOCKET_SECURITY_API_KEY" )
```

**Existing podman build pattern** (lines 82–90) — IMG-03 follows the same `podman build -t <image> -f <dockerfile> <context>` pattern:
```bash
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_BASE_IMAGE" \
            -f "$HARNESSED_DIR/base/Dockerfile.harnessed-base" "$HARNESSED_DIR"
```

Insert after line 190 (the `print_success` of the existing function — replace it), before the final `print_success`:
```bash
    # [IMG-03] Build the derived harnessed-<stack> image.
    local stack_harness derived_image derived_dockerfile
    stack_harness="$(yq '.harness // "claude"' "$ROOT/stacks/$stack/stack.yaml")"
    derived_image="harnessed-${stack}:latest"
    derived_dockerfile="$ROOT/profiles/$stack/Dockerfile.harnessed-${stack}"
    if [ -f "$derived_dockerfile" ]; then
        print_info "Building $derived_image for stack '$stack' ..."
        "$CONTAINER_RUNTIME" build \
            --build-arg "HARNESS=${stack_harness}" \
            -t "$derived_image" \
            -f "$derived_dockerfile" \
            "$ROOT"

        # [SC-01] Post-build osv-scanner V2 image scan of the derived image (mirrors BLD-02b).
        print_info "Running supply-chain image scan for $derived_image ..."
        local derived_tar derived_img_rc=0
        derived_tar="$(mktemp --suffix=.tar)"
        "$CONTAINER_RUNTIME" save "$derived_image" -o "$derived_tar"
        "$CONTAINER_RUNTIME" run --rm -v "$derived_tar":"$derived_tar":ro \
            "$HARNESSED_TOOLS_IMAGE" scan-image "$derived_tar" || derived_img_rc=$?
        rm -f "$derived_tar"
        if [ "$derived_img_rc" -ne 0 ]; then
            print_error "supply-chain image scan failed for $derived_image (HIGH+ finding)"
            return 1
        fi

        # [SC-03] Snyk container test (token-gated; warn-and-skip without prompting).
        local snyk_rc=0
        "$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
            "${TOKEN_ARGS[@]}" \
            "$HARNESSED_TOOLS_IMAGE" scan-snyk-container "$derived_image" || snyk_rc=$?
        if [ "$snyk_rc" -ne 0 ]; then
            print_error "snyk container test found HIGH+ finding in $derived_image"
            return 1
        fi
    fi

    # [SC-04] Socket source scan of recipe dirs (socket CLI has no container mode — Pitfall 7).
    # SC-04 is satisfied by the existing BLD-02a source scan (which already covers recipe dirs).
    # Document: socket scan create does not support image layers; source scan is equivalent.

    print_success "Stack '$stack' assembled → profiles/$stack/ + $HARNESSED_HATAGO_IMAGE${derived_image:+ + $derived_image} (scans clean)"
```

**Logging convention** (lines 9–13) — all new messages use the same helpers:
```bash
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }
```

---

### `recipes/gstack/recipe.yaml` (new)

**Analog:** `recipes/time/recipe.yaml`

Follow the same header comment + field order: `name`, `description`, `harnesses` (new), `expect` (new), then `mcp:` if applicable, then `skills:` if applicable.

```yaml
# Recipe: gstack — claude-only framework recipe (Phase 8 test artifact).
# harnesses: [claude] — declares this recipe as claude-only; ASM-01 rejects omp/gemini/etc. stacks.
# expect: confirms the installer landed the expected skill (RCP2-03).
name: gstack
description: gstack claude skill framework (claude-only recipe, Phase 8 test artifact).
harnesses: [claude]
expect:
  - gstack-skill
```

---

### `recipes/gstack/Dockerfile` (new)

**No codebase analog** — no recipe Dockerfiles exist yet. Use the RESEARCH Pattern 1 format.

```dockerfile
# Recipe Dockerfile for: gstack (Phase 8 test artifact)
# ARG HARNESS is provided by the assembled Dockerfile header; re-declared here for standalone builds.
ARG HARNESS=claude
RUN pnpm dlx @gstack/install --host ${HARNESS} --version 1.2.3
```

Key rules (from RESEARCH):
- The assembler STRIPS `FROM` and `ARG HARNESS` lines from this file before concatenation.
- Pin to a specific version tag — never `:latest` or `--branch main` (ASM-02 gate).
- Use `pnpm dlx`, never `npm`/`npx` (BLD-03 gate).
- The assembled Dockerfile's header already provides `FROM harnessed-${HARNESS}:latest` + `ARG HARNESS`.

---

### `stacks/gstack-time/stack.yaml` (new)

**Analog:** `tools/test-fixtures/stacks/tracer-time/stack.yaml` and existing proof stacks

```yaml
name: gstack-time
harness: claude
recipes:
  - gstack
  - time
```

---

### `tools/uat/phase-08.sh` (new)

**Analog:** `tools/uat/phase-06.sh` (closest match — fast manifests test + heavy container tests, `--quick` guard, `uat_run_phase` entrypoint)

**File header pattern** (lines 1–24 of phase-06.sh):
```bash
#!/usr/bin/env bash
# phase-08.sh — UAT suite for Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate.
#
# Sourced by run-uat.sh (after uat-common.sh). Every test follows Arrange → Act → Assert (AAA).
# Fast tests (manifest / validation) always run. Heavy tests (container build + scan) self-skip
# under --quick.
```

**Quick-guard pattern** (lines 27–28 of phase-06.sh):
```bash
RT="$(uat_runtime)"
needs_container() { [ "$UAT_QUICK" = "true" ]; }
```

**Fast manifests test pattern** (lines 63–86 of phase-06.sh) — copy the `test_matrix_manifests` structure; substitute fixture file paths and `assert_file_contains`/`assert_exists` calls:
```bash
test_schema_harnesses() {
    arrange
    act
    assert
    # RCP2-01: gstack recipe has a Dockerfile
    assert_exists "$HARNESSED_DIR/recipes/gstack/Dockerfile" "RCP2-01: gstack/Dockerfile ships"
    # RCP2-02: harnesses: field in recipe.yaml
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/recipe.yaml" "harnesses:" "RCP2-02: harnesses field present"
    # RCP2-03: expect: field in recipe.yaml
    assert_file_contains "$HARNESSED_DIR/recipes/gstack/recipe.yaml" "expect:" "RCP2-03: expect field present"
}
```

**Python validation test pattern** — invoke `harnessed-tools assemble` on a fixture root and assert exit code:
```bash
test_pin_validation_rejects_floating() {
    arrange
    act
    # Point at a test fixture with --branch main in its Dockerfile
    uat_run "$HARNESSED_TOOLS_BIN" assemble floating-recipe --root "$FIXTURE_ROOT" --build-dir "$TMP_DIR"
    assert
    assert_exit_nonzero "$UAT_RC" "ASM-02: floating ref rejected before emission"
    assert_contains "floating ref" "$UAT_OUT" "ASM-02: error message names the floating ref"
}
```

**Heavy test pattern** (lines 43–56 of phase-06.sh):
```bash
test_derived_image_build() {
    needs_container && { skip_test "skipped (--quick) — builds the gstack-time derived image"; return; }
    [ -z "$RT" ] && { skip_test "no container runtime found"; return; }
    arrange
    act
    uat_run "$HARNESSED" build gstack-time
    assert
    assert_exit_zero "$UAT_RC" "IMG-03: harnessed build gstack-time exits 0"
    assert_true "$RT" image inspect "harnessed-gstack-time:latest" "IMG-03: harnessed-gstack-time:latest exists"
}
```

**`uat_run_phase` entrypoint** (lines 97–110 of phase-06.sh):
```bash
uat_run_phase() {
    uat_suite "Phase 8 — Dockerfile Recipe Model + Assembler + Supply-Chain Gate"
    echo "  launcher: $HARNESSED  runtime: ${RT:-none}"
    [ "$UAT_QUICK" = "true" ] && echo "  --quick: only fast manifest/validation tests run"

    run_test schema_harnesses          "RCP2-01/02/03: gstack recipe structure (fast, no container)"
    run_test pin_validation_rejects_floating "ASM-02: floating ref rejected (fast, no container)"
    run_test harness_compat_rejected   "ASM-01: incompatible harness rejected (fast, no container)"
    run_test assembled_dockerfile_header "ASM-03: assembled Dockerfile has ARG HARNESS header (fast)"
    run_test rescan_filter_covers_derived "SC-02: harnessed-* filter covers harnessed-gstack-time (fast)"
    run_test derived_image_build       "IMG-03: harnessed build gstack-time → harnessed-gstack-time (heavy)"
    run_test osv_image_scan            "SC-01: osv-scanner passes on derived image (heavy)"
    run_test snyk_container_skip       "SC-03: snyk container test skips cleanly without token (heavy)"
}
```

---

## Shared Patterns

### Error Raise Pattern
**Source:** `tools/harnessed/schema.py` lines 55–57, 321–342
**Apply to:** `validate_harness_compat`, `validate_pin` in `schema.py`
```python
class SomeError(SchemaError):
    """One-line docstring stating the invariant violated."""

def validate_something(recipe: Recipe, ...) -> None:
    """Docstring citing the requirement ID."""
    if <condition>:
        raise SomeError(
            f"recipe '{recipe.name}': <human-readable explanation>. "
            "<Actionable fix hint>."
        )
```

### Subprocess Scanner + Warn-and-Skip
**Source:** `tools/harnessed/scan.py` lines 160–165, 226–258
**Apply to:** `_scan_snyk_container_image` in `scan.py`
```python
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except (subprocess.SubprocessError, OSError) as exc:
        raise ScanError(f"scanner invocation failed ({' '.join(cmd)}): {exc}") from exc

# Token-gated pattern:
if not os.environ.get("SNYK_TOKEN"):
    warnings.append("... skipped (no SNYK_TOKEN) ...")
    return
proc = _run([...])
if proc.returncode == 1:   # threshold-hit gate
    ...highs.extend(...)
elif proc.returncode in (2, 3):
    warnings.append(...)   # failure = warn, never abort
```

### Image Save → Scan → Cleanup
**Source:** `lib/harnessed-common.sh` lines 178–188
**Apply to:** Derived image SC-01 scan block in `build_stack()`
```bash
local img_tar img_rc=0
img_tar="$(mktemp --suffix=.tar)"
"$CONTAINER_RUNTIME" save "$IMAGE_NAME" -o "$img_tar"
"$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro \
    "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar" || img_rc=$?
rm -f "$img_tar"
if [ "$img_rc" -ne 0 ]; then
    print_error "supply-chain image scan failed for $IMAGE_NAME (HIGH+ finding)"
    return 1
fi
```

### UAT Test Structure (Arrange → Act → Assert)
**Source:** `tools/uat/uat-common.sh` + `tools/uat/phase-06.sh`
**Apply to:** `tools/uat/phase-08.sh`
```bash
test_<id>() {
    arrange
    # setup / preconditions
    act
    uat_run "$HARNESSED" <command>
    assert
    assert_exit_zero "$UAT_RC" "<label>"
    assert_contains "<string>" "$UAT_OUT" "<label>"
}
# Heavy test guard (place BEFORE arrange):
needs_container && { skip_test "skipped (--quick) — <reason>"; return; }
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `recipes/gstack/Dockerfile` | config | file-I/O | No recipe Dockerfiles exist in the codebase yet; this is the first |

---

## Metadata

**Analog search scope:** `tools/harnessed/`, `lib/`, `tools/uat/`, `recipes/`, `tools/test-fixtures/`
**Files scanned:** 9 primary source files read in full; 3 additional (cli.py, uat-common.sh, test-fixtures/recipes/) partially read for context
**Pattern extraction date:** 2026-06-23
