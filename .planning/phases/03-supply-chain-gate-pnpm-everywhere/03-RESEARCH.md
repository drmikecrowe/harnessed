# Phase 3: Supply-Chain Gate + pnpm-Everywhere — Research

**Researched:** 2026-06-15
**Domain:** Build-time software supply-chain hardening — pnpm 11 managed install policy + a credential-free vulnerability scan gate (osv-scanner V2 + pip-audit) + recipe lint for raw `npm`/`npx`
**Confidence:** HIGH for external facts (pnpm 11, osv-scanner V2, pip-audit all re-verified against official docs/registries on 2026-06-15); HIGH for repo integration points (actual code read); MEDIUM for the exact placement of image-scanning vs. lockfile-scanning (an architecture decision the planner must lock — see Open Questions).

> Phase-level research. The milestone research is the source for external facts already gathered:
> `.planning/research/STACK.md`, `.planning/research/PITFALLS.md` (Pitfall 6/7/11), `.planning/research/ARCHITECTURE.md`.
> This file narrows to Phase 3 (BLD-01/02/03), **corrects one stale milestone-research claim** (pnpm 11 *removed*
> `onlyBuiltDependencies` — see State of the Art), and maps every finding to the actual repo code this phase edits.

<user_constraints>
## User Constraints

**No CONTEXT.md — design from REQUIREMENTS + CLAUDE.md constraints.** This phase is MVP / vertical-slice mode; the discuss-phase was skipped, so there are no locked user decisions to copy. The binding constraints below are lifted verbatim from `CLAUDE.md` (which the role treats with the same authority as locked CONTEXT.md decisions) and from `.planning/REQUIREMENTS.md` Out-of-Scope. The planner MUST honor these as if locked.

### Binding constraints (from CLAUDE.md → §7/§15/§16 of `docs/harnessed-design.md`)
- **Supply chain:** pnpm everywhere (no npm/npx); build-time scan gate fails on high-severity; credentials referenced from host, never baked/committed (§7).
- **Tech stack:** all logic in the containerized `harnessed-tools` Python image (+ pnpm + scanners); host deps stay at podman/docker only (§15). osv-scanner/pip-audit run **inside images**, never as a new host dependency.
- **Execution model:** `harnessed-tools` **emits files only** — it NEVER invokes podman/docker or mounts a daemon socket (§15, D-12). Anything that needs the daemon (image scanning) runs in the host `build_stack` flow or the host-native test path, exactly like `harnessed test`.
- **Security/secrets:** scanner secrets are env-only, never an image layer or repo file; token-gated scanners are opt-in (§16).
- **Testing:** integration-only; behavior asserted through the running build, not assembler unit tests (§18 / REQUIREMENTS Out-of-Scope: "Assembler unit tests").
- **Non-interactive:** `harnessed build` must stay reproducible/non-interactive (CI + nightly timer) — never prompt.

### Out-of-Scope for this phase (REQUIREMENTS — do NOT plan)
- **`npm`/`npx` for JS installs** — explicitly forbidden ("No release-age cooldown, lifecycle scripts run by default — weaker supply-chain posture").
- **Token-gated scanners (snyk / Socket.dev)** — these are **Phase 5** (SEC-02/03). This phase ships ONLY the credential-free baseline (osv-scanner + pip-audit). Emit at most a one-line "deferred to Phase 5" note where snyk would slot in; do not implement `harnessed auth`.
- **Nightly re-scan timer** (SEC-04) — Phase 5.
- **varlock / 1Password secrets** (SEC-01) — Phase 5.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **BLD-01** | All JS installs (global, per-recipe, hatago servers) use pnpm with managed supply-chain config (`minimumReleaseAge`, lifecycle default-deny, store integrity). | Standard Stack §pnpm 11; Architecture Pattern 1 (ship managed config + route mise through pnpm); Code Examples §1–§3. The config keys, defaults, and the global-install mechanism are all CITED from pnpm.io (2026-06-15). |
| **BLD-02** | `harnessed build` runs osv-scanner + pip-audit (credential-free) and fails on high-severity findings. | Standard Stack §osv-scanner/§pip-audit; Architecture Pattern 2 (where the gate hooks into `build_stack`/`harnessed-tools`); Code Examples §4–§6; Pitfall 3 (osv-scanner has NO native severity threshold — gate filters JSON by CVSS); Validation Architecture (fixture proving a high-sev finding aborts the build). |
| **BLD-03** | Recipe validation flags any raw `npm`/`npx` usage and points at the pnpm equivalent. | Architecture Pattern 3 (validation hook in `schema.py`/`assemble.py`); Code Examples §7; Pitfall 4. Detection targets: `recipe.yaml` deps/scripts + any vendored plugin `package.json` scripts + the ported `vendor-plugin` (which currently shells `npm install`). |
</phase_requirements>

## Summary

Phase 3 makes `harnessed build` *trustworthy*. Today the build pipeline (the emit-only `harnessed-tools` assembler + the host `build_stack` flow in `lib/harnessed-common.sh`) produces a profile and bakes the hatago image with **zero supply-chain checks**, and the base/hatago images install JS with `pnpm` but **without any managed policy** (`pnpm@latest`, no config, mise's `npm:` backend silently using npm). This phase closes three gaps in lockstep:

1. **BLD-01 — pnpm-everywhere with managed config.** Pin `pnpm@11` and ship one managed config (the global `~/.config/pnpm/config.yaml` so `pnpm add -g` honors it, plus a project `pnpm-workspace.yaml` for any vendored tree) into every image that runs pnpm (`harnessed-base`, `hatago`, and the `harnessed-tools` image once it vendors node deps). pnpm 11 already turns on the three controls BLD-01 names *by default* — `minimumReleaseAge: 1440`, lifecycle default-deny via `strictDepBuilds: true` + the `allowBuilds` allowlist, and `verifyStoreIntegrity: true` — so the work is to **pin the version, make the config explicit/auditable, route mise's global node installs through pnpm** (`npm.package_manager = "pnpm"`), and curate the `allowBuilds` allowlist for packages that genuinely need native postinstall.

2. **BLD-02 — credential-free scan gate.** Bake the static `osv-scanner` V2 Go binary and `pip-audit` into the image that runs the gate, and invoke them in the `harnessed build` flow **before** a profile is committed or the hatago image is finalized. The hard caveat: **osv-scanner `scan` has no "fail only on high" flag** — it exits `1` on *any* finding. The gate must therefore run `--format json`, parse each finding's CVSS/severity, and fail the build only when severity ≥ HIGH (so transitive lows don't red-line every build). pip-audit similarly has no severity threshold; treat its findings through the same severity filter where the advisory carries a score.

3. **BLD-03 — recipe validation.** Extend the existing `schema.py`/`assemble.py` validation to scan recipe manifests (and vendored `package.json` scripts) for raw `npm`/`npx` tokens and abort `harnessed build` with the pnpm equivalent (`npm install`→`pnpm install`, `npx X`→`pnpm dlx X` / `pnx X`).

**Primary recommendation:** Ship the managed pnpm config first (BLD-01) so every subsequent install is policy-governed, then add the scan gate as a dedicated `harnessed-tools scan` subcommand invoked by `build_stack` (lockfile/source/Python scanning is pure file I/O and is emit-compatible), with image scanning done host-side against a `podman save` archive (`osv-scanner scan image --archive`) the same way `harnessed test` drives host podman. BLD-03 is a small, pure-Python validation pass with the lowest risk — implement it inside the assembler's existing fail-fast validation.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| **BLD-01** managed pnpm config shipped + applied to all pnpm trees | `base/Dockerfile.harnessed-base` + `hatago` + `tools` images (build-time) | `lib/` (config file source of truth) | "pnpm everywhere" is an image-layer concern; config must be present wherever `pnpm add -g`/`pnpm install` runs |
| **BLD-01** route mise global node installs through pnpm | `base/Dockerfile.harnessed-base` (mise settings) | — | mise's `npm:` backend defaults to npm; flip to pnpm so `npm:opencode-ai` etc. honor policy |
| **BLD-02** lockfile/source/Python scan (osv-scanner+pip-audit) | `harnessed-tools` image (emit-compatible file I/O) | host `build_stack` (invokes it) | Scanning files needs no daemon → stays in the emit-only image; keeps host at podman-only |
| **BLD-02** built-image scan (OS + baked deps) | host `build_stack` (`podman save` → `osv-scanner scan image --archive`) | osv-scanner binary (in a throwaway container) | Image scan needs the built image; host already runs `podman build` — mirror the `harnessed test` host-native pattern, never DooD |
| **BLD-02** severity gate (CVSS ≥ HIGH → fail) | `harnessed-tools` Python (parse osv JSON) | — | osv-scanner has no native threshold; the gate decision is Python logic over `--format json` |
| **BLD-03** raw npm/npx recipe lint | `harnessed-tools` `schema.py`/`assemble.py` (pure Python, build-time) | — | Validation of committed manifests + vendored scripts; reuses the existing fail-fast path |

## Standard Stack

### Core (new or hardened in Phase 3)

| Tool | Version (verified 2026-06-15) | Purpose | Why standard |
|------|-------------------------------|---------|--------------|
| **pnpm** | **11.x** (11.0 released 2026-04-28; 11.3 current line). Floor: requires **Node.js 22+**. | The only JS package manager — global (`pnpm add -g`), per-recipe (`pnpm install`), hatago's baked servers. | Supply-chain policy is the whole point. v11 ships `minimumReleaseAge`/lifecycle-deny/store-integrity **on by default**. `pnpm dlx` / `pnx` replace `npx`. [CITED: pnpm.io/blog/releases/11.0] |
| **osv-scanner** | **v2.3.8** (2026-05-08). Static Go binary. | Credential-free vuln scan of lockfiles, source manifests, `node_modules`, Python, and container images, backed by osv.dev + deps.dev. | Official Google frontend to OSV.dev; no auth, no account, SLSA-3 released binary. V2 adds container scanning + transitive Python via deps.dev. [CITED: github.com/google/osv-scanner] |
| **pip-audit** | **2.10.1** (PyPA). | Credential-free audit of Python deps (`requirements.txt` / installed venv / `pyproject.toml` project). | PyPA-official; PyPI advisory DB + OSV. No token. Second half of the always-on baseline gate. [VERIFIED: PyPI `pip index versions pip-audit`; slopcheck OK] |

### Supporting (already in repo — reuse)

| Tool | Where | Reuse in Phase 3 |
|------|-------|------------------|
| mise-en-place | `base/Dockerfile.harnessed-base:55` | Pin `pnpm@11`; set `npm.package_manager = "pnpm"` so the `npm:` backend tools (`opencode-ai`, `@openai/codex`, `@google/gemini-cli`) route through pnpm (BLD-01). [CITED: mise.jdx.dev/dev-tools/backends/npm.html] |
| uv / `uvx` / `uv tool` | `base/Dockerfile.hatago:16-29` | Python side — `pip-audit` can run via `uvx pip-audit` or be installed in the tools image; no change to the uv pinning pattern. |
| ruamel.yaml | `tools/pyproject.toml` | Parse `recipe.yaml` for the BLD-03 lint; already a dependency. |
| jq | `tools/Dockerfile:17` | Shape osv-scanner `--format json` output for the severity gate (or do it in Python). |
| rich | `tools/pyproject.toml`, `tools/harnessed/report.py` | Render a supply-chain summary table the same way the capability report renders (D-11 precedent). |

### Alternatives considered

| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| osv-scanner + pip-audit | Trivy, Grype | Excellent for OS-layer CVEs; osv-scanner V2 already does container + app deps, narrowing the gap. Add Trivy later only if OS-layer depth is wanted. Out of scope this phase. |
| pnpm 11 | npm + overrides, Yarn Berry | npm forfeits `minimumReleaseAge` + lifecycle default-deny — the core guard. Explicitly forbidden by REQUIREMENTS. |
| `pnpm dlx` | `npx`, `pnpm exec` | `npx` is forbidden (pull-and-run latest). `pnpm dlx`/`pnx` is the cooldown-respecting equivalent. |
| Severity gate in Python over JSON | osv-scanner native threshold | osv-scanner `scan` has **no** severity-threshold flag (only the experimental `fix` command has `--min-severity`); JSON-parse is the only option. See Pitfall 3. |

**Installation (inside images — never the host):**
```dockerfile
# osv-scanner: prebuilt static release binary (V2), pinned (no daemon needed for source/lockfile scan)
ARG OSV_SCANNER_VERSION=2.3.8
RUN curl -fsSL -o /usr/local/bin/osv-scanner \
      "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64" \
    && chmod +x /usr/local/bin/osv-scanner
# pip-audit: pinned via the tools image's Python toolchain
RUN pip install --no-cache-dir "pip-audit==2.10.1"
```

**Version verification done this session:** `pip index versions pip-audit` → 2.10.1 (latest). osv-scanner releases page → v2.3.8 (2026-05-08). pnpm.io/blog/releases/11.0 + pnpm.io/settings (docs version 11.x) read live.

## Package Legitimacy Audit

> slopcheck (v0.6.1) installed and run this session.

| Package | Registry | Age | Source repo | slopcheck | Disposition |
|---------|----------|-----|-------------|-----------|-------------|
| `pip-audit` | PyPI | 2.10.1, mature (PyPA project, 5+ yrs) | github.com/pypa/pip-audit | **[OK]** | Approved (BLD-02) |
| `osv-scanner` | GitHub releases (Go binary, **not** a registry pkg) | v2.3.8, 2026-05-08; 10.5k★ | github.com/google/osv-scanner | n/a (release-binary; verified GitHub release tag + SLSA-3 provenance) | Approved (BLD-02) — pin the version + verify the release checksum/signature at build |
| `pnpm` 11 | distributed via mise (`pnpm@11`) | 11.0 2026-04-28 | github.com/pnpm/pnpm | n/a (toolchain via mise, already in repo) | Approved (BLD-01) |
| `@himorishige/hatago-mcp-hub` | npm (already pinned `@0.0.16`, Phase 2) | unchanged | github.com/himorishige/hatago-mcp-hub | (not re-audited — pre-existing, pinned) | No change this phase |

**Packages removed due to slopcheck [SLOP]:** none.
**Packages flagged [SUS]:** none.
**Note:** `osv-scanner` is a Go release binary, not an npm/PyPI package — its legitimacy rests on the signed GitHub release + SLSA-3 attestation, not slopcheck. The plan SHOULD verify the downloaded binary's checksum against the release `SHA256SUMS` before `chmod +x`.

## Architecture Patterns

### System data flow (where each requirement lands in the existing build pipeline)

```
harnessed build <stack>                       (host: harnessed → lib/harnessed-common.sh::build_stack)
   │
   ├─[BLD-03] assemble step (emit-only tools image: harnessed-tools assemble)
   │      load_stack_with_recipes → VALIDATE recipes  ← raw npm/npx lint aborts here (fail-fast)
   │      fan skills/commands · merge hatago.config.json · emit profile
   │
   ├─[BLD-02a] scan step (emit-compatible: harnessed-tools scan <build-dir>)
   │      osv-scanner scan source -r <build-dir/vendored-trees>   --format json
   │      pip-audit -r <recipe requirements.txt> / venv          (JSON)
   │      → Python severity gate: any finding CVSS ≥ HIGH ⇒ exit non-zero  ⇒ build aborts
   │      (BEFORE the profile is treated as committed)
   │
   ├─ host podman build  (base/Dockerfile.hatago, etc.)  ← BLD-01 config active in image layers
   │
   └─[BLD-02b] image scan (host, like `harnessed test`):
          podman save <img> -o img.tar  →  osv-scanner scan image --archive img.tar --format json
          → same severity gate ⇒ non-zero ⇒ build fails
```

### Pattern 1 — Ship managed pnpm config + route everything through pnpm (BLD-01)

**What:** pnpm 11 reads policy from `pnpm-workspace.yaml` (project) or the **global** `~/.config/pnpm/config.yaml`; `.npmrc` is auth/registry-only now. For **global installs** (`pnpm add -g`, used by `base/Dockerfile.hatago:25`) the policy must live in the global config file. Ship one canonical config from `lib/` and `COPY` it into each image's `~/.config/pnpm/config.yaml`.

**When:** any image that runs pnpm — `harnessed-base`, `hatago`, and `harnessed-tools` once it vendors node deps.

**Config (the three BLD-01 controls; pnpm 11 defaults shown — make them explicit & audited):**
```yaml
# lib/pnpm/config.yaml  →  COPY to /home/harnessed/.config/pnpm/config.yaml
# (BLD-01: minimumReleaseAge + lifecycle default-deny + store integrity)
minimumReleaseAge: 1440          # minutes (1 day). v11 default; make explicit. (escape hatch: minimumReleaseAgeExclude)
minimumReleaseAgeStrict: true    # fail rather than silently fall back to an older mature version (default true when set explicitly)
blockExoticSubdeps: true         # block git/tarball/non-registry subdeps (v11 default)
verifyStoreIntegrity: true       # content-addressed store integrity check on link (v11 default)
strictDepBuilds: true            # NON-ZERO EXIT if any dep has an unreviewed build/postinstall script (v11 default) = lifecycle default-deny
allowBuilds:                     # the curated allowlist — packages permitted to run native build scripts
  esbuild: true
  # better-sqlite3: true         # add as real native-build deps appear; a denied build prints "add to allowBuilds"
```
- **mise routing:** in `base/Dockerfile.harnessed-base`, set `mise settings set npm.package_manager pnpm` (or `MISE_NPM_PACKAGE_MANAGER=pnpm`) and pin `pnpm@11` (currently `pnpm@latest`). Then `npm:opencode-ai`, `npm:@openai/codex`, `npm:@google/gemini-cli` install via pnpm and honor the policy. [CITED: mise.jdx.dev/dev-tools/backends/npm.html]
- **`pnpm setup`:** v11 isolates globals and moves binaries to `$PNPM_HOME/bin`; the hatago Dockerfile already pre-creates `$PNPM_HOME/bin` on PATH (`base/Dockerfile.hatago:22-23`) — keep that, and confirm it still resolves under v11's isolated-global layout.

**Anti-pattern:** putting policy only in `.npmrc` (ignored for non-auth settings in v11) or only in a project `pnpm-workspace.yaml` (a global `pnpm add -g` won't see it).

### Pattern 2 — Scan gate split: emit-compatible source scan + host image scan (BLD-02)

**What:** Two scan surfaces, two homes, one severity gate.
- **Source/lockfile/Python scan** runs *inside* the `harnessed-tools` image (a new `scan` subcommand or a step in `assemble`) — pure file I/O over the mounted build dir, so it stays emit-compatible (reads files, never drives podman). Scans: any vendored plugin's `pnpm-lock.yaml`/`package.json`, recipe `requirements.txt`/`pyproject.toml`, and a synthesized manifest for manifest-less globals if needed.
- **Image scan** runs *host-side* in `build_stack` after `podman build`: `podman save <img> -o <tar>` (host podman, allowed) then `osv-scanner scan image --archive <tar>` inside a throwaway `harnessed-tools` container. This mirrors how `harnessed test` runs host-native and drives host podman without DooD.

**Severity gate (the crux):** osv-scanner `scan` exits `1` on *any* finding (exit codes: `0` clean, `1` vuln found, `127` general error, `128` no packages). It has **no** severity threshold. So:
1. Run with `--format json`.
2. Parse each `results[].packages[].vulnerabilities[]`; read the OSV `severity[].score` (CVSS vector → numeric) or `database_specific.severity`.
3. Fail the build only if max severity ≥ HIGH (CVSS ≥ 7.0). Otherwise warn (render lows/mediums in the rich report) and pass.
This keeps "fails on high-severity" literally true without red-lining on every transitive low. [CITED: google.github.io/osv-scanner/output #Return Codes]

**pip-audit:** `pip-audit -r requirements.txt --format json` (or audit the uv venv for a `pyproject.toml` recipe); exits non-zero on any known vuln, also has no severity flag — run it through the same Python severity filter (PyPI/OSV advisories carry CVSS where available; findings without a score are surfaced as warnings unless the plan elects fail-closed). `--vulnerability-service osv` aligns it with osv-scanner's DB.

**Anti-pattern:** running osv-scanner on the host as a new prerequisite (breaks "podman is the only host dependency"); or trusting raw exit code 1 as "high severity" (it isn't — it's *any* finding).

### Pattern 3 — Raw npm/npx recipe lint (BLD-03)

**What:** A pure-Python validation pass in the assembler's existing fail-fast path. Detection targets, in order of certainty:
- `recipe.yaml` — any `command: npm`/`command: npx` in `mcp.servers`, any `scripts`/`deps` string containing `npm `/`npx ` (the schema parses unknown fields forward — read `Recipe.raw`).
- A vendored plugin's `package.json` `scripts.*` containing `npm`/`npx`.
- The ported `vendor-plugin` itself (PROJECT.md notes it "currently shells `npm install`") — flag/replace when it lands.

**Where it hooks:** `tools/harnessed/schema.py` already raises `SchemaError` on bad manifests and `tools/harnessed/assemble.py` already does fail-fast collision checks (`CollisionError`). Add a `validate_no_raw_npm(recipe)` that raises a new `RecipeLintError` (or reuse `SchemaError`) called from `load_recipe`/`assemble`, before any file is emitted. The error message MUST name the offending token and its pnpm equivalent:
- `npm install` → `pnpm install`
- `npm ci` → `pnpm ci` (v11 native)
- `npx <pkg>` → `pnpm dlx <pkg>` (or `pnx <pkg>`)
- `npm run <s>` → `pnpm run <s>`

**Anti-pattern:** a regex so loose it flags the substring "npm" inside words (e.g. a package named `npmlog`). Match word-boundaried command tokens (`\bnpx\b`, `\bnpm\b` at a command position), not arbitrary substrings.

### Recommended file touch-list (role → analog)

| File | Change | Why |
|------|--------|-----|
| `lib/pnpm/config.yaml` (new) | Managed pnpm policy (Pattern 1) | Single source of truth `COPY`'d into images (BLD-01) |
| `base/Dockerfile.harnessed-base` | Pin `pnpm@11`; `npm.package_manager=pnpm`; COPY pnpm config | Route global node installs through policy (BLD-01) |
| `base/Dockerfile.hatago` | COPY pnpm config; confirm `pnpm add -g` honors it under v11 isolated globals | hatago's baked server install governed (BLD-01) |
| `tools/Dockerfile` | Add osv-scanner binary + `pip-audit`; COPY pnpm config | Scanners live in the image (BLD-02) |
| `tools/pyproject.toml` | Add `pip-audit==2.10.1` dep (or `uvx`-run) | BLD-02 |
| `tools/harnessed/scan.py` (new) | osv-scanner/pip-audit invocation + CVSS severity gate | BLD-02 core logic |
| `tools/harnessed/schema.py` / `assemble.py` | `validate_no_raw_npm()` in the fail-fast path | BLD-03 |
| `tools/harnessed/cli.py` | New `scan` subcommand (mirror the `assemble`/`test` arg-parsing) | BLD-02 entrypoint |
| `lib/harnessed-common.sh::build_stack` | Invoke the scan step (source scan in tools image; image scan via `podman save` + `osv-scanner scan image --archive`) before declaring success | BLD-02 wiring |
| `Dockerfile` (legacy `container` image) | Pin `pnpm@11` + same mise routing **only if** the transparent/legacy path must share the policy | Open Question — see below |

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Vulnerability DB lookups | A custom advisory fetcher / CVE matcher | **osv-scanner** (osv.dev) + **pip-audit** (PyPI/OSV) | Matching package versions to advisories is a deep, constantly-changing problem; OSV is the authoritative open DB. (BLD-02) |
| Release-age quarantine | A custom "is this version too new?" check | pnpm **`minimumReleaseAge`** | pnpm computes this from registry `time` metadata across the full transitive graph. (BLD-01) |
| Lifecycle-script gating | A custom postinstall blocker | pnpm **`strictDepBuilds` + `allowBuilds`** | pnpm already default-denies build scripts and maintains the allowlist. (BLD-01) |
| Lockfile parsing | A YAML/JSON lockfile reader per ecosystem | osv-scanner's `scan source -r` (19+ lockfile types) | Lockfile formats are many and versioned; osv-scanner/scalibr already parse them. (BLD-02) |
| Store integrity | A custom content hash verifier | pnpm **`verifyStoreIntegrity`** | Built into the content-addressed store. (BLD-01) |
| Severity scoring | A custom CVSS calculator | Read the OSV `severity[].score` field osv-scanner already surfaces | Only the *threshold decision* is yours; never recompute CVSS. (BLD-02) |

**Key insight:** Phase 3 is almost entirely *configuration + invocation* of mature tools. The only genuinely custom code is (a) the CVSS-threshold decision over osv-scanner's JSON, and (b) the raw-npm/npx lint — both small, both pure functions, both testable through the build.

## Common Pitfalls

### Pitfall 1: pnpm 11 vs 10.19 default drift — config silently inert
**What goes wrong:** Authoring the config as if on pnpm 10.19, where `minimumReleaseAge`/`onlyBuiltDependencies` exist but are **off by default**, and/or using the removed `onlyBuiltDependencies` key — which pnpm 11 ignores (it was deleted, not deprecated). The guard appears configured but does nothing.
**Why:** v11 flipped defaults on AND removed the legacy build-dependency keys in favor of `allowBuilds`. `.npmrc` no longer carries these settings at all.
**How to avoid:** Pin `pnpm@11` (not `@latest`). Use `allowBuilds` (map), never `onlyBuiltDependencies`. Put policy in `pnpm-workspace.yaml`/global `config.yaml`, never `.npmrc`. Verify with `pnpm config list` inside the built image.
**Warning signs:** `pnpm-lock.yaml` resolving brand-new versions instantly; postinstall scripts running with no allowlist entry.

### Pitfall 2: `minimumReleaseAge` breaks first-party / just-published deps → red build
**What goes wrong:** A legitimately needed package published <24h ago (a hatago point release, a freshly cut recipe dep) is quarantined; with `minimumReleaseAgeStrict: true` the install *fails* rather than falling back.
**Why:** The cooldown applies to all deps including transitive; strict mode (default when you set the age explicitly) turns "no mature version in range" into a hard error.
**How to avoid:** Use `minimumReleaseAgeExclude` (supports names, scoped globs `@myorg/*`, and pinned versions `pkg@1.2.3`) as the documented escape hatch. Document the window as a deliberate, managed default (1440 = community sweet spot), not per-user guesswork. `pnpm audit --fix` auto-adds patched versions to the exclude list.
**Warning signs:** "no version satisfies minimumReleaseAge" on a dep you just published.

### Pitfall 3: Treating osv-scanner exit code 1 as "high severity"
**What goes wrong:** Wiring `osv-scanner ...; if [ $? -ne 0 ]; then fail` makes the build fail on **any** finding (a transitive low), not just high — over-blocking and training operators to ignore the gate; OR conversely assuming a non-zero means "high" and missing that exit `1` covers all severities.
**Why:** osv-scanner `scan` has no severity threshold; `0`=clean, `1`=any finding. The only `--min-severity` flag lives in the *experimental* `fix` command, not `scan`.
**How to avoid:** Always `--format json`; parse `severity[].score`; apply the HIGH (CVSS ≥ 7.0) threshold in Python. Reserve exit-code-only logic for the binary "did it run."
**Warning signs:** Every build red on low-severity transitive deps; or a high-sev dep passing because the JSON wasn't parsed.

### Pitfall 4: Lifecycle default-deny blocks legit native builds (esbuild/sharp/better-sqlite3)
**What goes wrong:** With `strictDepBuilds: true` and no `allowBuilds` entry, a package that *must* run a native postinstall (esbuild, sharp, better-sqlite3) fails to build, with an opaque "ignored build scripts" message.
**Why:** Default-deny is the point — but the allowlist must be curated.
**How to avoid:** Maintain `allowBuilds: { esbuild: true, ... }`; pnpm auto-appends unreviewed builders to `pnpm-workspace.yaml` with a placeholder so you flip them to `true`/`false` deliberately. A denied build should surface "add to allowBuilds", not a stack trace.
**Warning signs:** Missing compiled `.node` binaries at runtime; "this package has build scripts that were ignored."

### Pitfall 5: mise's npm backend still using npm → policy bypassed
**What goes wrong:** `base/Dockerfile.harnessed-base` installs `npm:opencode-ai` etc.; without `npm.package_manager = "pnpm"`, mise uses npm — no `minimumReleaseAge`, no lifecycle deny — silently defeating BLD-01 for exactly the global tools.
**Why:** mise's npm backend defaults to npm.
**How to avoid:** Set `npm.package_manager = "pnpm"` (or env `MISE_NPM_PACKAGE_MANAGER=pnpm`) in the base image before `mise install`. Verify global installs landed via pnpm (`pnpm list -g`).
**Warning signs:** npm globals in `~`; `pnpm list -g` empty though tools are installed.

### Pitfall 6: Non-interactive build broken by a scanner prompt / network need
**What goes wrong:** A scanner prompts or hangs (snyk asking for a token, osv-scanner stalling on no network), breaking CI/the nightly timer.
**Why:** Build must be reproducible/non-interactive. The egress firewall (applied to instances) and air-gapped CI can block osv.dev/deps.dev network calls.
**How to avoid:** Ship ONLY credential-free scanners this phase (snyk/Socket.dev are Phase 5 — emit a one-line deferral, never a prompt). For determinism, consider `osv-scanner --offline --download-offline-databases` (pre-seed the OSV DB at image-build time) so the gate runs without network. pip-audit similarly can hit network — note the dependency.
**Warning signs:** Build hangs awaiting input or network; a token appears in build logs.

### Pitfall 7: osv-scanner finds nothing because there's no lockfile (false-negative on globals)
**What goes wrong:** `pnpm add -g hatago` produces an isolated global dir with its own lockfile under `{pnpmHomeDir}/global/v11/{hash}/`, but a naive `scan source -r <repo>` won't see it; manifest-less globals scan as "0 packages" (exit 128) and pass vacuously.
**Why:** v11 isolates globals into hashed dirs; the scan must be pointed at them (or at the built image).
**How to avoid:** Image scanning (`scan image --archive`) is the reliable catch for baked globals — it inspects the actual installed files/OS packages. For source scanning, point osv-scanner at the global virtual store path or synthesize a manifest from `pnpm list -g --json`. Treat exit `128` (no packages found) as a *warning to investigate*, not a pass.
**Warning signs:** Scan reports 0 packages though the image clearly installed hatago/uvx tools.

## Code Examples

### §1 — Managed pnpm global config (BLD-01)
```yaml
# lib/pnpm/config.yaml  (COPY → /home/harnessed/.config/pnpm/config.yaml in every pnpm image)
minimumReleaseAge: 1440
minimumReleaseAgeStrict: true
blockExoticSubdeps: true
verifyStoreIntegrity: true
strictDepBuilds: true
allowBuilds:
  esbuild: true
```

### §2 — Base image: pin pnpm 11 + route mise through pnpm (BLD-01)
```dockerfile
# base/Dockerfile.harnessed-base (replace pnpm@latest; add the mise setting BEFORE mise install)
RUN mise settings set experimental true && \
    mise settings set npm.package_manager pnpm && \
    mise use -g node@22 pnpm@11 python@latest fd ripgrep \
        npm:opencode-ai npm:@openai/codex npm:@google/gemini-cli && \
    mise install
COPY lib/pnpm/config.yaml /home/harnessed/.config/pnpm/config.yaml
```

### §3 — hatago image already does `pnpm add -g` — just ensure config is present (BLD-01)
```dockerfile
# base/Dockerfile.hatago (config COPY makes the existing `pnpm add -g` honor policy)
COPY lib/pnpm/config.yaml /home/harnessed/.config/pnpm/config.yaml
# existing line stays, now policy-governed:
RUN mkdir -p "$PNPM_HOME/bin" && pnpm add -g "@himorishige/hatago-mcp-hub@${HATAGO_VERSION}"
```

### §4 — osv-scanner source scan + JSON (BLD-02)
```bash
# Exit 0 = clean, 1 = any finding, 127 = error, 128 = no packages. Severity gate is done in Python.
osv-scanner scan source -r --format json "$BUILD_DIR" > osv.json || true   # don't let exit 1 abort before we gate
```

### §5 — Python severity gate over osv-scanner JSON (BLD-02 — the custom bit)
```python
# tools/harnessed/scan.py
import json, subprocess

HIGH = 7.0  # CVSS

def _max_cvss(vuln: dict) -> float:
    best = 0.0
    for sev in vuln.get("severity", []):
        # OSV stores CVSS_V3 vector strings; osv-scanner also surfaces a numeric score.
        score = sev.get("score")
        if isinstance(score, (int, float)):
            best = max(best, float(score))
    return best

def gate(osv_json: dict) -> list[str]:
    """Return high-severity finding ids; empty list ⇒ pass."""
    highs = []
    for res in osv_json.get("results", []):
        for pkg in res.get("packages", []):
            for v in pkg.get("vulnerabilities", []):
                if _max_cvss(v) >= HIGH:
                    highs.append(v.get("id", "?"))
    return highs

def run(build_dir: str) -> int:
    proc = subprocess.run(
        ["osv-scanner", "scan", "source", "-r", "--format", "json", build_dir],
        capture_output=True, text=True,
    )
    if proc.returncode == 128:            # no packages — investigate, don't pass blindly
        return 0
    data = json.loads(proc.stdout or "{}")
    highs = gate(data)
    if highs:
        raise SystemExit(f"supply-chain gate: {len(highs)} HIGH+ findings: {', '.join(highs)}")
    return 0
```

### §6 — Host-side image scan in `build_stack` (BLD-02b)
```bash
# lib/harnessed-common.sh::build_stack — after the host `podman build` of the hatago image.
# Image scan needs the built image; do it host-side (like `harnessed test`), never DooD.
img_tar="$(mktemp --suffix=.tar)"
"$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"
"$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro "$HARNESSED_TOOLS_IMAGE" \
    scan-image "$img_tar"            # tools entrypoint runs: osv-scanner scan image --archive <tar> --format json + gate
rc=$?; rm -f "$img_tar"; [ "$rc" -eq 0 ] || { print_error "supply-chain gate failed"; return 1; }
```

### §7 — Raw npm/npx recipe lint (BLD-03)
```python
# tools/harnessed/schema.py (called from load_recipe / assemble, fail-fast before emit)
import re
_NPM = re.compile(r"\bnpx\b|\bnpm\s+(install|ci|run|exec|i)\b")
_FIX = {"npx": "pnpm dlx", "npm install": "pnpm install", "npm ci": "pnpm ci",
        "npm run": "pnpm run", "npm exec": "pnpm exec", "npm i": "pnpm install"}

def validate_no_raw_npm(recipe: "Recipe") -> None:
    hay = []
    for s in recipe.servers:
        if s.command in ("npm", "npx"):
            raise SchemaError(f"recipe '{recipe.name}': MCP server '{s.name}' uses raw '{s.command}'. "
                              f"Use 'pnpm dlx' (e.g. command: pnpm, args: [dlx, <pkg>]).")
        hay += [s.command or ""] + s.args
    blob = " ".join(hay) + " " + json_dumps_recipe_scripts(recipe.raw)
    if _NPM.search(blob):
        raise SchemaError(f"recipe '{recipe.name}': raw npm/npx detected. Replace per: {_FIX}")
```

## State of the Art

| Old (milestone STACK.md, 2026-06-14) | Current (verified 2026-06-15) | Impact |
|--------------------------------------|-------------------------------|--------|
| "`onlyBuiltDependencies` honored as legacy; prefer `allowBuilds`" | **`onlyBuiltDependencies`, `onlyBuiltDependenciesFile`, `neverBuiltDependencies`, `ignoredBuiltDependencies`, `ignoreDepScripts` were REMOVED in pnpm 11.** Only `allowBuilds` (name→bool map) works. | The plan MUST use `allowBuilds`; the legacy key is silently ignored. [CITED: pnpm.io/blog/releases/11.0 §"allowBuilds replaces the old build settings"] |
| "policy in `pnpm-workspace.yaml` (not `.npmrc`)" | Confirmed + extended: **`.npmrc` is auth/registry only** in v11; non-auth settings live in `pnpm-workspace.yaml` or the new global `~/.config/pnpm/config.yaml`. | Global installs need the global `config.yaml`. |
| (not noted) | **pnpm 11 isolates global installs** — each `pnpm add -g` gets its own dir+lockfile under `{pnpmHomeDir}/global/v11/{hash}/`; binaries in `$PNPM_HOME/bin`; `pnpm setup` required. | Affects how the gate finds global deps (Pitfall 7) and PATH. |
| "osv-scanner `--min-severity` to filter; fails on high" | `--min-severity` is **only on the experimental `fix` command**, NOT `scan`. `scan` exits 1 on *any* finding. | The HIGH threshold is Python logic over JSON, not a flag (Pitfall 3). |
| `lifecycle default-deny` (mechanism unnamed) | Implemented as **`strictDepBuilds: true`** (default v11) + `allowBuilds` allowlist. | Name the actual keys. |

**Deprecated/avoid:** `npm`/`npx` (forbidden), `onlyBuiltDependencies` family (removed), `.npmrc` for pnpm policy (auth-only now), osv-scanner exit-code-as-severity (wrong).

## Environment Availability

| Dependency | Required by | Available (host) | In-image plan | Fallback |
|------------|-------------|------------------|---------------|----------|
| podman/docker | build + image scan | ✓ (only host dep) | — | — |
| osv-scanner V2 | BLD-02 | not required on host | bake static binary into `harnessed-tools` | — |
| pip-audit | BLD-02 | not required on host | `pip install pip-audit==2.10.1` in tools image (or `uvx`) | — |
| pnpm 11 | BLD-01 | not required on host | via mise in base/hatago/tools images | — |
| osv.dev / deps.dev network | osv-scanner online mode | host has network at build | offline DB (`--download-offline-databases`) for determinism | offline DB pre-seeded at image build |

**Missing with no fallback:** none — every tool lives in an image; host stays podman-only.
**Network note:** osv-scanner/pip-audit query osv.dev/PyPI by default. If the build env is air-gapped or firewalled, pre-seed osv-scanner's offline DB at image-build time and pin pip-audit's DB; otherwise build needs egress to those hosts (NOT the instance egress firewall, which governs *runtime* instances, not the host build).

## Validation Architecture

> `nyquist_validation` not disabled → included. Per REQUIREMENTS, **no assembler unit tests** — behavior is asserted through the build. Phase 3's success criteria are themselves the tests.

### Test approach (integration, build as oracle)
| Req | Behavior to prove | Test type | How |
|-----|-------------------|-----------|-----|
| BLD-02 | `harnessed build` **fails** on a high-severity vuln | integration fixture | Add a throwaway fixture recipe/build-context pinning a dependency with a known HIGH OSV advisory (e.g. an old `requirements.txt` entry); run `harnessed build <fixture>`; assert non-zero exit + the finding id in output. Then assert a clean stack still builds green. |
| BLD-02 | Low/medium findings do **not** red-line | integration fixture | A fixture with only a known LOW advisory builds green (proves the severity gate, not raw exit 1). |
| BLD-01 | All JS installs go through pnpm with policy active | introspection | In the built image: `pnpm config list` shows `minimumReleaseAge=1440` etc.; `pnpm list -g` (not npm) lists the globals; `npm ls -g` is empty/absent. |
| BLD-01 | Lifecycle default-deny works | introspection | A fixture node dep with a postinstall NOT in `allowBuilds` is blocked (build script not run); adding it to `allowBuilds` lets it build. |
| BLD-03 | Raw npm/npx is flagged with the pnpm equivalent | integration | A fixture recipe with `command: npx` (or `npm install` in a script) makes `harnessed build` abort with the `pnpm dlx`/`pnpm install` message; the clean `time` recipe still passes. |

### Quick run
- `harnessed build <clean-stack>` → green (regression).
- `harnessed build <vuln-fixture>` → red with high-sev id.
- `harnessed build <npm-fixture>` → red with the lint message.

### Wave 0 gaps
- [ ] A `recipes/<fixture>` (or test build-context) with a pinned high-severity dep — needed to prove BLD-02. Pick a dependency+version with a *stable, well-known* HIGH OSV id so the test isn't flaky as advisories evolve; or pin osv-scanner's offline DB snapshot for determinism.
- [ ] A node fixture with a postinstall script to prove `allowBuilds` deny (BLD-01).
- [ ] A `recipes/<fixture>` using `npx` to prove BLD-03.

## Security Domain

> `security_enforcement: true`, ASVS L1, block-on: high. This phase *is* a security control, so the security lens is central.

### Applicable ASVS categories
| ASVS Category | Applies | Standard control |
|---------------|---------|------------------|
| V1 Encoding/Sanitization (input validation) | yes | BLD-03 recipe lint = input validation on authored manifests (word-boundaried token match, not loose substring). |
| V10 Malicious Code / Supply Chain | **yes (core)** | pnpm `minimumReleaseAge` (release-age quarantine), `strictDepBuilds`+`allowBuilds` (lifecycle default-deny), `verifyStoreIntegrity` (store integrity), osv-scanner+pip-audit (known-CVE gate). |
| V14 Configuration | yes | Managed pnpm config shipped from `lib/`, version-pinned scanners + pnpm@11, reproducible/non-interactive build. |
| V6 Cryptography / integrity | yes | Verify osv-scanner release-binary checksum/signature before install; pnpm content-addressed store integrity. |
| V2/V3/V4 (auth/session/access) | no | No auth surface added this phase (scanner tokens are Phase 5). |

### Threat patterns for this stack
| Pattern | STRIDE | Mitigation (this phase) |
|---------|--------|--------------------------|
| Compromised npm release installed instantly | Tampering / Elevation | `minimumReleaseAge: 1440` quarantine; `minimumReleaseAgeStrict` fail-closed |
| Malicious lifecycle/postinstall script | Elevation of Privilege | `strictDepBuilds: true` default-deny + curated `allowBuilds` |
| Known-CVE dep baked into an image | Tampering | osv-scanner image scan + pip-audit; HIGH gate aborts build |
| Slopsquatted / exotic-source subdep | Tampering | `blockExoticSubdeps: true`; BLD-03 lint; Package Legitimacy Audit |
| Store tampering between install runs | Tampering | `verifyStoreIntegrity: true` |
| Secret leaked into image/profile while wiring scanners | Information Disclosure | Scanners are credential-free this phase → **no secret to leak**; Phase 5 adds token handling env-only (Pitfall 7 of milestone PITFALLS) |
| Supply-chain tool itself tampered | Tampering | Pin + checksum-verify the osv-scanner release binary; pin pip-audit + pnpm versions |

## Project Constraints (from CLAUDE.md)

The planner MUST verify compliance with these (authority ≡ locked decisions):
1. **pnpm everywhere, no npm/npx** — every JS install (global/recipe/hatago) via pnpm; `npx`→`pnpm dlx`. Recipe validation enforces (BLD-03). [§7]
2. **Build-time scan gate fails on high-severity** — osv-scanner + pip-audit credential-free baseline (BLD-02). [§7]
3. **Credentials referenced from host, never baked/committed** — N/A this phase (credential-free scanners); do not introduce any token. [§7/§16]
4. **Host deps = podman/docker only** — scanners/pnpm live in images; nothing new on the host. Image scanning runs host-native against a `podman save` archive, not as a host tool install. [§15]
5. **`harnessed-tools` emits files only** — never drives podman/no daemon socket. Source/lockfile scanning is file I/O (OK in the tools image); image scanning is host-driven (`build_stack`), mirroring `harnessed test`. [§15, D-12]
6. **Non-interactive / reproducible build** — no prompts; pin every version; prefer offline OSV DB for determinism. [§7]
7. **Integration-only testing, no assembler unit tests** — prove BLD-01/02/03 through `harnessed build` on fixtures. [§18]
8. **Docs land with the feature** — Phase 3 deliverable includes the supply-chain/pnpm section of the recipe-authoring guide (the pnpm rule + the scan gate), per the "a feature isn't done until its docs exist" rule. [§17]
9. **Bash launchers under `set -euo pipefail`; fallible probes use `|| true`** — the new scan steps in `build_stack` must capture scanner exit codes safely (P1 blocker `a963a69`).

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | The cleanest emit-compatible home for source/lockfile scanning is a `harnessed-tools scan` subcommand; image scanning is host-driven in `build_stack` via `podman save`+`scan image --archive`. | Arch Pattern 2 | If the planner prefers all scanning host-side (or all in-image), wiring differs; both honor "podman-only host" + "emit-only tools" but the split is a design choice, not a verified fact. |
| A2 | HIGH = CVSS ≥ 7.0 is the right threshold for "high-severity." | Pattern 2 / Code §5 | If the project wants CRITICAL-only or a different cutoff, the constant changes; trivial to adjust. |
| A3 | osv-scanner's JSON `severity[].score` is numerically parseable (CVSS vector → score) per finding. | Code §5 | Some OSV entries carry only a CVSS *vector string*, not a number; the gate may need a vector→score parse (osv-scanner's table output already computes the number, so the data is present). Verify against a real finding during execution. |
| A4 | `pnpm add -g` reads policy from the global `~/.config/pnpm/config.yaml` under the harnessed user's home. | Pattern 1 | If XDG/`PNPM_HOME` layout differs in-image, the config path differs; verify with `pnpm config list` in the built image. |
| A5 | Image scanning at build is in scope for BLD-02 (vs. lockfile/Python only). | Arch / Validation | BLD-02 says "+ images" via §7 but SEC-04 (nightly image re-scan) is Phase 5; the planner may scope build-time image scan as optional and ship lockfile+Python+source as the MVP gate. State the chosen scope. |
| A6 | The legacy `Dockerfile` (`container`) need not carry the pnpm policy unless the transparent/legacy path must share it. | Touch-list / Open Q | transparent mode mounts host config and doesn't go through the supply-chain machinery (§3 degenerate case); but its image still installs JS globals via mise. Decide whether policy applies there. |

## Open Questions

1. **Scan-gate scope: images at build, or lockfile/Python only?**
   - Known: BLD-02 + §7 mention images; SEC-04 (nightly image re-scan) is explicitly Phase 5.
   - Unclear: whether build-time *image* scanning is MVP or deferred with the nightly timer.
   - Recommendation: ship lockfile/source + Python scanning as the non-negotiable gate; include build-time image scan if cheap (the `podman save` path is small), else defer the *image* surface to Phase 5's nightly timer and document it.

2. **Does the legacy `Dockerfile` (`container`) get the pnpm policy?**
   - Known: transparent mode is the degenerate case (no assembler, no profile, host config mounted).
   - Unclear: whether its image-layer JS globals must be policy-governed too.
   - Recommendation: apply the same pnpm@11 + config to `Dockerfile` for consistency (it installs the same `npm:` globals), unless the planner decides transparent is out of the supply-chain remit.

3. **Offline OSV DB for reproducibility?**
   - Known: osv-scanner queries osv.dev/deps.dev online by default; builds should be reproducible/non-interactive.
   - Recommendation: pre-seed `--download-offline-databases` at image-build time if determinism/air-gap matters; otherwise document the build's egress requirement to osv.dev/deps.dev/PyPI.

4. **Severity data shape from osv-scanner JSON** (see A3) — verify the score is numeric vs. a CVSS vector needing parsing, against a real high finding during execution.

## Sources

### Primary (HIGH confidence — read live 2026-06-15)
- https://pnpm.io/blog/releases/11.0 — pnpm 11 defaults (`minimumReleaseAge=1440`, `blockExoticSubdeps`, `strictDepBuilds`), **removal** of `onlyBuiltDependencies` family, `allowBuilds`, isolated global installs, `.npmrc` auth-only, Node 22+ requirement.
- https://pnpm.io/settings — `minimumReleaseAge`/`minimumReleaseAgeStrict`/`minimumReleaseAgeExclude`/`minimumReleaseAgeIgnoreMissingTime`, `blockExoticSubdeps`, `verifyStoreIntegrity`, `strictDepBuilds`, `allowBuilds`, `dangerouslyAllowAllBuilds` (docs version 11.x).
- https://google.github.io/osv-scanner/output/ — output formats + **Return Codes** (0 clean / 1 any finding / 127 error / 128 no packages); JSON shape with `severity`/CVSS.
- https://github.com/google/osv-scanner — V2, `scan source -r`, `scan image [--archive]`, offline mode, credential-free (osv.dev + deps.dev), install methods; latest release **v2.3.8** (2026-05-08).
- https://github.com/pypa/pip-audit + https://pypi.org/project/pip-audit/ — `-r requirements.txt`, `--format json`, `--vulnerability-service`, exit-on-vuln; **2.10.1** verified via `pip index versions` + slopcheck `[OK]`.
- https://mise.jdx.dev/dev-tools/backends/npm.html — `npm.package_manager = "pnpm"` routes the npm backend through pnpm.

### Secondary (MEDIUM — corroboration)
- https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults — minimumRelease-age default corroboration.
- https://cybersecuritynews.com/pnpm-11-turns-on-minimum-release-age/ — migration note: audit `onlyBuiltDependencies`→`allowBuilds`.
- https://developer.harness.io/docs/.../osv-scanner-reference/ — confirms severity gating is a *wrapper* feature, not native osv-scanner `scan`.

### In-repo ground truth (HIGH)
- `.planning/REQUIREMENTS.md` (BLD-01/02/03 + Out-of-Scope), `.planning/PROJECT.md`, `.planning/STATE.md`, `CLAUDE.md` (Constraints + Technology Stack).
- `docs/harnessed-design.md` §6/§7/§15/§16/§18.
- `.planning/research/STACK.md`, `.planning/research/PITFALLS.md` (Pitfalls 6/7/11).
- Actual code: `base/Dockerfile.harnessed-base`, `base/Dockerfile.hatago`, `tools/Dockerfile`, `tools/pyproject.toml`, `tools/harnessed/{cli,assemble,schema,emit}.py`, `recipes/time/recipe.yaml`, `lib/harnessed-common.sh` (`build_stack`/`build_images`), `harnessed` bootstrap, legacy `Dockerfile`.

## Metadata

**Confidence breakdown:**
- Standard stack (pnpm 11 / osv-scanner / pip-audit): **HIGH** — all re-verified against official docs/registries today; versions confirmed.
- Architecture (where the gate hooks in): **HIGH on constraints** (emit-only, podman-only, build flow read from actual code); **MEDIUM on the exact in-image-vs-host split** (a design choice the planner locks — A1/A5).
- Pitfalls: **HIGH** — grounded in pnpm 11 release notes + osv-scanner return-code docs + milestone PITFALLS.

**Research date:** 2026-06-15
**Valid until:** ~2026-07-15 for pnpm/osv-scanner (fast-moving — re-check release notes at execution); stable for the repo-integration findings.
