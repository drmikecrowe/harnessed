---
phase: 07-fat-base-agent-images
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - agents/claude/agent.yaml
  - agents/omp/agent.yaml
  - base/Dockerfile.harnessed-base
  - lib/harnessed-common.sh
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed four files delivered by phase 07: two agent manifests (`agents/claude/agent.yaml`,
`agents/omp/agent.yaml`), the fat base Dockerfile (`base/Dockerfile.harnessed-base`), and the
shared shell helpers (`lib/harnessed-common.sh`).

Two blockers found. First: `mise up` baked into `.bashrc` silently upgrades all tools on every
shell session, defeating the supply chain scan gate. Second: the lazy-build contract for the omp
harness (HRN-01) is broken at two call sites — claude-only users will always build omp on first
run. Five warnings cover reproducibility (unpinned runtime versions, apt layer leakage), a
`CONTAINER_RUNTIME` guard gap, orphaned agent manifests, and an unnecessary desktop app in the
image. Two info items round out the findings.

---

## Critical Issues

### CR-01: `mise up` in `.bashrc` Silently Upgrades Tools Past the Scanned Versions

**File:** `base/Dockerfile.harnessed-base:99`
**Issue:** `mise up 2>/dev/null` is baked into `.bashrc`, so every interactive shell session
auto-upgrades all installed tools. The supply chain gate (osv-scanner, pip-audit, snyk) runs at
image-build time against the pinned versions. After the image ships, `mise up` can pull in a
package with a HIGH+ CVE that was never scanned. The `2>/dev/null` suppression makes the upgrade
invisible. This breaks the security contract stated in §7 and invalidates post-build scan
guarantees.

**Fix:** Remove `mise up` from `.bashrc`. Upgrades should be a deliberate rebuild, not a
per-session side-effect. If users want an upgrade prompt, use `mise outdated` (read-only) instead.

```dockerfile
RUN echo 'PS1="\[\033[01;32m\][harnessed]\[\033[00m\] \[\033[01;34m\]\w\[\033[00m\]\$ "' >> /home/${USERNAME}/.bashrc && \
    echo 'eval "$(mise activate bash)"' >> /home/${USERNAME}/.bashrc && \
    echo 'mise trust -a 2>/dev/null' >> /home/${USERNAME}/.bashrc
#   ↑ remove the `mise up` line entirely
```

---

### CR-02: `build_images` and `ensure_images` Violate the Lazy-Build Contract for omp (HRN-01)

**File:** `lib/harnessed-common.sh:91-95` and `lib/harnessed-common.sh:201`
**Issue:** `build_images()` unconditionally includes `HARNESSED_OMP_IMAGE` in its build set (lines
91-95). `ensure_images()` uses the _absence_ of `HARNESSED_OMP_IMAGE` as one of three OR-conditions
to trigger `build_images` (line 201). The result: any first-run or clean environment will build the
omp harness even when no omp stacks exist, directly contradicting the documented HRN-01 contract
("LAZY ... called by the isolated launcher ONLY for `harness: omp` stacks, so claude-only users
are never forced to build omp").

The `ensure_omp_image()` lazy function (line 211) already exists for the correct pattern; the two
call sites above bypass it.

**Fix:**

1. Remove omp from `build_images`:
```bash
# build_images should build: base, claude, hatago only
build_images() {
    local force="${1:-false}"
    # ... (seed extra-tools.txt unchanged) ...
    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_BASE_IMAGE"; then
        # build base ...
    fi
    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_CLAUDE_IMAGE"; then
        # build claude ...
    fi
    # omp removed — lazy via ensure_omp_image
    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_HATAGO_IMAGE"; then
        # build hatago ...
    fi
}
```

2. Fix `ensure_images` to only gate on core images:
```bash
ensure_images() {
    if ! image_exists "$HARNESSED_CLAUDE_IMAGE" || ! image_exists "$HARNESSED_HATAGO_IMAGE"; then
        print_warning "harnessed images not found. Building (first run)…"
        build_images false
    fi
}
```

---

## Warnings

### WR-01: Unpinned Runtime Versions — Non-Reproducible Image Identity

**File:** `base/Dockerfile.harnessed-base:75-78`
**Issue:** `python@latest`, `bun`, `rust`, and `go` are installed with no version pin. Two
identical `harnessed build` runs on different days can produce different tool sets. The supply chain
scan result is not bound to a specific dependency set, so a scan today does not cover what ships
tomorrow. `node@24` and `pnpm@11` are correctly pinned; the others are not.

**Fix:** Pin each runtime to a specific version (or at minimum a minor):
```dockerfile
RUN mise use -g \
    node@24 \
    pnpm@11 \
    python@3.13 \
    bun@1 \
    rust@1.87 \
    go@1.24 \
    fd \
    ripgrep \
    npm:@openai/codex \
    npm:@google/gemini-cli && \
```

---

### WR-02: First `apt-get` Layer Leaks Package List Metadata

**File:** `base/Dockerfile.harnessed-base:12-25`
**Issue:** The first `RUN apt-get update && apt-get install -y ...` block does not clean up
`/var/lib/apt/lists/*`. The second RUN block (1Password, line 33) does `rm -rf /var/lib/apt/lists/*`,
but that cleanup only affects layer 2's overlay — it cannot remove data committed in layer 1.
Package list metadata (repository URLs, package names, versions) persists permanently in the image.
This leaks information and bloats the image.

**Fix:** Merge the cleanup into the same RUN that installs packages:
```dockerfile
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    unzip \
    ca-certificates \
    libssl-dev \
    zlib1g-dev \
    libffi-dev \
    vim \
    tree \
    gnupg \
    iptables \
    && rm -rf /var/lib/apt/lists/*
```

---

### WR-03: `CONTAINER_RUNTIME` Used Without Guaranteed Initialization

**File:** `lib/harnessed-common.sh:64`
**Issue:** `image_exists()` and all subsequent container commands use `"$CONTAINER_RUNTIME"` which
is only populated inside `detect_runtime()`. There is no default value, no export, and no guard in
the helper functions. A sourcing script that calls `image_exists`, `build_images`, or any lifecycle
helper before calling `detect_runtime` will execute `"" image inspect ...`, producing a confusing
"command not found" error rather than a clear diagnostic. The file has no top-level initialization
of `CONTAINER_RUNTIME`.

**Fix:** Initialize `CONTAINER_RUNTIME` at the top of the file so uninitialized use fails visibly,
and call `detect_runtime` eagerly at source time:
```bash
CONTAINER_RUNTIME=""  # set at top of file
# ... then call detect_runtime immediately after sourcing runtime.sh ...
detect_runtime  # ensure CONTAINER_RUNTIME is always set before helpers are available
```
Or alternatively, add a guard inside each helper:
```bash
image_exists() {
    [ -z "$CONTAINER_RUNTIME" ] && { print_error "detect_runtime not called"; return 1; }
    "$CONTAINER_RUNTIME" image inspect "$1" >/dev/null 2>&1
}
```

---

### WR-04: `agent.yaml` Manifests Are Not Consumed by Any Code

**File:** `agents/claude/agent.yaml:1-8`, `agents/omp/agent.yaml:1-8`
**Issue:** Neither file is referenced by any shell script, build function, or tool in the
repository. The `build_images` function hardcodes the Dockerfile paths directly (e.g.
`"$HARNESSED_DIR/base/Dockerfile.harnessed-claude"`). The agent manifests' `dockerfile` and
`image` fields have no readers. These manifests either represent an incomplete implementation
(the consuming code was never written) or are documentation that will silently drift from the
actual build paths as the codebase evolves.

**Fix:** Either (a) wire the assembler/build system to read `agents/<name>/agent.yaml` and drive
builds from these manifests (the intended architecture), or (b) remove the `dockerfile` and `image`
fields and mark the files clearly as documentation-only to prevent false trust.

---

### WR-05: `1password` Desktop App Unnecessarily Installed in Container

**File:** `base/Dockerfile.harnessed-base:32`
**Issue:** `apt-get install -y 1password 1password-cli` installs the full 1Password desktop GUI
application alongside the CLI. The comment says this is for `op-ssh-sign`, but:
1. The `1password` GUI package pulls in X11/dbus libraries, significantly increasing the image's
   attack surface in a headless container environment.
2. `allowAppAuth` (the design's preferred auth pattern per CLAUDE.md §14) works by mounting the
   host's 1Password agent socket — it does not require the app installed in the container.
3. The `op-ssh-sign` binary is the operative piece; packaging the full desktop app to get one
   binary is disproportionate.

**Fix:** Remove `1password` (the desktop package) and keep only `1password-cli`. If `op-ssh-sign`
is genuinely required, extract or symlink it separately rather than installing the entire GUI app:
```dockerfile
apt-get install -y 1password-cli && \
```

---

## Info

### IN-01: Unquoted Variable in `clean_instances`

**File:** `lib/harnessed-common.sh:364`
**Issue:** `"$CONTAINER_RUNTIME" rm $ids` — `$ids` is not quoted. While container IDs are
hex strings and unlikely to contain whitespace, this pattern is a shellcheck violation and
will misbehave if `$ids` is ever empty (it's already guarded by the empty check above, but
the guard depends on `[ -z "$ids" ]` not being bypassed by whitespace-only output).

**Fix:**
```bash
# shellcheck disable=SC2086  # intentional word-splitting for ID list
"$CONTAINER_RUNTIME" rm $ids
# OR pass as array if the runtime supports it:
read -ra id_array <<< "$ids"
"$CONTAINER_RUNTIME" rm "${id_array[@]}"
```

---

### IN-02: `wget` Installed but Unused

**File:** `base/Dockerfile.harnessed-base:15`
**Issue:** `wget` is in the base apt package list but all HTTP downloads in the Dockerfile and
related scripts use `curl`. `wget` adds to the image's binary footprint and is an additional
CVE surface for no benefit.

**Fix:** Remove `wget` from the apt package list. If a downstream layer or user script explicitly
needs it, install it there.

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
