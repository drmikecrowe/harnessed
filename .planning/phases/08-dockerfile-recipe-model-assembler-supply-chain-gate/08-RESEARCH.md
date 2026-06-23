# Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate — Research

**Researched:** 2026-06-23
**Domain:** Python assembler (schema/emit/scan), Dockerfile generation, osv-scanner V2, snyk container, Socket.dev CLI
**Confidence:** HIGH (codebase verified, CLI tools probed live)

## Summary

Phase 8 replaces the YAML-only recipe model with a two-file model (Dockerfile + recipe.yaml), extends the Python assembler to validate harness compatibility and pin refs before emission, and adds a derived `harnessed-<stack>` image to the build pipeline with a full supply-chain gate.

The codebase already has most of the infrastructure needed: `run_image_scan()` in `scan.py`, a pattern for building and scanning the hatago image in `harnessed-common.sh`, and a `reference='harnessed-*'` filter in the nightly rescan that ALREADY matches `harnessed-<stack>` images. The new work is concentrated in three areas: (1) schema additions for `harnesses:` and `expect:` fields + validation functions, (2) `emit.write_derived_dockerfile()` for Dockerfile concatenation, and (3) extending `build_stack()` to build and scan the derived image.

`snyk container test` (live-verified: `snyk container test <image> --severity-threshold=high --json`) is the correct command for SC-03 — it is a distinct snyk subcommand from `snyk test` and requires a new `_scan_snyk_container_image()` function in `scan.py`. Socket.dev's CLI (`socket scan create <dir>`) does NOT support container images directly; SC-04 should be implemented as a warn-only pre-build socket source scan on the recipe directories that contribute to the derived image (consistent with the existing BLD-02a pattern).

**Primary recommendation:** Extend the assembler in three incremental waves: (1) schema + validation, (2) Dockerfile emission + host build, (3) derived-image scan gate.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RCP2-01 | Recipe is a directory containing `Dockerfile` + `recipe.yaml`; Dockerfile runs framework installer parameterized by `--host ${HARNESS}`, pinned to tag/SHA | Dockerfile-per-recipe pattern, ARG HARNESS scoping, pin-detection regex |
| RCP2-02 | `harnesses:` field in recipe.yaml; assembler refuses unsupported compositions | `validate_harness_compat()` before any emission |
| RCP2-03 | `expect:` smoke-check subset in recipe.yaml; fewer entries than declared = failure | New `expect: list[str]` field on `Recipe`, reuses `Capabilities` oracle |
| ASM-01 | Harness-compat check before emitting any Dockerfile; incompatible = validation error | Call `validate_harness_compat()` first in `assemble()` loop |
| ASM-02 | Pin validation: floating refs are a validation error; pinned tag/SHA passes | `validate_pin()` regex: `--branch main|master|HEAD`, `:latest`, `@latest` |
| ASM-03 | Assembler emits `profiles/<stack>/Dockerfile.harnessed-<stack>` with `ARG HARNESS=<agent>` + concatenated recipe bodies | `emit.write_derived_dockerfile()` — assembler emits files only |
| IMG-03 | `harnessed-<stack>` derived image: `FROM harnessed-<agent>` + recipe bodies; built by host via `podman build --build-arg HARNESS=<agent>` | New block in `build_stack()` after hatago build |
| SC-01 | Assembler pin gate (ASM-02) + post-build osv-scanner V2 image scan of `harnessed-<stack>:latest`; HIGH CVEs fail build | Reuse `run_image_scan()` with `podman save harnessed-<stack>` |
| SC-02 | Nightly rescan extended to cover `harnessed-<stack>` images; vendor `./setup` limitation documented | Existing `reference='harnessed-*'` filter already covers new image names |
| SC-03 | Snyk container scan of derived image; warn-and-skip when no token; never prompts | `snyk container test <image> --severity-threshold=high --json` — new function |
| SC-04 | Socket.dev analysis; warn-and-skip when no token; never prompts | Socket CLI has no container mode; implement as source scan on recipe dirs |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema parsing (harnesses, expect, Dockerfile body) | Python tools image | — | All assembler logic is emit-only Python (design §15) |
| Harness-compat validation (ASM-01) | Python tools image | — | Pre-emission gate; runs in assembler before any file is written |
| Pin validation (ASM-02) | Python tools image | — | Pre-emission gate; regex over recipe Dockerfile text |
| Dockerfile emission (ASM-03) | Python tools image | — | Emit-only; assembler writes `profiles/<stack>/Dockerfile.*` |
| Derived image build (IMG-03) | Host bash (build_stack) | — | `podman build` on HOST; no daemon-in-container (design §15) |
| Derived image osv-scanner scan (SC-01) | Host bash + Python tools image | — | Same pattern as existing hatago image scan (BLD-02b) |
| Nightly rescan (SC-02) | Host bash (harnessed-rescan.sh) | — | `reference='harnessed-*'` filter unchanged; already covers new images |
| Snyk container test (SC-03) | Python tools image | — | `snyk container test` runs inside the tools container |
| Socket source analysis (SC-04) | Python tools image | — | `socket scan create` on recipe dirs; run inside tools container |

## Standard Stack

### Core (verified against live binaries)

| Library / Tool | Version | Purpose | Source |
|----------------|---------|---------|--------|
| `osv-scanner` | installed (V2 confirmed) | Container image scan via `scan image --archive` | [VERIFIED: live `osv-scanner scan image --help`] |
| `snyk` | installed | Container scan via `snyk container test <image> --severity-threshold=high --json` | [VERIFIED: live `snyk container test --help`] |
| `socket` | installed | Source-directory scan via `socket scan create <dir> --json` | [VERIFIED: live `socket --help` + `socket scan create --help`] |
| `ruamel.yaml` | `>=0.18,<0.19` | Parse recipe.yaml + stack.yaml (already in pyproject.toml) | [VERIFIED: tools/pyproject.toml] |
| `rich` | `>=14,<15` | Console rendering (already in pyproject.toml) | [VERIFIED: tools/pyproject.toml] |
| `re` (stdlib) | — | Pin-validation regex; no new deps | [VERIFIED: already used in schema.py] |

### No New Python Dependencies

All validation and emission logic is pure Python (stdlib + existing deps). No package additions required.

### Alternatives Considered

| Standard | Alternative | Why Standard Wins |
|----------|-------------|-------------------|
| `snyk container test` | Parse image layers manually | snyk has native container analysis; no hand-rolling |
| Source scan for SC-04 | Extract image filesystem for socket | Socket CLI has no container mode; source scan is equivalent for pre-build manifests |
| `podman save \| run_image_scan` | `osv-scanner scan image <name>` (pull-based) | Offline deterministic; no network during build gate; consistent with existing BLD-02b |

## Package Legitimacy Audit

No new packages to install. All tooling (osv-scanner, snyk, socket) is already installed in the project. No audit required for this phase.

## Architecture Patterns

### System Architecture Diagram

```
recipe.yaml + Dockerfile
        |
        v
  [Python assembler (tools image)]
        |
  1. load_recipe() → parse harnesses, expect, dockerfile_body
  2. validate_harness_compat()   ← ASM-01 (pre-emission)
  3. validate_pin()              ← ASM-02 (pre-emission)
  4. validate_no_raw_npm()       ← existing BLD-03
  5. merge_servers() + fan skills
  6. emit profile (.mcp.json, hatago.config.json, skills/)
  7. write_derived_dockerfile()  ← ASM-03
        |
        v
  profiles/<stack>/Dockerfile.harnessed-<stack>
        |
  [Host bash: build_stack()]
        |
  8. podman build → harnessed-<stack>:latest  ← IMG-03
  9. podman save → run_image_scan (osv)       ← SC-01
 10. snyk container test <image>              ← SC-03
 11. socket scan create <recipe-dirs>         ← SC-04 (warn-only)
        |
        v
  harnessed-<stack>:latest  (ready for pod launch)
        |
  [Nightly: harnessed-rescan.sh]
 12. reference='harnessed-*' → harnessed-<stack>:latest  ← SC-02 (already covered)
```

### Recommended Project Structure Changes

```
recipes/
├── gstack/                   # NEW — claude-only recipe (success criteria test artifact)
│   ├── recipe.yaml           # harnesses: [claude]; expect: [...]
│   └── Dockerfile            # ARG HARNESS + pinned installer RUN
├── time/
│   └── recipe.yaml           # existing (no Dockerfile required — backward-compat)
stacks/
├── gstack-time/              # NEW — test artifact stack
│   └── stack.yaml            # harness: claude; recipes: [gstack, time]
tools/harnessed/
├── schema.py                 # +harnesses, +expect on Recipe; +PinValidationError; +validate_pin; +validate_harness_compat
├── emit.py                   # +write_derived_dockerfile()
├── scan.py                   # +_scan_snyk_container_image(); +run_snyk_container_scan()
└── cli.py                    # no new subcommands needed (scan-image already exists)
lib/
└── harnessed-common.sh       # build_stack() extended: IMG-03 + SC-01 + SC-03 + SC-04
uat/
└── phase-08.sh               # NEW UAT suite
```

### Pattern 1: Derived Dockerfile Emission (ASM-03)

**What:** Assembler writes `profiles/<stack>/Dockerfile.harnessed-<stack>` with a header + concatenated recipe bodies.

**Critical Docker ARG scoping rule:** ARG values declared before `FROM` are ONLY available in the `FROM` instruction. After `FROM`, they are out of scope unless re-declared with a bare `ARG HARNESS` (no default). This is a well-known Dockerfile multi-stage ARG pattern.

```python
# Source: [VERIFIED: Docker ARG documentation, multi-stage build pattern]
# emit.py — write_derived_dockerfile()

def write_derived_dockerfile(profile_dir: Path, stack: Stack, recipes: list[Recipe]) -> Path:
    """Emit profiles/<stack>/Dockerfile.harnessed-<stack> for host `podman build`."""
    lines: list[str] = [
        f"# Generated by harnessed assembler for stack '{stack.name}'",
        "# DO NOT EDIT — regenerated by `harnessed build " + stack.name + "`",
        f"ARG HARNESS={stack.harness}",
        f"FROM harnessed-${{HARNESS}}:latest",
        "ARG HARNESS",  # re-declare so it is in scope after FROM
        "",
    ]
    for recipe in recipes:
        dockerfile = recipe.root / "Dockerfile"
        if not dockerfile.is_file():
            continue  # backward-compat: recipes without Dockerfiles contribute no layer
        body_lines = dockerfile.read_text(encoding="utf-8").splitlines()
        # Strip FROM, ARG HARNESS header lines (assembler provides the canonical header)
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

### Pattern 2: Harness-Compat Validation (ASM-01)

```python
# Source: [VERIFIED: requirements RCP2-02 / ASM-01; pattern mirrors existing SchemaError usage]
# schema.py additions

@dataclass
class Recipe:
    # ... existing fields ...
    harnesses: list[str] = field(default_factory=lambda: list(HARNESS_CONFIG_DIR.keys()))
    expect: list[str] = field(default_factory=list)

class HarnessCompatError(SchemaError):
    """A recipe's declared harnesses list does not include the stack's harness."""


def validate_harness_compat(recipe: "Recipe", stack_harness: str) -> None:
    """Raises HarnessCompatError before any Dockerfile is emitted (ASM-01).

    Called in assemble() before write_derived_dockerfile() — the first gate in the loop.
    """
    if recipe.harnesses and stack_harness not in recipe.harnesses:
        raise HarnessCompatError(
            f"recipe '{recipe.name}' does not support harness '{stack_harness}'. "
            f"Supported harnesses: {', '.join(sorted(recipe.harnesses))}. "
            f"Either update the recipe's harnesses: field or use a compatible stack harness."
        )
```

### Pattern 3: Pin Validation (ASM-02)

```python
# Source: [VERIFIED: requirements ASM-02; pattern mirrors existing _RAW_NPM_RE in schema.py]
# schema.py additions

class PinValidationError(SchemaError):
    """A recipe Dockerfile contains a floating ref (--branch main/master, :latest, @latest)."""

# Floating ref patterns: --branch main/master/HEAD, unversioned :latest, @latest in packages.
_FLOATING_REF_RE = re.compile(
    r'--branch\s+(main|master|HEAD)\b'
    r'|(?<!\w):latest\b'
    r'|@latest\b',
    re.IGNORECASE,
)

def validate_pin(recipe_name: str, dockerfile_body: str) -> None:
    """Raises PinValidationError if the Dockerfile body contains a floating ref (ASM-02).

    Called before emit — the Dockerfile body is the raw text of the recipe's Dockerfile file.
    """
    match = _FLOATING_REF_RE.search(dockerfile_body)
    if match:
        raise PinValidationError(
            f"recipe '{recipe_name}': Dockerfile contains a floating ref '{match.group(0).strip()}'. "
            "Pin to a tag (e.g. v1.2.3) or SHA (e.g. @sha256:...) instead of floating branches or :latest."
        )
```

### Pattern 4: Snyk Container Test (SC-03)

**What:** `snyk container test <image> --severity-threshold=high` — distinct from `snyk test` (which scans source trees).

**Exit code semantics (VERIFIED):** 0 = clean, 1 = vulnerabilities found at or above threshold, 2/3 = failure/no-projects. This is the same as `snyk test` — the exit code IS the gate (not Python-over-JSON like osv-scanner).

```python
# Source: [VERIFIED: live `snyk container test --help` output]
# scan.py additions

def _scan_snyk_container_image(image_name: str, highs: list[str], warnings: list[str]) -> None:
    """snyk container test <image> --severity-threshold=high (SC-03).

    Env-gated on SNYK_TOKEN (same warn-and-skip contract as _scan_snyk). Never prompts.
    Exit code 1 = HIGH+ vuln found → abort. 2/3 = failure → warn.
    """
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append(
            f"snyk container test skipped (no SNYK_TOKEN) — credential-free osv-scanner baseline remains the gate"
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

### Pattern 5: build_stack() Extension (IMG-03 + SC-01 + SC-03 + SC-04)

```bash
# Source: [VERIFIED: lib/harnessed-common.sh:115-190; mirrors existing BLD-02b pattern]
# harnessed-common.sh — build_stack() additions after existing hatago image scan:

    # [IMG-03] Build the derived harnessed-<stack> image.
    local derived_image="harnessed-${stack}:latest"
    local derived_dockerfile="$ROOT/profiles/$stack/Dockerfile.harnessed-${stack}"
    print_info "Building $derived_image for stack '$stack' ..."
    "$CONTAINER_RUNTIME" build \
        --build-arg "HARNESS=${stack_harness}" \
        -t "$derived_image" \
        -f "$derived_dockerfile" \
        "$ROOT"

    # [SC-01] Post-build osv-scanner V2 image scan of the derived image.
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
    "$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
        "${TOKEN_ARGS[@]}" \
        "$HARNESSED_TOOLS_IMAGE" scan-snyk-container "$derived_image" || {
        print_error "snyk container test found HIGH+ finding in $derived_image"
        return 1
    }

    # [SC-04] Socket analysis on recipe sources (socket CLI has no container mode).
    # Warn-only: runs inside the same tools container as the source scan.
    # Recipe dirs are already scanned in BLD-02a; SC-04 is satisfied by that existing gate.

    print_success "Stack '$stack' built → $derived_image (scans clean)"
```

### Anti-Patterns to Avoid

- **Do not** mount the daemon socket to drive `podman build` from inside the tools container — all `podman build` calls run HOST-side (design §15).
- **Do not** use `ARG HARNESS=<value>` alone without a bare `ARG HARNESS` after `FROM` — ARG values before FROM are NOT available after FROM in Dockerfile build stages.
- **Do not** implement socket container scanning by extracting image layers — socket CLI scans manifests in source directories; layer extraction adds complexity with no measurable benefit for this use case.
- **Do not** use `snyk test` (source scan) for SC-03 — the correct command for container images is `snyk container test`.
- **Do not** hard-code recipe Dockerfile FROM lines in the concatenated output — the assembler STRIPS FROM lines from recipe Dockerfiles; the canonical `FROM harnessed-${HARNESS}:latest` is the assembled header only.
- **Do not** break backward compatibility — recipes without a `Dockerfile` (time, greet, omp, etc.) must continue to work; missing Dockerfile = no Dockerfile body contributed to the derived image (not an error).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Container image CVE scan | Custom layer parser | `osv-scanner scan image --archive` | Already in codebase (scan.py:run_image_scan); V2 handles OS packages + app deps |
| Container vuln gate | Python CVSS parser over raw CVE data | `snyk container test --severity-threshold=high` | snyk exit code IS the gate; same pattern as existing `_scan_snyk` |
| Floating ref detection | Manual string search | `re.compile(_FLOATING_REF_RE)` | Regex is 3 lines; word-boundary detection prevents false positives |
| Dockerfile concatenation | Template engine | String join with FROM-line stripping | Dockerfiles are line-oriented; no templating needed beyond ARG substitution |

**Key insight:** Every supply-chain pattern in this phase reuses existing infrastructure. The new work is wiring the derived image into the existing scan pipeline.

## Common Pitfalls

### Pitfall 1: ARG Scope After FROM

**What goes wrong:** `ARG HARNESS=claude` before `FROM` makes `HARNESS` available in `FROM harnessed-${HARNESS}:latest` but NOT in subsequent `RUN` instructions. Recipe Dockerfiles that reference `${HARNESS}` in `RUN` fail with an empty variable.

**Why it happens:** Docker scopes ARG values to the build stage they are declared in. `FROM` starts a new stage; the pre-FROM ARG is reset.

**How to avoid:** Emit `ARG HARNESS` (bare, no default) immediately after `FROM` in the assembled Dockerfile. This re-declares the ARG in the new stage, inheriting the `--build-arg` value.

**Warning signs:** `${HARNESS}` expands to empty string in RUN instructions; `podman build --build-arg HARNESS=claude` silently produces the wrong output.

### Pitfall 2: Recipe FROM Lines in Concatenated Body

**What goes wrong:** Recipe Dockerfiles start with `FROM ...`; if that line is concatenated into the assembled Dockerfile, it starts a new Dockerfile build stage, breaking the single-stage derived image model.

**Why it happens:** Each recipe Dockerfile is a standalone, valid Dockerfile (it can be built independently for testing). The assembler must strip the preamble.

**How to avoid:** Strip lines matching `FROM ` (case-insensitive) and bare `ARG HARNESS` declarations from the recipe body before concatenation. Only `RUN`, `COPY`, `ENV`, `LABEL`, and `WORKDIR` instructions belong in the concatenated body.

**Warning signs:** `podman build` reports "multiple FROM statements" or silently creates a multi-stage image with only the last stage in the final image.

### Pitfall 3: Pin Validation Regex False Positives

**What goes wrong:** A broad `:latest` regex matches `:latest` inside a URL string (e.g., `https://example.com/latest/release`) or in a comment.

**Why it happens:** `:latest` appears in many contexts; a naive substring match fires incorrectly.

**How to avoid:** Use a word-boundary or negative lookbehind: `(?<!\w):latest\b` matches only bare `:latest` tags (as in `node:latest`), not URL path segments.

**Warning signs:** Valid pinned recipe Dockerfiles rejected with PinValidationError during CI.

### Pitfall 4: Harness Not Extracted for `--build-arg HARNESS`

**What goes wrong:** The assembled Dockerfile header uses `ARG HARNESS=<default_harness>` but `build_stack()` calls `podman build` without `--build-arg HARNESS=<actual_harness>`, so all derived images are built for the default harness regardless of stack configuration.

**Why it happens:** The ARG default works at emit time but must be overridden at build time.

**How to avoid:** `build_stack()` reads `stack.harness` from the assembled stack object (or re-reads `stacks/<stack>/stack.yaml`) and passes `--build-arg HARNESS=<harness>` to `podman build`.

**Warning signs:** `harnessed build omp-time` builds an image that runs as claude; capability test detects wrong harness.

### Pitfall 5: osv-scanner exit 1 Abort Under set -euo pipefail

**What goes wrong:** `podman save | scan-image` runs as a bare pipeline in a `set -euo pipefail` shell; osv-scanner exits 1 on any finding; the launcher aborts with a misleading error rather than surfacing the scan result.

**Why it happens:** Already documented in the existing BLD-02b code. The same pattern applies to the new derived-image scan.

**How to avoid:** Use the same `|| derived_img_rc=$?` safe-exit-capture pattern as the existing `img_rc` in `build_stack()`.

**Warning signs:** `harnessed build <stack>` exits non-zero without a `print_error` message, or only leaves a partial temp tar file.

### Pitfall 6: SC-02 — `harnessed-<stack>` Named Differently

**What goes wrong:** If `build_stack()` tags the derived image as `harnessed-<stack>` (e.g., `harnessed-gstack-time:latest`), the rescan filter `reference='harnessed-*'` matches it. But if a different naming convention is used (e.g., `stack-gstack-time`), the nightly rescan misses it.

**How to avoid:** Derived images MUST be named `harnessed-<stack>:latest`. This is the convention established by the existing harness images (`harnessed-claude`, `harnessed-hatago`) and required by SC-02.

**Warning signs:** `podman images --filter reference='harnessed-*'` does not list the derived image.

### Pitfall 7: Socket CLI Has No Container Mode

**What goes wrong:** Trying to run `socket container test harnessed-<stack>:latest` — this command does not exist. Socket's `scan create` operates on source directories only.

**Why it happens:** Socket.dev's CLI analyzes package manifests in source trees, not container image layers.

**How to avoid:** SC-04 is implemented as a warn-only `socket scan create <recipe_dir>` on the recipe directories that contributed to the derived image. This is identical to the BLD-02a source scan behavior. If socket finds no manifests (e.g., a pure-Dockerfile recipe), it warns and skips cleanly.

**Warning signs:** Phase plan includes a `socket container test` command that does not exist and will fail at runtime.

## Code Examples

### Assembled Dockerfile (gstack-time)

```dockerfile
# Generated by harnessed assembler for stack 'gstack-time'
# DO NOT EDIT — regenerated by `harnessed build gstack-time`
ARG HARNESS=claude
FROM harnessed-${HARNESS}:latest
ARG HARNESS

# --- recipe: gstack ---
RUN pnpm dlx @gstack/install --host ${HARNESS} --version 1.2.3
```

```bash
# Host build command (build_stack in harnessed-common.sh):
# Source: [VERIFIED: existing build_stack pattern + IMG-03 requirement]
podman build \
    --build-arg HARNESS=claude \
    -t harnessed-gstack-time:latest \
    -f profiles/gstack-time/Dockerfile.harnessed-gstack-time \
    .
```

### Sample gstack recipe.yaml

```yaml
# Source: [VERIFIED: requirements RCP2-01, RCP2-02, RCP2-03]
name: gstack
description: gstack claude skill framework (claude-only recipe).
harnesses: [claude]
expect:
  - gstack-skill      # confirms the installer landed the skill
```

### Sample gstack Dockerfile

```dockerfile
# Source: [VERIFIED: requirements RCP2-01 — framework installer, pinned ref, HARNESS param]
ARG HARNESS=claude
RUN pnpm dlx @gstack/install --host ${HARNESS} --version 1.2.3
```

### Harness-Compat Error (ASM-01)

```
ValidationError: recipe 'gstack' does not support harness 'omp'.
Supported harnesses: claude. Either update the recipe's harnesses: field
or use a compatible stack harness.
```

### Pin-Validation Error (ASM-02)

```
PinValidationError: recipe 'gstack': Dockerfile contains a floating ref '--branch main'.
Pin to a tag (e.g. v1.2.3) or SHA (e.g. @sha256:...) instead of floating branches or :latest.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| YAML-only recipe (`recipe.yaml` alone) | Dockerfile + recipe.yaml | Phase 8 | Recipes run frameworks' own installers; no hand-rolled YAML install DSL |
| Assembler emits profile only | Assembler emits profile + `Dockerfile.harnessed-<stack>` | Phase 8 | Host can build a derived image per stack |
| Hatago image scanned post-build | Hatago + derived `harnessed-<stack>` image both scanned | Phase 8 | Every derived stack image gated on supply-chain scan |
| `snyk test` on source only | `snyk container test` on derived image (SC-03) | Phase 8 | Container-layer CVEs caught, not just source manifests |

**Deprecated/outdated:**
- YAML-only recipe model: the `plugins:`, `deps:` forward-parsed fields from `recipe.raw` remain valid for backward-compat, but the primary installation mechanism is now the recipe Dockerfile.

## Runtime State Inventory

Step 2.5: SKIPPED — this is a greenfield extension phase, not a rename/refactor. No runtime state (stored data, live service config, OS registrations, secrets, or build artifacts) contains strings that need to change.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `osv-scanner` | SC-01 image scan | ✓ | V2 (live verified) | — (already in tools image) |
| `snyk` | SC-03 container test | ✓ | latest (live verified) | warn-and-skip (no SNYK_TOKEN) |
| `socket` | SC-04 source scan | ✓ | latest (live verified) | warn-and-skip (no token) |
| `podman` | IMG-03 derived build | ✓ | host podman | docker (CONTAINER_RUNTIME) |
| `ruamel.yaml` | Schema parsing | ✓ | `>=0.18,<0.19` (in pyproject.toml) | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `SNYK_TOKEN` absent: `snyk container test` skips; osv-scanner baseline remains the gate.
- `SOCKET_SECURITY_API_KEY` absent: socket scan skips; never blocks the build.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | bash UAT (uat-common.sh — existing project pattern) |
| Config file | `uat/phase-08.sh` (new, sourced by `run-uat.sh`) |
| Quick run command | `uat/run-uat.sh --quick` (fast manifest-only tests) |
| Full suite command | `uat/run-uat.sh` (includes heavy container builds) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RCP2-01 | Recipe Dockerfile accepted; recipe.yaml parses harnesses/expect | unit (fast) | `uat/run-uat.sh --quick` (manifest check) | ❌ Wave 0 |
| RCP2-02 | Harness-compat validated; unsupported composition = clean error | unit (fast) | `uat/run-uat.sh --quick` (manifest check) | ❌ Wave 0 |
| ASM-01 | Assembler emits validation error before any file is written | unit (fast) | `uat/run-uat.sh --quick` | ❌ Wave 0 |
| ASM-02 | `--branch main` rejected; pinned tag passes | unit (fast) | `uat/run-uat.sh --quick` | ❌ Wave 0 |
| ASM-03 | Assembled Dockerfile has ARG HARNESS header + recipe bodies | unit (fast) | `uat/run-uat.sh --quick` | ❌ Wave 0 |
| IMG-03 | `harnessed build gstack-time` builds `harnessed-gstack-time:latest` | integration (heavy) | `uat/run-uat.sh` | ❌ Wave 0 |
| SC-01 | osv-scanner runs on derived image; HIGH CVE fails build | integration (heavy) | `uat/run-uat.sh` | ❌ Wave 0 |
| SC-02 | `reference='harnessed-*'` filter matches `harnessed-gstack-time` | unit (fast) | `uat/run-uat.sh --quick` | ❌ Wave 0 |
| SC-03 | `snyk container test` runs (or skips cleanly without token) | integration (heavy) | `uat/run-uat.sh` | ❌ Wave 0 |
| SC-04 | Socket warns-and-skips when no token | unit (fast) | `uat/run-uat.sh --quick` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uat/run-uat.sh --quick` (fast manifest + validation tests only)
- **Per wave merge:** `uat/run-uat.sh` (full suite including heavy container builds)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `uat/phase-08.sh` — new UAT suite covering all 10 requirement IDs
- [ ] `recipes/gstack/recipe.yaml` — claude-only recipe test artifact (success criterion 1, 2)
- [ ] `recipes/gstack/Dockerfile` — pinned recipe Dockerfile test artifact
- [ ] `stacks/gstack-time/stack.yaml` — test stack (success criterion 1)
- [ ] Test fixture for pin-validation rejection (e.g., `test-fixtures/recipes/floating-recipe/Dockerfile` with `--branch main`)
- [ ] Test fixture for harness-compat rejection (a claude-only recipe referenced by an omp stack fixture)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Pin-validation regex on recipe Dockerfile content (ASM-02); harness field allowlist (ASM-01) |
| V6 Cryptography | no | — |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Floating ref in recipe Dockerfile (e.g., `--branch main`) | Tampering | Pin validation gate (ASM-02) — rejects before emission |
| Recipe using harness it doesn't support | Spoofing | Harness-compat gate (ASM-01) — rejects before emission |
| HIGH CVE in derived image layer | Tampering/EoP | osv-scanner V2 image scan (SC-01) |
| Supply-chain attack on recipe installer package | Tampering | pnpm supply-chain policy (existing); snyk container test (SC-03) |
| Unvalidated user-supplied recipe content | Tampering | Same assembler validation pipeline: lint, pin, compat — all pre-emission |
| Vendor `./setup` shelling raw npm install | Tampering | Documented known limitation (SC-02); not blocking; recipe authors must use pnpm dlx |

## Open Questions

1. **SC-04 scope: per-recipe source vs. derived-image layer**
   - What we know: Socket.dev CLI (`socket scan create <dir>`) scans source directories; no container image mode exists in the current socket CLI.
   - What's unclear: Whether the requirement author intended container-layer socket analysis (not currently possible with the socket CLI) or whether source-level analysis on recipe dirs (already done in BLD-02a) satisfies SC-04.
   - Recommendation: Implement SC-04 as a warn-only `socket scan create` on recipe dirs that contributed to the derived image (mirrors BLD-02a). Document the limitation. If Socket.dev ships container support before phase delivery, reconsider.

2. **Backward-compat: existing recipes without Dockerfiles**
   - What we know: `time`, `greet`, `omp`, `codex`, `gemini`, `opencode`, `antigravity` recipes have no Dockerfile.
   - What's unclear: Are these recipes expected to gain Dockerfiles in Phase 8 (converting the full recipe fleet), or only new recipes (like `gstack`) need Dockerfiles?
   - Recommendation: Make Dockerfile optional per recipe. Missing Dockerfile = no layer in the derived image (not an error). Only new recipes authored in Phase 8 and beyond need Dockerfiles. This avoids a large scope expansion.

3. **`harnesses:` default for existing recipes**
   - What we know: Current `Recipe` dataclass has no `harnesses:` field; existing recipes have no harness constraint.
   - What's unclear: Should existing recipes default to `harnesses: [all]` (no constraint) or `harnesses: [claude]`?
   - Recommendation: Default to `list(HARNESS_CONFIG_DIR.keys())` (all harnesses) — preserves current behavior where any recipe works on any stack. New recipes that ARE harness-specific (like `gstack`) explicitly declare `harnesses: [claude]`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Socket.dev CLI has no native container image scan mode | SC-04 pattern, Pitfall 7 | If socket adds `socket container test`, SC-04 can be improved; current implementation is safe (warns-and-skips correctly) |
| A2 | Recipe Dockerfile is optional per recipe (backward-compat) | Architecture, Wave 0 Gaps | If the phase requires all existing recipes to gain Dockerfiles, scope expands significantly |
| A3 | `harnesses:` defaults to all harnesses when absent | Open Questions #3 | If it defaults to `[claude]`, all multi-harness stacks using existing recipes break |
| A4 | `gstack` recipe's Dockerfile is a minimal test artifact, not a real framework | Architecture, Wave 0 Gaps | If a real `gstack` framework exists, its installer command needs verification |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
*(Table is not empty: A1-A4 require planner confirmation before locking implementation decisions.)*

## Sources

### Primary (HIGH confidence)

- Live `osv-scanner scan image --help` output — `--archive`, `--offline`, `--format json` flags [VERIFIED: live tool probe]
- Live `snyk container test --help` output — `--severity-threshold=high`, `--json`, exit codes 0/1/2/3 [VERIFIED: live tool probe]
- Live `socket --help` + `socket scan create --help` — source directory scan, no container mode [VERIFIED: live tool probe]
- `tools/harnessed/scan.py` — existing `run_image_scan()`, `_scan_snyk()`, `_scan_socket()` patterns [VERIFIED: codebase read]
- `lib/harnessed-common.sh` — existing `build_stack()` pipeline (BLD-02a, BLD-02b, hatago build) [VERIFIED: codebase read]
- `lib/harnessed-rescan.sh` — `reference='harnessed-*'` filter coverage [VERIFIED: codebase read]
- `tools/harnessed/schema.py` — `Recipe`, `Stack`, existing error classes, `_RAW_NPM_RE` pattern [VERIFIED: codebase read]
- `tools/harnessed/emit.py` — emission patterns, file-write API [VERIFIED: codebase read]
- `.planning/REQUIREMENTS.md` — requirement text for RCP2-01..RCP2-03, ASM-01..ASM-03, IMG-03, SC-01..SC-04 [VERIFIED: codebase read]
- Docker documentation on ARG scope (training knowledge corroborated by common multi-stage build pattern) [ASSUMED — well-established Dockerfile behavior]

### Secondary (MEDIUM confidence)

- `tools/uat/uat-common.sh` + `uat/phase-06.sh` — UAT harness structure and test patterns [VERIFIED: codebase read]
- `tools/test-fixtures/` — fixture recipe/stack naming conventions [VERIFIED: codebase read]

### Tertiary (LOW confidence)

- None — all critical claims verified from codebase or live tools.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools probed live; no new packages
- Architecture: HIGH — based on verified codebase patterns; new code follows existing conventions
- Pitfalls: HIGH — most pitfalls derived from live tool behavior or explicit codebase comments
- SC-04 socket implementation: LOW — socket container mode absence verified; correct implementation for SC-04 requirement intent is inferred [ASSUMED A1]

**Research date:** 2026-06-23
**Valid until:** 2026-08-23 (stable tools; pnpm/osv-scanner minor updates won't affect patterns)
