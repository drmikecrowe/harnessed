---
phase: 09-surgical-profile-mount-history-surfacing
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - lib/harnessed-isolated.sh
  - lib/harnessed-manifest-mounts.sh
  - lib/manifests/antigravity.yaml
  - lib/manifests/claude.yaml
  - lib/manifests/codex.yaml
  - lib/manifests/gemini.yaml
  - lib/manifests/omp.yaml
  - lib/manifests/opencode.yaml
  - tools/harnessed/assemble.py
  - tools/harnessed/emit.py
  - tools/uat/phase-09.sh
findings:
  critical: 3
  warning: 4
  info: 3
  total: 10
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the Phase 09 surgical profile mount and history surfacing implementation: per-harness
YAML manifests, the `harnessed_manifest_mounts()` bash helper, integration in `harnessed-isolated.sh`,
Python assembler cleanup, and the UAT suite.

The manifest data model and the production mount logic are sound. The main defects concentrate in
two places: silent error swallowing when yq fails on a manifest (the mounts proceed with zero
entries and no diagnostic), and a broken UAT integration test that asserts two unrelated paths are
equal and therefore never correctly verifies MNT2-02 path mirroring. A secondary issue is the
hatago readiness loop completing silently after 30 seconds even when hatago never binds, leaving
the user attached to an instance with a dead MCP connection.

---

## Critical Issues

### CR-01: yq parse errors on manifests are silently swallowed — mounts proceed with no entries

**File:** `lib/harnessed-manifest-mounts.sh:43` and `:55`

**Issue:** Both `yq` calls redirect stderr to `/dev/null` and their exit codes are not checked.
If a manifest is malformed YAML or yq exits non-zero for any reason, the `while` loop body never
executes (no output), so neither profile files nor history dirs are mounted. The container starts
with no profile config and no history — a silent correctness failure with no diagnostic output.

The `2>/dev/null` suppression was presumably added to tolerate empty arrays (e.g., `history_dirs: []`),
but `yq '.history_dirs[]'` on an empty array already produces no output with exit 0; suppression is
not necessary for that case.

**Fix:**
```bash
# Capture yq output; propagate errors; let the caller see what went wrong.
local yq_out
yq_out="$(yq '.profile_files[]' "$manifest")" || {
    print_warning "Failed to read profile_files from $manifest (yq exit $?)"; return 1; }
while IFS= read -r f; do
    ...
done <<< "$yq_out"
```
Apply the same pattern to the `history_dirs[]` read at line 55.

---

### CR-02: `test_path_mirroring` asserts two unrelated values — MNT2-02 is never actually verified

**File:** `tools/uat/phase-09.sh:127-139`

**Issue:** The test captures `host_pwd="$(pwd)"` (the UAT runner's working directory, e.g.
`/home/mcrowe/Programming/Personal/code-container`), then launches a headless container with
`proj="/tmp/uat-mirror-$$"` as the project path. It then execs `pwd` inside the container
with no `-w` flag — so the result is the container image's default `WORKDIR` (typically `/root`
or `/home/user`). The assertion `assert_eq "$host_pwd" "$ctr_pwd"` compares the test runner's
cwd against the container image's default working directory. These are unrelated and will never
equal each other. MNT2-02 path mirroring (the bind mount making `proj` accessible at the same
path inside the container) is never exercised.

**Fix:** Replace with a test that actually verifies the bind is present at the correct path:
```bash
# Verify the project directory is accessible at its host absolute path inside the container.
local check
check="$("$RT" exec "$inst" bash -c "test -d '$proj' && echo EXISTS" 2>/dev/null || echo "MISSING")"
assert_eq "EXISTS" "$check" "host project path accessible at same absolute path in container (MNT2-02)"
```
Or, if the intent is to verify the working directory of an `exec` call:
```bash
ctr_pwd="$("$RT" exec -w "$proj" "$inst" bash -c 'pwd' 2>/dev/null || echo "EXEC_FAILED")"
assert_eq "$proj" "$ctr_pwd" "container pwd at project path matches host path (MNT2-02)"
```

---

### CR-03: Hatago readiness wait silently times out — harness attaches with a dead MCP connection

**File:** `lib/harnessed-isolated.sh:207-210`

**Issue:** The 30-second readiness loop exits without error if hatago never binds port `$HATAGO_PORT`.
The interactive attach then proceeds immediately, and the harness session opens with a
non-functional MCP connection. The user sees nothing wrong until they try to use an MCP tool.

```bash
for _i in $(seq 1 30); do
    "$CONTAINER_RUNTIME" exec "$instance" bash -lc "timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/$HATAGO_PORT'" >/dev/null 2>&1 && break
    sleep 1
done
# ← falls through silently; no check that the loop broke early
```

**Fix:** Check whether the loop succeeded before proceeding:
```bash
local _hatago_ready=false
for _i in $(seq 1 30); do
    "$CONTAINER_RUNTIME" exec "$instance" bash -lc \
        "timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/$HATAGO_PORT'" >/dev/null 2>&1 \
        && { _hatago_ready=true; break; }
    sleep 1
done
if [ "$_hatago_ready" != "true" ]; then
    print_warning "hatago did not bind :$HATAGO_PORT after 30 s — MCP tools may be unavailable"
fi
```
A harder failure (exit 1) is also reasonable if a non-functional MCP session is unacceptable.

---

## Warnings

### WR-01: yq may emit literal `null` for absent YAML keys — spurious mount attempt

**File:** `lib/harnessed-manifest-mounts.sh:28-43`

**Issue:** `yq '.profile_files[]'` on a YAML document where the `profile_files` key is absent
(not an empty array but truly absent) emits the string `null` to stdout with exit 0, rather than
empty output. The guard `[ -z "$f" ] && continue` does not catch the string `"null"`. The function
would then attempt to source a profile file named `null` from `profile_dir`, issuing a spurious
warning. All current manifests define `profile_files:` explicitly, so this is latent, but any
future manifest that omits the key would trigger it.

**Fix:** Add an explicit `null` guard alongside the empty-string guard:
```bash
[ -z "$f" ] || [ "$f" = "null" ] && continue
```
Apply the same to the `history_dirs` loop at line 49.

---

### WR-02: `needs_container` function name is semantically inverted relative to its callers

**File:** `tools/uat/phase-09.sh:21`

**Issue:** `needs_container()` returns exit 0 (true) when `UAT_QUICK=true`. Callers use the
pattern `needs_container && { skip_test; return; }`, meaning the test is SKIPPED when quick mode
is active. The name reads as "this test needs a container" (i.e., return true if a container is
required), but the actual semantics are "should I skip this test because we're in quick mode."
A future maintainer reading `needs_container && skip` would have to double-check the function body
to understand the logic inversion.

**Fix:** Rename to `skip_if_quick` or `in_quick_mode` and invert the logic to match the call
site intent:
```bash
skip_if_quick() { [ "$UAT_QUICK" = "true" ]; }
# callers: skip_if_quick && { skip_test "skipped (--quick)"; return; }
```

---

### WR-03: omp slug in UAT diverges from production `project_relpath()` for out-of-HOME paths

**File:** `tools/uat/phase-09.sh:178`

**Issue:** The test duplicates slug computation using `realpath --relative-to="$HOME"`, which
returns a `..`-prefixed relative path when the project directory is outside `$HOME`. The production
function `project_relpath()` (lib/harnessed-common.sh:389-392) uses `basename` as its fallback for
paths outside `$HOME`. If the UAT runner's cwd is outside `$HOME`, the slug computed in the test
differs from the slug computed by `harnessed_manifest_mounts`, so the test asserts the existence of
a different directory than the one the production code created.

**Fix:** Source and use the production helper, or replicate its exact logic:
```bash
# Match production project_relpath() exactly
local p="${proj%/}"
if [[ "$p" == "$HOME/"* ]]; then
    relpath="${p#"$HOME"/}"
else
    relpath="$(basename "$p")"
fi
local omp_slug="-${relpath//\//'-'}"
```

---

### WR-04: `emit.py` Dockerfile filter strips any ARG starting with `HARNESS` — too broad

**File:** `tools/harnessed/emit.py:124-127`

**Issue:** The filter:
```python
not ln.strip().upper().startswith("ARG HARNESS")
```
would silently strip a recipe ARG named `ARG HARNESS_PROXY_URL` or any other `HARNESS`-prefixed
build argument. The intent is to strip only `ARG HARNESS` (the exact token, the build-stage scope
anchor), not all ARGs that happen to start with that prefix.

**Fix:** Match the exact token with a word boundary:
```python
import re
_ARG_HARNESS_RE = re.compile(r'^ARG\s+HARNESS\s*$', re.IGNORECASE)

filtered = [
    ln for ln in body_lines
    if not ln.strip().upper().startswith("FROM ")
    and not _ARG_HARNESS_RE.match(ln.strip())
]
```

---

## Info

### IN-01: Dead variable `net` intentionally preserved — adds long-term maintenance noise

**File:** `lib/harnessed-isolated.sh:78`

**Issue:** `local net="${HARNESSED_NET:-harnessed-net}"` is assigned but never read. The comment
acknowledges this ("assigned-but-unused") and justifies it as a "D-04 anchor." A dead variable
that exists only to document a historical default belongs in a comment, not in executable code.
Future readers may not check the comment and could incorrectly assume `net` is used.

**Fix:** Remove the variable; record the D-04 default solely in a comment above the `pod_net_args`
block:
```bash
# D-04 default name was "harnessed-net"; now read directly from HARNESSED_NET.
local pod_net_args=()
```

---

### IN-02: `mcp_cfg` variable declared at broad scope but used only in the claude branch

**File:** `lib/harnessed-isolated.sh:226`

**Issue:** `local mcp_cfg="$CONTAINER_HOME/.mcp.json"` is declared before the harness dispatch
block but consumed only in the final `else` (claude) branch. For every other harness the variable
is unused. Moving it into the relevant branch makes intent clearer.

**Fix:**
```bash
else
    local mcp_cfg="$CONTAINER_HOME/.mcp.json"
    "$CONTAINER_RUNTIME" exec -it ... \
        bash -l -c "$mise_init && claude --mcp-config '$mcp_cfg' --strict-mcp-config"
fi
```

---

### IN-03: Path-mirroring bind at line 71 has no explicit access mode

**File:** `lib/harnessed-manifest-mounts.sh:71`

**Issue:** `MOUNT_ARGS+=( -v "$project_path:$project_path" )` omits the access mode. All other
mounts in the file specify `:ro` or `:rw` explicitly. Podman defaults to `:rw`, which is
presumably the intent (the harness must write to the project), but the inconsistency is a
readability gap and could surprise a reviewer expecting every bind to declare its mode.

**Fix:**
```bash
MOUNT_ARGS+=( -v "$project_path:$project_path:rw" )
```

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
