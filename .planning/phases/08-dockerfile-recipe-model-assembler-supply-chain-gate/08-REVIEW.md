---
phase: 08-dockerfile-recipe-model-assembler-supply-chain-gate
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - tools/harnessed/schema.py
  - tools/harnessed/emit.py
  - tools/harnessed/assemble.py
  - tools/harnessed/scan.py
  - tools/harnessed/cli.py
  - lib/harnessed-common.sh
  - tools/uat/phase-08.sh
  - recipes/gstack/recipe.yaml
  - stacks/gstack-time/stack.yaml
  - recipes/floating-recipe/recipe.yaml
  - stacks/floating-test/stack.yaml
  - stacks/omp-gstack-test/stack.yaml
findings:
  critical: 3
  warning: 5
  info: 0
  total: 8
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-06-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase 8 Dockerfile recipe model, assembler, supply-chain scan gate, common shell
library, and UAT fixtures. The Python files are well-structured and the CVSS computation is
implemented correctly. Three correctness bugs are present; none are security vulnerabilities, but
two will produce silent failures or bad config under specific recipe authoring patterns, and the
third causes incorrect supply-chain lint rejections on valid recipes.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: ARG HARNESS filter strips any `ARG HARNESSED_*` from recipe Dockerfiles

**File:** `tools/harnessed/emit.py:133-137`

**Issue:** `write_derived_dockerfile` filters recipe Dockerfile lines with:

```python
if not ln.strip().upper().startswith("ARG HARNESS")
```

`startswith("ARG HARNESS")` matches any line whose stripped, uppercased form begins with that
prefix — including `ARG HARNESSED_VERSION=1.0`, `ARG HARNESSES_LIST=a,b`, etc. Any recipe that
declares an ARG whose name begins with `HARNESSED` (a natural naming choice given the project
name) would have that declaration silently stripped from the assembled Dockerfile. The build would
then fail at the first `${HARNESSED_*}` reference with no hint that the ARG was removed by the
assembler.

**Fix:** Tighten the filter to match only the exact ARG names the assembler injects:

```python
filtered = [
    ln for ln in body_lines
    if not re.match(r'^\s*FROM\s+', ln, re.IGNORECASE)
    and not re.match(r'^\s*ARG\s+HARNESS\s*(=.*)?$', ln, re.IGNORECASE)
]
```

The `ARG HARNESS` re-declaration (bare, no value) and `ARG HARNESS=<value>` forms are both
matched; nothing else is.

---

### CR-02: Network-native MCP server with no `url:` produces null-URL hatago config entry

**File:** `tools/harnessed/emit.py:80-91` and `tools/harnessed/schema.py:168-187`

**Issue:** `_hatago_entry()` emits `{"url": server.url, "type": server.transport}` for any
server where `is_stdio_child` is False. `is_stdio_child` is False when `transport != "stdio"` OR
`command is None`. A recipe author who writes:

```yaml
mcp:
  servers:
    - name: my-api
      transport: http
      # url: accidentally omitted
```

passes schema parsing (no `url` requirement is validated in `_parse_servers`), passes
`validate_no_raw_npm`, passes `validate_harness_compat`, and reaches `_hatago_entry` where
`server.url` is `None`. The emitted `hatago.config.json` entry is `{"url": null, "type": "http"}`.
hatago receives an invalid null-URL proxy entry; the server will fail to start with no assembler
error.

**Fix:** Add a validation guard in `_parse_servers` or at the top of `_hatago_entry`:

```python
# In _hatago_entry, before the network-native branch:
if not server.is_stdio_child:
    if not server.url:
        raise SchemaError(
            f"mcp server '{server.name}': network-native transport '{server.transport}' "
            "requires a 'url' field"
        )
    entry = {"url": server.url, "type": server.transport}
    ...
```

---

### CR-03: Haystack join in `validate_no_raw_npm` produces false-positive rejections

**File:** `tools/harnessed/schema.py:349-362`

**Issue:** The lint gate joins all command strings and args into a single space-delimited string
before applying the regex:

```python
match = _RAW_NPM_RE.search(" ".join(haystack))
```

This causes two correctness bugs:

1. **Word-boundary false positives on package names**: `_RAW_NPM_RE` uses `\bnpx\b`. In a package
   name like `@scope/npx-tools` or `my-npx-runner`, the hyphen is a non-word character, so
   `\bnpx\b` matches the substring `npx` within the package name. A recipe with
   `args: [dlx, my-npx-runner]` is correctly using `pnpm dlx` but would be rejected.

2. **Cross-server arg contamination**: If server A has `args: ["...", "npm"]` and server B has
   `args: ["install", "..."]`, the joined string contains `npm install` spanning two servers'
   args, producing a false collision.

**Fix:** Apply the regex per-string instead of on the joined haystack:

```python
for candidate in haystack:
    if candidate and _RAW_NPM_RE.search(candidate):
        token = _RAW_NPM_RE.search(candidate).group(0)
        equiv = _NPM_TO_PNPM.get(token.strip(), "pnpm")
        raise RecipeLintError(
            f"recipe '{recipe.name}': raw npm/npx token '{token.strip()}' detected. "
            f"Replace it with the pnpm equivalent '{equiv}'."
        )
```

This still needs the word-boundary guards but avoids cross-contamination and the per-candidate
approach allows accurate error messages.

---

## Warnings

### WR-01: `_resolve_service_servers` mutates shared `McpServer` objects in place

**File:** `tools/harnessed/assemble.py:71-81`

**Issue:** The function sets `server.url` and `server.transport` directly on the `McpServer`
dataclass instances, which are the same objects stored in `recipe.servers`. After `assemble()`
returns, any caller that inspects `result.recipes[i].servers` sees mutated transport/URL values
that were not present in the parsed manifest. `run_capability_test` (called independently of
`assemble`) loads fresh recipe objects, so there is no current bug, but this is a latent
correctness hazard if the assembler result's recipe list is ever used for manifest comparison.

**Fix:** Clone the server in the resolution step:

```python
from dataclasses import replace
...
resolved = replace(server, url=f"http://host.containers.internal:{svc.port}/mcp",
                   transport="http" if server.transport == "stdio" else server.transport)
servers[servers.index(server)] = resolved
```

Or collect a new list rather than mutating in place.

---

### WR-02: Unquoted `$(rt_userns_args)` in three `podman run` calls

**File:** `lib/harnessed-common.sh:127,159,221`

**Issue:** Three `"$CONTAINER_RUNTIME" run` calls use unquoted command substitution:

```bash
"$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
```

If `rt_userns_args` ever emits output containing spaces in a value (e.g., a flag value with a
space), word splitting would split it incorrectly. The pattern is common in shell for optional
multi-flag injection, but the correct approach is an array:

**Fix:** Use an array for optional args:

```bash
local -a userns_args
mapfile -t userns_args < <(rt_userns_args)
"$CONTAINER_RUNTIME" run --rm "${userns_args[@]}" \
```

Or if `rt_userns_args` is known to always return simple flags, document the contract explicitly
and add a guard in `rt_userns_args` itself.

---

### WR-03: `needs_container()` name inverts its semantics

**File:** `tools/uat/phase-08.sh:13`

**Issue:**

```bash
needs_container() { [ "$UAT_QUICK" = "true" ]; }   # true ⇒ heavy test should skip
```

The function returns true when `UAT_QUICK=true` — i.e., when the heavy test should **skip**.
Every call site reads `needs_container && { skip_test ...; return; }`. The name implies "returns
true when this test requires a container" but actually returns true when the test should be
skipped due to quick mode. A future maintainer adding a test could misread this and write the
guard backwards.

**Fix:** Rename to match the actual semantics:

```bash
in_quick_mode() { [ "$UAT_QUICK" = "true" ]; }
# Usage:
in_quick_mode && { skip_test "skipped (--quick) — ..."; return; }
```

---

### WR-04: `_RAW_NPM_RE` pattern misses common npm subcommands

**File:** `tools/harnessed/schema.py:281`

**Issue:** The npm lint regex only covers `npm install|ci|run|exec|i`. It does not cover `npm
add`, `npm update`, `npm uninstall`, `npm start`, `npm test`, `npm publish`, `npm link`, or
`npm ls`. A recipe that writes `npm add malicious-package` in a script would bypass the lint gate
entirely. The supply-chain policy intention (pnpm everywhere) is not fully enforced.

**Fix:** Expand the alternation or use a broader pattern for npm:

```python
_RAW_NPM_RE = re.compile(
    r"\bnpx\b"
    r"|\bnpm\s+(install|ci|run|exec|i|add|update|uninstall|start|test|publish|link|ls|list)\b"
)
```

Alternatively, match any `npm <subcommand>` where the subcommand is a word (`\bnpm\s+\w+\b`)
and let the error message guide authors to the pnpm equivalent.

---

### WR-05: Redundant list comprehension in image scan functions

**File:** `tools/harnessed/scan.py:338,413`

**Issue:** Both `run_image_scan` and `run_image_scan_online` use:

```python
warnings = [vid for vid in _all_finding_ids(data)]
```

`_all_finding_ids` already returns `list[str]`. The comprehension wraps it in another list
iteration for no effect.

**Fix:**

```python
warnings = _all_finding_ids(data)
```

---

_Reviewed: 2026-06-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
