# harnessed — Comprehensive Remediation Plan

## Context

`harnessed` launches isolated, composable AI-coding-harness stacks (claude/omp/opencode/gemini/antigravity/codex) as podman pods with an MCP hub (hatago). It is split into a **bash tier** (the `harnessed` launcher + `lib/*.sh`, 2247 lines) that orchestrates podman, and a **Python tier** (`tools/harnessed/`, 2079 lines) that owns schema, assembly, scanning, and the capability test.

Three problems have accumulated to the point of active harm:

1. **Documentation describes a deleted feature.** "transparent" mode and the `container` alias were removed from the code, but README and the design doc still present them as live — including a **broken quickstart**.
2. **The build-artifact (`profiles/`) lifecycle is incoherent.** Generated profiles are written into the install clone, never cleaned on `git pull`, and 10 of 11 on-disk profiles fail the current is-built guard because the emitter's shape changed underneath them. Two guards disagree about what "built" means.
3. **The bash launcher has outgrown bash at the config layer.** It re-implements the Python parser with `sed`, with silent-failure sites; harness dispatch is smeared across 5 hand-synced if-chains; there are no unit tests for security-critical code.

**Decision taken with the user (this session):** retire the self-imposed "podman is the only host dependency" constraint and **unify the launcher into the existing Python package as a Typer CLI distributed via pipx/uvx**. Sequencing is *migrate-first, fix-during* — substantive docs are rewritten to describe the new architecture rather than twice. The intended outcome: one tool, one parser, one path-resolver, a place for unit tests, and docs that match reality.

---

## 1. Executive Summary & Verdict

The core architectural bets are sound — the Python assembler, the emit-only / host-builds split, podman-first composition, pnpm-everywhere — and should be preserved. The damage is concentrated in three repairable areas: doc drift around a removed feature, an incoherent generated-artifact lifecycle with a guard/shape mismatch that breaks launches, and a bash launcher that strains specifically at YAML/config parsing while remaining clean at podman orchestration. None of this is a fundamental design failure; it is accumulated drift plus one boundary that has moved.

**Verdict: needs-significant-work** (not a from-scratch redesign). The remediation is a *targeted re-platforming of the launcher onto Python* (which the existing Python tier already half-supports) plus a documentation and artifact-lifecycle cleanup — executable incrementally without discarding the working assembler.

---

## 2. Findings

### Theme A — Documentation accuracy (transparent ghost + drift)

| # | Severity | Evidence | Issue |
|---|---|---|---|
| A1 | **Blocker** | `README.md` §"One engine, two modes" (44–57); Quickstart §1 (101–106); command table (131–132); `## The container back-compat alias` (177–181); installer note (69) | README presents `transparent` as a co-equal mode with a **broken quickstart** (`harnessed transparent` / `container` both error/don't exist). 8 structural locations. First thing a new user runs fails. |
| A2 | High | `docs/harnessed-design.md` §2 (27–41), and refs in §3/§4/§4b/§10/§12/§13/§14/§15/§16/§17 — ~19 hit-lines | Design doc still describes "two config modes"; §12 contains a full `Built-in transparent stack` YAML block; §10 repo layout lists `stacks/transparent/stack.yaml` and the `container` alias. |
| A3 | Low | `docs/codebase/*` (ARCHITECTURE/CONCERNS/CONVENTIONS/INTEGRATIONS/STACK/STRUCTURE/TESTING) | 7 files already **deleted on disk, unstaged**. No tracked doc cross-references them. Just needs staging + commit. No regeneration step is wired into the build, so the map will rot again if regenerated as-is. |
| A4 | Low | `docs/recipe-adoption-gap-analysis.md:38` (untracked) | Parenthetical "(Phase 9/10 are unbuilt.)" is false — both shipped. |
| A5 | Info | `docs/guides/*` (recipe-authoring, secrets, service-authoring, stacks, troubleshooting); `DESIGN.md`; all `lib/*.sh`; all `stacks/*/stack.yaml`; `docs/research/*` | **Clean** — Phase 11 sweep was effective here. Confirms the drift is isolated to README + design doc + the two untracked planning docs. |
| A6 | Medium | No regeneration mechanism for `docs/codebase/`; `docs/comprehensive-development-plan.md` + `docs/research/*` untracked | Systemic: the codebase map was a one-shot generation with no ownership/regen step. Untracked planning docs accumulate under `docs/`. |

### Theme B — Build-artifact lifecycle & path/state resolution

| # | Severity | Evidence | Issue |
|---|---|---|---|
| B1 | **Blocker** | `lib/harnessed-isolated.sh:65` checks `$profile_dir/.mcp.json` (root); 10/11 on-disk profiles have it at `.claude/.mcp.json` | Launch guard fails for 10/11 existing profiles → forced rebuild every launch, or hard error. |
| B2 | High | Launch guard (`harnessed-isolated.sh:65`, root `.mcp.json`) vs test guard (`harnessed:334`, `.claude/` dir) | **Two contradictory is-built guards.** They give opposite verdicts for the same profile set (test passes OLD-shape, launch passes NEW-shape). |
| B3 | High | `tools/harnessed/emit.py:10–12` docstring says `.claude/.mcp.json`; `write_mcp_json()` (49) writes `profile_dir/".mcp.json"` (root) | Emitter code diverged from its own docstring; on-disk profiles match the docstring, not the code. |
| B4 | High | Manifest mounts `.mcp.json` → `$CONTAINER_HOME/.claude/.mcp.json` (`harnessed-manifest-mounts.sh`); but `claude --mcp-config` is invoked with `$CONTAINER_HOME/.mcp.json` (`harnessed-isolated.sh:226`) | **Container-side MCP path mismatch** — for NEW-shape profiles the mounted file and the `--mcp-config` path differ; MCP silently not loaded. |
| B5 | High | `install.sh` clones to `~/.local/share/code-container`; `assemble.py:78` writes `build_dir/profiles/<stack>`; `git pull --ff-only` update path never cleans `profiles/` | Generated output lives in the install clone; `git pull` that changes a stack's recipes leaves the old profile in place silently. Clone tree should be immutable shipped source. |
| B6 | Medium | profile_dir computed at `harnessed:334`, `harnessed-isolated.sh:64`, `assemble.py:78`; instance name at `harnessed:377` and `harnessed-isolated.sh:70` | Path/state resolution scattered, no single source of truth. Only `XDG_STATE_HOME` is used (`harnessed-isolated-config.sh:74`); no `XDG_DATA/CACHE`. History dirs bypass XDG entirely (`$HOME/.claude/*`). |

### Theme C — Architecture & code quality (the launcher)

| # | Severity | Evidence | Issue |
|---|---|---|---|
| C1 | High | No `tests/`, no pytest in `pyproject.toml` | **Zero unit tests** for security-critical Python: `scan.py:_cvss3_base()`, `scan.py:gate()` (HIGH threshold), `schema.py:validate_no_raw_npm()`, `validate_pin()`, `emit.py`, `capability.py:build_report()`. Regressions only caught by a live build hitting a real CVE. |
| C2 | Medium | `harnessed-services.sh:37` `_svc_yaml_val()` | sed-on-YAML truncates `image: registry.io:5000/img` → `registry.io`. **Silently** builds wrong image. |
| C3 | Medium | `harnessed-isolated.sh:149–155` | `services:` parsed as inline `[a,b]` only; **block-style YAML lists start zero services, silently**. |
| C4 | Medium | `harnessed-manifest-mounts.sh:28,51` call `yq` on the **host** | Undocumented host dependency that contradicts the stated "podman-only host" constraint (moot once that constraint is retired, but currently a latent `yq: not found` failure). |
| C5 | Medium | `harnessed-secrets.sh:90` error text: `npm i -g varlock` | Violates pnpm-everywhere constraint (CLAUDE.md §7). Should be `pnpm add -g`. |
| C6 | Low-Med | `schema.py`: `McpServer.transport` (87–89) unvalidated vs `{stdio,http,sse}`; `Stack.harness` validated lazily only in `harness_config_dir`; `ServiceDef.port` no range check; `assemble.py:69–79` silently ignores contradictory `service:`+`command:`; `McpServer.url_env` parsed but never emitted (no-op) | Schema/validator gaps — invalid configs pass all gates and fail at runtime (or silently no-op). |
| C7 | Low | `harnessed-isolated.sh` re-attach (89–110) vs fresh-attach (227–256) | ~60 lines of near-identical 6-branch harness dispatch duplicated; only `claude` differs (adds `--mcp-config`). Dispatch smeared across **5 sites** total. |
| C8 | Low | `harnessed-isolated.sh:78` `net` var; `harnessed-secrets.sh:162` single-line-only snyk.json sed parse | Dead code; brittle JSON parse that silently drops `SNYK_TOKEN` on prettyprinted input. |

**Architecture read:** bash is *not* straining at podman (build/run/exec/pod, TTY, traps, runtime abstraction are clean and idiomatic). It strains **only** at config reading, where it re-implements `schema.py`'s parser in `sed`. That boundary has moved — the config layer now belongs entirely in Python.

---

## 3. Architecture Decision (item 4)

**Recommendation: migrate the launcher into the Python package as a Typer CLI distributed via pipx/uvx. Retire the "podman-only host dependency" constraint.**

**Rationale (evidence-earned):**
- The config layer is already Python's job; bash duplicates it lossily (C2, C3, B-series). Unification deletes the dual-parser seam outright.
- Harness dispatch centralizes in the existing `HARNESS_CONFIG_DIR` dict (`schema.py:41–48`) instead of 5 hand-synced bash if-chains (C7).
- Gives security-critical code a unit-test home (C1).
- A single Python path-resolver kills the scattered profile_dir/instance-name sites (B6) and makes the XDG relocation (B5) a one-place change.
- Distribution cost is near-zero with **uvx** (no persistent install); **Typer** matches the repo's type-hints-everywhere convention.
- The clean TTY attach is preserved via `os.execvp("podman", ["exec","-it",...])` — process replacement hands off the terminal natively; no bash shim needed.

**Alternatives rejected:**
- *Keep bash, add an `emit-stack-info` shim* — fixes the parser seam but leaves 5-site dispatch, no test home, and two languages for one tool. Half-measure.
- *Bash thin-shim wrapper* — keeps a shell entrypoint for no benefit once Python owns `os.execvp`.
- *Go/Rust rewrite* — discards the working 2079-line Python tier; types/modules don't justify the cost. Not earned.

**Preserved unchanged:** the Python assembler, emit-only/host-builds split, podman pod composition, pnpm-everywhere, hatago-as-hub, Claude-format-canonical.

---

## 4. Sequenced Work Plan

### Wave 0 — Stop-the-bleeding (minutes; architecture-independent, lands immediately)
- **W0.1** Fix the broken README quickstart command only (the `harnessed transparent` / `container` invocation) so the first thing a user runs works. *(full README rewrite deferred to W2.)* — `README.md:101–106,131–132`
- **W0.2** `npm i -g varlock` → `pnpm add -g varlock` — `harnessed-secrets.sh:90`
- **W0.3** Stage the 7 `docs/codebase/*` deletions; delete the false parenthetical at `docs/recipe-adoption-gap-analysis.md:38`.
- **W0.4** Reconcile the guard mismatch (B1/B2) *as a hotfix on current bash*: pick the NEW shape (`.mcp.json` at root) as canonical, update both guards (`harnessed-isolated.sh:65`, `harnessed:334`) and the `--mcp-config` path (`:226`) + manifest mount target (B4) to agree, and force re-emit of stale profiles. This unblocks launches before the migration lands.

### Wave 1 — Python launcher foundation (the migration backbone)
- **W1.1** Add Typer + the `harnessed` console-script entrypoint to `pyproject.toml`; pytest dev-dep + `tests/` skeleton.
- **W1.2** Build a single `paths.py` resolver: profile dir, per-instance state, instance naming, container-side paths — one source of truth (resolves B6). Profiles relocate to **`$XDG_DATA_HOME/harnessed/profiles/`** (resolves B5); clone becomes immutable source.
- **W1.3** Port podman orchestration to Python `subprocess`/`os.execvp` (build/run/exec/pod/attach), reusing `schema.py` for all config reads — deletes every sed-on-YAML site (C2, C3) and the host `yq` dependency (C4).
- **W1.4** Centralize the 6-harness dispatch on `HARNESS_CONFIG_DIR`; collapse the duplicated attach branches (C7).
- **W1.5** Port secrets/token discovery and the firewall/rescan glue.

### Wave 2 — Hardening & doc rewrite (fix-during)
- **W2.1** Unit tests for `_cvss3_base`, `gate`, `validate_no_raw_npm`, `validate_pin`, `build_report`, `emit.py`, the new `paths.py` (C1).
- **W2.2** Close schema gaps: validate `transport` set, `harness` eagerly in `load_stack`, `port` range, error on `service:`+`command:`, decide `url_env` (implement or remove) (C6).
- **W2.3** Rewrite `README.md` and `docs/harnessed-design.md` to describe the **single isolated mode** + the new Python/pipx/uvx distribution (A1, A2). Update CLAUDE.md/AGENTS.md constraints (drop "podman-only host dep"; add pipx/uvx + Python).
- **W2.4** Wire a doc-accuracy mechanism (A3, A6): either a `harnessed docs map` regeneration subcommand run in CI, or remove `docs/codebase/` from tracking and treat it as on-demand. Decide tracking policy for untracked planning docs.

### Wave 3 — Cleanup & cutover
- **W3.1** Remove the bash launcher + `lib/*.sh` once Python reaches parity (keep `egress-firewall.sh` injected script if still container-side).
- **W3.2** Update `install.sh`/`uninstall.sh` for the pipx/uvx model; profile cache lives in XDG, cleaned by a `harnessed clean` subcommand.
- **W3.3** Migrate UAT suites (`tools/uat/phase-*.sh`) to drive the Python CLI; keep them integration-level.

---

## 5. Risk & Blast-Radius

- **W0.4 guard hotfix** touches the launch path for every stack — must force-re-emit all stale profiles or the fix masks B3. Low risk if profiles are treated as disposable (they are).
- **W1.2 path resolver / XDG move** threads through every profile_dir + instance-name site (B6) and the install model (B5). Highest blast radius: a missed site sends a mount to the wrong host-absolute path (DooD footgun). Mitigation: single resolver, integration test that asserts mount sources resolve under `$XDG_DATA_HOME`.
- **W1.3 podman port** is the core risk — TTY attach, mount-arg assembly, and `set -euo pipefail`/trap-cleanup semantics must be reproduced exactly. Mitigation: port behind the existing UAT suites; keep bash launcher runnable until parity is proven (W3.1 is the cutover gate).
- **W2.3 doc rewrite** depends on the architecture being settled — that's why it's fix-during, not Wave 0.
- **Distribution change** (`install.sh`) affects new + existing users; needs a clear upgrade note (bash `harnessed` → pipx/uvx console-script).

---

## 6. Open Decisions

1. **Profile location confirmed** → `$XDG_DATA_HOME/harnessed/profiles/` (user chose XDG user-space). Remaining sub-choice: DATA vs CACHE — recommend **DATA** (profiles are mount sources at runtime, not throwaway). *Confirm at W1.2.*
2. **`docs/codebase/` future** — regenerate-in-CI vs untrack-and-treat-on-demand (A6). Recommend untrack for now; revisit a generator later. *Needs a call at W2.4.*
3. **`McpServer.url_env`** — implement runtime URL-from-env substitution, or remove the dead field (C6)? Needs intent. *W2.2.*
4. **Minimum host story** — pin a supported path: `uvx harnessed ...` (zero install) as default, `pipx install` as the persistent option. Affects install.sh + docs. *W3.2.*
5. **Bash removal timing** — delete `lib/*.sh` at cutover (W3.1) or keep a deprecation window? Recommend delete-at-parity to avoid two maintained launchers.

---

## 7. Verification

- **Wave 0:** `harnessed <stack>` (a built stack) launches without the guard error; quickstart command in README runs; `rg -n 'npm i' lib/` clean; `git status` shows `docs/codebase/` staged deleted.
- **Wave 1:** existing UAT suites (`tools/uat/phase-04/05/06/08/09.sh`) pass against the Python CLI; `harnessed build <stack>` writes to `$XDG_DATA_HOME/harnessed/profiles/<stack>/` (not the clone); `rg -n "sed -n.*yaml|grep.*\\^harness:" lib/ harnessed` returns nothing.
- **Wave 2:** `pytest` green for CVSS/gate/validators/paths; a stack.yaml with `transport: grpc` now fails assembly with a clear error; `rg -n transparent README.md docs/harnessed-design.md` returns nothing (CSS hits in `DESIGN.md` excluded).
- **Wave 3:** `uvx harnessed list` works on a clean machine with only podman + uv; `harnessed clean` purges the XDG profile cache; no `lib/*.sh` launcher remains (`fd harnessed- lib/`).
- **End-to-end oracle (per remediation-prompt.md):** assemble + launch each stack in `docs/RECIPE-STRESS-TEST.md` and assert the capability test (`claude mcp list` / `hatago://servers`) matches the stack manifest.
