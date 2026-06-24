This file is a merged representation of a subset of the codebase, containing specifically included files, combined into a single document by Repomix.

# File Summary

## Purpose
This file contains a packed representation of a subset of the repository's contents that is considered the most important context.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Repository files (if enabled)
5. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Only files matching these patterns are included: docs/**, .planning/*.md, .planning/codebase/*.md, README.md
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded
- Files are sorted by Git change count (files with more changes are at the bottom)

# Directory Structure
```
.planning/
  codebase/
    ARCHITECTURE.md
    CONCERNS.md
    CONVENTIONS.md
    INTEGRATIONS.md
    STACK.md
    STRUCTURE.md
    TESTING.md
  PROJECT.md
  RECIPE-ARCHITECTURE-MILESTONE.md
  ROADMAP.md
  STATE.md
  v1.0-MILESTONE-AUDIT.md
docs/
  guides/
    recipe-authoring.md
    secrets.md
    service-authoring.md
    stacks.md
    troubleshooting.md
  prompts/
    recipe-authoring-prompt.md
  research/
    home-folder-antigravity-requirements.md
    home-folder-claude-requirements.md
    home-folder-harness-history-overview.md
    home-folder-omp-requirements.md
  comprehensive-development-plan.md
  harnessed-design.md
  recipe-adoption-gap-analysis.md
  RECIPE-STRESS-TEST.md
README.md
```

# Files

## File: .planning/v1.0-MILESTONE-AUDIT.md
`````markdown
---
milestone: v1.0
audited: 2026-06-21T00:00:00Z
status: tech_debt
scores:
  requirements: 39/39
  phases: 5/5
  integration: 14/14   # cross-phase seams wired
  flows: 5/5           # E2E flows intact
gaps:
  requirements: []     # zero unsatisfied — FAIL gate not triggered
  integration: []      # zero blockers
  flows: []            # zero broken flows
tech_debt:
  - phase: 01-containerized-engine-transparent-stack
    items:
      - "Frontmatter hygiene: all three SUMMARYs (01-01/02/03) have empty `requirements-completed`; the 9 reqs are enumerated + evidenced only in 01-VERIFICATION.md (manual cross-check resolved them to satisfied)"
  - phase: 05-secrets-hardening-docs-completeness
    items:
      - "Frontmatter hygiene: 05-01/05-02 SUMMARY `requirements-completed` carry inline `#` comments that pollute the YAML array (e.g. `[SEC-02]   # SEC-01 is PARTIAL here ...`); union still covers all 7 reqs"
  - phase: cross-phase (services)
    items:
      - "G-1 (warning): `ensure_harnessed_net()` in lib/harnessed-services.sh:26 is dead code (zero callers); `svc_up` passes no --network and uses the rootless host-gateway model. Stale comments (services.sh:2-5, services/ping/service.yaml:2-5) still say 'on harnessed-net'. Functional outcome (SVC-02 shared service) is correct; only the mechanism description + dead function mislead maintainers"
      - "G-2 (info): recipes/ping/recipe.yaml:4 comment shows DNS-by-name URL `http://ping:8080/mcp`; assembler emits `http://host.containers.internal:8080/mcp` (code correct, comment stale)"
      - "G-3 (info): systemd/harnessed-rescan.service:3-4 comment credits `harnessed install` for the launcher symlink, but that subcommand writes per-stack shims; the launcher lands via curl install.sh"
  - phase: nyquist-coverage
    items:
      - "Phases 01-04 have no `*-VALIDATION.md` artifact (MISSING). All four are otherwise covered: P1 operator live run + automated checks, P2 3 live gates green, P3 03-UAT (8/8) + live re-run, P4 phase-04.sh (16/16, 50 checks) live. Process-artifact gap, not a test-coverage gap"
      - "Phase 05 VALIDATION.md exists, `nyquist_compliant: false` (PARTIAL): every automatable leg green (8 tests, 38 checks); 4 live legs (HV-1..HV-4) are irreducibly manual (1Password / browser / overnight timer) and all RESOLVED"
---

# Milestone v1.0 — Audit Report: harnessed

**Audited:** 2026-06-21
**Status:** `tech_debt` — all 39 requirements satisfied, 5/5 phases passed, 5/5 E2E flows intact, 0 blockers. Accumulated non-critical debt (stale comments + one dead function + frontmatter hygiene + 4 missing VALIDATION.md artifacts) flagged for review.

## Definition of Done (ROADMAP)

> harnessed grows from `container` into a launcher for isolated, composable harness stacks: foundation (transparent host-mirror, zero regression) → one isolated tracer-bullet stack (assemble → run → assert green) → supply-chain gate → shared services + recipe breadth + full CLI → opt-in secrets + gated docs. Each phase delivers an observable E2E capability.

All five phases are marked Complete in ROADMAP.md and each carries a `passed` VERIFICATION.md.

## Requirements Coverage (3-Source Cross-Reference)

39/39 v1 requirements **satisfied**. Sources cross-referenced per REQ-ID: phase VERIFICATION.md status table, SUMMARY `requirements-completed` frontmatter, REQUIREMENTS.md traceability checkbox.

| Phase | REQ-IDs | VERIFICATION | SUMMARY frontmatter | Traceability | Final |
|-------|---------|--------------|---------------------|--------------|-------|
| 1 | ENG-01..03, MODE-01..02, AUTH-01, MNT-01..03 (9) | passed, all 9 ✓ + operator live run | **empty** (hygiene gap) | all `[x]` | **satisfied** (manual verify via VERIFICATION evidence) |
| 2 | MODE-03, AUTH-02, RCP-01..04, MCP-01..03, TST-01..02 (11) | passed, 12/12 truths + 4 SC live | union = all 11 | all `[x]` | **satisfied** |
| 3 | BLD-01..03 (3) | passed, 5/5 truths live re-run | union = all 3 | all `[x]` | **satisfied** |
| 4 | SVC-01..03, STA-01..02, CLI-01..03, HRN-01 (9) | passed, 16/16 suite | union = all 9 | all `[x]` | **satisfied** |
| 5 | SEC-01..04, DOC-01..03 (7) | passed, 7/7 VERIFIED (HV-1..4 resolved) | union = all 7 (comment-polluted YAML) | all `[x]` | **satisfied** |

**Status-matrix note (Phase 1):** VERIFICATION `passed` + SUMMARY frontmatter `missing` → matrix yields *partial (verify manually)*. Manual verification: 01-VERIFICATION.md enumerates each of the 9 requirements as ✓ SATISFIED with specific evidence (MOUNT_ARGS inspection, copy-on-start unit check, firewall apply, operator-approved live interactive run). Resolved to **satisfied**; the empty frontmatter is logged as tech debt, not a coverage gap.

**Orphan detection:** none. Every REQ-ID in the traceability table appears in at least one phase VERIFICATION.md. No requirement assigned-but-unverified.

**FAIL gate:** not triggered — zero `unsatisfied` requirements.

## Phase Verification Summary

| Phase | Status | Score | Notes |
|-------|--------|-------|-------|
| 1. Containerized Engine + Transparent Stack | passed | 5/5 truths, 9/9 reqs | 1 blocker found+fixed during exec (`set -e` pipeline, `a963a69`); operator-confirmed live |
| 2. Isolated Tracer-Bullet Stack | passed | 12/12 truths, 4/4 SC, 11/11 reqs | 3 real bugs found+fixed live (`4c9b665`, `1c2efea`, `94793f5`); post-close MCP isolation leak fixed (`57b13b9`, `629f76e`) |
| 3. Supply-Chain Gate + pnpm-Everywhere | passed | 5/5 truths, 3/3 reqs | VERIFICATION reconciled from 03-UAT (8/8) + live re-run 2026-06-19 |
| 4. Shared Services + Recipe Breadth + Full CLI | passed | 6/6 truths, 9/9 reqs | phase-04.sh: 16/16 tests, 50/50 checks live 2026-06-19; UAT gaps closed by 04-04 |
| 5. Secrets, Hardening + Docs Completeness | passed | 7/7 reqs, 4/4 SC | HV-1/HV-2 resolved (`81a7f3f`); HV-3 snyk browser auth resolved 2026-06-21 (`27fe91b` --network=host); HV-4 linger resolved 2026-06-19 |

No phase reported critical gaps. No phase is missing VERIFICATION.md.

## Cross-Phase Integration

Static integration audit (read-only): **14/14 seams wired**, parse-clean (12/12 `bash -n`, 9/9 `py_compile`).

| Seam | Wired | Affected REQ-IDs |
|------|-------|------------------|
| Dispatcher routes every subcommand to its lib function | ✓ | CLI-01..03, SVC-01, SEC-03..04 |
| Subcommands parsed before stack-name fallthrough (collision-safe) | ✓ | CLI-01, SEC-03, SVC-01 |
| P2 isolated sources P1 common + mounts + firewall | ✓ | ENG-01..03, MODE-01..03, MNT-01..02 |
| P3 scan.py invoked in build_stack BEFORE image bake | ✓ | BLD-02 |
| P3 assembler validate_no_raw_npm BEFORE any emit | ✓ | BLD-03, RCP-04 |
| P3 pnpm config COPY'd into all images | ✓ | BLD-01 |
| P4 services reuse P1 runtime + P2 service-ref resolution | ✓ | SVC-01..03 |
| P4 CLI subcommands dispatch to cli.sh functions | ✓ | CLI-01..03 |
| P5 --env-file → isolated (both pod members) | ✓ | SEC-01 |
| P5 --env-file → transparent | ✓ | SEC-01 |
| P5 --env-file → services (per-service schema) | ✓ | SEC-01, SVC-01 |
| P5 --env-file → build scan | ✓ | SEC-01..02, BLD-02 |
| P5 auth dispatch → secrets auth_scanner (host config, no image layer) | ✓ | SEC-03 |
| P5 rescan: timer → dispatcher → rescan lib → online scan (drops --offline) | ✓ | SEC-04 |

## E2E Flows

**5/5 intact, 0 broken.**

| Flow | Status | Where it breaks |
|------|--------|-----------------|
| A — isolated: build → scan gate → bake → `--fresh` pod boot → capability test green | intact | none |
| B — transparent: mounts + egress firewall + `.claude.json` copy-on-start | intact | none |
| C — services: `svc up` → two instances share one service | intact | none (via rootless host-gateway, **not** a named `harnessed-net` bridge — see G-1) |
| D — secrets: `.env.schema` → host varlock → `--env-file` into all 4 consumers | intact | none |
| E — hardening: `auth` → host config; nightly timer → online rescan | intact | none |

## Tech Debt (non-blocking)

### Cross-phase (services)
- **G-1 (warning):** `ensure_harnessed_net()` (lib/harnessed-services.sh:26) is dead code — zero callers. `svc_up` attaches no `--network`; the rootless host-gateway model (`host.containers.internal:<port>`, whitelisted by egress-firewall.sh:62-63) delivers SVC-02 correctly. Stale comments (services.sh:2-5, services/ping/service.yaml:2-5) still claim "on harnessed-net". Fix: delete the dead function (or gate it behind `HARNESSED_NET` in `svc_up`) and correct the comments to match the host-gateway reality.
- **G-2 (info):** recipes/ping/recipe.yaml:4 comment shows `http://ping:8080/mcp`; assembler emits `http://host.containers.internal:8080/mcp`. Code correct; comment stale.
- **G-3 (info):** systemd/harnessed-rescan.service:3-4 comment credits `harnessed install` for the launcher symlink; that subcommand writes per-stack shims — the launcher lands via curl install.sh.

### Frontmatter hygiene
- **Phase 1:** all three SUMMARYs have empty `requirements-completed`; the stats reader sees no mapping. Backfill ENG-01..03/MODE-01..02/AUTH-01/MNT-01..03 into the SUMMARY frontmatter.
- **Phase 5:** 05-01/05-02 `requirements-completed` arrays carry inline `#` comments that pollute the parsed YAML (`summary-extract` returns the comment string verbatim). Move the PARTIAL notes out of the array values.

### Nyquist coverage (discovery only)
- Phases 01-04 lack `*-VALIDATION.md`. All four are otherwise covered (operator live run / 3 live gates / 03-UAT 8/8 / phase-04.sh 16/16). This is a missing process artifact, not a test-coverage hole.
- Phase 05 `nyquist_compliant: false` (PARTIAL): automatable legs green; 4 live legs manual-only by design, all resolved.

## Nyquist Coverage

| Phase | VALIDATION.md | Compliant | Classification |
|-------|---------------|-----------|----------------|
| 01 | missing | — | MISSING (covered via operator live run + automated checks) |
| 02 | missing | — | MISSING (covered via 3 live gates green) |
| 03 | missing | — | MISSING (covered via 03-UAT 8/8 + live re-run) |
| 04 | missing | — | MISSING (covered via phase-04.sh 16/16, 50 checks live) |
| 05 | exists | false | PARTIAL (automatable legs green; 4 manual-only live legs, resolved) |

`compliant: 0 · partial: 1 · missing: 4 · overall: partial` — discovery only; no auto-validate.

## Verdict

Milestone v1.0 meets its definition of done: every requirement satisfied, every phase verified, every cross-phase seam wired, every E2E flow intact, zero blockers. Classified `tech_debt` (not `passed`) solely to surface the accumulated non-critical items above — stale comments, one dead function, SUMMARY frontmatter hygiene, and 4 missing VALIDATION.md artifacts — for an explicit accept-or-clean decision before completion.
`````

## File: docs/guides/stacks.md
`````markdown
# Composing stacks

A **stack** is a manifest (`stacks/<name>/stack.yaml`) that composes **one** harness with a chosen
set of recipes (and optional shared services). A running stack is a podman pod — harness
container + hatago + any declared services — composed at runtime, not baked at build time (`FROM`
can't union sibling systems; design §3, §6).

For the *why* (why one harness per stack, the runtime-pod model), read
[docs/harnessed-design.md §2 & §12](../harnessed-design.md). This guide shows the *how* with worked
examples from this repo's `stacks/`.

## What a stack is

```
stacks/<name>/stack.yaml        # the manifest (you author or scaffold)
  ↓ harnessed build <stack>     # assemble (emit-only) + scan + host podman build
profiles/<name>/                # GENERATED + committed; mounted into the harness container
  .claude/{skills,commands,...} # the assembled, version-controlled profile
  hatago.config.json
```

Recipes are resolved **ahead of time** into a committed profile plus pinned images; the host runs
`podman build`, and nothing is assembled at container start (design §15).

## The `stack.yaml` schema

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`Stack`).
Key fields:

```yaml
name: <stack>                     # required
harness: claude                   # claude | omp | opencode | gemini | antigravity | codex  (exactly one)
recipes: [a, b, c]                # list of recipes/ to compose
services: [ping]                  # optional — shared sidecars to attach (auto-started on launch)
permissions: yolo                 # optional — prompt (default) | yolo (writes skip-permission config)
state:                            # optional
  persist: true                   # default; `--fresh` overrides at runtime
  session_state: host             # host (default — sessions persist, inspectable) | volume
```

Notes:

- **One harness per stack** (design §8). `claude` mounts the profile natively; `omp` consumes the
  *same* Claude-canonical profile via `claude-hooks-bridge`; **`opencode`** also consumes the same
  `.claude/` profile, reading `.claude/skills/**/SKILL.md` + `CLAUDE.md` natively (MCP wired via the
  image-baked `~/.config/opencode` config instead of `.mcp.json`) — no re-authoring for either.
  **`gemini`**, **`antigravity`** (`agy`), and **`codex`** (OpenAI Codex CLI) mount the same `.claude/` profile for parity but do NOT
  natively consume Claude skills/commands (their native asset formats differ); their real capability
  wiring is MCP via image-baked config (`gemini` → `~/.gemini/settings.json`, `antigravity` →
  `~/.gemini/config/mcp_config.json`, `codex` → `~/.codex/config.toml`) pointing at the hatago hub.
- Only the fields you exercise are required; the assembler parses the rest forward.

## Worked example 1: `tracer-time` (claude, one recipe)

[`stacks/tracer-time/stack.yaml`](../../stacks/tracer-time/stack.yaml) is the Phase 2 tracer bullet —
the smallest end-to-end slice:

```yaml
name: tracer-time
harness: claude       # claude | omp | opencode | gemini | antigravity | codex  (exactly one)
recipes: [time]
```

The full lifecycle:

```bash
harnessed build tracer-time      # assemble → scan → build hatago → image scan
harnessed tracer-time            # launch the pod (harness + hatago), attach
harnessed test tracer-time       # capability report: ✓ time (mcp), ✓ time-helper (skill)
```

`harnessed build` emits the `profiles/tracer-time/` tree (assembled from `recipes/time`) and builds
the hatago image. `harnessed tracer-time` composes the pod and attaches; `harnessed test` brings the
instance up `--fresh` headless and asserts the manifest's declared capabilities are live (design
§18). Running an unbuilt stack errors and tells you to `harnessed build` first.

## Worked example 2: `ping-time` (a stack with a shared service)

[`stacks/ping-time/stack.yaml`](../../stacks/ping-time/stack.yaml) composes a stdio recipe (`time`)
with a service-ref recipe (`ping`) and attaches a shared sidecar:

```yaml
name: ping-time
harness: claude
recipes: [time, ping]
services: [ping]
```

- `recipes: [time, ping]` — the assembler composes **two** recipes into one profile: the `time` stdio
  server (hatago child) **and** the `ping` network-native server (hatago URL-proxy). The capability
  test asserts both.
- `services: [ping]` — the launcher **auto-starts** the `ping` sidecar on launch
  (`ensure_service_up`) if it isn't already running. The service is a standalone container (own
  image + volume), **not** a pod member; its lifecycle is independent of any instance.

Authoring the sidecar itself is covered in the [service-authoring guide](service-authoring.md).

> Other stacks in this repo follow the same shape: [`stacks/claude-multi`](../../stacks/claude-multi/stack.yaml)
> (two recipes on claude — proves multi-recipe composition) and [`stacks/omp-time`](../../stacks/omp-time/stack.yaml)
> (the same `time` recipe on the `omp` harness via the bridge — proves one canonical profile runs on
> either harness). [`stacks/opencode-time`](../../stacks/opencode-time/stack.yaml) runs the same `time`
> recipe on the `opencode` harness. [`stacks/gemini-time`](../../stacks/gemini-time/stack.yaml),
> [`stacks/antigravity-time`](../../stacks/antigravity-time/stack.yaml), and
> [`stacks/codex-time`](../../stacks/codex-time/stack.yaml) run the same `time` recipe on
> the `gemini`, `antigravity`, and `codex` harnesses — proving one canonical profile runs on all six harnesses.

## Scaffolding a new stack

`harnessed new` (CLI-02) writes a manifest for you — validating the harness and refusing to
overwrite an existing stack:

```bash
harnessed new my-stack --harness claude --recipes time,greet
# → writes stacks/my-stack/stack.yaml:
#   name: my-stack
#   harness: claude
#   recipes: [time, greet]
```

`--harness` must be `claude`, `omp`, `opencode`, `gemini`, `antigravity`, or `codex` (hard error otherwise). Recipes need not pre-exist yet —
`harnessed new` **warns** (not fails) if a recipe dir is missing, so you can author the stack first
and the recipes after.

## Build + run lifecycle

| Step | Command | Notes |
| --- | --- | --- |
| Build | `harnessed build <stack>` | Assemble (emit-only) + scoped source scan + host hatago build + image scan. Fails on HIGH. |
| Run | `harnessed <stack> [path]` | Compose the pod (harness + hatago), attach. Auto-builds missing images. |
| Clean-room run | `harnessed <stack> --fresh` | Tear down any existing pod/instance first; reseed state from the profile. |
| Capability test | `harnessed test <stack>` | Launch `--fresh` headless + assert declared capabilities (markdown report). |
| List | `harnessed list` | Authored stacks + running instances. |
| Stop / remove | `harnessed stop \| rm <stack>` | Stop or remove every instance of a stack (across projects). |
| Install | `harnessed install <stack>` | Write a `~/.local/bin/<stack>` launcher shim (launch by name from any cwd). |

State persists by default: an instance writes `projects/` + `history.jsonl` to a
harnessed-owned host dir with a legible project slug (STA-02). `--fresh` is the throwaway path. See
the [troubleshooting guide](troubleshooting.md) for the state-dir layout and `--fresh` semantics.

## See also

- [docs/harnessed-design.md §2 & §12](../harnessed-design.md) — the *why* (the stack model, the stack manifest, state).
- [Recipe-authoring guide](recipe-authoring.md) — author the recipes a stack composes.
- [Service-authoring guide](service-authoring.md) — author the sidecars a stack attaches.
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `Stack` model.
`````

## File: docs/prompts/recipe-authoring-prompt.md
`````markdown
# Recipe-authoring prompt

A reusable base prompt for handing an LLM the job of authoring **one** `harnessed`
recipe. Paste the block below and fill in the brief at the bottom.

- **External LLM (no repo access):** the prompt is self-contained — use it as-is.
- **An agent that can read this repo:** trim the schema/example blocks and instead say
  *"Read [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) and the
  `recipes/time` + `recipes/ping` examples,"* then keep only the **Hard rules**,
  **Decision guide**, **Acceptance**, and the brief — the guide is the single source of truth.
- If the recipe needs a `service:` sidecar, also fold in
  [`docs/guides/service-authoring.md`](../guides/service-authoring.md); this prompt covers the
  recipe file, not the service it points at.

---

````markdown
# Task: author a `harnessed` recipe

You are authoring ONE recipe for `harnessed` — a tool that assembles
single-purpose AI-harness containers. A **recipe** is a hand-authored integration
for one capability bundle (an MCP server and/or a set of skills/commands). Recipes
are composed into **stacks** and assembled **ahead of time** into a committed,
version-controlled profile — nothing is resolved at container start.

A recipe lives at `recipes/<name>/recipe.yaml` and contributes to two layers:
- **MCP layer** — server entries under `mcp.servers`, merged into the stack's hatago config.
- **File-extension layer** — `skills` / `commands` in Claude-canonical form, fanned
  into harness-native profile paths.
A recipe may have either layer, both, or neither.

## Output

Produce the full file tree, each file in its own fenced block with its path:
1. `recipes/<name>/recipe.yaml`
2. Any skill/command dirs it ships: `recipes/<name>/skills/<leaf>/SKILL.md` (frontmatter
   `name` + `description`, then markdown body).
Do not write prose outside the files except a short rationale for the transport choice.

## `recipe.yaml` schema (only fields you exercise are required)

```yaml
name: <recipe-name>            # required
description: <one-liner>       # optional

mcp:                           # MCP layer (optional)
  servers:
    - name: <server>           # required
      # stdio child (hatago spawns it, stdio→HTTP) — REQUIRES command:
      command: <cmd>
      args: [<arg>, ...]
      transport: stdio         # explicit; default
      # OR network-native (hatago proxies by URL) — no command:
      url: <http-url>          # direct URL, OR
      service: <service-name>  # reference services/<name>/service.yaml → http://<name>:<port>/mcp
      transport: http
      url_env: <ENV>           # optional
      env: {<k>: <v>}          # optional
      headers: {<k>: <v>}      # optional

skills:                        # file-extension layer (optional)
  - path: skills/<leaf>        # leaf dir name = harness-native target (.claude/skills/<leaf>)
commands:
  - path: commands/<leaf>
```

## Hard rules (non-negotiable — the build enforces these)

1. **Transport is explicit.** Decide and justify:
   - **stdio** for a light, dependency-free server hatago bakes into its image and
     spawns as a child. The harness never runs the command itself.
   - **streamable-http** (`url:` or `service:`) for a network-native server (your own
     sidecar or a remote). One endpoint, POST + optional GET/SSE stream.
   - **SSE is deprecated** (MCP spec 2025-06-18 and Claude Code). NEVER author a new SSE server.
2. **pnpm everywhere — no `npm`/`npx`.** Any JS install uses `pnpm`; `pnpm dlx` replaces `npx`.
   Raw `npm`/`npx` in scripts/deps fails the build.
3. **`uvx` for light Python MCP servers** (e.g. `uvx mcp-server-time`). Heavier Python deps
   declare `deps.python` (pyproject.toml or requirements.txt, installed via uv).
4. **No name collisions.** Each skill/command leaf fans into `.claude/skills/<leaf>` etc.
   and the assembler fails fast on a duplicate leaf name across the stack — pick a unique leaf.
5. **A `service:` ref needs a separate service to exist** (its own image/Dockerfile/server +
   `services/<name>/service.yaml`). If the brief implies a stateful/shared/long-lived backend,
   say so and note the service must be authored too (out of scope for this recipe file).

## Decision guide

- Light, self-contained tool you want baked in → **stdio** (`command` + `args`).
- Stateful, shared, or long-lived backend that outlives any instance → **service ref**
  (`service:` + `transport: http`) + a companion service.
- A behavior/instruction bundle with no server → **skills/commands only**, no `mcp:`.

## Worked example (stdio MCP + a standalone skill)

```yaml
# recipes/time/recipe.yaml
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
```markdown
<!-- recipes/time/skills/time-helper/SKILL.md -->
---
name: time-helper
description: Ask the time MCP server for the current time in any IANA timezone and convert times.
---
# Time Helper
Use the `time` MCP server (exposed through the hatago hub at the harness's single MCP
endpoint) to answer time questions. Call `get_current_time` with an IANA timezone...
```

## Acceptance (how it'll be validated)

The recipe is added to a stack and exercised with:
`harnessed build <stack>` (assemble + supply-chain scan, fails on raw npm/npx and on
HIGH-severity vuln) → `harnessed test <stack>` (capability report: each declared MCP
server connects, each skill/command is present). Author so both pass.

────────────────────────────────────────
## THE RECIPE TO BUILD

- **Name:** <recipe-name>
- **What capability it adds:** <one or two sentences>
- **Backing MCP server (if any):** <package / command / URL, and whether it's stdio-light,
  your own HTTP sidecar, or a remote>
- **Skills/commands to ship (if any):** <names + what each instructs the agent to do>
- **Notes/constraints:** <auth, env vars, network needs, etc.>
````
`````

## File: docs/research/home-folder-antigravity-requirements.md
`````markdown
# Surfacing antigravity (`~/.gemini/antigravity-cli`) project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Companions:** [home-folder-claude-requirements.md](home-folder-claude-requirements.md),
[home-folder-omp-requirements.md](home-folder-omp-requirements.md)
**Investigated on:** `osmc` (antigravity runs there as **root**, workspace `/root`).
**Decision:** Surface the per-conversation file stores under `~/.gemini/antigravity-cli/`
(`conversations/`, `brain/`, `implicit/`) plus the global `history.jsonl` and the `cache/` index.
Per-conversation DBs are **one file each, UUID-namespaced** → whole-parent-dir mount is
collision-free and WAL-safe (closer to Claude's model than omp's). Path-mirror so the `workspace`
key matches. **`~/.gemini` proper belongs to a different harness — do not surface it for
antigravity.**

## The "tell": antigravity is self-contained; `~/.gemini` proper is gemini-cli

The user's hypothesis was that if antigravity's latest dates show up in `~/.gemini` files, the two
share state. They **don't**:

| Tree | Newest write |
|------|-------------|
| `antigravity-cli/` | **2026-06-21 19:53** (active session) |
| everything else in `~/.gemini/` | **2026-06-17 12:04**; actual chats 06-05 → 06-17 |

The 06-21 antigravity session left no trace outside `antigravity-cli/`. The parent `~/.gemini`
(`history/`, `tmp/root/chats/session-*.jsonl`, `state.json`, `oauth_creds.json`, `projects.json`)
is the **gemini-cli** harness's store — a sibling tool nesting under the same dir. antigravity even
has its own auth token (`antigravity-cli/antigravity-oauth-token`, 06-21 19:51), so it doesn't read
the shared `oauth_creds.json`.

**One soft cross-link:** `antigravity-cli/cache/projects.json` maps workspace `/root` → projectId
`6523305a-…`, and a record for that id exists at the *shared* `~/.gemini/config/projects/6523305a-….json`
(last written 06-17, **not** rewritten during the 06-21 session). antigravity carries the
workspace→projectId map locally, so history surfacing does **not** require the shared file. Noted as
a risk, not a dependency.

**Conclusion: the antigravity surface is entirely `~/.gemini/antigravity-cli/`.**

## Keying model — a *third* variant

| Harness | Project key | Per-unit history |
|---------|-------------|------------------|
| Claude | project-path slug (`projects/<slug>/`) | files (`.jsonl` + UUID dirs) |
| omp | `$HOME`-relative path slug (`sessions/<slug>/`) | files **+ shared SQLite** |
| **antigravity** | **`workspace` path string** (the cwd) | **one SQLite file per conversation**, UUID-named |

There is **no per-project directory**. The project↔conversation association lives in index files:

- `cache/projects.json` → `{"<workspace>": "<projectId>"}` — e.g. `{"/root": "6523305a-…"}`
- `cache/last_conversations.json` → `{"<workspace>": "<conversationId>"}` — only the **latest**
  conversation per workspace
- `history.jsonl` → every prompt line tagged `"workspace":"/root"` (filterable by project)

Per-conversation data is keyed by **conversation UUID** (`cid`):
- `conversations/<cid>.db` — SQLite trajectory/transcript (tables: `steps`, `trajectory_meta`,
  `trajectory_metadata_blob`, `gen_metadata`, `executor_metadata`, `parent_references`,
  `battle_mode_infos`)
- `brain/<cid>/.system_generated/` — agent working memory: `logs/transcript.jsonl`,
  `transcript_full.jsonl`, `tasks/`, `messages/`, plus generated `.md` reports + `.metadata.json`
- `implicit/<cid>.pb` — per-session implicit context (protobuf, opaque)

## Layout of `~/.gemini/antigravity-cli/` (skimmed 2026-06-22)

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `conversations/<cid>.db` | History — per-conversation transcript/trajectory | conversation UUID | **Yes — mount** |
| `brain/<cid>/` | History — per-conversation agent memory (transcripts, tasks, messages, reports) | conversation UUID | **Yes — mount** |
| `implicit/<cid>.pb` | History — per-session implicit context (protobuf) | conversation UUID | Yes (opaque blob) |
| `history.jsonl` | History — global prompt log, each line tagged `workspace` | global, `workspace` field | **Yes — guarded merge** |
| `cache/last_conversations.json` | Index — workspace → latest conversation id | workspace | Yes — merge (needed for resume-last) |
| `cache/projects.json` | Index — workspace → projectId | workspace | Yes — merge |
| `cache/onboarding.json` | Cache | — | No |
| `mcp_config.json`, `mcp/<server>/*.json` | Config — MCP defs + tool cache | — | No (profile provides) |
| `settings.json`, `keybindings.json` | Config | — | No |
| `builtin/skills/`, `builtin/.checksum`, `knowledge/knowledge.lock` | Builtin config | — | No |
| `antigravity-oauth-token` | **Auth secret** | — | No (auth-seeded separately) |
| `bin/` (`agentapi`, `webm_encoder`) | Native binaries | — | No |
| `log/cli-*.log`, `cli.log` | Logs | — | No |
| `updater/`, `last_check.timestamp`, `installation_id` | Runtime / identity | — | No |

## Why this is the easy one: per-conversation DBs

Unlike omp (one shared `agent.db` mixing auth + all projects), antigravity gives each conversation
its **own** `conversations/<cid>.db`. That means:

- **Whole-dir mount of `conversations/` is collision-free and WAL-safe** — the container only ever
  writes *new* `<cid>.db` files (new conversations = new UUIDs); it never opens a host conversation's
  DB as a second writer. Same fail-safe property as Claude's UUID-keyed dirs.
- Same for `brain/<cid>/` and `implicit/<cid>.pb`.
- **No auth comingling** — the oauth token is a separate file, excluded by construction.

The only shared-file hazards are the small JSON indexes (`cache/*.json`) and `history.jsonl`
(append-only) — both whole-file-rewrite/append, so handle by **guarded teardown merge**, not rw
bind-mount (same rule as Claude's `.claude.json`/`history.jsonl`).

## Implementation guidance

1. **Path mirroring.** antigravity keys history by the `workspace` *string* (the cwd). Run the
   container at the same absolute path so `workspace` matches the host's project key. (On osmc the
   workspace is `/root` because it runs as root — in the container it's the mirrored project path.)

2. **Mount the per-conversation history dirs whole, rw** (collision-free, WAL-safe):
   `conversations/`, `brain/`, `implicit/`. On a single-workspace host this surfaces exactly that
   workspace's history; on a multi-workspace host it also exposes other workspaces' conversations
   (read-side visibility only — low concern for personal tooling).

3. **`history.jsonl` → guarded teardown merge filtered by `workspace`** (not rw-mount). Append the
   project's lines into the host file; no-op on schema mismatch. Ship disabled until pinned.

4. **`cache/projects.json` + `cache/last_conversations.json` → teardown merge** (small JSON maps,
   merge the project's key). Needed so the host can list the project and resume its latest
   conversation. Do **not** rw-mount (whole-file rewrite race).

5. **Never surface** `antigravity-oauth-token` (auth-seeded by the profile mechanism), `bin/`,
   `log/`, `updater/`, config files, or the parent `~/.gemini/` tree.

6. **Data-driven manifest + §18 oracle test**, as with the other harnesses: after a throwaway
   session, assert a new `conversations/<cid>.db` and `brain/<cid>/` appeared on the host, and that
   `history.jsonl` gained a line for the workspace.

## Risks / open questions

- **No complete workspace→conversation index.** `cache/last_conversations.json` records only the
  *latest* conversation per workspace. To enumerate *all* of a workspace's conversations for
  precise per-project filtering (multi-workspace hosts), you'd scan each `conversations/<cid>.db`
  trajectory metadata for the workspace — **unverified that the DB stores the workspace**; confirm
  on a multi-workspace host. On single-workspace hosts (osmc = `/root`) this is moot; whole-dir
  mount is exact.
- **Shared projectId record** at `~/.gemini/config/projects/<projectId>.json`. antigravity has the
  workspace→projectId map locally, so resume shouldn't need it — but confirm before assuming the
  shared `~/.gemini/config/` can be fully ignored.
- **`implicit/<cid>.pb`** is protobuf — surfaced as an opaque blob; not human-inspectable without
  the schema.
- **Runs as root on osmc.** The workspace key `/root` is an artifact of that. In the container the
  workspace is the mirrored project path; the keying logic is identical (string match on cwd).

## Verification done

- `find` skim of `~/.gemini` + `~/.gemini/antigravity-cli` (depth 3) on osmc.
- Compared newest mtimes: antigravity-cli **06-21 19:53** vs rest of `~/.gemini` **06-17 12:04** →
  not mirrored; parent tree is gemini-cli.
- `cache/projects.json` = `{"/root":"6523305a-…"}`; `cache/last_conversations.json` =
  `{"/root":"39279a69-…"}`.
- `history.jsonl` lines carry `"workspace":"/root"`.
- `conversations/<cid>.db` schema captured (per-conversation SQLite; `steps` + `trajectory_*`).
- antigravity has its own `antigravity-oauth-token` (self-contained auth).
- `sqlite3` present on osmc (`/usr/bin/sqlite3`).
- **Not** verified: whether a conversation DB stores its `workspace` (needed only for
  multi-workspace per-project filtering); whether `~/.gemini/config/projects/<id>.json` is required
  for resume.
`````

## File: docs/research/home-folder-claude-requirements.md
`````markdown
# Surfacing Claude Code project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Decision:** Surface **everything joinable** (option 3) via targeted rw bind-mounts, with the
one format-parsing step (`history.jsonl` merge) quarantined as a guarded, disable-able teardown.
**Run the container working dir at the same absolute path as the host** (path mirroring) — this
deletes the slug-remap hazard and keeps surfaced history host-coherent (see Hazard A).

## Problem

Isolated stacks do **not** mount host `~/.claude` wholesale (no transparent-style mirror). But we
still want a project's **history** — conversation transcripts, file-rewind backups, subagent runs,
per-project memory — to persist to the host's global Claude store so it survives throwaway
containers and shows up alongside non-containerised work. The task: identify the *exact* subpaths
to bind-mount, and the keying hazards that make a naive mount wrong.

## Layout of `~/.claude` (skimmed 2026-06-22)

Top-level dirs/files, classified by whether they hold per-project **history** vs config/cache:

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `projects/<slug>/` | History — transcripts (`<uuid>.jsonl`) + `memory/` | **project path slug** | **Yes** |
| `file-history/<uuid>/` | History — pre-edit file snapshots (`<hash>@v1/@v2`), powers rewind/undo | session UUID | **Yes** |
| `tasks/<uuid>/` | History — subagent/Task run records | session UUID | **Yes** |
| `session-env/<uuid>/` | History — `sessionstart-hook-*.sh` env captures | session UUID | **Yes** |
| `todos/<uuid>…` | History — per-session todo lists (empty on this box, session-keyed by design) | session UUID | **Yes** |
| `history.jsonl` | History — every prompt typed; each line has `"project"` + `"sessionId"` | global append, project field | **Yes, guarded** |
| `plans/*.md` | History — plan-mode artifacts, named by random slug | **no on-disk key** (project only in content) | Deferred — see Ambiguous |
| `shell-snapshots/snapshot-zsh-<ts>-<rand>.sh` | History-ish — shell env snapshots | timestamp, not session | No (can't map cleanly) |
| `sessions/<number>.json` | Session group state | numeric id (terminal/tab group) | No |
| `agents/ commands/ skills/ rules/ hooks/ plugins/` | Config | — | No |
| `cache/ .search_cache/ paste-cache/ downloads/ stats-cache.json debug/ ide/ chrome/ backups/ context-mode/ sandbox/` | Cache / runtime | — | No |
| `.credentials.json settings*.json` | Secrets / config | — | No (credentials handled by existing auth-seed layer) |

## The core hazard: two join keys

Only `projects/<slug>/` is keyed **directly** by project path. Everything else historical is keyed
by **session UUID**, generated at session start *inside* the container. The UUID→project mapping
lives in two places:

- the `.jsonl` **filenames** under `projects/<slug>/` (filename = session UUID), and
- `history.jsonl` lines (`"project"` + `"sessionId"`).

### Hazard A — the project slug differs inside the container → **solved by path mirroring**

The slug is derived from the **absolute cwd**. Evidence — both already exist on this host:

```
projects/-home-mcrowe-Programming-Personal-code-container/      ← host runs   (cwd /home/mcrowe/…)
projects/-container-mcrowe-Programming-Personal-code-container/ ← container   (cwd /container/mcrowe/…)
```

Critically, the path leak is **not just the slug** — every transcript line embeds the cwd-rooted
absolute path, and so do `file-history` references. Confirmed on this host:

```
host slug transcript:      "cwd":"/home/mcrowe/Programming/Personal/code-container"
                           "file_path":"/home/mcrowe/Programming/Personal/code-container/Dockerfile"
container slug transcript: "cwd":"/container/mcrowe/Programming/Personal/code-container"
```

If the container runs at a *different* path (`/container/mcrowe/…`), the surfaced history is
internally consistent but **host-invalid**: clickable `file_path:line` refs resolve to a
non-existent `/container/…`, rewind blobs key to paths the host can't act on, and a later host
session sees its `projects/` dir split across two slugs.

**Decision: mirror the path.** Run the container working dir at the *same* absolute path as the
host (`/home/mcrowe/Programming/Personal/code-container` inside, byte-for-byte). This:
- deletes the remap entirely — the `projects/` mount becomes plain same-path → same-path, with no
  dependency on CC's path→slug algorithm;
- keeps every recorded path host-coherent;
- makes the DooD pattern clean — container `PWD` == host `PWD`, so `-v $PWD:$PWD` works with no
  translation (satisfies §15's host-absolute-path rule directly);
- coalesces transparent + isolated runs of the same project into one history — which is the goal
  ("this project's history, regardless of how it ran").

Isolation is about **config** (skills/MCP/memory/profile), not the working-dir path; mirroring the
path leaks no host config, so the isolation guarantee is intact. Only `~/.claude` config stays
synthetic — not the project path. The current `-container-mcrowe-…` behaviour is therefore a
**change to make**, not the target state.

### Hazard B — UUID-keyed dirs have no project subfolder

`file-history/`, `tasks/`, `session-env/`, `todos/` are flat `<uuid>/` at top level. You can't
pre-create a per-project mount (UUID unknown until the session starts), so you mount the **parent
dir whole**. This is collision-free (everything is UUID-namespaced; new sessions just add dirs).
Cost: the container can *read* other projects' UUID dirs — a read-side visibility leak of file-backup
blobs, not config or secrets. Accepted.

### Hazard C — `history.jsonl` is a global append-only file

Never rw-bind it (same whole-file-rewrite race we already rejected for `.claude.json`). Surface it
by **append-merging** lines filtered on `"project"` at teardown.

## Decision rationale (why option 3, not 2)

Brittleness is **not** "more mounts." A bind-mount makes zero assumptions about dir *contents*: if a
future Claude Code release renames `tasks/`, the mount becomes an inert no-op and the new dir goes
uncaptured — **silent degradation, not container failure.** So the four UUID-keyed mounts are
effectively free in fragility terms.

The **only** genuinely brittle piece is the `history.jsonl` append-merge, because it parses an
undocumented line schema. That risk is one isolated component.

Two fragilities are **shared by options 2 and 3 equally**, so they don't favour the smaller option:
the slug-remap (depends on CC's path→slug algorithm) and the UUID-keying convention.

Net: take the full surface, quarantine the one parsing step.

## Implementation guidance

1. **Run the container at the host project path** (mirroring), then mount the project dir
   same-path → same-path — no slug remap:
   ```
   --workdir /home/mcrowe/Programming/Personal/code-container \
   -v $HOST_CLAUDE/projects/-home-mcrowe-…-code-container \
      :$CONTAINER_CLAUDE/projects/-home-mcrowe-…-code-container:rw
   ```
   Slug is identical both sides. Surfaces transcripts + per-project `memory/`. (DooD rule satisfied
   — source is a **host absolute path**, and container `PWD` == host `PWD`.)

2. **Mount the four UUID-keyed parent dirs rw** (fail-safe, collision-free):
   `file-history/`, `tasks/`, `session-env/`, `todos/`.

3. **`history.jsonl` = guarded, disable-able teardown step.** Append only lines whose `"project"`
   matches the project, wrapped so a parse failure **logs a warning and no-ops** rather than
   corrupting the host file. Ship it disabled until the format is confirmed; a CC schema change can
   then only break this one feature, not the container.

4. **Make the mount set data-driven** — a list/map in config, not inline `-v` flags — so a future CC
   layout change is a one-line manifest edit, not a code change.

5. **Add a §18 oracle assertion** — after a throwaway session, assert the host now has
   `file-history/<new-uuid>/` and `projects/<slug>/<new-uuid>.jsonl`. Silent upstream renames then
   surface as a failing test (red CI) instead of silent data loss.

## Ambiguous / out of scope

- `plans/*.md` — plan-mode artifacts carry no on-disk project key (random-slug filenames; project
  only referenced in content). Surfacing would require content inspection or mtime↔session
  correlation. Deferred.
- `shell-snapshots/` (timestamp-keyed) and `sessions/<number>.json` (terminal-group-keyed) — not
  cleanly mappable to a project. Not surfaced.

## Verification done

- `fd` skim of `~/.claude` top two levels (dirs + root files).
- Confirmed session-UUID keying of `file-history/`, `session-env/`, `tasks/` by sampling entries.
- Confirmed `projects/<slug>/<uuid>.jsonl` filename = session UUID (carries `sessionId`).
- Confirmed `history.jsonl` line schema carries `"project"` + `"sessionId"`.
- Confirmed dual-slug evidence (`-home-mcrowe-…` and `-container-mcrowe-…`) in `projects/`.
- `todos/` empty on this host but session-keyed by design (noted, not assumed populated).
`````

## File: docs/research/home-folder-harness-history-overview.md
`````markdown
# Surfacing harness project history — cross-harness overview & plan

**Status:** living index
**Date:** 2026-06-22
**Scope:** how each AI-coding harness stores per-project history in the user's home dir, and how an
**isolated** harnessed stack surfaces that history back to the host's global store (the harness's
config stays isolated; only *history* is surfaced).

This is the index for the per-harness research docs and the playbook for onboarding new harnesses.

## Documents

| Harness | Home root | Doc | Status |
|---------|-----------|-----|--------|
| Claude Code | `~/.claude/` | [home-folder-claude-requirements.md](home-folder-claude-requirements.md) | ✅ researched |
| omp | `~/.omp/` | [home-folder-omp-requirements.md](home-folder-omp-requirements.md) | ✅ researched |
| antigravity | `~/.gemini/antigravity-cli/` | [home-folder-antigravity-requirements.md](home-folder-antigravity-requirements.md) | ✅ researched |
| opencode | `~/.config/opencode/` + `~/.local/share/opencode/` (to confirm) | _this doc, §Planned_ | ⏳ to investigate |
| codex | `~/.codex/` | _this doc, §Planned_ | ⏳ to investigate |
| gemini-cli | `~/.gemini/` (proper) | — | ⏳ if surfaced (note: antigravity nests *under* this but is separate) |
| _future_ | — | — | follow §Onboarding |

## The invariant decisions (apply to every harness)

These held across all three researched harnesses and are the defaults for any new one.

1. **Path mirroring.** Run the container working dir at the **identical absolute host path**. Every
   harness embeds the cwd somewhere that matters — in the project-slug (Claude), in transcript
   `cwd` fields (all three), or as the `workspace` key (antigravity, omp `history`). Mirroring makes
   the slug/key line up *and* keeps embedded paths host-valid (clickable refs, actionable rewind),
   *and* makes DooD `-v $PWD:$PWD` translation-free (§15). Decided once, applies everywhere.

2. **Classify every path into exactly one of: history / config / cache / auth.** Only **history** is
   surfaced. Config comes from the committed profile; cache/runtime is rebuilt in-container; auth is
   seeded separately and **never** surfaced.

3. **Mount files; export databases.** A bind-mount exposes a whole file with no per-project slice.
   - **File-per-unit, UUID/content-namespaced** (Claude `file-history/`, `projects/<slug>/`; omp
     `sessions/<slug>/`; antigravity `conversations/`, `brain/`, `implicit/`) → **whole-parent-dir
     rw mount is safe**: the container only ever writes *new* namespaced entries, never a second
     writer on an existing file. Also WAL-safe for per-unit SQLite.
   - **Shared single file** — a DB holding many projects' rows (omp `history.db`, `agent.db`) or a
     whole-file-rewrite/append JSON (`.claude.json`, `history.jsonl`, antigravity `cache/*.json`) →
     **never rw-mount** (lost-write race / WAL corruption / cross-project leak). Surface via a
     **guarded teardown merge/export** filtered by the project key, that **no-ops on schema
     mismatch** instead of corrupting the host store. Ship disabled until the format is pinned.

4. **Never bind-mount a store that co-locates auth.** omp's `agent.db` mixes `auth_credentials` with
   the thread index — the canonical trap. Verify each DB's tables before mounting.

5. **Make the mount/export set data-driven** — a per-harness manifest (host source → container dest,
   plus teardown-merge targets), not inline `-v` flags. An upstream layout change becomes a one-line
   manifest edit.

6. **Add a §18 oracle test per harness.** After a throwaway session, assert the host gained the
   expected new history artifact (new transcript file / DB / appended history line). Silent upstream
   renames then fail CI instead of silently losing data.

## Keying models compared

The single biggest cross-harness difference — it dictates the mount shape.

| Harness | Project key | Per-unit history storage | Surfacing shape |
|---------|-------------|--------------------------|-----------------|
| Claude | project-path slug (`-home-mcrowe-…`) | files: `projects/<slug>/*.jsonl` + UUID-keyed sibling dirs (`file-history/`, `tasks/`, …) | mount slug dir (remapped→mirrored) + whole UUID dirs; merge `history.jsonl` |
| omp | `$HOME`-relative path slug (`-Programming-…`) | files: `sessions/<slug>/` **+ shared SQLite** (`history.db`, `agent.db`) | mount `sessions/<slug>/`; export `history.db` by `cwd`; **never** touch `agent.db` (auth) |
| antigravity | `workspace` path string | **one SQLite file per conversation** (`conversations/<cid>.db`) + `brain/<cid>/` + `implicit/<cid>.pb` | whole-dir mount of those three (UUID-safe); merge `history.jsonl` + `cache/*.json` |
| opencode | _TBD_ | _TBD_ | _TBD_ |
| codex | _TBD_ | _TBD_ | _TBD_ |

Observations that likely generalize:
- A **global prompt log** keyed by cwd/workspace recurs in every harness (Claude `history.jsonl`,
  omp `history.db`, antigravity `history.jsonl`). Expect one; expect to merge it by project key.
- **Auth is always its own concern** — sometimes a discrete file (Claude `.credentials.json`,
  antigravity `antigravity-oauth-token`), sometimes fused into a DB (omp `agent.db`). Always locate
  it first.
- "rollout" + `<timestamp>_<uuid>.jsonl` (omp) is **OpenAI Codex lineage** — codex likely shares
  this format, so omp's findings are the best prior for codex (see Planned).

## Mount-decision flowchart (per path)

```
For each path under the harness home root:
  ├─ Is it auth/secret?            → DO NOT surface (seed separately)
  ├─ Is it config?                 → DO NOT surface (profile provides)
  ├─ Is it cache/log/runtime?      → DO NOT surface (rebuilt in-container)
  └─ Is it history?
       ├─ file-per-unit, UUID/content-namespaced?  → whole-parent-dir rw mount (safe)
       ├─ project-path-keyed dir?                  → mount that dir, mirrored path (safe)
       └─ shared single file (DB or rewrite/append JSON)?
            ├─ co-locates auth?  → NEVER mount; export only the project's rows on teardown
            └─ else             → guarded teardown merge/export, filtered by project key
```

## Planned harnesses

> Treat the layouts below as **hypotheses to verify**, not facts. Known config/auth paths come from
> the project's CLAUDE.md harness wiring; history layout is unconfirmed until investigated.

### opencode (`~/.config/opencode/` + likely `~/.local/share/opencode/`)

- **Known (config/auth):** MCP wired via image-baked `~/.config/opencode/opencode.json` → hatago.
  Consumes `.claude/skills/**` + `~/.claude/CLAUDE.md` natively (no bridge). Auth typically
  `~/.local/share/opencode/auth.json` *(verify)*.
- **To investigate:** where session/message history lives (suspected `~/.local/share/opencode/` —
  opencode keeps project storage there, possibly SQLite or per-project JSON). Confirm project keying
  (path slug vs id), whether auth is a discrete file vs DB-fused, and the global-history location.

### codex (`~/.codex/`)

- **Known (config/auth):** `~/.codex/config.toml` (MCP `[mcp_servers.hatago]` → Streamable-HTTP),
  `~/.codex/auth.json` (mounted ro), `~/.codex/prompts` (its prompt format).
- **To investigate (strong prior = omp, which is Codex-lineage):** expect rollout transcripts at
  `~/.codex/sessions/…/rollout-<ts>-<uuid>.jsonl` (possibly date-bucketed) and a global
  `~/.codex/history.jsonl`. Confirm whether sessions are date-bucketed or path-slug-keyed (decides
  whether per-project filtering needs a `cwd` scan, as omp's empty-`threads` case showed), and
  whether any SQLite index co-locates auth.

### Investigation command template (run per new harness)

Same pattern used for the three researched harnesses (adapt `ROOT`; prepend `ssh <host>` if remote,
run via the `!` prefix since `ssh` is permission-denied to the agent):

```
ROOT=~/.codex   # or ~/.config/opencode, ~/.local/share/opencode, …
echo "=== tree (depth 3) ==="; find $ROOT -maxdepth 3 2>/dev/null | head -100
echo "=== 15 newest files ==="; find $ROOT -type f -printf "%TY-%Tm-%Td %TH:%TM  %p\n" 2>/dev/null | sort -r | head -15
echo "=== any SQLite? list tables (watch for auth_* alongside history) ==="; \
  for db in $(find $ROOT -name '*.db' 2>/dev/null); do echo "-- $db"; sqlite3 "$db" ".tables"; done
echo "=== global prompt log? does it carry cwd/workspace? ==="; \
  find $ROOT -name 'history*.jsonl' -exec head -2 {} \;
```

Then write `home-folder-<harness>-requirements.md` following the established template (Tell /
Keying model / Layout table / Mount guidance / Risks / Verification done) and add a row to the
Documents table above.

## Onboarding checklist for a new harness

1. Locate the home root and run the investigation template.
2. Compare newest mtimes across sibling trees to catch shared-vs-separate state (the antigravity
   "tell").
3. **Find auth first** — discrete file or DB-fused? Mark it never-surface.
4. Classify every path (history / config / cache / auth).
5. Identify the **project key** (path slug? id? `workspace` string?) and the **per-unit storage**
   (files? per-unit DB? shared DB?).
6. Apply the flowchart → produce the mount list + teardown-merge list.
7. Add the data-driven manifest entry + the §18 oracle assertion.
8. Write the per-harness doc; update this index.
`````

## File: docs/research/home-folder-omp-requirements.md
`````markdown
# Surfacing omp (`~/.omp`) project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Companion to:** [home-folder-claude-requirements.md](home-folder-claude-requirements.md)
**Decision:** Surface per-project history by mounting the **file-based** `agent/sessions/<slug>/`
tree (mirrors the Claude `projects/` approach). The **SQLite** stores are handled by a guarded
teardown export filtered on `cwd` — **never bind-mount `agent.db`** (it co-locates auth
credentials). Run the container at the host project path (path mirroring), same as Claude.

## Headline difference from Claude Code

Claude stores all per-project history as **files** (`projects/<slug>/*.jsonl` + UUID-keyed dirs).
omp is a **hybrid**:

- Per-project conversation transcripts + tool logs are **files** under `agent/sessions/<slug>/` —
  cleanly mountable per-project. ✅
- Global prompt history, the resume/thread index, auth, settings, usage, and cache live in
  **shared SQLite DBs** (`history.db`, `agent.db`, `models.db`) with WAL. You **cannot** slice one
  project's rows out of a shared DB with a bind-mount, and one of those DBs (`agent.db`) holds
  **auth credentials** next to the thread index. ⚠️

So: mount the files, export the DB slices.

## Layout of `~/.omp` (skimmed 2026-06-22)

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `agent/sessions/<slug>/` | History — rollout `<ts>_<uuid>.jsonl` transcripts + per-session tool-log subdirs (`N.read.log`, `N.bash.log`, `N.async.log`, named `.jsonl`) | **project path slug** (`$HOME`-relative) | **Yes — mount** |
| `agent/blobs/` | History-adjacent — content-addressed pasted-image store (`<sha>` + `<sha>.webp/png/jpg`), referenced by transcripts | content hash (global, shared) | Optional (mount whole if you want image refs to resolve) |
| `history.db` (+ `-shm`/`-wal`) | History — global prompt log: `(prompt, created_at, cwd, session_id)` + FTS5 | shared DB, `cwd` column | **Yes — teardown export by `cwd`**, not mount |
| `agent.db` (+ `-shm`/`-wal`) | **MIXED** — `threads` (resume index: `id, rollout_path, cwd, source_kind`), **`auth_credentials`**, `settings`, `usage_*`, `cache`, `jobs`, `model_usage`, `stage1_outputs` | shared DB | **No — never bind-mount** (auth co-located). See thread-index note. |
| `models.db` (+ `-shm`/`-wal`) | Model catalogue cache | — | No |
| `agent/config.yml`, `agent/mcp.json`, top-level `mcp.json` | Config | — | No (profile provides these) |
| `agent/skills` | Config — **symlink** → `../../.agents/skills` (host shared skills) | — | No (and a symlink that would dangle in-container) |
| `agent/terminal-sessions/pts-N` | Ephemeral tty session state | pts/tty number | No |
| `context-mode/` | context-mode MCP plugin's own session DBs | hash | No (plugin-managed) |
| `logs/`, `natives/`, `gpu_cache.json`, `install-id` | Logs / native-binary cache / GPU cache / install identity | — | No |

## Keying details (verified)

### Slug derivation is `$HOME`-relative, not absolute

omp strips `$HOME` from the cwd, then maps `/`→`-`. Evidence from `agent/sessions/`:

```
/home/mcrowe/Programming/Personal/code-container  →  -Programming-Personal-code-container
/tmp                                              →  -tmp   (no $HOME prefix → kept absolute)
```

Consequence: as long as the project sits at the **same path relative to `$HOME`** inside the
container, the slug matches the host's — even if container `$HOME` differs. But the rollout
transcripts still embed the **absolute** cwd (confirmed:
`"cwd":"/home/mcrowe/Programming/Personal/code-container"` inside a `sessions/.../*.jsonl`), so for
host-coherent file references the same path-mirroring decision as Claude applies: **run the
container at the identical absolute host path.** That makes both the slug *and* every embedded path
line up.

### The SQLite stores are genuinely shared (multi-project)

- `history.db`: **501 rows across 13 distinct `cwd`s** on this host — one global table, filterable
  by `cwd`. The omp analogue of Claude's global `history.jsonl`.
- `agent.db` `threads`: index of `(id, rollout_path, cwd, source_kind)` — maps a thread to its
  rollout file and project. **Currently 0 rows on this host**, i.e. per-project resume operates off
  the on-disk `sessions/<slug>/` rollouts, not this index. (If a future omp build populates and
  *requires* `threads` for resume, surfacing history would also need a `cwd`-filtered export of
  thread rows — see Risks.)
- `agent.db` `auth_credentials`: **3 rows** — confirms secrets live in the same file as the thread
  index. This is why `agent.db` must never be bind-mounted to surface history.

## Why the DBs are export-not-mount

1. **No per-project slice.** A bind-mount surfaces a whole file; you can't expose only this
   project's rows of a shared table.
2. **Auth co-mingling** (`agent.db`). Mounting it rw would surface/persist credentials and merge
   container auth state into the host store — exactly the kind of leak the design forbids.
3. **WAL corruption risk.** These DBs run in WAL mode (`-shm`/`-wal` present). Bind-mounting a live
   SQLite file into a second writer (container omp while host omp may also run) risks corruption —
   the same hazard that rules out rw-mounting Claude's `.claude.json` and `history.jsonl`.

## Implementation guidance

1. **Path mirroring** (same decision as Claude): run the container working dir at the identical
   host absolute path. Slug + embedded cwd both line up.

2. **Mount the file-based per-project history** — same-path → same-path, no remap:
   ```
   --workdir /home/mcrowe/Programming/Personal/code-container \
   -v $HOST_OMP/agent/sessions/-Programming-Personal-code-container \
      :$CONTAINER_OMP/agent/sessions/-Programming-Personal-code-container:rw
   ```
   Surfaces rollout transcripts + per-session tool logs.

3. **(Optional) Mount `agent/blobs/` whole, rw** — content-addressed and collision-free, like
   Claude's UUID-keyed dirs. Only needed if you want pasted-image references inside surfaced
   transcripts to resolve. Read-side visibility of other projects' blobs is the only cost.

4. **`history.db` → guarded teardown export by `cwd`**, not a mount. After the session, copy this
   project's rows out and merge into the host `history.db` (e.g. `INSERT … SELECT … WHERE cwd =
   '<project>'`). Wrap so a schema mismatch logs and no-ops rather than corrupting the host DB —
   parallel to Claude's guarded `history.jsonl` merge. Ship disabled until the schema is pinned.

5. **`agent.db` → do not mount; do not auto-export.** It is auth + settings + usage + (empty)
   thread index. Leave the container with its own fresh `agent.db` (auth seeded by the profile's
   own mechanism). Revisit only if a future omp build makes `threads` mandatory for resume.

6. **Data-driven mount manifest + §18 oracle test**, same as Claude: list the omp paths in config,
   and after a throwaway session assert the host now has a new
   `agent/sessions/<slug>/<ts>_<uuid>.jsonl`. A silent upstream layout change then fails CI instead
   of losing data.

## Risks / open questions

- **Thread index may become load-bearing.** `agent.db.threads` is empty today, so file-based resume
  works. If omp starts requiring it, file-only surfacing would list transcripts the harness can't
  resume — would need a `cwd`-filtered thread-row export added to teardown.
- **Concurrent host omp.** If the user runs omp on the host while a container omp runs the same
  project, the teardown `history.db` merge must tolerate concurrent writers (transaction + retry).
  The file `sessions/` mounts are append-only-by-new-file, so they don't race.
- **`models.db`** intentionally not surfaced — it's a cache; the container rebuilds it.

## Verification done

- `fd` skim of `~/.omp` to depth 3.
- Confirmed `agent/sessions/<slug>/` holds `<ts>_<uuid>.jsonl` rollouts + per-session tool-log
  subdirs; slug is `$HOME`-stripped (`-Programming-…`, `-tmp`).
- Confirmed rollout `.jsonl` embeds absolute `"cwd"`.
- `history.db`: schema `(prompt, created_at, cwd, session_id)` + FTS; 501 rows / 13 cwds (global,
  filterable).
- `agent.db`: `threads` schema `(id, updated_at, rollout_path, cwd, source_kind)`, **0 rows**;
  `auth_credentials` **3 rows** (secrets co-located).
- `agent/skills` is a symlink to host `.agents/skills`.
`````

## File: docs/comprehensive-development-plan.md
`````markdown
# Plan: Recipe Development Workflow, Tooling & Standardized QA

## Context

The repo has a landed Dockerfile-recipe model (Phase 8): a recipe is `recipes/<name>/recipe.yaml`
(+ optional `Dockerfile`); the assembler validates pin/harness-compat/no-raw-npm, emits a derived
stack image, and gates on a supply-chain scan. `docs/RECIPE-STRESS-TEST.md` scopes **11 real-world
packages** to turn into recipes. The ask is to plan **how these get developed repeatably**:

1. a standardized test loop exercised as each recipe is authored;
2. a template + command that scaffolds a new recipe folder with stubs;
3. a Q/A policy on which harnesses each recipe is tested against.

End state: the maintainer can develop the 11 recipes against one loop, and an external contributor
can clone, run `harnessed new recipe`, author, self-test against a defined matrix, and open a PR
with a checklist — with near-zero invented process.

**Scope chosen (by the user):** the workflow/tooling + two minimal prerequisite architecture slices
so every recipe *shape* is testable: (a) an `expect:` probe slice and the mount change that makes it
work for image-baked skills; (b) the `hooks:` assembler merge (GAP 2). Hindsight (multi-container,
GAP 7) and headroom proxy mode stay deferred — out of scope.

---

## What is and isn't testable today (grounding)

Verified in code this session:

- **MCP servers** declared under `mcp:` → asserted by `harnessed test` via hatago's `hatago://servers`
  resource (`capability.introspect_mcp`). Works today. serena/headroom/codebase-memory/tokensave are
  testable now.
- **Skills/commands fanned from `skills:`/`commands:`** into the profile → asserted by filesystem
  listing (`capability._fileext_from_filesystem`). Works today. `time`/`greet` prove it.
- **Skills baked into the image by a recipe `Dockerfile`** → **shadowed at runtime**:
  `lib/harnessed-isolated.sh:134-138` does `cp -a "$profile_dir/.claude" "$run_claude"` then mounts
  the whole dir, overwriting the image's `~/.claude/skills/`. And `schema.expected_capabilities`
  (schema.py:402) reads only `recipe.skills`/`recipe.commands`, never `recipe.expect`. So
  Dockerfile-baked skills are invisible **and** unasserted. (Phase 9/10 are unbuilt.)
- **`hooks:`** → parsed forward-only into `recipe.raw`; `emit.write_settings_json` (emit.py:64) writes
  only `permissions.allow`. Nothing merges recipe hooks into `settings.json` (GAP 2, unbuilt).
- **`expect:`** → flat `list[str]` (schema.py:123, load_recipe:217); not consumed by the oracle.
- **No `harnessed new recipe`** (only `new <stack>`, harnessed-cli.sh:60). No `recipes/_template/`.
  No PR template / CONTRIBUTING. Proof-stack convention is `<harness>-time`, not per-recipe.
- **Re-scan already exists** as `harnessed rescan` (`lib/harnessed-rescan.sh`, SEC-04): it iterates
  every `harnessed-*` image, `podman save`s each, and scans **online** against a fresh osv.dev DB
  (catches CVEs disclosed *after* build), exiting non-zero on any HIGH. The build-time scan
  (`build_stack` BLD-02b) is the offline counterpart. So "scan the images again" is an existing
  capability — the plan reuses it rather than adding a parallel `harnessed scan`.

---

## Naming convention (recipes, stacks, images, containers)

Composed names are **`<harness>_<recipe>[_<recipe>...]`** — the harness ALWAYS comes first, fields
separated by `_`, hyphens allowed *within* a name. Two separators are required because recipe names
legitimately contain `-` (e.g. `codebase-memory`); a single separator would make
`claude-codebase-memory-context-mode` unparseable. Examples: `claude_serena`,
`claude_codebase-memory_context-mode`, `codex_tokensave`.
- **Recipe names** match `[a-z][a-z0-9-]*` (lowercase, hyphen-ok, **no `_`**). Enforce in `new_recipe`
  (B2) and as an assembler validation — reject `_` so the field separator stays unambiguous. Verified:
  no existing recipe or stack uses `_`.
- **Harness names** are the fixed six (claude/omp/opencode/gemini/antigravity/codex) — no separators.
- **Stack → image → container** inherit the stack's separators: image `harnessed-claude_codebase-memory`,
  container `harnessed-claude_codebase-memory-<projhash>`. Docker's reference grammar permits `_`, and
  the `reference='harnessed-*'` glob + literal `harnessed-<stack>-` prefix match never parse on
  separators, so `_` in image/container names is safe.
- **Proof stacks** (C2) follow the same rule: `stacks/claude_serena/`, not `stacks/serena-claude/`.
- **Legacy** stacks (`tracer-time`, `codex-time`, …) predate the rule and are left as-is; new proof
  stacks follow `<harness>_<recipe>`.

## Approach

Five work groups. **A (prereq slices) and B (scaffold) are independent of each other and unblock
everything else.** C/D are workflow+docs (depend on A/B existing). E (the 11 recipes) applies the
loop and depends on A (for skill/tool/hooks shapes). Order within a group is the build order.
**Step 0 (persistence):** before any other work, write this plan verbatim to
`docs/comprehensive-development-plan.md` — the repo-side sibling of `RECIPE-STRESS-TEST.md` and
`recipe-adoption-gap-analysis.md` — so the canonical planning artifact is version-controlled.

### A. Prerequisite slices (make every recipe shape testable)

**A1 — Surface image-baked skills at runtime (the mount slice).**
Make image-baked `~/.claude/{skills,commands,agents,hooks,rules}` visible at runtime so the agent
and the capability test see them, **without** disturbing the existing per-instance history
persistence (whole-dir state dir under `XDG_STATE_HOME`).
- Edit `lib/harnessed-isolated.sh` at the create block (lines ~131-138): after the existing
  `cp -a "$profile_dir/.claude" "$run_claude"` (the `--fresh`/first-create branch), **also extract
  the image's baked extension dirs and merge them into `$run_claude`**:
  `cid=$(podman create ":latest" …)`, then for each of `skills commands agents hooks rules`:
  `podman cp "$cid:/home/harnessed/.claude/<sub>/." "$run_claude/.claude/<sub>/"` (merge), then
  `podman rm "$cid"`.
- Reuse the existing collision discipline: a leaf dir present in **both** the profile and the image
  is a build-time bug (the assembler already fail-fasts on `skills:` leaf collisions in
  `synclinks.LinkSyncer`); image dirs are additive. Do not fail the launch on overlap — warn and let
  the profile copy win (profile = authored truth).
- `--fresh` already re-runs this block, so tests are reproducible.
- **Fallback if `podman create/cp` proves fragile on a runtime**: instead seed at *build* time — the
  assembler extracts baked extension dirs from the freshly built `harnessed-<stack>` image into the
  committed profile during `harnessed build`. Same effect, different stage. Pick whichever the
  runtime supports cleanly; runtime-seed is preferred (keeps the profile config-only per the Phase 9
  end-state).

**A2 — `expect:` oracle + deterministic probes (the expect-probe slice).**
- **Schema** (`tools/harnessed/schema.py`): make `expect` structured. In `load_recipe` (L202-220),
  accept either a flat list (back-compat → treated as skills) or a dict `{skills: [...], tools: [...]}`.
  Add `Recipe.expect_skills: list[str]` and `Recipe.expect_tools: list[str]` (replace the flat
  `expect` field). Update the `recipes/gstack/recipe.yaml` fixture from `expect: [gstack-skill]` to
  `expect: {skills: [gstack-skill]}`.
- **Oracle** (`schema.expected_capabilities`, L402): extend `Capabilities` with a `tools: list[str]`
  field; populate it from `recipe.expect_tools`; extend `skills` to include `recipe.expect_skills`
  (unioned with fanned `recipe.skills` leaf names).
- **Probes** (`tools/harnessed/capability.py`): skills already work via `_fileext_from_filesystem`
  (L492) once A1 lands. **Add** a deterministic tool probe: `_tools_present(instance, tools)` runs
  `command -v <tool>` per expected tool through `_exec` (L179); present iff exit 0. Wire into
  `introspect` (L511) and `build_report` (L124). Add a `TOOL` capability kind constant.
- **Report** (`tools/harnessed/report.py` + the `--json` dict in `CapabilityResult.to_dict`): add the
  tool row (name / kind=tool / present / detail = which `command -v` failed).
- **Out of scope:** the LLM "ask-the-agent with negative control" probe (milestone §6 / Phase 10).
  Deterministic filesystem+PATH assertion is the minimal smoke check `expect:` is meant to be
  (milestone Key Decision 10). Noted as future hardening, not built here.

**A3 — `hooks:` assembler merge (GAP 2).**
- **Schema** (`schema.py`): add a `Hook`/`HookEvent` model and parse `recipe.hooks` (claude-canonical
  shape: event name → list of `{matcher, command}`) out of `raw` into `Recipe.hooks: dict[str,
  list[HookEntry]]`. Malformed entries raise `SchemaError` (fail-fast), matching existing parsers.
- **Merge** (`tools/harnessed/assemble.py`, new `_merge_hooks(recipes)` beside `_merge_servers`
  L46): deep-merge per event across recipes; a duplicate `(matcher, command)` from two recipes raises
  `CollisionError` (mirrors `_merge_servers`'s name-collision rule).
- **Emit** (`emit.write_settings_json`, L64): accept the merged hooks and emit Claude Code's
  `settings.json` hook format: `{"hooks": {"PreToolUse": [{"matcher": "...", "hooks": [{"type":
  "command", "command": "..."}]}], …}}` alongside the existing `permissions`. Hook *scripts* (the
  `command:` binaries, e.g. `context-mode`, `agentmemory-hook`) are image-baked by each recipe's
  Dockerfile; assert their presence via `expect.tools` (A2).
- **Harness scope:** claude + omp (omp consumes the same `settings.json` via the bridge). The recipes
  that need hooks (context-mode, hyperpowers, agentmemory) declare `harnesses: [claude, omp]`, so
  per-harness hook-format generation is out of scope.

### B. Recipe scaffolding (Q2)

**B1 — `recipes/_template/` reference.**
Ship a human-browseable, fully-commented reference: `recipes/_template/recipe.yaml` (every field
with a one-line purpose), `recipes/_template/Dockerfile` (pinned-clone skeleton with `ARG HARNESS` +
`ARG <NAME>_REF`), and `recipes/_template/skills/.keep`. This is the copy source for the no-command
path and the single schema reference.

**B2 — `harnessed new recipe` command.**
- **Parser** (`harnessed` launcher, the `new)` block L152-172): after the existing stack parsing,
  detect `new recipe <name> [--type mcp|skills|service] [--harnesses a,b]` and dispatch to a new
  `new_recipe` (in `lib/harnessed-cli.sh`, beside `new_stack` L60). Keep `new <stack>` working
  unchanged (disambiguate on the second token: `recipe` → recipe, else stack).
- **`new_recipe` behavior:** validate `<name>` matches `[a-z][a-z0-9-]*` (no `_` — see Naming
  convention) and the harness list against the 6 (`claude|omp|opencode|gemini|antigravity|codex`);
  refuse to overwrite `recipes/<name>/`; write type-tailored stubs via
  heredoc (mirrors `new_stack`'s style):
  - `--type mcp` → `recipe.yaml` with an `mcp.servers[]` stdio stub + a `Dockerfile` install stub.
  - `--type service` → `recipe.yaml` with `mcp.servers[].service` + note that `services/<name>/` must
    be authored (link to `docs/guides/service-authoring.md`).
  - `--type skills` (default) → `recipe.yaml` with `skills: [{path: skills/<name>-helper}]` + a
    `skills/<name>-helper/SKILL.md` stub (frontmatter `name`+`description`).
  - Always include `harnesses:` (default per type: mcp/service → all 6; skills → `[claude, omp]`)
    and an `expect:` block matching the type, so the test oracle is non-vacuous from the start.
- **Also scaffold a default proof stack** `stacks/claude_<name>/stack.yaml` (`harness: claude`,
  `recipes: [<name>]`) so `harnessed build claude_<name>` + `harnessed test claude_<name>` work
  immediately. Refuse overwrite if it exists.

### C. Standardized dev loop + Q/A matrix (Q1 + Q3)

**C1 — The loop (documented + enforced by tooling):**
scaffold (`harnessed new recipe`) → author (`recipe.yaml` + `Dockerfile`/`skills/`) → proof stack
exists by default → `harnessed build claude_<name>` (validates pin/harness/npm + scans) →
`harnessed test claude_<name>` (capability report) → read diagnostics, iterate → run the matrix (C4)
→ open PR with the checklist (D2).

**C2 — Proof-stack convention:** `stacks/<harness>_<recipe>/stack.yaml` (e.g.
`stacks/claude_serena/`, `stacks/codex_codebase-memory/`), per the Naming convention. The `new recipe`
command creates the claude one; contributors add one per additional declared harness.

**C3 — Tiered harness declaration + test breadth (the Q3 standardization).** Q/A tests a recipe
against **exactly the harnesses in its `harnesses:` list**, and the list is set by recipe shape:
- **Pure skill/command content** (claude-canonical; e.g. caveman, hyperpowers): `harnesses: [claude,
  omp]` (omp via the bridge). Test claude + omp.
- **MCP-only, harness-agnostic** (e.g. codebase-memory, tokensave): `harnesses:` = all 6 (or the
  maintainer's chosen subset). Test every listed harness.
- **Hybrid (skills + MCP)**: scope to the harnesses that consume skills — `[claude, omp]` — even if
  the MCP would run elsewhere; do not claim harness support the skill half can't deliver.
- **Service-backed** (agentmemory, gbrain): `[claude, omp]` unless the service is harness-agnostic.

**C4 — `harnessed qa` matrix subcommand (the release gate).**
A first-class subcommand — not a script, not `make` — so build/test/release automation is the same
CLI contributors already use. No new host dependency, and crucially **no arbitrary-code include**:
the per-recipe surface stays the sandboxed, scanned `recipe.yaml` (a contributed `recipe.yaml` can
only declare a pinned, scanned Dockerfile — it cannot run host shell at invocation time, the way an
auto-included `.mk` would). This is why `harnessed qa` was chosen over `make` + per-recipe `.mk`.
- **Launcher** (`harnessed`, a new `qa)` case parsed like `test)` at L96-103): `harnessed qa
  [--stack <name>] [--json] [--quick] [--keep]` consumes argv and dispatches to the Python tools CLI.
- **Runner** (`tools/harnessed/cli.py`, new `_run_qa` beside `_run_test` L139 + a `qa` subparser in
  `_build_parser`): auto-discover every proof stack (`stacks/*/stack.yaml`); for each, run the
  existing build gates (assemble + pin/harness/npm validation + scan via `assemble` + the `scan`
  module) then the capability test (`run_capability_test`) — **reusing the exact gates a single
  `harnessed build`+`test` applies, so there is no second code path to drift.** Aggregate per-stack
  pass/fail, render a markdown matrix (+ `--json` for CI), exit non-zero if any stack fails.
- **`--quick`** (container-free): validate every recipe manifest + `harnesses` declaration against
  the C3 shape rule + pin/npm lint, without launching containers — the fast CI gate. The full matrix
  (real containers per recipe) is the heavier pre-release gate; "validate before release" = `harnessed qa`.
- **`--stack <name>`** narrows to one proof stack for contributor self-test
  (`harnessed qa --stack claude_serena`).
- **Pre-release online re-scan** (folded in, not a new command): after each proof stack's build+test,
  run `run_image_scan_online` on the derived `harnessed-<stack>` image — the fresh-DB re-scan that
  catches CVEs disclosed since build (the build-time scan is offline). `--quick` skips it. This is
  "scan the images again before release," reusing the existing `scan-image-online` gate.
- **Scope `harnessed rescan`** with a new `--stack <name>` (or `--image <name>`) filter — today it
  scans the whole fleet — so a contributor re-scans a single recipe image:
  `harnessed rescan --stack claude_serena`. A one-arg narrowing of the `reference='harnessed-*'` loop
  in `harnessed_rescan_images` (lib/harnessed-rescan.sh:59).

### D. Onboarding + contributor flow

**D1 — `docs/guides/contributing-recipes.md`**: the adopt-an-external-system workflow (the 6-step
model already in `docs/recipe-adoption-gap-analysis.md`), the C1 loop, the C3 tiered-harness rule,
the `expect:` smoke-check guidance (pick names unlikely to be renamed upstream; it's a liveness
check, not completeness), and the supply-chain pin requirement (tag/SHA/release-URL; never a
floating branch — `validate_pin` rejects it). Cross-link from `docs/guides/recipe-authoring.md`.

**D2 — PR surface:** add `.github/pull_request_template.md` (recipe checklist: pinned source;
`harnessed build` green incl. scan; one proof stack per declared harness green via `harnessed qa`;
`harnesses:` matches the shape rule; `expect:` filled; no raw npm/npx) and a top-level
`CONTRIBUTING.md` that points at `contributing-recipes.md`.

### E. Develop the 11 recipes (apply the loop; tiered by architecture fit)

Per-recipe install detail lives in `docs/RECIPE-STRESS-TEST.md` — do not duplicate it here. Each
recipe delivers: `recipes/<name>/{recipe.yaml, Dockerfile or skills/}`, one proof stack per declared
harness, and a green `harnessed test` for each. Decisions per recipe:

| # | Recipe | Shape | `harnesses` | Oracle (`mcp` / `expect`) | Proof stacks | Depends on |
|---|--------|-------|-------------|---------------------------|--------------|------------|
| 1 | caveman | Dockerfile skills | claude, omp | `expect.skills:[caveman,caveman-compress,caveman-stats]` | claude, omp | A1,A2 |
| 2 | serena | stdio MCP (uvx) | claude, omp | `mcp:[serena]` | claude, omp | — |
| 3 | solidspec | Dockerfile tool + commands | claude, omp, opencode, codex, gemini | `expect.tools:[solidspec]` | claude + declared | A2 |
| 4 | tokensave | stdio MCP (cargo) | claude, omp, opencode, codex, gemini, antigravity | `mcp:[tokensave]`, `expect.tools:[tokensave]` | claude + declared | A2 (git hooks deferred) |
| 5 | codebase-memory | stdio MCP (binary curl) | all 6 | `mcp:[codebase-memory]`, `expect.tools:[codebase-memory-mcp]` | claude + declared | A2 + pin-URL note |
| 6 | headroom (MCP) | stdio MCP (pip) | claude, omp | `mcp:[headroom]` | claude, omp | — |
| 7 | agentmemory | service MCP + hooks + skills | claude, omp | `mcp:[agentmemory]`, `hooks`, `expect` | claude, omp | A3 + `services/agentmemory/` |
| 8 | gbrain | service MCP (PGLite) | claude, omp | `mcp:[gbrain]` | claude, omp | `services/gbrain/` |
| 9 | context-mode | stdio MCP + hooks | claude, omp | `mcp:[context-mode]`, `hooks` | claude, omp | A3 |
| 10 | hyperpowers | Dockerfile skills/commands + hooks | claude, omp | `expect.skills`, `hooks` | claude, omp | A1,A2,A3 |

**Build order (mirrors the stress-test tiers):**
1. E2 serena, E6 headroom — pure stdio MCP, testable today, prove the loop end-to-end with zero
   new slices. Do these **first**, before A, to validate the loop on green-field recipes.
2. A1 + A2, then E1 caveman, E3 solidspec, E5 codebase-memory, E4 tokensave — exercise image-baked
   skills/tools + binary pin.
3. A3, then E9 context-mode, E10 hyperpowers, E7 agentmemory (+ `services/agentmemory/`), E8 gbrain
   (+ `services/gbrain/`) — exercise hooks + service-refs.
4. **Deferred:** hindsight (needs GAP 7 multi-container compose-backed services — out of scope);
   headroom proxy mode (network intermediary — out of scope).

**Pin validation note for E5 (codebase-memory):** the binary is a GitHub release URL
(`releases/download/v<X.Y.Z>/…`). Confirm `schema.validate_pin` (L365) accepts a pinned release URL
(it rejects `--branch main/master`, `:latest`, `@latest`). If the regex over-matches the URL, extend
it to treat `releases/download/v<semver>/` as pinned (GAP 4) — a one-line regex tweak, called out in
`validate_pin`'s docstring.

---

## Critical files & anchors

- `tools/harnessed/schema.py` — `Recipe` (L116), `load_recipe` (L202), `expected_capabilities`
  (L402), `validate_pin` (L365). A2/A3 schema changes + the pin-URL check.
- `tools/harnessed/capability.py` — `expected_capabilities` (L115), `build_report` (L124),
  `introspect` (L511), `_fileext_from_filesystem` (L492), `_exec` (L179). A2 tool probe + oracle wiring.
- `tools/harnessed/emit.py` — `write_settings_json` (L64), `write_derived_dockerfile` (L108). A3 hooks
  emit.
- `tools/harnessed/assemble.py` — `assemble` (L84), the validation loop (L92-97), `_merge_servers`
  (L46). A3 `_merge_hooks` + hook validation in the loop.
- `lib/harnessed-isolated.sh` — create/mount block (L131-138). A1 image-skill seeding.
- `lib/harnessed-cli.sh` — `new_stack` (L60). B2 `new_recipe` sibling.
- `harnessed` (launcher) — `new)` parser (L152-172) + dispatch (L272). B2 `new recipe` routing.
- `recipes/_template/` (new), `recipes/gstack/recipe.yaml` (A2 fixture update), the `harnessed qa`
  subcommand (launcher `qa)` parser + `tools/harnessed/cli.py` `_run_qa`), `docs/guides/contributing-
  recipes.md` (new), `.github/pull_request_template.md` (new).

---

## Verification

Run from the repo root; podman required for the heavy legs.

- **Loop on a green recipe (do first):** `harnessed new recipe serena --type mcp` → tree + proof
  stack exist; author `recipes/serena`; `harnessed build claude_serena` (green, incl. scan);
  `harnessed test claude_serena` → `serena (mcp)` ✓. Proves B2 + C1 with no new slices.
- **A1 + A2 (image-baked skills now visible + asserted):** build `caveman`; before A1
  `harnessed test claude_caveman` does NOT list the baked skill; after A1+A2 it reports
  `caveman (skill)` ✓ and `caveman-compress (skill)` ✓. `harnessed test claude_solidspec` →
  `solidspec (tool)` ✓ via `command -v`.
- **A3 (hooks merged):** `harnessed build claude_context-mode` then
  `cat profiles/claude_context-mode/.claude/settings.json` contains a `hooks.PreToolUse` entry;
  `harnessed test` reports the hook binary present via `expect.tools`.
- **B2 no-overwrite / validation:** `harnessed new recipe serena --type mcp` a second time exits
  non-zero ("already exists"); `--harnesses foo` exits non-zero with the valid list.
- **C4 matrix:** `harnessed qa` runs every proof stack; with all recipes green it exits 0;
  break one `expect` entry → it exits non-zero naming the failing stack.
- **D2 PR template:** a new PR renders the checklist.
- **E coverage:** each of the 10 in-scope recipes has ≥1 green proof stack; the table's "Proof
  stacks" column is the acceptance list.

---

## Assumptions & contingencies

- **A1 mount approach is the riskiest step.** Preferred: runtime `podman create`/`podman cp` seed of
  image extension dirs into the per-instance state dir (additive, preserves history persistence). If
  that is fragile on docker/apple runtimes, fall back to build-time seeding during `harnessed build`
  (extract baked dirs from the derived image into the committed profile). Either achieves "image
  skills visible + asserted"; pick the one the runtime supports.
- **Degraded path if A1 slips:** skill-content recipes (caveman, hyperpowers) can temporarily ship
  their skill files as `skills:` dirs (fanned into the profile, testable today) instead of
  Dockerfile-baked. This mildly conflicts with the "don't vendor third-party data" principle
  (milestone KD 7), so it is a stop-gap only while A1 lands, not the destination.
- **`expect` flat→nested is a breaking schema change** but the only consumer is the `gstack` fixture
  (updated in A2). No external callers (no CI wired to `expect`).
- **Tiered harness testing (C3) means up to 6 builds for harness-agnostic MCP recipes.** Accepted per
  the chosen scope; the matrix runner parallelizes and `--quick` validates manifests without builds.
- **Hindsight and headroom-proxy stay deferred** (GAP 7 / network-intermediary). The plan does not
  pretend otherwise; "unblocks all 11" is read as "all recipe *shapes*", with hindsight explicitly
  out of scope.
`````

## File: docs/recipe-adoption-gap-analysis.md
`````markdown
# Recipe-adoption gap analysis

> **Purpose.** This document is the input to a milestone. It audits the gap between (a) what
> `harnessed`'s recipe system and authoring docs **can express today**, and (b) the intended workflow:
> **take an external system that already exists (e.g.
> [gstack](https://github.com/garrytan/gstack)) and install that system into a container, across
> harnesses.**
>
> It is **not** a rewrite of the guides — it is the precursor to one. §"Decisions resolved" records
> what the maintainer has already decided; §"Work remaining" is what the milestone must build.

## Framing principle (read first)

**Recipe adoption is an iterative, human-in-the-loop author → build → test → repeat loop — not a
zero-touch acquire.** A recipe is hand-authored (by a human + an LLM). The author reads the target
system's repo, decides the install shape per harness, encodes it in the recipe, and the
`harnessed build` / `harnessed test` cycle validates it. **These setups are not expected to be 100%
without some user work.** The tooling's job is to make the loop fast and give the author a clear
inventory to review — not to guarantee a fully-automated install of an arbitrary external system.

This reframes several gaps below: where automation is infeasible (e.g. guessing an MCP wiring from a
repo), the contract is "the prompt/tooling *helps*; the recipe designer *decides*."

## The adoption model (corrected)

Adopting an external system means, for one recipe:

1. **Author reads the repo** (its README / `AGENTS.md` / install docs — via defuddle/context) and
   determines the installation steps per harness.
2. **The recipe declares an install that runs inside the harness container.** Concretely: a per-stack
   **derived harness image** `FROM harnessed-<harness>` whose build runs the real installer
   (`git clone … && ./setup`, `bun install`, …). The installer's effects land **globally in the
   container** under `~/.claude` and `~/.agents` (in-container — **not** the host).
3. **Per-harness rule:**
   - `claude` → install per the claude instructions.
   - `omp` → **always** install per the **claude** instructions **and** ensure the omp-claude-bridge
     (`@drmikecrowe/omp-claude-hooks-bridge`) is present.
   - others → install to that harness's native path as the system documents (or, where the harness
     can't consume skills, MCP-only — see GAP-3).
4. **MCP is wired to hatago explicitly.** The installer's own global MCP registration (e.g. gstack's
   `claude mcp add gbrain`) runs **inside the harness container** and does **not** propagate to
   hatago (a separate container). So the recipe must **also** declare the server in `mcp.servers` so
   hatago exposes it at the single endpoint. The authoring prompt best-effort derives this wiring from
   the repo context; **otherwise the recipe designer wires it by hand.**
5. **Supply chain: the external repo is pinned (sha) and scanned** — non-negotiable.
6. **Test = an inventory dump**, not a deep capability assertion: a simple output from the running
   instance showing the **skills, commands, plugins, and MCP servers installed**. The author reviews
   it. (Testing is for the *system*; individual recipes are hand-written and hard to test deeply.)

### gstack, walked through this model

gstack is the proof case (grounded in its README +
[`AGENTS.md`](https://github.com/garrytan/gstack/blob/main/AGENTS.md) +
[`USING_GBRAIN_WITH_GSTACK.md`](https://github.com/garrytan/gstack/blob/main/USING_GBRAIN_WITH_GSTACK.md)):

- A repo + `./setup` installer. Claude path: `git clone … ~/.claude/skills/gstack && ./setup`. Needs
  **Bun** + Node. 40+ generated `SKILL.md` slash commands + ~50 `bin/gstack-*` scripts + compiled
  browser binaries.
- Multi-host: `./setup --host <agent>` fans skills to each native path (`~/.codex/skills`,
  `~/.config/opencode/skills`, `~/.cursor/skills`, …).
- A stateful MCP server, **gbrain** (`gbrain serve`, stdio) — needs a DB (`gbrain init`, PGLite or
  Supabase) + embedding keys (`VOYAGE_API_KEY`/`OPENAI_API_KEY`); self-registers via
  `claude mcp add gbrain`. gstack itself says other agents "can register `gbrain serve` manually."
- Runtime side effects: edits `CLAUDE.md`/`AGENTS.md`, locks under `~/.gstack/`, may provision
  Supabase.

Under the model above: an omp stack adding gstack → derived `FROM harnessed-omp`, `RUN`s the claude
install path, the bridge is already in the omp image, gbrain is declared in `mcp.servers` (because
`claude mcp add` inside the harness won't reach hatago), and `harnessed test` dumps the installed
skills/commands/MCP for review.

## Decisions resolved

The maintainer has decided the following (this section supersedes the original gap analysis's "open
decisions"):

| # | Decision | Source |
|---|---|---|
| D-1 | Adoption is **author → build → test → repeat**, not zero-touch. Tooling helps; designer decides. | Framing principle |
| D-2 | Install **globally in the container** under `~/.claude` **and** `~/.agents` (in-container, **not** host). | GAP-3/4 |
| D-3 | The installer **runs inside the harness container** — via a per-stack **derived harness image** (`FROM harnessed-<harness>` + the real installer). | GAP-6 |
| D-4 | **`harness === omp` ⟹ install per the claude instructions AND ensure the omp-claude-bridge is present.** Hard rule. | GAP-5 |
| D-5 | MCP is declared in `mcp.servers` so it reaches hatago; the installer's in-container self-registration does **not** propagate. Prompt derives it best-effort; designer wires otherwise. | GAP-7 |
| D-6 | External repos **must** be pinned (sha) and scanned. Non-negotiable. | GAP-8 |
| D-7 | Docs (guide + prompt) are **in scope for the plan** — the plan fixes them. | GAP-9 |
| D-8 | Test = a lightweight **inventory dump** (skills/commands/plugins/MCP installed). No deep per-recipe capability assertion. | GAP-10 |

## Work remaining (the milestone scope)

Each item states **Evidence**, **Impact**, and **What's needed**. Items marked **🔴 load-bearing**
shape the whole design.

### WR-1 🔴 — The `~/.claude` profile mount shadows image-baked skills (discovered constraint)

- **Evidence.** In a stack the harness container's `~/.claude/` is a bind-mount of a
  per-instance **copy** of the committed profile:
  [`lib/harnessed-isolated.sh:134-138`](../lib/harnessed-isolated.sh) —
  `cp -a "$profile_dir/.claude" "$run_claude"` then `-v "$run_claude:$CONTAINER_HOME/.claude:rw"`.
  A directory bind-mount **replaces** the image's `~/.claude/`, so anything an installer bakes into
  the derived harness image's `~/.claude/skills/` is **invisible at runtime.** `~/.agents`, by
  contrast, is **not** mounted, so image-baked `~/.agents/` survives.
- **Impact.** This directly complicates D-2/D-3: "install globally into `~/.claude` via a derived
  image" does **not** work as literally stated — the mount hides it. `~/.agents` survives but nothing
  today consumes it (no mount, and no harness reads `~/.agents` natively).
- **What's needed.** A decision on how adoption output is surfaced, e.g. one of:
  (a) run the installer in a build container and **fold its `~/.claude` + `~/.agents` output into the
  committed profile** (`profiles/<stack>/.claude` + a new `~/.agents` mount) so the existing mount
  picks it up; (b) change the `~/.claude` mount to an overlay/merge instead of a replace; (c) bake
  non-claude assets into the image's `~/.agents` (survives) and claude assets into the profile.
  This is the central implementation decision — see "Open questions."

### WR-2 — No per-stack derived harness image (the build pipeline can't run an installer)

- **Evidence.** Today the harness image is **shared** (`harnessed-base → harnessed-<harness>`), and
  only **hatago** is per-stack-derived (it bakes the stack's stdio servers —
  [`harnessed-common.sh:108-191`](../lib/harnessed-common.sh)). There is no mechanism for a recipe to
  contribute a Dockerfile fragment that extends the harness image and runs a real installer.
  [`tools/harnessed/assemble.py`](../tools/harnessed/assemble.py) imports only `synclinks` + `schema`
  and calls `syncer.fan()` — no image-derivation step.
- **Impact.** D-3 (run the installer inside the harness container) is unimplementable today. There is
  no `harnessed-<stack>` harness image, no build path that runs `bun install` / `./setup` and captures
  the result.
- **What's needed.** A per-recipe/per-stack **harness-image derivation** in the assembler: recipes can
  declare a build step (a `RUN`-able installer, pinned repo + sha) that produces a derived
  `harnessed-<stack>` image from `harnessed-<harness>`. This is the adoption equivalent of how hatago
  is already per-stack-derived.

### WR-3 — No `~/.agents` mount, and no consumption story

- **Evidence.** The launcher mounts `~/.claude` only
  ([`harnessed-isolated.sh:138`](../lib/harnessed-isolated.sh)); `~/.agents` is never mounted, and no
  harness reads `~/.agents` natively (each reads its own native path — gstack's `--host` flags prove
  this: `~/.codex/skills`, `~/.config/opencode/skills`, …). The user's prior host namespace
  `~/.agents` is not replicated in-container.
- **Impact.** D-2 ("install into `~/.agents`") has nowhere to land and nothing to read it. Combined
  with WR-1, the in-container `~/.agents` target needs both a mount and a defined consumer (or an
  explicit decision that `~/.agents` is the *store* and a fan step links it into each harness's native
  path).
- **What's needed.** Wire `~/.agents` into the launch path (a committed `profiles/<stack>/.agents`
  + mount), and define how it reaches each harness — either a fan/sync step into native paths, or a
  documented rule that non-claude harnesses are MCP-only.

### WR-4 — No harness-conditional recipe logic

- **Evidence.** A recipe is harness-agnostic today; the harness difference is only in *how each reads
  the same profile* ([`schema.py:27-40`](../tools/harnessed/schema.py);
  [`stacks.md:44-51`](guides/stacks.md)). The recipe schema has no per-harness sections.
- **Impact.** D-4 (omp ⟹ claude install + bridge) and the general "claude does X, others do Y"
  branching are unexpressable. An adoption recipe would silently install the wrong variant, or omit
  the bridge for omp.
- **What's needed.** A recipe construct for harness-targeted install directives (resolved at assemble
  time against `stack.harness`), including the hard rule that omp always selects the claude install
  path + bridge.

### WR-5 — omp-bridge enforcement must be hard, not implicit

- **Evidence.** The bridge exists and works (`@drmikecrowe/omp-claude-hooks-bridge`, declared by
  [`recipes/omp/recipe.yaml`](../recipes/omp/recipe.yaml), baked image-time in
  [`base/Dockerfile.harnessed-omp`](../base/Dockerfile.harnessed-omp)). But a recipe can't *declare*
  "I need the bridge when harness=omp" — it relies on the stack author remembering the `omp` recipe.
- **Impact.** D-4 is currently a convention, not an enforced rule. An omp stack that adopts an
  external system but forgets the `omp` recipe breaks at runtime with no build-time signal.
- **What's needed.** Make `harness === omp` **always** pull the claude install path + the bridge,
  enforced at assemble time (not the stack author's responsibility). Reconcile naming
  ("omp-claude-bridge" vs `@drmikecrowe/omp-claude-hooks-bridge`).

### WR-6 — MCP-to-hatago wiring has no procedure / no interception

- **Evidence.** The decision guide (stdio-light vs service) exists in
  [`recipe-authoring.md`](guides/recipe-authoring.md) but has no adoption procedure, and nothing
  intercepts an installer's self-registration (`claude mcp add …` → `~/.claude.json` inside the
  harness), which never reaches hatago ([`harnessed-design.md:70-74`](harnessed-design.md)). gstack's
  gbrain is also a **stateful** server (DB + keys + init) — a service candidate, not a light stdio
  child.
- **Impact.** D-5 is currently all-manual with no guidance. An adopter following the external
  system's own MCP instructions ends up with a server reachable only inside the harness container,
  bypassing the hatago endpoint the rest of the stack assumes.
- **What's needed.** An "adopt an MCP server" procedure in the guide (classify → declare in
  `mcp.servers` or as a `service:` → intercept/redirect self-registration), leaning on the existing
  service-authoring path ([`service-authoring.md`](guides/service-authoring.md)) for stateful servers
  like gbrain. Best-effort automated derivation in the prompt; manual fallback by the designer.

### WR-7 — Supply-chain pinning/acquisition is unbuilt (must be built — D-6)

- **Evidence.** BLD-02/BLD-03 scan recipe sources + declared deps
  ([`schema.py:299-345`](../tools/harnessed/schema.py)). There is no repo+sha pinning and no scan of
  an externally-cloned tree; the designed `vendor-plugin` git-subdir+sha was never built. The pnpm/npm
  lint doesn't reach inside an external installer that shells `bun install`/`npm install`.
- **Impact.** D-6 ("it must") is currently unenforceable. Adopting a system that clones further repos
  / builds native code bypasses the project's headline safety property.
- **What's needed.** First-class `{repo, sha, subdir}` acquisition as a scanned, pinned input; a
  decision on how installer-pulled transitive deps are audited. Ties to WR-2 (the derived-image build
  is where acquisition + scan happen).

### WR-8 — Docs + prompt describe the wrong problem (D-7: plan fixes them)

- **Evidence.** [`recipe-authoring.md`](guides/recipe-authoring.md) and
  [`recipe-authoring-prompt.md`](prompts/recipe-authoring-prompt.md) are framed "author ONE recipe
  from scratch." The prompt's brief assumes *you* define the capability. Neither has an "adopt an
  external system" section, and the in-repo [`recipes/gstack`](../recipes/gstack) is the wrong
  artifact (a hand-written "methodology" summary, not an install).
- **Impact.** This is the direct cause of the wrong `recipes/gstack`. The docs produce
  approximations, not installs.
- **What's needed.** A new "Adopting an external system" doc + prompt variant covering the six-step
  model above, gstack as the worked example, the defuddle-context-driven authoring loop, and an
  explicit correction of the `~/.agents` mental model (in-container global, not host). Reconcile
  `recipes/gstack` into a real adoption recipe (depends on WR-1..WR-7) or scope it explicitly.

### WR-9 — Test must emit the inventory dump (D-8)

- **Evidence.** [`capability.py`](../tools/harnessed/capability.py) derives expected capabilities from
  the manifest's declared recipes and asserts them. It is not built to *dump* whatever an external
  installer landed (skills/commands/plugins/MCP present in the running instance) for human review.
- **Impact.** D-8 (inventory dump) is not produced today.
- **What's needed.** A `harnessed test` output mode that lists, from the running instance, the
  skills/commands/plugins/MCP servers actually installed — the author's review artifact in the
  author→build→test loop. Keep it simple; do not attempt deep per-recipe behavioral assertion.

## Recommended milestone — "Phase 7: External-system adoption"

Mirrors the ROADMAP's phase/plan structure ([`ROADMAP.md`](../.planning/ROADMAP.md)).

**Goal.** As a stack author, I can add a recipe that *installs an external system* (repo + installer +
per-harness global install + MCP) into a container via an author→build→test loop, with sha-pinning,
an omp-bridge guarantee, and an inventory dump to review — gstack as the proof.

**Success criteria** (what must be TRUE):

1. A recipe can declare a pinned external repo + an installer that runs inside a per-stack **derived
   harness image** (`FROM harnessed-<harness>`), and `harnessed build` produces it (WR-2, WR-7).
2. The installer's global output is actually **visible at runtime** in `~/.claude` and/or `~/.agents`
   (WR-1's mount-shadow resolved; `~/.agents` wired in — WR-3).
3. `harness === omp` **always** installs the claude variant **and** the bridge, enforced at assemble
   time (WR-4, WR-5).
4. The system's MCP servers reach hatago (declared in `mcp.servers` / `service:`; self-registration
   redirected) (WR-6).
5. `harnessed test` emits an **inventory dump** (skills/commands/plugins/MCP installed) for the
   author to review (WR-9).
6. An "Adopting an external system" doc + prompt variant exist, `recipes/gstack` is a real adoption
   recipe (or explicitly scoped), and the `~/.agents` mental model is corrected (WR-8).

**Suggested plans** (one decision + waves):

- **07-00 (decision):** Resolve **WR-1** (how adoption output survives the `~/.claude` mount +
  reaches harnesses). *This is the load-bearing decision — see Open questions.*
- **Wave 1:** 07-01 per-stack derived harness image + pinned acquisition + scan (WR-2, WR-7) →
  07-02 harness-conditional logic + omp-bridge hard rule (WR-4, WR-5).
- **Wave 2:** 07-03 `~/.agents` wiring + adoption-output surfacing (WR-1 impl, WR-3) → 07-04
  MCP-to-hatago procedure + interception (WR-6).
- **Wave 3:** 07-05 inventory-dump test mode (WR-9).
- **Wave 4:** 07-06 docs + prompt + reconcile `recipes/gstack` (WR-8).

## Open questions (still need maintainer input)

1. **WR-1 — the `~/.claude` mount shadow.** When the installer runs in the derived harness image and
   writes to `~/.claude/skills`, the existing `~/.claude` profile mount
   ([`harnessed-isolated.sh:134-138`](../lib/harnessed-isolated.sh)) hides it. Which resolution?
   (a) fold installer output into the committed profile + add a `~/.agents` mount; (b) change the
   `~/.claude` mount to an overlay/merge; (c) bake only into `~/.agents` (survives) and route
   claude-class harnesses to read it. Recommendation: (a) — smallest change to the proven mount model.
2. **WR-3 — what consumes `~/.agents` in-container?** No harness reads it natively today. Is
   `~/.agents` a *store* that a fan step links into each harness's native path (reviving the
   `sync-plugin-links` idea, in-container), or is it only for harnesses that read it? For
   `gemini`/`antigravity`/`codex`, is external-skill adoption **MCP-only** (cheaper; matches what
   they consume), or do we add native fan targets?
3. **gbrain (WR-6).** Treat as a stateful **service sidecar** (DB + init + keys) rather than a light
   stdio child? If yes, gstack-on-harnessed = "gstack skills + gbrain service."
4. **`recipes/gstack` scope.** Replace the methodology-summary with a real adoption recipe (after
   WR-1..7 land), or keep a deliberately-scoped "methodology" recipe and add a separate full-adoption
   path?
`````

## File: docs/RECIPE-STRESS-TEST.md
`````markdown
# Recipe Stress-Test: 11 Real-World Packages

> **Purpose:** validate the recipe architecture (`.planning/RECIPE-ARCHITECTURE-MILESTONE.md`)
> against real packages. Each package is classified by recipe type, data model, and the specific
> challenges it surfaces. Gaps in the architecture are collected at the end.

---

## Classification Matrix

| Package | Type | Runtime | MCP? | Hooks? | Data store | Recipe shape |
|---|---|---|---|---|---|---|
| **serena** | MCP server | Python (uvx) | stdio | no | `.serena/` per-project | MCP recipe |
| **agentmemory** | MCP server + memory | Node (npm) | **HTTP :3111** | **yes (12)** | SQLite (0 external DBs) | **service + recipe** |
| **headroom** | compression proxy/MCP | Python (pip) | stdio or proxy | no | CCR cache (local files) | MCP recipe |
| **gbrain** | brain/MCP + daemon | Bun (TypeScript) | stdio + HTTP | no | PGLite or Postgres | **service + recipe** |
| **solidspec** | CLI + skills | Rust (cargo) | no | no | spec files in project | skills recipe |
| **codebase-memory-mcp** | MCP server | **C binary** | stdio | no | SQLite `.codebase-memory/` | MCP recipe (binary) |
| **context-mode** | MCP + hooks | Node (npm) | stdio | **yes (6)** | SQLite FTS5 | **MCP + hooks recipe** |
| **tokensave** | MCP server | Rust (cargo) | stdio | git hooks | libSQL `.tokensave/` | MCP recipe |
| **caveman** | skills only | Node (install) | no | auto-activate | none | skills recipe |
| **hindsight** | service sidecar | Docker (postgres) | network-native | no | Postgres volume | **existing service** |
| **hyperpowers** | skills + hooks | Shell/Markdown | no | **yes** | task docs in project | skills recipe |

---

## Per-Package Analysis

### 1. serena — semantic code intelligence MCP

**Repo:** `github.com/oraios/serena` · Python · MIT · 25.7K stars

**What it is:** MCP server providing IDE-level semantic code retrieval, editing, refactoring. Uses
language servers (LSP) for 40+ languages. Has a per-project memory system (`.serena/memories/`).

**Install:** `uvx --from git+https://github.com/oraios/serena serena start-mcp-server` (or
`pip install serena && serena start-mcp-server`).

**Recipe:**
```yaml
# recipes/serena/recipe.yaml
name: serena
description: Semantic code intelligence — IDE-level retrieval, editing, refactoring via LSP.
harnesses: [claude, omp]
mcp:
  servers:
    - name: serena
      command: uvx
      args: [--from, git+https://github.com/oraios/serena@v1.2.0, serena, start-mcp-server, --context, ide-assistant]
      transport: stdio
```
```dockerfile
# recipes/serena/Dockerfile
FROM harnessed-claude:latest
# No build step needed — uvx resolves at runtime via hatago.
# Language servers install lazily on first use (serena auto-installs them).
```

**Data model:** `.serena/` in the project directory — project config (`project.yml`) + memories
(`memories/*.md`) + language server cache. Persists via the project mount. Shared across stacks
that work on the same project.

**Challenge — language server binaries:** Serena auto-installs language servers on first use
(`pip install` / `npm install` per language). These need network access at runtime (or pre-baking
in the image). For offline-capable stacks, the recipe Dockerfile could pre-install common language
servers. For online stacks, serena handles it at runtime.

**Verdict:** Clean fit. stdio MCP server, hatago child. No hooks, no service. The only subtlety
is language server installation (runtime vs bake).

---

### 2. agentmemory — persistent memory server

**Repo:** `github.com/rohitg00/agentmemory` · TypeScript · Apache 2.0 · 23.8K stars

**What it is:** Persistent memory for AI coding agents. 53 MCP tools, 12 auto hooks, 15 skills.
Runs its own HTTP server on :3111. Built on the iii engine. Zero external databases (embedded).

**Install:** `npm install -g @agentmemory/agentmemory && agentmemory` (starts server on :3111).

**This package breaks the mold.** It's NOT a stdio MCP server — it's a long-running HTTP server
with its own port. It also installs hooks (PreToolUse, PostToolUse, SessionStart, etc.) and skills.
Three integration surfaces: MCP (HTTP), hooks, skills.

**Recipe shape — service + recipe:**
```yaml
# recipes/agentmemory/recipe.yaml
name: agentmemory
description: Persistent memory for AI coding agents — 53 MCP tools, auto hooks, session recall.
harnesses: [claude, omp]
mcp:
  servers:
    - name: agentmemory
      service: agentmemory          # → network-native, hatago URL-proxies to the service
      transport: http
      url: http://agentmemory:3111/mcp    # DNS name within the runtime group
hooks:
  # Merged into settings.json (hook scripts are image-baked by the Dockerfile)
  PreToolUse: [{ matcher: "*", command: "agentmemory-hook pre-tool" }]
  PostToolUse: [{ matcher: "*", command: "agentmemory-hook post-tool" }]
  SessionStart: [{ matcher: "*", command: "agentmemory-hook session-start" }]
expect:
  tools: [agentmemory]              # the server binary
  skills: [memory-recall]           # a smoke-check skill
```

The service definition (own image, own volume):
```yaml
# services/agentmemory/service.yaml
name: agentmemory
image: ghcr.io/rohitg00/agentmemory:latest    # or built from the recipe Dockerfile
port: 3111
volume: agentmemory-data
```

**Data model:** SQLite embedded store. Must persist across sessions (the whole point is persistent
memory). The service volume (`agentmemory-data`) handles this.

**Surfaces GAP 1 (HTTP-native MCP) and GAP 2 (hooks registration).** See Architecture Gaps below.

---

### 3. headroom — context compression

**Repo:** `github.com/headroomlabs-ai/headroom` · Python+Rust · Apache 2.0 · 47.8K stars

**What it is:** Compresses tool outputs, logs, RAG chunks before they reach the LLM. 60–95% fewer
tokens. Three modes: library, proxy, MCP server.

**Install:** `pip install "headroom-ai[all]"` or `npm install headroom-ai`.

**Recipe (MCP mode — simplest):**
```yaml
name: headroom
description: Context compression — 60-95% fewer tokens via smart routing + AST/code/prose compressors.
harnesses: [claude, omp]
mcp:
  servers:
    - name: headroom
      command: headroom
      args: [mcp]
      transport: stdio
```

**Challenge — the proxy mode.** Headroom can also run as a proxy (`headroom proxy --port 8787`)
that intercepts LLM API calls and compresses them in-flight. This is architecturally different
from an MCP server — it's a network intermediary between the agent and the LLM provider. Harnessed
doesn't currently model this (the harness talks directly to the LLM). Supporting proxy mode would
require routing the harness's LLM traffic through headroom, which is a network-level change.

**Verdict:** MCP mode is a clean fit (stdio, hatago child). Proxy mode is out of scope for now —
it requires a network-intermediary model that harnessed doesn't have.

---

### 4. gbrain — knowledge brain

**Repo:** `github.com/garrytan/gbrain` · TypeScript (Bun) · MIT · 23.9K stars

**What it is:** A knowledge brain for AI agents — synthesis, graph traversal, gap analysis. Can
run as stdio MCP (`gbrain serve`) or HTTP MCP (`gbrain serve --http`). Uses PGLite (embedded
Postgres, no server) or external Postgres/Supabase at scale.

**Install:** `bun install -g github:garrytan/gbrain && gbrain init --pglite`.

**Recipe shape — service + recipe (like agentmemory):**
```yaml
name: gbrain
description: Knowledge brain — synthesis, graph traversal, gap analysis across people/companies/ideas.
harnesses: [claude, omp]
mcp:
  servers:
    - name: gbrain
      service: gbrain
      transport: http
      url: http://gbrain:3112/mcp
expect:
  tools: [gbrain]
```

The service runs `gbrain serve --http` with a persistent volume for the PGLite database.

**Data model:** PGLite database (embedded Postgres). The brain accumulates knowledge over time —
this is long-lived personal data that MUST persist and grow. Service volume (`gbrain-data`).

**Challenge — the dream cycle.** GBrain runs a nightly "dream cycle" (cron jobs that enrich and
consolidate). This is a daemon, not an on-demand MCP server. It needs to run continuously. This
fits the service model (long-running container).

---

### 5. solidspec — spec-driven development

**Repo:** `github.com/jyjeanne/solidspec` · Rust · MIT · 6 stars (early)

**What it is:** CLI tool for multi-methodology spec-driven development. 7 workflows (minimal,
spec-driven, security-first, tdd-driven, intent-driven, apex-driven, intent-apex). Generates spec
files, plan files, task lists in the project repo.

**Install:** `cargo install solidspec` (from source — no binary releases yet).

**Recipe:**
```yaml
name: solidspec
description: Multi-methodology spec-driven development — spec → plan → tasks → implement → ship.
harnesses: [claude, omp, opencode, codex, gemini]   # registers slash commands for many agents
expect:
  tools: [solidspec]
```
```dockerfile
FROM harnessed-claude:latest
ARG SOLIDSPEC_REF=v0.1.0
RUN cargo install --git https://github.com/jyjeanne/solidspec --tag ${SOLIDSPEC_REF}
```

**Data model:** Spec files in the project repo (`spec.md`, `plan.md`, `tasks.md`). Managed by git.
No external data store.

**Verdict:** Clean fit. Pure CLI + skills recipe. No MCP, no hooks, no service. Like caveman.

---

### 6. codebase-memory-mcp — code intelligence (C binary)

**Repo:** `github.com/DeusData/codebase-memory-mcp` · C · MIT · 12.2K stars

**What it is:** MCP server that indexes codebases into a persistent knowledge graph. 158 languages
via tree-sitter. Single static binary, zero runtime dependencies. 14 MCP tools.

**Install:** `curl ... | bash` (downloads prebuilt binary from GitHub releases).

**Recipe:**
```yaml
name: codebase-memory
description: Code intelligence — 158-language knowledge graph via tree-sitter. Single binary, zero deps.
harnesses: [claude, omp, opencode, codex, gemini, antigravity]
mcp:
  servers:
    - name: codebase-memory
      command: codebase-memory-mcp
      transport: stdio
```
```dockerfile
FROM harnessed-claude:latest
ARG CBM_VERSION=1.2.0
RUN curl -fsSL "https://github.com/DeusData/codebase-memory-mcp/releases/download/v${CBM_VERSION}/codebase-memory-mcp-linux-amd64.tar.gz" \
    | tar xzf - -C /tmp && install -m 0755 /tmp/codebase-memory-mcp /usr/local/bin/ && rm -rf /tmp/*
```

**Data model:** SQLite database at `.codebase-memory/` in the project directory. Per-project index.
Persists via the project mount.

**Challenge — binary install via curl.** Not a package manager (pip/npm/cargo). The recipe
Dockerfile downloads from GitHub releases. The pin is the release version in the URL. The
assembler's pin validation needs to accept GitHub release URLs (not just git clone --branch).

**Verdict:** Clean fit for the Dockerfile model. Surfaces that pin validation must handle release
URLs, not just git refs.

---

### 7. context-mode — context window optimization

**Repo:** `github.com/mksglu/context-mode` · TypeScript · ELv2 · 18K stars

**What it is:** MCP server that sandboxes tool output (98% reduction), persists session memory
(SQLite FTS5), and enforces routing via hooks. 11 MCP tools + 6 hooks.

**Install:** `npm install -g context-mode` or Claude Code plugin marketplace.

**Recipe:**
```yaml
name: context-mode
description: Context window optimization — sandbox tools (98% reduction), session continuity, routing enforcement.
harnesses: [claude, omp]
mcp:
  servers:
    - name: context-mode
      command: context-mode
      transport: stdio
hooks:
  PreToolUse: [{ matcher: "Bash|Read|WebFetch", command: "context-mode hook claude-code beforetool" }]
  PostToolUse: [{ matcher: "*", command: "context-mode hook claude-code aftertool" }]
  PreCompact: [{ matcher: "*", command: "context-mode hook claude-code precompress" }]
  SessionStart: [{ matcher: "*", command: "context-mode hook claude-code sessionstart" }]
```

**Data model:** SQLite FTS5 session store. Per-session (deleted on fresh session). Persists during
a session across compactions.

**Surfaces GAP 2 (hooks registration).** The recipe needs to declare hooks that the assembler
merges into `settings.json`. The hook scripts (the `context-mode hook` commands) are image-baked.

---

### 8. tokensave — semantic code intelligence (Rust)

**Repo:** `github.com/aovestdipaperino/tokensave` · Rust · MIT · 246 stars

**What it is:** MCP server with pre-indexed semantic knowledge graph. 80+ MCP tools, 50+ languages.
libSQL graph DB. Also installs git hooks (post-commit, post-checkout for auto-sync).

**Install:** `cargo install tokensave` or `brew install` or prebuilt binaries.

**Recipe:**
```yaml
name: tokensave
description: Semantic code intelligence — 80+ tools, knowledge graph, 50+ languages, 100% local.
harnesses: [claude, omp, opencode, codex, gemini, antigravity]
mcp:
  servers:
    - name: tokensave
      command: tokensave
      transport: stdio
```
```dockerfile
FROM harnessed-claude:latest
ARG TOKENSAVE_VERSION=0.8.0
RUN cargo install tokensave --version ${TOKENSAVE_VERSION}
```

**Data model:** libSQL database at `.tokensave/` in the project directory. Per-project. Persists
via the project mount.

**Challenge — git hooks.** Tokensave installs post-commit/post-checkout git hooks for auto-sync.
In a container, these would need to be in the project's `.git/hooks/` dir. Since the project is
mounted, the hooks persist with the project. But installing them requires running `tokensave install --git-hook yes` which modifies the project's git config. This is a recipe Dockerfile step that
runs against the image (not the project) — the hooks would need to be installed at runtime
(per-project), not at build time.

**Verdict:** MCP recipe with a runtime hook-installation step. The git hooks are per-project
runtime setup, not image-bake.

---

### 9. caveman — token compression skill

**Repo:** `github.com/JuliusBrussee/caveman` · JavaScript · MIT · 76K stars

**What it is:** Claude Code skill that makes the agent talk concisely ("caveman"). Cuts ~75% of
output tokens. Pure skill — no MCP, no data, no hooks (auto-activates via skill activation).

**Install:** `curl ... | bash` (installs skill files into agent skills dirs).

**Recipe:**
```yaml
name: caveman
description: Token compression skill — cuts ~75% of output tokens by talking concisely.
harnesses: [claude, omp, opencode, codex, gemini]
expect:
  skills: [caveman, caveman-compress, caveman-stats]
```
```dockerfile
FROM harnessed-claude:latest
ARG HARNESS=claude
ARG CAVEMAN_REF=v2.1.0
RUN git clone --branch ${CAVEMAN_REF} --depth 1 https://github.com/JuliusBrussee/caveman.git /tmp/caveman \
    && cd /tmp/caveman && ./install.sh --host ${HARNESS} \
    && rm -rf /tmp/caveman
```

**Data model:** None. Pure skill.

**Verdict:** Cleanest possible recipe. Skills-only, exactly like gstack.

---

### 10. hindsight — memory/recall service (multi-container stack)

**URL:** `hindsight.vectorize.io` · Docker (AlloyDB Omni + app)

**What it is:** Memory and recall system for AI agents. The user has a complete working deployment
at `~/.config/hindsight/docker-compose.yml` — a 3-container docker-compose stack, NOT a single
sidecar.

**The real topology (from `~/.config/hindsight/docker-compose.yml`):**

``+hindsight-net (bridge)
  ├── db (google/alloydbomni:17)          Postgres + vector + ScaNN extensions
  │     port 5438, volume alloydb_data
  ├── alloydb-init (one-shot)             Creates database + CREATE EXTENSION vector, alloydb_scann
  │     depends_on: db (service_started)
  └── hindsight (ghcr.io/vectorize-io/hindsight)
        ports 8888 (API) + 9999 (MCP/control plane)
        depends_on: alloydb-init (service_completed_successfully)
        env: LLM keys, DB URL, tenant API key, rate-limit config
```

**Secrets:** varlock + 1Password (`.env.schema` with `op://` refs). Resolves:
- `ZAI_API_KEY`, `OPENROUTER_API_KEY` (LLM provider keys for reflect/consolidation)
- `HINDSIGHT_API_TENANT_API_KEY` (tenant auth — shared by API + control plane)
- LLM provider config (model, base URL, rate limits)

**Recipe (the MCP declaration — thin):**
```yaml
name: hindsight
description: Memory and recall — AlloyDB-backed persistent memory with AI reflect/consolidate.
harnesses: [claude, omp]
mcp:
  servers:
    - name: hindsight
      service: hindsight
      transport: http
      url: http://host.containers.internal:8888/mcp
```

**The real challenge — this is a multi-container stack, not a single sidecar.** The current service
model (`services/<name>/service.yaml`) assumes one image, one port, one volume. Hindsight needs:
- **2+ containers with a dependency chain** (db → init → app)
- **Multiple ports** (8888 API + 9999 control plane)
- **Secrets resolution** (varlock `op://` refs → env)
- **A specialized DB image** (AlloyDB Omni with vector + ScaNN extensions)
- **An init step** (CREATE DATABASE + CREATE EXTENSION)

**Surfaces GAP 7 (multi-container service stacks).** See Architecture Gaps below.

**How to turn the existing deployment into a recipe:**
The user has a working docker-compose stack. The cleanest path is:
1. The service definition wraps the existing compose file — `svc up hindsight` runs
   `docker compose -f ~/.config/hindsight/docker-compose.yml up -d` (with varlock secret resolution).
2. The recipe declares the MCP connection to the running stack.
3. The service model extends to support compose-file-backed services (not just single-image sidecars).

This is NOT just "extract an MCP declaration." The service model itself needs to grow to express
multi-container topologies with dependencies, init steps, and secrets.
---

### 11. hyperpowers — workflow skills

**Repo:** `github.com/withzombies/hyperpowers` · Shell/Markdown · MIT · 80 stars

**What it is:** Workflow guidance for Claude Code — task tracking, plan management, TDD, code
review, debugging skills. Skills + hooks + commands + agents. All markdown/shell.

**Install:** Claude Code plugin marketplace or git clone into `.agents/skills/`.

**Recipe:**
```yaml
name: hyperpowers
description: Workflow guidance — brainstorming, planning, TDD, code review, debugging skills.
harnesses: [claude]
expect:
  skills: [brainstorming, writing-plans, executing-plans, review-implementation, verification-before-completion]
```
```dockerfile
FROM harnessed-claude:latest
ARG HYPERPOWERS_REF=v0.3.0
RUN git clone --branch ${HYPERPOWERS_REF} --depth 1 https://github.com/withzombies/hyperpowers.git /tmp/hp \
    && cp -r /tmp/hp/.agents/skills/* /home/harnessed/.claude/skills/ \
    && cp -r /tmp/hp/.claude-plugin /home/harnessed/.claude/.claude-plugin \
    && rm -rf /tmp/hp
```

**Data model:** Task docs in the project (`plans/active/<slug>/`). Managed by git.

**Challenge — hooks.** Hyperpowers includes hooks (session-start context injection, skill
activation suggestions, stop-time reminders). These need `settings.json` hook registrations.

**Verdict:** Skills recipe with hooks. Like context-mode, surfaces GAP 2.

---

## Architecture Gaps Surfaced

### GAP 1: HTTP-native MCP servers (not stdio)

**Packages:** agentmemory (:3111), gbrain (:3112), headroom (proxy mode)

**Problem:** The hatago model wraps stdio MCP servers (spawn as child, stdio→HTTP). But some MCP
servers are themselves HTTP servers with their own ports. These can't be hatago children.

**Existing coverage:** The McpServer schema already has `transport: http`, `url`, and `service:`
fields. The hatago URL-proxy mode handles network-native servers. So the schema supports it.

**What's missing:** The recipe needs a way to declare that an MCP server runs as a service (not
a hatago child). The `service:` field + a `services/` entry handles this — but the recipe model
currently doesn't have a way to declare a service dependency. The recipe says "I need service X
running" and the stack composition ensures it.

**Resolution:** recipe.yaml `mcp.servers[].service: <name>` already references a service. The
stack's `services: [agentmemory]` list ensures the service starts. This works today — the gap is
just that no recipe has used it yet. **No architecture change needed, just a new recipe pattern.**

### GAP 2: Hooks registration ⚠️ (real gap)

**Packages:** agentmemory (12 hooks), context-mode (6 hooks), hyperpowers (hooks), tokensave (git hooks)

**Problem:** The recipe model has `mcp:` (merged into hatago config) and `expect:` (smoke check).
But several packages also install hooks — `PreToolUse`, `PostToolUse`, `SessionStart`, etc. — that
the harness discovers from `settings.json`. The recipe has no way to declare hooks.

**Why it matters:** Hooks are how tools like agentmemory and context-mode enforce their behavior
(auto-saving memories, sandboxing tool output). Without hooks, the MCP server is present but the
automatic behavior doesn't fire.

**Proposed resolution:** Add a `hooks:` field to recipe.yaml, merged by the assembler into the
profile's `settings.json`:

```yaml
# recipe.yaml
hooks:
  PreToolUse:
    - matcher: "Bash|Read|WebFetch"
      command: "context-mode hook claude-code beforetool"
  PostToolUse:
    - matcher: "*"
      command: "context-mode hook claude-code aftertool"
```

The assembler merges all recipes' `hooks:` into one `settings.json` (same merge model as `mcp:`).
The hook scripts themselves are image-baked by the recipe Dockerfile.

**Harness-specific hooks:** Different harnesses have different hook formats (Claude Code's
`settings.json` hooks vs omp's hook config). The `harnesses:` field scopes which harnesses a
recipe supports, and the assembler generates the right format per harness.

**This is the one real architecture gap.** It requires:
1. A `hooks:` field in recipe.yaml + the schema (`Recipe.hooks`)
2. Assembler merge logic (merge hooks across recipes into `settings.json`)
3. Harness-specific hook format generation (claude vs omp vs others)

### GAP 3: Per-project data stores (mostly handled)

**Packages:** serena (`.serena/`), codebase-memory-mcp (`.codebase-memory/`), tokensave (`.tokensave/`)

**Analysis:** Most of these create their data IN THE PROJECT DIRECTORY. Since the project is
mounted (rw), these persist naturally across container restarts. **No architecture change needed.**

**Edge case — tools that store data outside the project:** gbrain uses PGLite at a configurable
path. If configured to `~/.gbrain/`, it needs a mount. If configured to the project dir, it's
fine. The recipe Dockerfile or an env var can set the path. The data-driven mount manifest (§4c
of the milestone) can declare a tool-specific data mount if needed.

### GAP 4: Binary downloads (not package managers)

**Packages:** codebase-memory-mcp (GitHub release binary)

**Analysis:** The recipe Dockerfile handles this naturally: `RUN curl ... | tar xzf ... && install`.
The pin is the release version in the URL. The assembler's pin validation needs to accept pinned
release URLs, not just `git clone --branch <tag>`.

**Resolution:** Extend pin validation (ASM-02) to recognize GitHub release URL patterns
(`releases/download/v<X.Y.Z>/...`) as pinned. A floating `releases/latest` URL is rejected.
**Minor extension to ASM-02, not a new architecture concept.**

### GAP 5: The service-recipe boundary

**Packages:** hindsight (multi-container stack), agentmemory (HTTP server), gbrain (daemon + DB)

**Analysis:** The distinction is clear in principle:
- **stdio MCP server** → recipe (hatago child, spawned on demand)
- **HTTP/container/server** → service (own image, own volume, long-running)
- A recipe can reference a service via `mcp.servers[].service: <name>`

But the current service model (`services/<name>/service.yaml`: one image, one port, one volume)
is too simple for real-world services like hindsight (3 containers, dependencies, init step,
secrets). See GAP 7.

For simple HTTP MCP servers (agentmemory, gbrain in PGLite mode), the single-container service
model works. The gap is specifically multi-container stacks.

### GAP 6: Git hooks (per-project runtime setup)

**Packages:** tokensave (post-commit/post-checkout), potentially others

**Analysis:** Git hooks live in the project's `.git/hooks/` directory. They can't be baked into
the image (the project is mounted, not the image's git). They must be installed at runtime, per
project.

**Resolution:** The recipe can declare a "first-run" or "project-setup" step that installs git
hooks when the container starts against a new project. This is a runtime concern, not a build-time
one. The recipe Dockerfile installs the hook SCRIPTS in the image; a startup hook or the harness's
session-start mechanism installs them into the project's `.git/hooks/`.

**This is a minor gap** — it's a runtime setup pattern, not an architecture-level missing concept.
The hooks registration (GAP 2) could subsume this: a `SessionStart` hook that symlinks the
image-baked git hooks into the project.

### GAP 7: Multi-container service stacks ⚠️ (real gap)

**Packages:** hindsight (AlloyDB + init + app), potentially gbrain at scale (Postgres + app)

**Problem:** The service model assumes one image, one port, one volume. Hindsight's real topology
(from `~/.config/hindsight/docker-compose.yml`) is a docker-compose stack:

```
db (AlloyDB Omni) → alloydb-init (one-shot) → hindsight (app, 2 ports)
```

This needs:
- **Multiple containers with a dependency chain** (db must start before init, init must complete
  before app)
- **An init step** (CREATE DATABASE + CREATE EXTENSION vector, alloydb_scann)
- **Multiple ports** (8888 API + 9999 control plane)
- **Secrets resolution** (varlock `op://` refs → env vars, same as the harnessed secrets layer)
- **A specialized DB image** (AlloyDB Omni, not vanilla postgres)
- **Inter-container networking** (app reaches db via DNS name on a private bridge)

The current `service.yaml` schema (`name`, `image`, `port`, `volume`) cannot express this.

**Proposed resolution — compose-file-backed services:**

Extend the service model so a service can be backed by a docker-compose/podman-compose file
instead of a single image:

```yaml
# services/hindsight/service.yaml
name: hindsight
compose: docker-compose.yml          # ← compose file in the service dir (or a path)
port: 8888                           # primary port (for host.containers.internal reachability)
healthcheck: "curl -sf http://localhost:8888/health"
secrets: true                        # resolve ~/.config/hindsight/.env.schema via varlock
```

`svc up hindsight` runs `docker compose up -d` (with varlock-resolved env), waits for the
healthcheck, and the recipe's MCP declaration points at `host.containers.internal:8888/mcp`.

The user already has this working at `~/.config/hindsight/`. The service definition wraps the
existing compose file rather than reimplementing it. This is the "don't reinterpret the install"
principle applied to services — run the existing compose stack, don't rebuild it.

**Why this matters:** Real-world services (databases with extensions, multi-tier apps, init
scripts) are naturally multi-container. Forcing them into a single-image model would require
reimplementing their topology, which is exactly the "reinterpret the install" anti-pattern the
recipe model rejects.


## Additional Architecture Considerations

Three decisions the stress-test surfaced that need to be captured in the architecture spec.

### CONSIDERATION 1: Secret source pluggability (beyond 1Password)

**Surfaced by:** hindsight (`.env.schema` with `op://` refs), but every service with secrets.

Today harnessed wires varlock + 1Password exclusively. The `.env.schema` uses
`@plugin(@varlock/1password-plugin@0.3.2)` and `op(op://Vault/Item/field)` refs. But not every
operator uses 1Password.

**The `.env.schema` is already the interface — backends are pluggable.** The `@plugin` directive
is the extension point. Today's options:

| Secret source | How it works | Status |
|---|---|---|
| **1Password** | `@plugin(...1password-plugin)` + `op(op://...)` refs | Wired today |
| **Plain `.env` file** | No `.env.schema` → inert → plain env passthrough | Works today |
| **Literal values in schema** | `KEY=value` (no function call) → varlock resolves literal | Works today |
| **KeePassXC** | Needs a varlock plugin + `keepassxc(entry://...)` refs | Not wired — needs a plugin |
| **Bitwarden** | Needs a varlock plugin + `bw(...)` refs | Not wired |

The architecture spec should state: the secret resolution layer is pluggable via varlock
plugins. The `.env.schema` `@plugin` directive selects the backend. Operators who don't use
1Password can: (a) use plain `.env` files (no resolution), (b) use literal values in the schema,
or (c) write/use a varlock plugin for their password manager. Each service's `.env.schema`
declares its own plugin — different services can use different backends.

**Two distinct host-integration concerns for password managers:**

**A. Secret resolution (launch-time, host-side).** Varlock runs on the HOST, resolves
`op://`/`keepassxc://`/`bw://` refs to values, passes as env to the container. The container
never talks to the password manager. This is the varlock plugin concern (per-backend TBD):

- **1Password:** solved — `op` app-auth talks to the desktop app on the host.
- **KeePassXC:** `keepassxc-cli` reads the `.kdbx` file on the host. For unlocked-session access
  (no master password re-entry), needs IPC to the running KeePassXC app via DBus/socket — TBD
  whether the varlock process can reach it.
- **Bitwarden:** `bw` CLI uses API auth (login + unlock → session key). No desktop app needed,
  but the session key must be acquired/persisted non-interactively for automated builds — TBD.

**B. In-container crypto operations (runtime, socket-forwarded).** SSH signing (git commits/tags)
and GPG signing need the host's agent sockets mounted into the container. This is the §4a
host-integration layer — **already established, shared by every stack:**

- **SSH signing:** `SSH_AUTH_SOCK` forwarded into the container. Works for ALL password managers
  that provide SSH agent integration — 1Password, KeePassXC (`Settings → SSH Agent`), and Bitwarden
  (`Settings → SSH Agent`) all add keys to the system SSH agent. The existing socket mount handles
  all three; no per-password-manager socket is needed.
- **GPG signing with hardware keys (YubiKey):** GPG agent SSH socket + `~/.gnupg` (ro) +
  YubiKey USB device passthrough (`--device`). Already in §4a. The YubiKey appears inside the
  container as a `/dev/hidraw*` device; the GPG agent (running on the host) handles the
  cryptographic operations via the forwarded socket. Works for `git commit --gpg-sign` and
  `git tag -s` inside the container, signed by the hardware key on the host.

**Summary:** concern A (secret resolution) needs per-backend varlock plugins (TBD for KeePassXC
and Bitwarden). Concern B (crypto agent forwarding) is already solved by the §4a mount layer and
is password-manager-agnostic — any manager that feeds the system SSH agent works with the existing
`SSH_AUTH_SOCK` forward. GPG/YubiKey signing is also already handled.

### CONSIDERATION 2: Shared database services

**Surfaced by:** hindsight (AlloyDB Omni), gbrain (PGLite/Postgres at scale).

**A database is a service, and multiple recipes can share one DB instance with separate
databases.** Instead of each service running its own Postgres:

```
services/postgres/                    ONE shared Postgres service
  init/
    001-create-hindsight-db.sql       CREATE DATABASE hindsight_db
    001-create-gbrain-db.sql          CREATE DATABASE gbrain_db

recipes/hindsight/recipe.yaml         declares: needs postgres, database hindsight_db
recipes/gbrain/recipe.yaml            declares: needs postgres, database gbrain_db
```

When services DON'T share: hindsight uses AlloyDB Omni (Postgres + vector + ScaNN extensions) —
specialized enough to warrant its own instance. gbrain in PGLite mode is embedded (no external
DB). The decision criteria: same engine + same extensions = share one instance, separate
databases. Different engine or extension sets = separate instances.

### CONSIDERATION 3: Data storage — bind mounts, not named volumes

**Surfaced by:** hindsight (named volume `alloydb_data`), all services with persistent data.

**Decision: use bind mounts at `~/.local/share/harnessed/{service}/`, not named volumes.**

| Concern | Named volumes | Bind mounts |
|---|---|---|
| Inspectability | Opaque (need runtime commands) | `ls`, `du`, `tree` directly |
| Backup | Runtime-specific export | `tar` / `rsync` / `cp` (any tool) |
| Runtime portability | Podman ≠ docker ≠ Apple container volumes | Host paths work everywhere |
| Orphan risk | Volumes survive service removal; accumulate | Dir is visible, manually cleanable |
| Consistency | Session state already uses bind mounts — volumes are inconsistent | Same model as the state dir |

The service data path convention:

```
~/.local/share/harnessed/
  hindsight/db-data/         AlloyDB data dir (bind-mounted into db container)
  agentmemory/data/          SQLite store
  gbrain/pglite/             PGLite database
```

For compose-file-backed services (GAP 7), the compose file's named volumes are replaced with
bind-mount declarations parameterized by `HARNESSED_DATA_DIR` (defaults to
`${XDG_DATA_HOME:-$HOME/.local/share}/harnessed`, set by the launcher before invoking compose).
The hindsight compose file changes from `alloydb_data:/var/lib/postgresql/data` to
`${HARNESSED_DATA_DIR}/hindsight/db-data:/var/lib/postgresql/data`.

UID mapping: rootless podman maps the container user to the host user via `--userns=keep-id`.
The launcher creates the data dir with correct permissions before starting the service (same
pattern as the state-dir creation today).
---

## Summary: What the Architecture Handles vs What It Doesn't

### Handled cleanly (no changes needed):

| Pattern | Packages | Why it works |
|---|---|---|
| stdio MCP server (hatago child) | serena, headroom (MCP mode), codebase-memory-mcp, tokensave | Existing `mcp:` + hatago stdio→HTTP |
| Skills-only recipe | caveman, solidspec, hyperpowers, gstack | Existing Dockerfile recipe model |
| Simple HTTP service (1 image, 1 port) | agentmemory, gbrain (PGLite mode) | Existing `services/` + `mcp.servers[].service` |
| Per-project data in project dir | serena, codebase-memory-mcp, tokensave | Project mount (rw) persists it |
| Binary install via curl | codebase-memory-mcp | Recipe Dockerfile `RUN curl ... && install` |
| Pinned source (tag/SHA) | all | Existing ASM-02 pin validation |

### Needs architecture work:

| Gap | Packages | What's needed |
|---|---|---|
| **Hooks registration** (GAP 2) | agentmemory, context-mode, hyperpowers | `hooks:` field in recipe.yaml → merged into `settings.json` by assembler. Hook scripts image-baked. |
| **Multi-container service stacks** (GAP 7) | hindsight, gbrain (at scale) | Service model extends to compose-file-backed services (multi-container, dependencies, init steps, secrets). The user's working `~/.config/hindsight/docker-compose.yml` is the reference topology. |
| **Pin validation for release URLs** (GAP 4) | codebase-memory-mcp | ASM-02 extension: recognize `releases/download/v<X.Y.Z>/` as pinned |
| **Git hooks at runtime** (GAP 6) | tokensave | SessionStart hook or runtime setup step (subsumed by GAP 2) |

---

## Recipe Authoring Priority

Ordered by architecture-fit (cleanest first, surfacing gaps last):

### Tier 1 — Clean fits (no architecture changes, validates the model)

1. **caveman** — pure skills, no MCP, no hooks. Simplest possible recipe after gstack.
2. **serena** — stdio MCP server, per-project data via project mount. Validates the MCP recipe.
3. **solidspec** — CLI + skills via cargo. Validates the fat-base (Rust runtime pre-installed).
4. **tokensave** — stdio MCP via cargo + per-project libSQL. Validates Rust runtime in base.
5. **codebase-memory-mcp** — stdio MCP via binary download. Validates non-package-manager installs.
6. **headroom** (MCP mode only) — stdio MCP via pip. Clean fit. Proxy mode deferred.

### Tier 2 — Simple service-backed recipes (validates single-container service integration)

7. **agentmemory** — HTTP MCP server as a single-container service + recipe declaring MCP + hooks.
   Validates the service-recipe boundary for simple services. (Hooks need GAP 2.)
8. **gbrain** (PGLite mode) — HTTP MCP + embedded DB as a single-container service. Validates
   persistent-volume services.

### Tier 3 — Multi-container service (validates GAP 7 resolution)

9. **hindsight** — the real stress test. 3-container docker-compose stack (AlloyDB + init + app)
   with secrets, dependencies, and an init step. The user has a working deployment at
   `~/.config/hindsight/`. This recipe validates compose-file-backed services.

### Tier 4 — Surfaces the hooks gap (validates once GAP 2 is resolved)

10. **context-mode** — MCP + hooks. The hooks are essential (routing enforcement).
11. **hyperpowers** — skills + hooks. Workflow hooks (session-start, stop-time reminders).

### Deferred

12. **headroom** (proxy mode) — network intermediary between agent and LLM. Architecturally out
    of scope — requires a network-intermediary model harnessed doesn't have.
13. **gbrain** (Postgres at scale) — multi-container (Postgres + app). Same GAP 7 as hindsight.

---

## Recommended Execution Order

1. **Build Tier 1 recipes** (caveman, serena, solidspec, tokensave, codebase-memory-mcp, headroom
   MCP) — six recipes that validate the model with zero architecture changes.

2. **Resolve GAP 2 (hooks)** — add `hooks:` to recipe.yaml + assembler merge. Unblocks Tier 4.

3. **Build Tier 2 recipes** (agentmemory, gbrain PGLite) — validate single-container service +
   recipe integration.

4. **Resolve GAP 7 (multi-container services)** — extend service model for compose-file-backed
   stacks. Unblocks Tier 3.

5. **Build Tier 3 recipe** (hindsight) — the real stress test. Wraps the user's existing
   `~/.config/hindsight/docker-compose.yml` as a compose-file-backed service.

6. **Build Tier 4 recipes** (context-mode, hyperpowers) — validate hooks registration.

---

## Recommended Execution Order

1. **Build Tier 1 recipes** (caveman, serena, solidspec, tokensave, codebase-memory-mcp) — these
   validate the recipe model with zero architecture changes. Five working recipes proves the model.

2. **Build Tier 2 recipes** (hindsight, gbrain) — validate the service-recipe boundary and
   HTTP-native MCP.

3. **Resolve GAP 2 (hooks)** — add `hooks:` to recipe.yaml + assembler merge. This unblocks
   Tier 3.

4. **Build Tier 3 recipes** (context-mode, hyperpowers, agentmemory) — validate hooks + the most
   complex multi-surface recipe.

5. **Defer Tier 4** (headroom proxy mode) — noted as a future network-intermediary model.
`````

## File: .planning/codebase/ARCHITECTURE.md
`````markdown
<!-- refreshed: 2026-06-24 -->
# Architecture

**Analysis Date:** 2026-06-24

## System Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│               Host: `harnessed` bash bootstrap                   │
│               (`harnessed`, `lib/harnessed-common.sh`)           │
└──────┬──────────────┬────────────────┬───────────────────────────┘
       │              │                │
       ▼              ▼                ▼
┌──────────┐  ┌─────────────┐  ┌──────────────────┐
│  build   │  │  test       │  │  launch (isolated)│
│  path    │  │  path       │  │  path             │
│(emit+scan│  │(capability  │  │(pod: harness +    │
│+podman   │  │ test)       │  │ hatago + services)│
│ build)   │  │             │  │                   │
└────┬─────┘  └──────┬──────┘  └──────┬────────────┘
     │               │                │
     ▼               ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│      harnessed-tools Python package (`tools/harnessed/`)         │
│  schema.py → assemble.py → emit.py  |  scan.py  |  capability.py│
└─────────────────────────────────────────────────────────────────┘
     │ writes
     ▼
┌─────────────────────────────────────────────────────────────────┐
│   Committed Profile (`profiles/<stack>/`)                        │
│   .claude/{skills,commands}  hatago.config.json  .mcp.json      │
│   baked-servers.json  settings.json                              │
└─────────────────────────────────────────────────────────────────┘
     │ mounted into pod
     ▼
┌──────────────────────────┐   shared pod netns (localhost)
│  Harness Container       │ ◄──────────────────────────────┐
│  (harnessed-claude/omp/  │                                │
│   opencode/gemini/etc.)  │  http://localhost:3535/mcp     │
│  Reads .mcp.json →       │ ──────────────────────────────►│
│  connects to hatago      │                                │
└──────────────────────────┘                                │
                                        ┌───────────────────┴─┐
                                        │  hatago MCP Hub      │
                                        │  (harnessed-hatago)  │
                                        │  Spawns stdio child  │
                                        │  MCP servers         │
                                        └──────────────────────┘
                                                │
                                        via host.containers.internal
                                                │
                                        ┌───────▼──────────────┐
                                        │  Shared Services      │
                                        │  (e.g. harnessed-ping)│
                                        │  own image + volume   │
                                        └──────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `harnessed` bootstrap | CLI entry point, arg parsing, dispatch to lib | `harnessed` |
| `harnessed-common.sh` | Image names, runtime detection (podman/docker), instance lifecycle | `lib/harnessed-common.sh` |
| `harnessed-isolated.sh` | Launch isolated stack pod (harness + hatago) | `lib/harnessed-isolated.sh` |
| `harnessed-mounts.sh` | §4a host-integration mounts (SSH, GPG, git, project dir) | `lib/harnessed-mounts.sh` |
| `harnessed-isolated-config.sh` | §4b auth seeding (ro credentials.json + token-free stub) | `lib/harnessed-isolated-config.sh` |
| `harnessed-services.sh` | Shared service lifecycle (svc up/down/list) | `lib/harnessed-services.sh` |
| `harnessed-manifest-mounts.sh` | Per-harness profile file mounts from manifests | `lib/harnessed-manifest-mounts.sh` |
| `harnessed-cli.sh` | First-class subcommands: list, stop, rm, new, install | `lib/harnessed-cli.sh` |
| `harnessed-secrets.sh` | Optional varlock + 1Password secrets layer | `lib/harnessed-secrets.sh` |
| `harnessed-runtime.sh` | Runtime abstraction (podman pods vs docker) | `lib/harnessed-runtime.sh` |
| `harnessed-rescan.sh` | Post-build nightly CVE rescan (SEC-04) | `lib/harnessed-rescan.sh` |
| `schema.py` | Parse/validate recipe.yaml + stack.yaml into typed dataclasses | `tools/harnessed/schema.py` |
| `assemble.py` | Orchestrate the emit-only assembly: read → fan → merge → emit | `tools/harnessed/assemble.py` |
| `emit.py` | Write profile artifacts (.mcp.json, hatago.config.json, etc.) | `tools/harnessed/emit.py` |
| `scan.py` | Supply-chain scan gate (osv-scanner + pip-audit + snyk) | `tools/harnessed/scan.py` |
| `capability.py` | Per-stack capability test: manifest oracle vs live pod introspection | `tools/harnessed/capability.py` |
| `report.py` | Rich terminal rendering of capability test results | `tools/harnessed/report.py` |
| `synclinks.py` | Fan skills/commands from recipes into profile tree (collision-detect) | `tools/harnessed/synclinks.py` |
| `cli.py` | harnessed-tools CLI entry point (assemble/test/scan subcommands) | `tools/harnessed/cli.py` |

## Pattern Overview

**Overall:** Emit-Only Assembler + Runtime Pod Composition

**Key Characteristics:**
- The assembler (`harnessed-tools`) reads manifests and writes profile artifacts; it NEVER invokes podman/docker
- Profiles are committed to `profiles/<stack>/` and are a pure function of their recipes/stack manifests (reproducible)
- At launch, the host bash bootstrap runs all `podman` commands directly (no Docker-out-of-Docker, no daemon socket)
- All harnesses share ONE Claude-canonical profile format (`.claude/` tree); non-claude harnesses adapt via image-baked config pointing at hatago
- hatago is the single MCP hub; harness `.mcp.json` points only at `http://localhost:3535/mcp` — never at individual servers directly

## Layers

**Manifest Layer (source of truth):**
- Purpose: Declare stack composition (harness + recipes) and recipe contents (MCP servers, skills)
- Location: `stacks/<name>/stack.yaml`, `recipes/<name>/recipe.yaml`
- Contains: YAML declarations — harness, recipe list, MCP servers, skills paths
- Depends on: Nothing (leaf input)
- Used by: schema.py, assemble.py

**Assembler Layer (build-time, emit-only):**
- Purpose: Transform manifests into committed profile artifacts
- Location: `tools/harnessed/` (Python package, run inside `harnessed-tools` container)
- Contains: schema.py, assemble.py, emit.py, synclinks.py, scan.py
- Depends on: Manifest layer
- Used by: `harnessed build <stack>` (host bash → `podman run harnessed-tools assemble`)

**Profile Layer (committed artifact):**
- Purpose: Committed output of assembly — the harness profile mounted at launch
- Location: `profiles/<stack>/`
- Contains: `.claude/skills/`, `.claude/commands/`, `.mcp.json`, `hatago.config.json`, `baked-servers.json`, `settings.json`
- Depends on: Assembler layer (generated from)
- Used by: `harnessed-isolated.sh` (mounted into the harness container at launch)

**Image Layer (Dockerfile lineage):**
- Purpose: Container images providing toolchains and harness binaries
- Location: `base/Dockerfile.harnessed-*`, `Dockerfile.hatago`, `services/<name>/Dockerfile`, `tools/Dockerfile`
- Contains: harnessed-base (lineage root) → harness-specific images (harnessed-claude, omp, opencode, gemini, antigravity, codex)
- Depends on: harnessed-base (all harness images inherit FROM it)
- Used by: `harnessed build` (host runs `podman build`)

**Runtime Layer (host bash, launch-time):**
- Purpose: Compose and launch the pod at runtime
- Location: `lib/harnessed-isolated.sh`, `lib/harnessed-common.sh`, `lib/harnessed-mounts.sh`, `lib/harnessed-isolated-config.sh`
- Contains: Mount construction, pod lifecycle, auth seeding, egress firewall
- Depends on: Profile layer (reads committed artifacts), Image layer (pulls built images)
- Used by: `harnessed <stack> [path]`

**Service Layer (independent sidecars):**
- Purpose: Long-lived shared services reachable across stack instances
- Location: `services/<name>/` (own Dockerfile + service.yaml + server)
- Contains: Network-native MCP servers (e.g. `services/ping/server.py`)
- Depends on: Nothing from other layers
- Used by: Recipes that declare `service: <name>` in their MCP server entries

## Data Flow

### Build Path: `harnessed build <stack>`

1. Parse `stacks/<stack>/stack.yaml` + each `recipes/<name>/recipe.yaml` → typed objects (`tools/harnessed/schema.py`)
2. Validate: no raw npm/npx, harness compat, no floating Dockerfile refs (`tools/harnessed/assemble.py`)
3. Run source scan: osv-scanner + pip-audit over recipe dirs (`tools/harnessed/scan.py:run_source_scan`)
4. Fan skills/commands from each recipe into profile tree, detect collisions (`tools/harnessed/synclinks.py`)
5. Merge all recipe MCP servers → `hatago.config.json` (`tools/harnessed/emit.py:write_hatago_config`)
6. Emit `.mcp.json` with single hatago endpoint, `settings.json`, `baked-servers.json` (`tools/harnessed/emit.py`)
7. Write derived `Dockerfile` for hatago image with baked servers (`tools/harnessed/emit.py:write_derived_dockerfile`)
8. Host runs `podman build` on emitted Dockerfile → `harnessed-hatago:<stack>` image
9. Run image scan on built image (`tools/harnessed/scan.py:run_image_scan`)
10. Committed profile lands in `profiles/<stack>/`

### Launch Path: `harnessed <stack> [path]`

1. Parse harness from `stacks/<stack>/stack.yaml` → select harness image (`lib/harnessed-isolated.sh`)
2. Lazy-build non-claude harness images if not present (`lib/harnessed-common.sh:ensure_*_image`)
3. Construct mount args: §4a host-integration mounts (`lib/harnessed-mounts.sh`)
4. Seed auth: ro credentials.json mount + generated `.claude.json` stub (`lib/harnessed-isolated-config.sh`)
5. Auto-start declared shared services (`lib/harnessed-services.sh:ensure_service_up`)
6. Create pod (`podman pod create`) with harness container + hatago container in shared netns
7. Apply egress firewall via `lib/egress-firewall.sh` (iptables inside harness container)
8. Start pod → hatago spawns its configured stdio children
9. Interactive: attach to harness (`claude --mcp-config`, `opencode`, etc.); headless: `sleep infinity` for introspection

### Test Path: `harnessed test <stack>`

1. Launch stack `--fresh` in headless mode (`HARNESSED_HEADLESS=true`)
2. Wait for hatago port 3535 to bind (readiness signal)
3. Introspect live pod: query `hatago://servers` resource for MCP servers; scan mounted profile dirs for skills/commands (`tools/harnessed/capability.py:introspect`)
4. Compare actual vs expected (derived from manifest via `schema.py:expected_capabilities`)
5. Build `CapabilityReport` → render with rich (`tools/harnessed/report.py`)
6. Teardown (`--fresh` removes pod)

**State Management:**
- Pod names follow `harnessed-<stack>-<projhash>` convention
- Service volumes (`<service>-data`) persist across `svc down`; `--purge` destroys them
- History dirs (`~/.claude/projects`, `~/.claude/file-history`, etc.) mounted rw from host for session continuity

## Key Abstractions

**Stack (`stack.yaml`):**
- Purpose: Declares ONE harness + list of recipes to compose
- Examples: `stacks/tracer-time/stack.yaml`, `stacks/ping-time/stack.yaml`
- Pattern: Minimal YAML; assembler parses forward (tolerant of unknown fields per D-14)

**Recipe (`recipe.yaml`):**
- Purpose: Declares MCP servers and skills/commands to add to a harness
- Examples: `recipes/time/recipe.yaml`, `recipes/ping/recipe.yaml`
- Pattern: `mcp.servers[]` (name, command, args, transport) + `skills[]` (path)

**Profile (committed artifact):**
- Purpose: Assembled, committed harness config — single source of truth at launch
- Examples: `profiles/tracer-time/`, `profiles/ping-time/`
- Pattern: Pure function of recipes/stack; regenerated from scratch on `harnessed build <stack>`

**Agent Manifest (`agents/<harness>/agent.yaml`):**
- Purpose: Declares harness image + Dockerfile for lazy build
- Examples: `agents/claude/agent.yaml`, `agents/omp/agent.yaml`
- Pattern: `type: agent`, `harness:`, `image:`, `dockerfile:`

**Service (`services/<name>/`):**
- Purpose: Long-lived shared sidecar with own image + volume + port
- Examples: `services/ping/`
- Pattern: `service.yaml` (name, image, volume, port, healthcheck) + `Dockerfile` + `server.py`

**Harness Manifest (`lib/manifests/<harness>.yaml`):**
- Purpose: Declares which profile files to mount and which history dirs to expose per harness
- Examples: `lib/manifests/claude.yaml`, `lib/manifests/omp.yaml`
- Pattern: `profile_files:` + `history_dirs:`

## Entry Points

**`harnessed` (bootstrap):**
- Location: `harnessed` (repo root)
- Triggers: User invocation (or shim at `~/.local/bin/<stack>`)
- Responsibilities: Parse all subcommands, source lib scripts, dispatch to correct path

**`harnessed-tools` (Python CLI):**
- Location: `tools/harnessed/cli.py` (entrypoint `harnessed.cli:main`)
- Triggers: Called inside `harnessed-tools` container by `harnessed build <stack>`
- Responsibilities: assemble, test (capability), scan subcommands

**`harnessed_isolated()` (launch function):**
- Location: `lib/harnessed-isolated.sh`
- Triggers: `harnessed <stack> [path]` dispatch
- Responsibilities: Build mount args, create pod, attach interactive or headless

## Architectural Constraints

- **Emit-only assembler:** `tools/harnessed/` NEVER calls podman/docker; all container operations are host-native bash
- **No Docker-out-of-Docker:** Every `-v` uses host absolute paths (host `HOME`/`PWD` passed as env); no daemon socket mounted into containers
- **FROM = lineage only:** `base/Dockerfile.harnessed-*` uses `FROM harnessed-base` for toolchain inheritance only; harness composition is runtime pod (never build-time `FROM` union)
- **One harness per stack:** Exactly one of claude/omp/opencode/gemini/antigravity/codex per stack manifest
- **Claude-canonical profile:** All harnesses read the same `.claude/` profile; non-claude harnesses adapt via image-baked config pointing at hatago
- **SSE deprecated:** MCP transport must be `streamable-http` or `stdio` (wrapped by hatago to HTTP); SSE is rejected
- **pnpm everywhere:** `npm`/`npx` are linted out by the assembler (BLD-03); `pnpm dlx` replaces `npx`
- **Global state:** `CONTAINER_RUNTIME`, `HARNESSED_DIR`, `MOUNT_ARGS` (array) are module-level bash globals shared across sourced lib scripts
- **Threading:** Single-threaded bash launcher; Python assembler is single-process (no async)

## Anti-Patterns

### Mounting `~/.claude.json` read-write

**What happens:** Bind-mounting the host's whole `~/.claude.json` into the container rw
**Why it's wrong:** Claude rewrites this file constantly; a shared rw mount races with the host process and corrupts state
**Do this instead:** Generate a minimal token-free stub in `lib/harnessed-isolated-config.sh`; mount only `~/.claude/.credentials.json` ro

### Using `FROM` to compose two harness systems

**What happens:** Trying to `FROM harnessed-claude` and `FROM harnessed-omp` together in one Dockerfile
**Why it's wrong:** `FROM` is linear inheritance; there is no "union two sibling images" operator
**Do this instead:** Compose at runtime in a podman pod — separate images, shared network namespace

### Calling podman from within the assembler

**What happens:** Any podman/docker call inside `tools/harnessed/`
**Why it's wrong:** The assembler runs inside `harnessed-tools` container; it has no daemon access and is emit-only by design
**Do this instead:** Emit artifacts only; the host bash bootstrap runs all `podman build`/`podman run` calls

### Using container-internal paths in `-v` flags

**What happens:** `-v /home/harnessed/something:/dest` where the source resolves inside the tool container
**Why it's wrong:** DooD bind sources resolve on the HOST daemon; the container's internal view points at nothing
**Do this instead:** Pass host `HOME`/`PWD` as env vars; use them in every `-v` source

## Error Handling

**Strategy:** Fail-fast with explicit error messages; structured exceptions in Python; `set -euo pipefail` in bash

**Patterns:**
- Python assembler raises typed exceptions: `SchemaError`, `RecipeLintError`, `CollisionError`, `ScanError`, `CapabilityError`
- Bash scripts use `print_error` + `exit 1` for user-visible failures
- Supply-chain scan: HIGH severity (CVSS >= 7.0) raises `ScanError` and aborts the build; lower findings are warnings
- Capability test: returns structured `CapabilityReport` with per-capability pass/fail; CI exit code driven by report

## Cross-Cutting Concerns

**Logging:** Bash: colored `print_info/success/warning/error` helpers in `lib/harnessed-common.sh`. Python: `rich.Console` for terminal rendering.
**Validation:** Assembler validates all manifests before any file emission (fail-fast order: lint → compat → pin → scan → emit)
**Authentication:** Credentials referenced from host, never baked. Claude: ro `.credentials.json` + token-free stub. opencode: ro `auth.json`. gemini: ro OAuth files. codex: ro `auth.json`. All via `lib/harnessed-isolated-config.sh`.
**Supply-chain:** pnpm supply-chain policy baked into base image at `lib/pnpm/config.yaml`; osv-scanner + pip-audit are always-on gate; snyk/socket are token-gated and warn-and-skip when no token.

---

*Architecture analysis: 2026-06-24*
`````

## File: .planning/codebase/CONCERNS.md
`````markdown
# Codebase Concerns

**Analysis Date:** 2026-06-24

## Tech Debt

**Profiles committed then gitignored:**
- Issue: `profiles/` was previously tracked in git and many profile files are now deleted (`D` status in git). `.gitignore` now correctly excludes `/profiles/`, but the tracked files have not been removed via `git rm`. Any `git status` shows dozens of deleted files, and `git checkout` of an old commit could restore the ignored directory.
- Files: `profiles/*/` (all profile dirs), `.gitignore`
- Impact: Confusing git status; `git stash` or bisect operations may restore stale profiles that shadow live builds
- Fix approach: Run `git rm -r --cached profiles/` to remove all tracked entries, then commit

**Single hatago image tag shared across all stacks:**
- Issue: `build_stack()` always tags the built hatago image as `harnessed-hatago:latest`. Building stack A overwrites the hatago image that stack B was running against. All stacks share a single mutable image tag.
- Files: `lib/harnessed-common.sh:213` (`build_stack`), `lib/harnessed-common.sh:39` (`HARNESSED_HATAGO_IMAGE`)
- Impact: A rebuild of any stack silently changes the image for all running or future instances; no per-stack hatago image isolation
- Fix approach: Tag as `harnessed-hatago-<stack>:latest` and reference it per-stack in the launcher

**CVSS vector string parsing is hand-rolled:**
- Issue: `scan.py` implements a full CVSS v3.1 base score calculator from scratch (metric tables `_AV`, `_AC`, `_PR_*`, `_UI`, `_CIA`, roundup function). This is the load-bearing build abort gate.
- Files: `tools/harnessed/scan.py:37-115`
- Impact: Any mistake in the formula silently allows HIGH CVEs through or incorrectly aborts builds; the code is complex enough to contain subtle bugs (e.g., scope-changed PR table selection)
- Fix approach: Depend on the `cvss` PyPI package (actively maintained, FIRST.org validated) instead of a manual implementation

**`jq` is an undocumented host dependency violating the "podman-only" invariant:**
- Issue: `harnessed-isolated-config.sh` unconditionally calls `jq` on the host to read `~/.claude.json` and generate the `.claude.json` stub. The design doc (CLAUDE.md §15) explicitly states "podman is the only host dependency," but `jq` is required for isolated mode.
- Files: `lib/harnessed-isolated-config.sh:97-120`
- Impact: Isolated mode (the primary mode) fails with a clear error on hosts without `jq`; contradicts documented constraints
- Fix approach: Either document `jq` as a required host tool, or generate the stub via a throwaway tools container instead of the host

**`[INFERENCE]` items unverified in production:**
- Issue: Several design decisions are explicitly marked `[INFERENCE]` in `docs/harnessed-design.md` §14 and `CLAUDE.md`. These include: the exact fields Claude Code gates onboarding on in `.claude.json`; whether `CLAUDE_CONFIG_DIR` relocates `.claude.json` not just `.claude/`; whether `mise`'s `npm:` backend routes through pnpm for supply-chain policy.
- Files: `lib/harnessed-isolated-config.sh:10-19` (onboarding stub fields), `CLAUDE.md:172,179`, `docs/harnessed-design.md:508-550`
- Impact: A Claude Code update that adds an onboarding gate field will break isolated mode silently (no prompt, just stuck); pnpm supply-chain policy may not apply to mise-installed tools
- Fix approach: Each [INFERENCE] should have a UAT checkpoint that verifies empirically and pins the result as a fixture

## Known Bugs

**Snyk container test silently degrades to warning when tools container lacks daemon socket:**
- Symptoms: `SC-03` (snyk container test) exits 2 ("failure") instead of testing the image; the build succeeds with a warning
- Files: `tools/harnessed/scan.py:348-349` (documented in comment), `lib/harnessed-common.sh:261-268`
- Trigger: When the tools container runs `snyk container test <image>` it has no access to the host's podman socket and cannot pull the image layers for inspection
- Workaround: The osv-scanner baseline (BLD-02b) still runs on the saved tar archive and covers this gap; SC-03 is a secondary gate

## Security Considerations

**Egress firewall uses DNS-resolved static IPs:**
- Risk: The firewall resolves domain IPs at container startup and uses those IPs as iptables rules. Cloud/CDN services (GitHub, npm registry, Anthropic API) use dynamic IP pools that change. A session started after an IP rotation will have stale allowlist rules.
- Files: `lib/egress-firewall.sh:79-100`
- Current mitigation: DNS is always allowed (UDP/TCP port 53), so resolution succeeds; the resolved IPs are the most recent at launch time
- Recommendations: Either allow the CDN IP ranges via CIDR blocks, or add a refresh hook triggered by connection failure; document the IP-staleness risk window

**Antigravity uses OS system keyring — no credential pre-seeding:**
- Risk: `agy` (antigravity harness) authenticates via Google OAuth stored in the OS Secret Service keyring. A clean-room container has no keyring daemon, so every new container instance requires an interactive re-auth (printed URL or browser flow). Sessions cannot be recovered across container recreates.
- Files: `lib/harnessed-isolated-config.sh:60-67`, `base/Dockerfile.harnessed-antigravity`
- Current mitigation: Warning printed on launch; documented limitation in `docs/guides/`
- Recommendations: If agy adds an API key option or a credential-file export, implement pre-seeding. For now, document clearly that `--fresh` on an antigravity stack always prompts for auth.

**Claude installer and mise installer use unpinned curl-pipe-bash:**
- Risk: `Dockerfile.harnessed-claude` and `Dockerfile.harnessed-base` use `curl ... | bash` with no version pinning for the claude CLI and mise respectively. Any supply-chain compromise of those installer scripts affects the image silently.
- Files: `base/Dockerfile.harnessed-claude:7`, `base/Dockerfile.harnessed-base:51`, `base/Dockerfile.harnessed-antigravity:30`, `base/Dockerfile.hatago` (uv installer)
- Current mitigation: Images pass the post-build osv-scanner scan; the build-time scan catches known CVEs after the fact
- Recommendations: Pin the claude installer via `--version <pin>` flag if available; for mise, use a release-tagged URL with SHA verification; note that agy explicitly has no version-pin mechanism (vendor limitation)

**`OP_SERVICE_ACCOUNT_TOKEN` injected into tools container env:**
- Risk: When resolving secrets in headless mode (no host varlock), `OP_SERVICE_ACCOUNT_TOKEN` is passed via `-e` to the tools container. Any process inside that container that logs env variables could expose it.
- Files: `lib/harnessed-secrets.sh:78-85`
- Current mitigation: `--rm` on the tools container; the token is not written to any image layer; container is short-lived
- Recommendations: Acceptable for current use; note that `--env-file` is slightly safer than `-e` for tokens (no shell history exposure)

## Performance Bottlenecks

**`harnessed build` runs serial image saves for scanning:**
- Problem: `build_stack()` runs `podman save <image> -o <tar>` before each osv-scanner run, synchronously. A stack with a large base image (~2GB+) means two sequential save operations (hatago image + derived stack image) before scan results are known.
- Files: `lib/harnessed-common.sh:218-258`
- Cause: The scan design requires a tar archive (osv-scanner image mode); saves are O(image size)
- Improvement path: Cache save tars keyed by image digest; skip the save when the image hasn't changed since the last scan

**Hatago readiness uses a 30-second busy-wait with 1-second sleep intervals:**
- Problem: The launcher polls for hatago's HTTP port with a 1-second sleep per iteration, up to 30 retries. No feedback until a connection succeeds or all 30 retries are exhausted.
- Files: `lib/harnessed-isolated.sh:207-209`
- Cause: No readiness signal from the pod members; HTTP port binding is the only observable signal
- Improvement path: Add a hatago `--readiness-timeout` flag if available, or use exponential backoff; print progress after N seconds

## Fragile Areas

**`stop_if_last_session` — race window in session counting:**
- Files: `lib/harnessed-common.sh:450-466`
- Why fragile: Counts attached sessions by scanning `ps ax` output for matching `podman exec -it` commands. A new session started between the count and the `stop` will keep the container alive incorrectly; a session that exits in that window will leave the container running
- Safe modification: Do not call `stop_if_last_session` from contexts where session count matters; prefer explicit `harnessed stop <stack>` for lifecycle management
- Test coverage: Not covered by UAT (requires timing-sensitive multi-process setup)

**`.claude.json` stub field set is empirically unverified:**
- Files: `lib/harnessed-isolated-config.sh:110-120`
- Why fragile: The fields (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID`) are documented as `[INFERENCE]` in design §14. A Claude Code update adding a new onboarding gate field will cause isolated mode to silently prompt for re-login without a clear error.
- Safe modification: Add a UAT assertion that launching a fresh isolated instance completes without an onboarding prompt; treat a prompt as a failing test
- Test coverage: Covered by phase-04 and phase-06 UAT but only when the specific fields happen to be sufficient

**`harnessed-manifest-mounts.sh` depends on `yq` being in PATH:**
- Files: `lib/harnessed-manifest-mounts.sh:28,51`
- Why fragile: `yq` is called on the host to parse `lib/manifests/<harness>.yaml`. The error handling returns `1` on yq failure but only prints a warning. If yq is absent or returns a non-zero exit, MOUNT_ARGS is partially populated.
- Safe modification: Add a `command -v yq` check at the top of `harnessed_manifest_mounts` and emit a clear dependency error
- Test coverage: No UAT test exercises the yq-absent failure path

**Services: inline YAML parsing via `sed` with no quoting validation:**
- Files: `lib/harnessed-services.sh:35-38` (`_svc_yaml_val`)
- Why fragile: Reads `service.yaml` scalar values via `sed -n "s/^${key}: *//p"` followed by `tr -d '"'`. A `service.yaml` value containing special characters (colons, brackets) will be silently misread
- Safe modification: Use `yq` (already a dependency in manifest-mounts) for all YAML reading; or require strictly flat `key: simple-value` fields in service.yaml and document that constraint
- Test coverage: `tools/test-fixtures/services/` has only the ping service; no test for malformed service.yaml

## Scaling Limits

**All stacks share one `harnessed-hatago:latest` image:**
- Current capacity: One hatago image configuration per host at a time
- Limit: Cannot run two stacks simultaneously if they have different MCP server sets and both need a fresh build — building one overwrites the other
- Scaling path: Per-stack hatago image tags (`harnessed-hatago-<stack>:latest`); requires updating `HARNESSED_HATAGO_IMAGE` to be dynamic in `build_stack` and both launchers

## Dependencies at Risk

**`@himorishige/hatago-mcp-hub` — single maintainer, early-stage:**
- Risk: The entire MCP aggregation layer depends on this package. It is a small npm package with a single author (`himorishige`). If it is abandoned or breaks on a hatago schema change, all isolated stacks lose MCP connectivity.
- Impact: Every stack's MCP capability chain breaks
- Migration plan: hatago's config format is simple JSON; the fallback is to replace it with another hub (`@samanhappy/mcphub`, `mcp-gateway`) or a thin custom stdio-to-HTTP bridge

**`agy` (antigravity) — no API key mechanism, installer lacks version pinning:**
- Risk: The `agy` CLI has no documented API-key env var for non-interactive auth. The installer (`curl ... | bash`) has no version-pin flag. If Google changes the auth model or the binary URL, the antigravity harness is broken silently.
- Impact: `harnessed-antigravity` image builds successfully but agy prompts for interactive auth on every container recreate
- Migration plan: Monitor for an `ANTIGRAVITY_API_KEY` or credential-file option; if unavailable, document antigravity as a "persistent session only" harness (never `--fresh`)

**`node@22` (LTS), `python@3.12` — major-only pins in mise:**
- Risk: `Dockerfile.harnessed-base` pins `node@22` and `python@3.12` (major only). Patch-level updates via mise are automatic on each image rebuild, meaning a patch that breaks a dependency would propagate silently.
- Impact: Non-reproducible builds between rebuild dates
- Migration plan: Pin to exact versions (`node@22.x.y`, `python@3.12.x`) in `Dockerfile.harnessed-base`; update pins deliberately rather than on every build

## Missing Critical Features

**Apple `container` runtime not supported:**
- Problem: `lib/harnessed-runtime.sh` explicitly documents that Apple's `container` tool (one VM+IP per container) has no shared-netns/pod equivalent and is not handled. The harness depends on localhost-shared netns for hatago connectivity.
- Blocks: Users on macOS who use Apple `container` instead of Podman/Docker cannot run isolated stacks at all
- Fix: Requires a different MCP endpoint model (dynamic port + env var instead of `localhost:3535`) or a per-container DNS mechanism

**No automated rollback on failed scan:**
- Problem: If `harnessed build <stack>` passes the source scan but fails the image scan, the `profiles/<stack>/` directory has already been written. The next `harnessed <stack>` launch will use a stale (potentially inconsistent) profile while the caller thinks the build failed.
- Files: `lib/harnessed-common.sh:124-276` (`build_stack`)
- Blocks: Reproducible, atomic build semantics
- Fix: Write profiles to a temp directory first; rename to final location atomically only after all scans pass

## Test Coverage Gaps

**Python assembler has no unit tests:**
- What's not tested: `schema.py` (YAML parsing, schema validation, collision detection), `assemble.py` (server merging, service resolution), `emit.py` (artifact writing), `scan.py` (CVSS calculation, severity gating), `synclinks.py` (skill/command fan-out, collision detection)
- Files: `tools/harnessed/schema.py`, `tools/harnessed/assemble.py`, `tools/harnessed/emit.py`, `tools/harnessed/scan.py`, `tools/harnessed/synclinks.py`
- Risk: Logic bugs in CVSS calculation or YAML parsing go undetected until a full UAT run against a live container
- Priority: High — the CVSS gate and collision detection are correctness-critical

**No test for secrets resolution failure paths:**
- What's not tested: `resolve_secret_env` failure modes (varlock exits non-zero, empty schema, malformed dotenv output), `discover_scanner_tokens` with malformed `snyk.json`
- Files: `lib/harnessed-secrets.sh`
- Risk: A broken secrets configuration aborts the launch with an unhelpful message and no recovery guidance
- Priority: Medium

**UAT harness matrix only runs if all harness images are pre-built:**
- What's not tested: `phase-06.sh` tests `test_harness_omp`, `test_harness_opencode`, etc. only when those harness images exist. If a CI run hasn't pre-built them, these tests are silently skipped.
- Files: `tools/uat/phase-06.sh`
- Risk: A regression in an alternative harness's MCP wiring (omp, gemini, codex) goes undetected
- Priority: Medium — gate on image existence but emit a clear skip vs silent pass

---

*Concerns audit: 2026-06-24*
`````

## File: .planning/codebase/CONVENTIONS.md
`````markdown
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
`````

## File: .planning/codebase/INTEGRATIONS.md
`````markdown
# External Integrations

**Analysis Date:** 2026-06-24

## AI Harness CLIs

**Claude Code (Anthropic):**
- Installed via: `curl -fsSL https://claude.ai/install.sh | bash` into `harnessed-claude` image (`base/Dockerfile.harnessed-claude`)
- Auth: `~/.claude/.credentials.json` (OAuth) mounted read-only into harness container
- Config: minimal `.claude.json` stub generated by assembler; never rw-mount the host's `~/.claude.json`
- MCP wiring: `.claude/.mcp.json` in the committed profile pointing to `http://localhost:3535/mcp`
- Native reads: `.claude/skills/`, `.claude/commands/`, `.claude/agents/`, CLAUDE.md

**OpenAI Codex:**
- Installed via: `mise use -g npm:@openai/codex` in `base/Dockerfile.harnessed-codex`
- Auth: `~/.codex/auth.json` mounted read-only, or `OPENAI_API_KEY` env var
- MCP wiring: baked `~/.codex/config.toml` → `[mcp_servers.hatago] url = "http://localhost:3535/mcp"` (native Streamable-HTTP, codex 0.139+)
- Native reads: `AGENTS.md` (does not read Claude skills/commands)

**Google Gemini CLI:**
- Installed via: `mise use -g npm:@google/gemini-cli` in `base/Dockerfile.harnessed-gemini`
- Auth: `~/.gemini` OAuth creds mounted from host, or `GEMINI_API_KEY`/`GOOGLE_API_KEY` env var
- MCP wiring: baked `~/.gemini/settings.json` → `mcpServers.hatago.url = "http://localhost:3535/mcp"` + `type: "http"`
- Native reads: GEMINI.md + gemini-native extension format (not Claude skills/commands)

**Antigravity (agy — Google):**
- Installed via: `curl -fsSL https://antigravity.google/cli/install.sh | bash` in `base/Dockerfile.harnessed-antigravity`
- Auth: Google OAuth via system keyring (no API-key env var); prompts on first launch in clean container
- MCP wiring: baked `~/.gemini/config/mcp_config.json` → `mcpServers.hatago.serverUrl = "http://localhost:3535/mcp"`

**opencode (sst/opencode):**
- Installed via: official vendor installer `curl -fsSL https://opencode.ai/install | bash` into `~/.opencode/bin` in `base/Dockerfile.harnessed-opencode`; pinned version (ARG `OPENCODE_VERSION=1.17.9`)
- Auth: configured inside the image; provider-dependent
- MCP wiring: baked `~/.config/opencode/opencode.json` → single hatago Streamable-HTTP entry at `http://localhost:3535/mcp`
- Native reads: `.claude/skills/**/SKILL.md`, `~/.claude/CLAUDE.md` (shares Claude-canonical profile natively)

**omp (Oh My Pi):**
- Installed via: `mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}"` (ARG `OMP_VERSION=16.0.1`) in `base/Dockerfile.harnessed-omp`
- Bridge: `@drmikecrowe/omp-claude-hooks-bridge` npm plugin pre-installed; maps Claude hooks/skills at runtime
- MCP wiring: via the hooks bridge translating the Claude-canonical `.mcp.json` profile

## MCP Hub

**hatago (`@himorishige/hatago-mcp-hub@0.0.16`):**
- Image: `harnessed-hatago` (`base/Dockerfile.hatago`)
- Install: `pnpm add -g "@himorishige/hatago-mcp-hub@${HATAGO_VERSION}"` (never npm/npx)
- Endpoint: `http://localhost:3535/mcp` (Streamable-HTTP, in-pod shared netns)
- Config: per-stack `hatago.config.json` generated by assembler, mounted at runtime
- Spawns stdio MCP server children (stdio→HTTP bridge)
- Transport: Streamable-HTTP only (SSE is deprecated in MCP spec 2025-06-18)

## MCP Servers (Baked / Recipe-provided)

**mcp-server-time (tracer-bullet, baked):**
- Type: stdio child spawned by hatago
- Install: `uv tool install "mcp-server-time==${MCP_SERVER_TIME_VERSION}"` (ARG `2026.6.4`) in `base/Dockerfile.hatago`
- Runtime invocation: `uvx mcp-server-time`; runs fully offline (no network at scan time)

**ping service (shared service sidecar):**
- Image: `harnessed-ping:latest` (`services/ping/Dockerfile`)
- Implementation: `services/ping/server.py` — Python `fastmcp` (MCP Python SDK)
- Port: 8080 (host-published, `0.0.0.0`)
- Healthcheck: `curl -sf http://localhost:8080/health`
- Reached by hatago as: `http://host.containers.internal:8080/mcp` (or `http://ping:8080/mcp` via `HARNESSED_NET` bridge)
- Volume: `ping-data` (service-scoped, persists across `svc down`)

## Supply-Chain Security Scanners

**osv-scanner 2.3.8 (credential-free, always-on):**
- Static Go binary; downloaded and checksum-verified in `tools/Dockerfile`
- Scans: lockfiles, `node_modules`, container image archives
- Offline DB: pre-seeded at `/opt/osv-cache/osv-scanner/` (PyPI + npm ecosystems)
- Gate: build aborts on CVSS ≥ 7.0 (HIGH); warnings below

**pip-audit 2.10.1 (credential-free, always-on):**
- Python dep dependency in `tools/pyproject.toml`
- Scans any recipe shipping `requirements.txt`/`pyproject.toml`
- Uses PyPI advisory DB + OSV

**snyk CLI (token-gated, optional):**
- Install: `pnpm add -g snyk` (requires `allowBuilds: {snyk: true}` in `tools/pnpm-workspace.yaml`)
- Auth env: `SNYK_TOKEN` (set via `harnessed auth snyk`; persisted to host `~/.config`, never an image layer)
- Command: `snyk test --severity-threshold=high`
- Behavior: warn-and-skip if no token (non-interactive builds always succeed without it)

**socket.dev CLI (token-gated, optional):**
- Auth env: `SOCKET_SECURITY_API_KEY` (set via `harnessed auth socket`)
- Behavior: warn-and-skip if no token

## Secrets Management

**1Password CLI (`op`):**
- Installed via official apt repo in `harnessed-base` (`base/Dockerfile.harnessed-base`) and `harnessed-tools` (`tools/Dockerfile`)
- Auth options:
  1. Mounted desktop-app agent socket (preferred for interactive use, `allowAppAuth`)
  2. `OP_SERVICE_ACCOUNT_TOKEN` env var (headless/CI only; scoped narrowly)
- Usage: resolves `op://Vault/Item/field` refs; `op run`/`op read` for inline ref injection

**varlock (opt-in secrets layer):**
- Activates only when `~/.config/harnessed/.env.schema` exists
- Reads `@env-spec` DSL schema; resolves `op(op://...)` refs via `varlock run -- <cmd>`
- Inert with no schema — zero-config path requires no secrets tooling

## Networking / Egress Control

**Egress firewall (`lib/egress-firewall.sh`):**
- Applied at each container session start via iptables rules (in-memory)
- Whitelist (outbound):
  - `api.anthropic.com`, `statsig.anthropic.com` — Claude API
  - `github.com`, `api.github.com`, `codeload.github.com`, `objects.githubusercontent.com`, `raw.githubusercontent.com`, `uploads.github.com`, `alive.github.com`
  - `registry.npmjs.org` — npm registry
  - `pypi.org`, `files.pythonhosted.org` — Python packages
  - `mise.jdx.dev` — mise tool manager
- Additional domains can be passed as arguments (e.g. external AI API hosts)
- Bypass: `harnessed --no-firewall ...` skips firewall for a single run

## Installation / Distribution

**Repository:**
- GitHub: `https://github.com/drmikecrowe/code-container`
- Installer: `curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash`
- Clones to `~/.local/share/code-container`; symlinks `harnessed` to `~/.local/bin` or `/usr/local/bin`

## CI/CD & Monitoring

**CI Pipeline:** None detected (no `.github/workflows/` or CI config present)

**Nightly re-scan timer:**
- `lib/harnessed-rescan.sh` — systemd user timer (defined in `systemd/`) re-runs osv-scanner against installed images for post-build CVE disclosure
- Mirrors `nightly-updates` pattern; credential-free (no token required for rescan)

## Environment Variables (Required at Runtime)

- `HARNESSED_DIR` — resolved repo directory (set by bootstrap)
- `CLAUDE_CONFIG_DIR` — optional relocation of Claude config directory
- `SNYK_TOKEN` — scanner token (optional; warn-and-skip if absent)
- `SOCKET_SECURITY_API_KEY` — scanner token (optional; warn-and-skip if absent)
- `OP_SERVICE_ACCOUNT_TOKEN` — 1Password service account (headless/CI only)
- `OPENAI_API_KEY` — codex auth fallback
- `GEMINI_API_KEY` / `GOOGLE_API_KEY` — gemini-cli auth fallback
- `HARNESSED_NET` — opt-in bridge network name (default: pasta/host-gateway networking)
- `NO_FIREWALL` — set to `true` to skip egress iptables rules

---

*Integration audit: 2026-06-24*
`````

## File: .planning/codebase/STACK.md
`````markdown
# Technology Stack

**Analysis Date:** 2026-06-24

## Languages

**Primary:**
- Bash — Host bootstrap (`harnessed`, `install.sh`) and all shell library modules (`lib/*.sh`). Dependency-free; podman/docker is the only host requirement.
- Python 3.12 / 3.13 — `harnessed-tools` image: the build-time assembler (`tools/`) and the `ping` shared service (`services/ping/server.py`).
- JavaScript / TypeScript — Harness CLIs (Claude Code, Codex, Gemini, opencode), the hatago MCP hub, and recipe JS deps; managed via pnpm inside images.

**Secondary:**
- YAML — Stack and recipe definition format (`stacks/*/stack.yaml`, `recipes/*/recipe.yaml`), parsed by ruamel.yaml.
- TOML — codex config baked into `harnessed-codex` image (`~/.codex/config.toml`).
- JSON — hatago config output (`hatago.config.json`), gemini/opencode baked configs, osv-scanner output.

## Runtime

**Container engine (host — the only host dependency):**
- Podman ≥ 5.6, current 5.8.2 (rootless, preferred). Falls back to Docker if podman is not found.
- Rootless podman pods provide shared network namespace for harness + hatago containers.
- No API socket mounted inside containers; all podman commands run host-side.

**Base image OS:**
- Ubuntu 24.04 (`harnessed-base`, `harnessed-tools` uses `python:3.13-slim`)

**Tool manager (in-image):**
- `mise` (calendar-versioned, 2026.x) — installs and shims node, python, pnpm, fd, ripgrep, and harness-specific CLIs inside all images derived from `harnessed-base`.

**Package Manager (JS):**
- `pnpm@11` — the only JS package manager; governed by managed supply-chain policy in `lib/pnpm/config.yaml` (COPY'd into every image).
- Policy: `minimumReleaseAge: 1440`, `minimumReleaseAgeStrict: true`, `blockExoticSubdeps: true`, `verifyStoreIntegrity: true`, `strictDepBuilds: true`.
- Per-project `allowBuilds` goes in `tools/pnpm-workspace.yaml` (not global config).
- No npm or npx anywhere in the project.

**Package Manager (Python):**
- `uv` 0.11.8 — installed via the official shell installer into `harnessed-hatago` image; manages Python deps and runs Python MCP servers via `uvx`.
- `pip` — used only in the `harnessed-tools` image for the assembler's own install (`pip install --no-cache-dir .`).

## Frameworks

**Core (Python assembler — `tools/`):**
- `rich` ≥14,<15 — terminal rendering for capability reports and build output.
- `ruamel.yaml` ≥0.18,<0.19 — YAML parse/emit with round-trip comment preservation for recipe and stack manifests.
- `pip-audit` 2.10.1 — credential-free Python dependency audit; part of the supply-chain scan gate.

**MCP Layer:**
- `@himorishige/hatago-mcp-hub` 0.0.16 (pnpm global, `harnessed-hatago` image) — aggregates all stack MCP servers behind a single Streamable-HTTP endpoint on `:3535`.
- `mcp-server-time` 2026.6.4 (uvx, baked into `harnessed-hatago`) — tracer-bullet stdio MCP server for time/timezone queries; spawned as hatago child.
- `fastmcp` (mcp Python SDK) — used by `services/ping/server.py` for the ping tracer shared service.

**Build/Dev:**
- `osv-scanner` 2.3.8 (static Go binary, `harnessed-tools` image) — credential-free CVE scan of lockfiles and images at build time; HIGH threshold gate (CVSS ≥ 7.0).
- `snyk` (pnpm global, token-gated) — `snyk test --severity-threshold=high` on npm/pnpm trees; warn-and-skip without token.
- `socket` CLI (token-gated) — optional supply-chain behavioral signals; warn-and-skip without token.
- `jq` (system package, `harnessed-tools` image) — JSON shaping of emitted artifacts.
- `yq` (mikefarah Go binary) — YAML/JSON munging in shell assembler glue.

## Key Dependencies

**Critical:**
- `@himorishige/hatago-mcp-hub@0.0.16` — the MCP aggregation hub; every stack's harness reaches MCP capabilities exclusively through it at `http://localhost:3535/mcp`.
- `ruamel.yaml>=0.18` — parses all recipe and stack manifests; the assembler's data contract.
- `rich>=14` — the sole terminal rendering library; used in capability reports.

**Infrastructure:**
- `pip-audit==2.10.1` — locked version; part of the non-optional build gate alongside osv-scanner.
- `1password-cli` (op) + `1password` desktop app — installed via official apt repo in `harnessed-base` and `harnessed-tools` images; `op` binary only (no desktop app) in `harnessed-tools`.
- `varlock` (`dmno-dev/varlock`) — opt-in secrets layer; inert unless `~/.config/harnessed/.env.schema` exists.

## Configuration

**Environment:**
- No host `.env` file. Credentials are env-only, injected at launch.
- Optional varlock + 1Password for `op://` secret resolution (`harnessed auth snyk|socket` for scanner tokens).
- `HARNESSED_DIR` — set by `harnessed` bootstrap to the resolved repo directory.
- `CONTAINER_HOME=/home/harnessed` — in-container home for all harness images.
- `HARNESSED_NET` — opt-in bridge network name for bridge-capable hosts; default is `host.containers.internal` via pasta networking.
- `NO_FIREWALL` — set to `true` to skip egress firewall (default: `false`).
- `XDG_CACHE_HOME=/opt/osv-cache` — offline OSV database location in `harnessed-tools` image.

**Build:**
- `base/Dockerfile.harnessed-base` — lineage root; all harness images build `FROM` this.
- `base/Dockerfile.hatago` — MCP hub image; `FROM harnessed-base`.
- `base/Dockerfile.harnessed-{claude,omp,opencode,gemini,antigravity,codex}` — per-harness images; each `FROM harnessed-base`.
- `tools/Dockerfile` — assembler image; `FROM python:3.13-slim` (independent lineage).
- `lib/pnpm/config.yaml` — master pnpm supply-chain policy; COPY'd into every image.
- `tools/pnpm-workspace.yaml` — project-scoped `allowBuilds` (snyk only); COPY'd into tools image.

## Platform Requirements

**Development (host):**
- Podman ≥ 5.6 (rootless) or Docker. `loginctl enable-linger $USER` required for rootless socket persistence.
- `git` — for `install.sh` repo clone.
- No host Python, Node, or uv required.

**Production / Deployment:**
- Local only. Stacks run as podman pods on the user's own machine.
- Each stack = one pod (`harnessed-<stack>-<projhash>`) containing harness container + hatago container.
- Shared services (e.g., ping) run as standalone containers outside the pod, host-published on fixed ports.

---

*Stack analysis: 2026-06-24*
`````

## File: .planning/codebase/STRUCTURE.md
`````markdown
# Codebase Structure

**Analysis Date:** 2026-06-24

## Directory Layout

```
code-container/
├── harnessed                    # Host bootstrap CLI (bash, the only host entrypoint)
├── install.sh                   # Installer: clones repo + symlinks harnessed onto PATH
├── uninstall.sh                 # Uninstaller
├── Dockerfile                   # Legacy single-container image (pre-harnessed)
├── AGENTS.md                    # AI assistant instructions (points to CLAUDE.md)
├── CLAUDE.md                    # Project instructions + technology stack reference
├── DESIGN.md                    # Design rationale (§ references used throughout codebase)
├── Permissions.md               # Harness permission configuration guide
├── extra-tools.txt              # User-editable list of extra mise tools to bake
├── skills-lock.json             # Vendored skill lock file
│
├── lib/                         # Bash library modules sourced by harnessed bootstrap
│   ├── harnessed-common.sh      # Image names, runtime detection, instance lifecycle
│   ├── harnessed-isolated.sh    # Isolated stack pod launcher (main launch path)
│   ├── harnessed-mounts.sh      # §4a host-integration mounts (SSH/GPG/git/project)
│   ├── harnessed-isolated-config.sh  # §4b auth seeding (credentials + stub)
│   ├── harnessed-cli.sh         # Subcommands: list/stop/rm/new/install/uninstall
│   ├── harnessed-services.sh    # Shared service lifecycle (svc up/down/list)
│   ├── harnessed-secrets.sh     # Optional varlock + 1Password secrets layer
│   ├── harnessed-runtime.sh     # Runtime abstraction (podman pods vs docker)
│   ├── harnessed-rescan.sh      # Nightly CVE rescan trigger (SEC-04)
│   ├── harnessed-manifest-mounts.sh  # Per-harness profile file mounts
│   ├── egress-firewall.sh       # iptables egress firewall (applied inside harness)
│   ├── manifests/               # Per-harness mount manifests (YAML)
│   │   ├── claude.yaml          # profile_files + history_dirs for claude harness
│   │   ├── omp.yaml
│   │   ├── opencode.yaml
│   │   ├── gemini.yaml
│   │   ├── antigravity.yaml
│   │   └── codex.yaml
│   └── pnpm/
│       └── config.yaml          # Managed pnpm supply-chain policy (baked into images)
│
├── base/                        # Dockerfiles for base + harness images
│   ├── Dockerfile.harnessed-base       # Lineage root (Ubuntu + mise + pnpm + python)
│   ├── Dockerfile.harnessed-claude     # FROM base + Claude Code CLI
│   ├── Dockerfile.harnessed-omp        # FROM base + omp + claude-hooks-bridge
│   ├── Dockerfile.harnessed-opencode   # FROM base + opencode + baked MCP config
│   ├── Dockerfile.harnessed-gemini     # FROM base + gemini-cli + baked MCP config
│   ├── Dockerfile.harnessed-antigravity # FROM base + agy + baked MCP config
│   ├── Dockerfile.harnessed-codex      # FROM base + codex + baked MCP config
│   └── Dockerfile.hatago               # hatago MCP hub image
│
├── agents/                      # Agent manifest files (harness image declarations)
│   ├── claude/agent.yaml
│   └── omp/agent.yaml
│
├── stacks/                      # Stack manifests (user-authored, one per stack)
│   ├── tracer-time/stack.yaml   # Tracer bullet: claude + time recipe
│   ├── ping-time/stack.yaml
│   ├── claude-multi/stack.yaml
│   ├── omp-time/stack.yaml
│   ├── opencode-time/stack.yaml
│   ├── gemini-time/stack.yaml
│   ├── codex-time/stack.yaml
│   └── antigravity-time/stack.yaml
│
├── recipes/                     # Recipe manifests + skill assets (user-authored)
│   ├── time/
│   │   ├── recipe.yaml          # MCP server declaration + skills reference
│   │   └── skills/time-helper/  # Standalone skill shipped by this recipe
│   ├── ping/recipe.yaml         # Service-referenced MCP server
│   ├── greet/
│   │   ├── recipe.yaml
│   │   └── skills/greet-helper/
│   ├── omp/recipe.yaml
│   ├── opencode/recipe.yaml
│   ├── gemini/recipe.yaml
│   ├── codex/recipe.yaml
│   ├── antigravity/recipe.yaml
│   ├── gstack/recipe.yaml
│   └── floating-recipe/recipe.yaml  # Test fixture (intentional bad pin)
│
├── services/                    # Shared service sidecars (own image + volume)
│   └── ping/
│       ├── Dockerfile
│       ├── server.py            # MCP streamable-HTTP server
│       └── service.yaml         # name, image, volume, port, healthcheck
│
├── profiles/                    # Committed assembled profiles (generated by assembler)
│   ├── tracer-time/
│   │   ├── .claude/skills/      # Fanned skill trees from recipes
│   │   ├── .mcp.json            # Single hatago endpoint
│   │   ├── hatago.config.json   # hatago child-server config
│   │   ├── baked-servers.json   # Servers the hatago image must bake
│   │   └── settings.json        # Pre-approved MCP tools
│   └── <other-stacks>/          # Same structure for each assembled stack
│
├── tools/                       # Build-time tooling (runs inside harnessed-tools container)
│   ├── Dockerfile               # harnessed-tools image (Python + scanners)
│   ├── pyproject.toml           # Python package declaration
│   ├── uv.lock                  # Python dependency lockfile
│   ├── pnpm-workspace.yaml
│   ├── harnessed/               # Python package: the emit-only assembler
│   │   ├── __init__.py
│   │   ├── cli.py               # CLI entry point (assemble/test/scan subcommands)
│   │   ├── schema.py            # Parse + validate recipe/stack YAML → typed dataclasses
│   │   ├── assemble.py          # Orchestrate assembly (read → fan → merge → emit)
│   │   ├── emit.py              # Write profile artifacts (EMIT ONLY, no podman)
│   │   ├── scan.py              # Supply-chain scan gate (osv-scanner + pip-audit + snyk)
│   │   ├── capability.py        # Per-stack capability test (manifest oracle vs live pod)
│   │   ├── report.py            # Rich terminal rendering of capability results
│   │   └── synclinks.py         # Fan skills/commands into profile tree (collision detect)
│   ├── test-fixtures/           # Minimal fixture manifests for assembler unit tests
│   │   ├── recipes/             # low-recipe, npm-recipe, svc-recipe, vuln-recipe
│   │   ├── stacks/              # Corresponding test stacks
│   │   └── services/
│   └── uat/                     # User acceptance tests (integration-level, phase-based)
│       ├── run-uat.sh
│       ├── uat-common.sh
│       ├── phase-04.sh
│       ├── phase-05.sh
│       ├── phase-06.sh
│       ├── phase-08.sh
│       └── phase-09.sh
│
├── docs/                        # Documentation
│   ├── guides/                  # How-to guides (recipe authoring, stacks, services, secrets)
│   ├── prompts/                 # LLM prompts for authoring guides
│   └── research/                # Research notes
│
├── systemd/                     # Systemd user timer for nightly rescan (SEC-04)
│
├── web/                         # Static documentation website (Astro)
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── layouts/
│       ├── data/
│       └── styles/
│
├── .planning/                   # GSD planning artifacts (phases, roadmap, codebase docs)
│   ├── PROJECT.md
│   ├── ROADMAP.md
│   ├── STATE.md
│   ├── codebase/                # This directory
│   ├── milestones/
│   ├── phases/
│   └── todos/
│
└── .agents/                     # Project-scoped agent skills
    └── skills/
```

## Directory Purposes

**`lib/`:**
- Purpose: All bash modules sourced by the `harnessed` bootstrap at runtime
- Contains: Launch logic, mount construction, auth seeding, service lifecycle, CLI subcommands
- Key files: `harnessed-common.sh` (shared helpers), `harnessed-isolated.sh` (main launch path), `harnessed-mounts.sh` (§4a mounts)

**`base/`:**
- Purpose: Dockerfiles for the harness image lineage
- Contains: `harnessed-base` (lineage root) + one Dockerfile per supported harness + hatago hub
- Key files: `Dockerfile.harnessed-base` (toolchain foundation), `Dockerfile.hatago` (MCP hub)

**`stacks/`:**
- Purpose: User-authored stack manifests — each declares ONE harness + recipe list
- Contains: One subdirectory per stack, each with `stack.yaml`
- Key files: `stacks/tracer-time/stack.yaml` (reference example)

**`recipes/`:**
- Purpose: User-authored recipe manifests + bundled skill/command assets
- Contains: One subdirectory per recipe with `recipe.yaml` + optional `skills/` subdirs
- Key files: `recipes/time/recipe.yaml` (tracer bullet reference)

**`services/`:**
- Purpose: Shared service sidecars with independent lifecycle
- Contains: One subdirectory per service with `Dockerfile`, `server.py`, `service.yaml`
- Key files: `services/ping/service.yaml` (reference example)

**`profiles/`:**
- Purpose: Committed assembled profiles — the output of `harnessed build <stack>`
- Contains: One subdirectory per assembled stack; regenerated from scratch on each build
- Key files: `profiles/<stack>/.mcp.json`, `profiles/<stack>/hatago.config.json`
- Generated: Yes (by assembler); Committed: Yes (deterministic; profiles are version-controlled)

**`tools/harnessed/`:**
- Purpose: Python package implementing the emit-only assembler and capability tester
- Contains: `schema.py`, `assemble.py`, `emit.py`, `scan.py`, `capability.py`, `report.py`, `synclinks.py`
- Key files: `cli.py` (entrypoint), `schema.py` (manifest oracle used by test + assemble)

**`tools/uat/`:**
- Purpose: Integration-level user acceptance tests (phase-based)
- Contains: One shell script per implementation phase (`phase-04.sh` through `phase-09.sh`)
- Key files: `uat-common.sh` (shared UAT helpers)

**`lib/manifests/`:**
- Purpose: Per-harness mount manifest YAML files
- Contains: `<harness>.yaml` with `profile_files` and `history_dirs` lists
- Key files: `lib/manifests/claude.yaml` (reference)

**`lib/pnpm/`:**
- Purpose: Managed pnpm supply-chain policy applied to ALL pnpm trees in images
- Contains: `config.yaml` (COPIED into images during build; never a runtime-only config)

## Naming Conventions

**Files:**
- Bash lib modules: `harnessed-<purpose>.sh` (e.g. `harnessed-mounts.sh`)
- Python modules: lowercase snake_case (e.g. `assemble.py`, `scan.py`)
- Dockerfiles: `Dockerfile.<image-name>` in `base/`, plain `Dockerfile` in `services/<name>/`
- YAML manifests: `stack.yaml`, `recipe.yaml`, `service.yaml`, `agent.yaml` — always singular

**Directories:**
- Stack names: `kebab-case` (e.g. `tracer-time`, `ping-time`)
- Recipe names: `kebab-case`, usually a noun (e.g. `time`, `ping`, `greet`)
- Service names: match recipe reference name (e.g. `ping`)
- Profile names: exactly match stack names (assembler enforces this)

**Container/pod names:**
- Pod instances: `harnessed-<stack>-<projhash>` (generated by `generate_instance_name` in `lib/harnessed-common.sh`)
- Images: `harnessed-<component>:latest` (e.g. `harnessed-base:latest`, `harnessed-claude:latest`, `harnessed-hatago:latest`)

## Key File Locations

**Entry Points:**
- `harnessed`: Host CLI bootstrap — all user-facing commands start here
- `tools/harnessed/cli.py`: harnessed-tools assembler entrypoint (runs inside container)

**Configuration:**
- `stacks/<name>/stack.yaml`: Stack declaration (harness + recipes)
- `recipes/<name>/recipe.yaml`: Recipe declaration (MCP servers + skills)
- `services/<name>/service.yaml`: Service declaration (image + volume + port)
- `lib/pnpm/config.yaml`: Global pnpm supply-chain policy (baked into images)
- `lib/manifests/<harness>.yaml`: Per-harness mount manifest

**Core Logic:**
- `lib/harnessed-isolated.sh`: Main stack launch function (`harnessed_isolated`)
- `lib/harnessed-mounts.sh`: §4a host-integration mount construction
- `lib/harnessed-isolated-config.sh`: §4b auth seeding
- `tools/harnessed/schema.py`: Manifest parsing (used by both assembler and capability test)
- `tools/harnessed/assemble.py`: Assembly orchestration
- `tools/harnessed/emit.py`: Profile artifact emission

**Dockerfiles:**
- `base/Dockerfile.harnessed-base`: Toolchain lineage root
- `base/Dockerfile.harnessed-claude`: Claude Code harness image
- `base/Dockerfile.hatago`: hatago MCP hub image
- `tools/Dockerfile`: harnessed-tools assembler image

**Testing:**
- `tools/uat/phase-*.sh`: Integration UAT scripts (phase-based)
- `tools/test-fixtures/`: Minimal fixture manifests for assembler unit tests
- `tools/harnessed/capability.py`: Per-stack capability test (manifest oracle vs live pod)

## Where to Add New Code

**New harness support (e.g. a new AI coding tool):**
- Image: `base/Dockerfile.harnessed-<harness>` (FROM harnessed-base)
- Agent manifest: `agents/<harness>/agent.yaml`
- Harness image constant: `lib/harnessed-common.sh` (add `HARNESSED_<HARNESS>_IMAGE`)
- Lazy-build call: `lib/harnessed-isolated.sh` (add `ensure_<harness>_image` call)
- Schema constant: `tools/harnessed/schema.py` (`HARNESS_CONFIG_DIR` dict + validation set)
- CLI scaffolder: `lib/harnessed-cli.sh` (`new_stack` harness case list)
- Auth seeding: `lib/harnessed-isolated-config.sh` (`harnessed_isolated_auth_mounts` function)
- Harness mount manifest: `lib/manifests/<harness>.yaml`

**New recipe:**
- Create `recipes/<name>/recipe.yaml` (follow `recipes/time/recipe.yaml` as template)
- Optional: `recipes/<name>/skills/<skill-name>/SKILL.md` for bundled skills

**New stack:**
- Create `stacks/<name>/stack.yaml` (or use `harnessed new <name> --harness <h> --recipes a,b`)
- Run `harnessed build <name>` to assemble the profile

**New shared service:**
- Create `services/<name>/Dockerfile`, `services/<name>/server.py`, `services/<name>/service.yaml`
- Reference in recipe: `service: <name>` under `mcp.servers[]`

**New lib bash module:**
- Create `lib/harnessed-<purpose>.sh`
- Source it in `lib/harnessed-isolated.sh` or `lib/harnessed-common.sh` as appropriate

**New Python assembler module:**
- Create `tools/harnessed/<module>.py`
- Import from `tools/harnessed/cli.py` or `tools/harnessed/assemble.py`

**New UAT test:**
- Create `tools/uat/phase-<NN>.sh` (use `tools/uat/uat-common.sh` helpers)

## Special Directories

**`profiles/`:**
- Purpose: Committed assembled profiles (output of `harnessed build <stack>`)
- Generated: Yes (by `harnessed-tools assemble`)
- Committed: Yes — profiles are version-controlled as the build artifact

**`tools/__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No (in `.gitignore`)

**`.planning/`:**
- Purpose: GSD planning workflow artifacts (phases, roadmap, todos, codebase docs)
- Generated: Partially (phases generated by GSD commands)
- Committed: Yes

**`.agents/skills/`:**
- Purpose: Project-scoped agent skills for Claude Code
- Generated: No (authored)
- Committed: Yes

---

*Structure analysis: 2026-06-24*
`````

## File: .planning/codebase/TESTING.md
`````markdown
# Testing Patterns

**Analysis Date:** 2026-06-24

## Test Framework

**Runner:**
- Custom pure-Bash UAT harness — no external test framework (`tools/uat/uat-common.sh`)
- No bats, no pytest, no Jest — dependency-free by design (matches the project's "podman is the only host dependency" ethos)

**Assertion Library:**
- Pure bash built-ins: `[[ =~ ]]` for regex, `[[ == *..* ]]` for substring, `[ -e ]` / `[ -x ]` for filesystem checks
- All assertions defined in `tools/uat/uat-common.sh`

**Run Commands:**
```bash
./tools/uat/run-uat.sh <phase>           # Run a full phase UAT suite (e.g., 4 or 04)
./tools/uat/run-uat.sh <phase> --quick   # Skip heavy container-launch tests
./tools/uat/run-uat.sh <phase> <test_id> # Run a single named test
```

## Test File Organization

**Location:**
- All UAT suites live in `tools/uat/`
- One suite file per feature phase: `tools/uat/phase-<NN>.sh`

**Naming:**
- Phase suites: `phase-<NN>.sh` (zero-padded phase number)
- Shared harness: `uat-common.sh`
- Driver: `run-uat.sh`

**Structure:**
```
tools/uat/
├── uat-common.sh          # Shared AAA markers, assertion helpers, driver
├── run-uat.sh             # Phase-selection driver (sources uat-common.sh + suite)
├── phase-04.sh            # Phase 4 suite: shared services + full CLI
├── phase-05.sh            # Phase 5 suite: secrets + hardening
├── phase-06.sh            # Phase 6 suite
├── phase-08.sh            # Phase 8 suite
└── phase-09.sh            # Phase 9 suite
```

## Test Structure

**Suite Organization:**

Each phase suite defines `test_<id>()` functions and a `uat_run_phase` entrypoint.
Every test follows the AAA (Arrange → Act → Assert) pattern:

```bash
test_svc_up() {
    arrange
    "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true   # tolerate absence
    act
    uat_run "$HARNESSED" svc up ping
    assert
    assert_exit_zero "$UAT_RC" "svc up ping exits 0"
    assert_contains "is up" "$UAT_OUT" "reports the service is up"
}
run_test svc_up "svc up publishes port and lists"
```

**Patterns:**
- `arrange` / `act` / `assert` are purely visual markers (they echo section names; no control flow)
- `uat_run` captures both stdout+stderr into `UAT_OUT` and exit code into `UAT_RC`
- Assertions never abort — they accumulate pass/fail counts; `uat_summary` returns non-zero if any failed
- Cleanup in Arrange uses `|| true` to tolerate absent state (idempotent setup)
- Container-heavy tests self-skip via a `needs_container` guard:
  ```bash
  needs_container() { [ "$UAT_QUICK" = "true" ]; }
  test_foo() {
      needs_container && { skip_test "skipped (--quick)"; return; }
      ...
  }
  ```

## Assertion Library

All assertions are defined in `tools/uat/uat-common.sh`. Arguments are positional — label is always last:

```bash
assert_exit_zero    "$UAT_RC"      "label"
assert_exit_nonzero "$UAT_RC"      "label"
assert_eq           "$actual"   "$expected"  "label"
assert_ne           "$actual"   "$unexpected" "label"
assert_match        "regex"     "$actual"    "label"
assert_not_match    "regex"     "$actual"    "label"
assert_contains     "substring" "$actual"    "label"
assert_not_contains "substring" "$actual"    "label"
assert_exists       "/path"      "label"
assert_not_exists   "/path"      "label"
assert_file_contains "/path" "substring" "label"
assert_executable   "/path"      "label"
assert_true         cmd [args...]  "label"   # pass if cmd exits 0
assert_false        cmd [args...]  "label"   # pass if cmd exits non-zero
```

## Mocking

**Framework:** None — no mock library. Tests exercise the REAL `harnessed` CLI binary against the real container runtime.

**Patterns:**
- **Env-var injection** to force inert/alternate paths without touching real credentials:
  ```bash
  uat_run_env "HARNESSED_SCHEMA=/nonexistent/path/.env.schema" "$HARNESSED" build tracer-time
  uat_run_env "SNYK_TOKEN=dummy-uat-token" "$HARNESSED" build tracer-time
  ```
- **Pre-flight cleanup** to establish a known state before acting:
  ```bash
  "$HARNESSED" svc down ping --purge >/dev/null 2>&1 || true
  ```
- **Container self-skip** under `--quick` to skip tests that need a live pod

**What NOT to Mock:**
- The `harnessed` launcher itself — tests drive it as a black box
- The container runtime — container-launch tests use the real podman/docker

## Test Types

**UAT / Integration Tests (primary):**
- Scope: Behavior asserted through the running CLI against the stack manifest as oracle (design §18)
- Drives the real `harnessed` binary
- Asserts CLI exit codes, stdout/stderr content, container/pod/volume state
- The stack manifest (`stack.yaml` + `recipe.yaml`) is the oracle — never hardcoded expectations
- Live container tests require a running podman/docker daemon

**Capability Tests (automated integration, via `harnessed test <stack>`):**
- Scope: Per-stack — launches a `--fresh` headless instance, introspects the live pod, diffs actual vs declared capabilities
- Oracle: `schema.py`'s `expected_capabilities(stack, recipes)` derives expected MCP servers/skills/commands from the manifest
- Python entry: `tools/harnessed/capability.py` → `run_capability_test()`
- Report: rendered by `tools/harnessed/report.py` (rich table or JSON for CI via `--json`)
- CI exit code: non-zero when any declared capability is missing
- Pure functions (`build_report`, `expected_capabilities`) are unit-testable without podman

**UAT Quick Mode:**
- `--quick` flag skips all tests that require a container launch
- Fast (non-container) tests still run: CLI argument parsing, flag validation, schema error paths
- Heavy tests document their skip reason: `skip_test "skipped (--quick) — runs the tools container"`

**Manual-Only Tests:**
- Documented per-phase in `<NN>-HUMAN-UAT.md` files
- Cover: live `op://` secret resolution, 1Password desktop-app auth, overnight nightly timer, browser OAuth flows
- Not scriptable — require interactive input or overnight state

## Fixtures and Factories

**Test Data:**
- Real authored stacks (`stacks/tracer-time/stack.yaml`, `stacks/ping-time/stack.yaml`) double as test fixtures
- No synthetic fixture files — tests reuse the actual repo manifests
- Env override pattern for nonexistent paths:
  ```bash
  UAT_NO_SCHEMA="/nonexistent/harnessed-uat-$$/.env.schema"
  ```

**State isolation:**
- Container-launch tests tear down via `--purge` in Arrange and cleanup in teardown
- `--fresh` flag on instance launches ensures no state bleed between test runs (threat T-02-08)
- `uat_pod_rm` helper force-removes pods by name in cleanup

## Coverage

**Requirements:** No numeric coverage target enforced. Integration coverage is behavior-driven against the manifest oracle.

**Explicit gap tracking:**
- Known gaps are annotated in suite files as inline comments:
  ```bash
  # Two tests encode KNOWN GAPS as red regression checks (go green when the fix lands):
  #   - no_args_help     (UAT gap 6B): bare `harnessed` should show usage
  #   - legible_slug     (UAT gap 6) : state-dir slug should be a legible path
  ```
- Manual-only legs tracked in `<NN>-HUMAN-UAT.md` per phase

**View test output:**
```bash
./tools/uat/run-uat.sh 4              # Full suite with summary
./tools/uat/run-uat.sh 4 --quick      # Fast-only pass
./tools/uat/run-uat.sh 4 svc_up       # Single test by id
```

## Test Output Format

`uat-common.sh` produces structured terminal output:

```
╔══════════════════════════════════════════════════════════════╗
║  UAT SUITE: <title>
╚══════════════════════════════════════════════════════════════╝

━━━ TEST 1: svc up publishes port and lists  (svc_up) ━━━
  ▸ Arrange
  ▸ Act
    ▸ harnessed svc up ping
  ▸ Assert
    ✓ svc up ping exits 0
    ✓ reports the service is up
  → PASS

════════════════════════════════════════════════════════════════
  TESTS:  3 passed, 0 failed, 1 skipped (4 total)
  CHECKS: 8 passed, 0 failed
════════════════════════════════════════════════════════════════
```

Pass/fail counts are cumulative across all assertions within the suite. Exit code from `uat_summary` is non-zero if any test failed.

## Python Unit-Testable Surface

The following Python functions are pure (no subprocess, no podman) and are explicitly designed for unit testing:

- `tools/harnessed/schema.py`: `load_recipe`, `load_stack`, `validate_no_raw_npm`, `validate_pin`, `validate_harness_compat`, `expected_capabilities`
- `tools/harnessed/scan.py`: `_cvss3_base`, `_roundup`, `_severity_score` (CVSS parsing, no subprocess)
- `tools/harnessed/capability.py`: `build_report`, `expected_capabilities` (diff logic, no podman)

No Python unit test files (`*.test.py` / `*.spec.py` / `test_*.py`) are present. Testing relies exclusively on the UAT harness driving the assembled CLI.

---

*Testing analysis: 2026-06-24*
`````

## File: .planning/RECIPE-ARCHITECTURE-MILESTONE.md
`````markdown
# Milestone: Recipe Architecture & Agent Rebuild

> **Status:** Ready for execution
> **Mode:** Vertical-MVP (each task delivers an observable end-to-end capability)
> **Depends on:** Transparent mode removal (complete); the codebase is now single-mode harnessed

## Summary

Rebuild the harness images as fat agent bases, introduce a Dockerfile-based recipe model where
recipes run frameworks' own installers (no reinterpretation), gate the build on a supply-chain scan
of the derived image, and validate with a combined capability test (structured MCP probe +
un-primed ask-the-agent). Ship two agent images (claude, omp) and one proof-of-concept recipe
(gstack).

---

## Architecture Specification

### 1. Image Lineage (3 layers)

```
harnessed-base          Toolchain: mise, python@3.12, node@22, pnpm@11, bun, rust, go,
                        common CLI tools (fd, ripgrep), 1Password CLI, egress firewall,
                        pnpm supply-chain config.
                        Conservative version pins (NOT latest) for maximum compatibility —
                        most frameworks support python 3.12 + node 22 LTS. Recipes override
                        via `mise use -g <tool>@<version>` when they need a different version.
                        NO harness CLIs (moved out — a claude stack must not carry omp/codex/gemini).

harnessed-<agent>       Agent base: FROM harnessed-base + ONE harness CLI + its config baking
  harnessed-claude        (curl claude.ai/install.sh | bash)
  harnessed-omp           (omp CLI + claude-hooks-bridge + pi-adapter)
                        Built once, cached, reused across stacks.
                        Bakes the harness's native MCP config pointing at the hatago endpoint.

harnessed-<stack>       Derived stack image: FROM harnessed-<agent> + recipe Dockerfile bodies.
  harnessed-tracer-time   GENERATED by the assembler (one per stack).
  harnessed-gstack        Contains everything the recipes installed (skills, tools, plugins).
```

The base pins conservative stable versions (python 3.12, node 22 LTS — not latest) so most
recipes work out-of-the-box without version overrides. mise is pre-installed so a recipe that
needs a different version adds one line: `RUN mise use -g python@3.13 && mise install`. The
philosophy: boring defaults that maximize compatibility, with mise as the override mechanism.

### 2. Recipe Model (Dockerfile + YAML)

A recipe is a directory with two files:

**`recipe.yaml`** — what hatago needs to know + which harnesses it supports + a smoke-check list:
```yaml
name: gstack
description: Garry Tan's Claude Code framework — 23 specialist skills + browse tool.

# Which harnesses this recipe's installer can target. The assembler refuses to compose
# the recipe onto a stack whose harness is not listed (clean error, not a cryptic build
# failure). Drives the `--host $HARNESS` value passed to the installer (see Dockerfile).
harnesses: [claude]

# MCP servers this recipe provides (merged across recipes into hatago.config.json).
# Absent for pure-skills recipes like gstack.
mcp:
  servers:
    - name: time
      command: uvx
      args: [mcp-server-time]
      transport: stdio

# Smoke check (NOT a completeness oracle): a stable subset the test asks the agent about
# to confirm the install LANDED. The framework may ship more than this; that is fine —
# we are confirming the installer completed, not enumerating everything it shipped.
# Pick entries unlikely to be renamed across upstream versions.
expect:
  skills: [office-hours, plan-ceo-review, review, qa, ship]
  tools: [browse]
```

**`Dockerfile`** — how to install (runs the framework's own installer as-is, pinned + parameterized):
```dockerfile
FROM harnessed-claude:latest
# Pin to a tag/SHA (reproducibility + supply chain) — never float on a branch.
# $HARNESS is substituted by the assembler from the stack's harness (build ARG).
ARG HARNESS=claude
ARG GSTACK_REF=v1.4.0
RUN git clone --branch ${GSTACK_REF} --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack \
    && cd ~/.claude/skills/gstack && ./setup --host ${HARNESS}
```

**The principle: don't reinterpret the install — run it.** The framework's setup script knows how
to install itself. The recipe's job is to get out of the way: FROM the agent image, run the
installer, done. The assembler does not parse SKILL.md files, discover skill trees, or understand
the framework's layout. It concatenates Dockerfile bodies and lets the framework handle its own
business. Two non-negotiables sit on top of "run it": the source is **pinned to a tag/SHA** (we
version-control the recipe and *which version* it installs — never the vendor's data, never a
floating branch), and the **harness is parameterized** (`--host ${HARNESS}`), not hardcoded — the
recipe declares the harnesses it supports and the assembler passes the right one. Where an
installer needs a post-install tweak for a given harness, that's an ordinary extra `RUN` in the
recipe Dockerfile — the escape hatch is always available.

### 3. Agents as Recipes (`type: agent`)

Agents and framework recipes share the same mechanism — both are a Dockerfile + a YAML manifest.
The `type` field distinguishes them:

```yaml
# agents/claude/recipe.yaml
name: claude
type: agent
harness: claude
description: Claude Code harness base image.
```
```dockerfile
# agents/claude/Dockerfile
FROM harnessed-base:latest
RUN curl -fsSL https://claude.ai/install.sh | bash
```

| Field | `type: agent` | `type: recipe` (default) |
|---|---|---|
| FROM | `harnessed-base` | `harnessed-<agent>` |
| Built | Once, cached as `harnessed-<name>` | Concatenated into `harnessed-<stack>` per stack |
| Composes | No (one per stack) | Yes (many per stack, bodies concatenated) |
| Has `mcp:` | No | Optional |
| Has `expect:` | No | Optional (smoke check) |
| `harness:` / `harnesses:` | `harness:` (the one it provides) | `harnesses:` (the set its installer supports; assembler refuses other stacks) |

Directory layout:
```
agents/                     ← type: agent (harness base images)
  claude/
    recipe.yaml
    Dockerfile
  omp/
    recipe.yaml
    Dockerfile

recipes/                    ← type: recipe (framework capabilities, default)
  gstack/
    recipe.yaml
    Dockerfile
  time/
    recipe.yaml
    Dockerfile
```

The assembler handles them differently:
- `type: agent` → `harnessed build` builds it as a standalone cached image (`harnessed-<name>`)
- `type: recipe` → `harnessed build <stack>` strips the FROM, concatenates the body into the
  stack's derived Dockerfile

### 4. Profile Mount Model Change

**Problem:** Today the launcher mounts the entire `~/.claude/` tree from the profile (copy-on-start
to a per-instance state dir). This **replaces** whatever the image baked — recipe-installed skills
would be invisible at runtime (the gap-analysis WR-1 problem, now load-bearing).

**Fix:** Stop mounting the whole `~/.claude/` dir. Mount surgically:

| Path | Source | Why |
|---|---|---|
| `~/.claude/skills/` | **Image** (recipe Dockerfile baked them) | Survives — no mount over it |
| `~/.claude/.mcp.json` | **Profile** (assembler-generated, points at hatago) | Per-stack MCP config |
| `~/.claude/settings.json` | **Profile** (assembler-generated, permissions) | Per-stack settings |
| `~/.claude/.credentials.json` | **Host** (ro, unchanged) | Auth seeding |

The profile shrinks: it carries only the assembler-generated config files (`.mcp.json`,
`settings.json`, `hatago.config.json`), NOT skills. Skills are image-baked by recipe Dockerfiles.

**Per-harness config-file equivalents** (same surgical pattern, harness-specific paths):

| Harness | Config files mounted from profile |
|---------|----------------------------------|
| claude | `~/.claude/.mcp.json`, `~/.claude/settings.json` |
| omp | `~/.omp/agent/config.yml`, `~/.omp/agent/mcp.json` |
| opencode | `~/.config/opencode/opencode.json` (image-baked → hatago endpoint) |
| gemini | `~/.gemini/settings.json` (image-baked → hatago `mcpServers`) |
| codex | `~/.codex/config.toml` (image-baked → hatago `[mcp_servers.hatago]`) |
| antigravity | `~/.gemini/antigravity-cli/mcp_config.json` |

#### 4a. Path Mirroring

The container **working directory** must be the **identical absolute host path** of the project.
Set `--workdir $HOST_PWD` in the launcher (with `HOST_PWD` passed as env from the host).

Why this matters:
- **Claude** project slug (`projects/<slug>/`) is derived from the absolute cwd. A container at
  `/container/mcrowe/…` would produce a different slug than the host's `-home-mcrowe-…` — history
  would bifurcate.
- **omp** `agent/sessions/<slug>/` uses a `$HOME`-relative slug. Path mirroring makes both slugs
  line up, *and* keeps embedded transcript `"cwd"` fields host-coherent (clickable file refs work).
- **antigravity** keys history by the `workspace` string (the cwd). Mirroring makes the container's
  workspace key match the host's.
- **DooD `-v $PWD:$PWD`** works with no translation — container `PWD` == host `PWD`.

Isolation is about config (skills/MCP/profile), not the working-dir path. Mirroring the path
leaks no host config.

#### 4b. History Surfacing (per-harness)

History persistence mounts are separate from config mounts. The rule: **mount files; export
databases.** File-per-unit stores (UUID/slug-keyed) are safe to rw-mount because the container
only ever writes new namespaced entries. Shared single-file stores (SQLite with multiple projects'
rows, or whole-file-rewrite JSON) are **never** rw-mounted — they surface via guarded teardown
merge/export filtered by project key.

**Claude Code (`~/.claude/`)**

rw-mount (per-project or UUID-namespaced, collision-free):
- `projects/<project-slug>/` — transcripts + per-project `memory/`
- `file-history/` — pre-edit file snapshots (UUID-keyed)
- `tasks/` — subagent run records (UUID-keyed)
- `session-env/` — session-start hook captures (UUID-keyed)
- `todos/` — per-session todo lists (UUID-keyed)

Guarded teardown (ships **disabled** until format is pinned; no-ops on schema mismatch):
- `history.jsonl` — append lines matching `"project":<slug>`

Never mounted: `skills/`, `commands/`, `hooks/`, `rules/`, `plugins/`, cache dirs, `.credentials.json`
(auth-seeded separately).

**omp (`~/.omp/`)**

rw-mount (collision-free):
- `agent/sessions/<project-slug>/` — rollout transcripts + per-session tool logs (file-per-session)
- `agent/blobs/` (optional) — content-addressed image store (only if pasted-image refs must resolve)

Guarded teardown (ships **disabled**):
- `history.db` — export rows by `cwd = '<project>'`; merge into host DB

**Never** mounted: `agent.db` — co-locates `auth_credentials` with the thread index; mounting it
would expose credentials and merge container auth state into the host. Container runs with a fresh
`agent.db` (auth seeded by the profile).

**antigravity (`~/.gemini/antigravity-cli/`)**

rw-mount (UUID-namespaced, collision-free, WAL-safe — each conversation is its own SQLite file):
- `conversations/` — per-conversation SQLite transcript (UUID-named)
- `brain/` — per-conversation agent memory (UUID-named)
- `implicit/` — per-session implicit context blobs (UUID-named)

Guarded teardown (ships **disabled**):
- `history.jsonl` — lines matching `"workspace":<project-path>`
- `cache/projects.json` — merge this project's workspace→projectId key
- `cache/last_conversations.json` — merge this project's workspace→conversationId key

Never mounted: `antigravity-oauth-token` (auth), `bin/`, `log/`, `settings.json`, `mcp_config.json`,
`builtin/`, or the parent `~/.gemini/` tree (that is gemini-cli's separate store).

**opencode + codex** — history layouts not yet investigated. Each harness's execution phase must:
1. Run the investigation template in `docs/research/home-folder-harness-history-overview.md`.
2. Write `docs/research/home-folder-<harness>-requirements.md`.
3. Add the harness entry to the mount manifest (see §4c).

#### 4c. Data-Driven Mount Manifests

The mount and teardown-merge set for each harness is defined in a **structured per-harness manifest
config** (not inline `-v` flags in bash). An upstream harness layout change is a one-line manifest
edit. The manifest declares:
- **rw bind-mounts** (source → container dest, with collision rationale)
- **teardown-merge targets** (host file, filter key, merge strategy, enabled/disabled)
- **oracle assertions** (what must appear on the host after a throwaway session, for the §18 test)

### 5. Assembler Changes

**Current flow** (`tools/harnessed/assemble.py` + `emit.py`):
1. Read stack.yaml + recipes → parse recipe.yaml (mcp, skills, commands)
2. Fan skills/commands into `profiles/<stack>/.claude/`
3. Merge MCP servers → `hatago.config.json` + `.mcp.json`
4. Emit profile

**New flow:**
1. Read stack.yaml + recipes → parse recipe.yaml (**harnesses**, **mcp**, **expect**) — drop
   skills/commands parsing
2. **NEW:** Harness-compatibility check — for each recipe, assert the stack's `harness` is in the
   recipe's `harnesses:` list. Refuse with a clean error if not (e.g. "recipe gstack supports
   [claude], cannot compose onto harness omp") rather than letting it fail mid-build.
3. Merge MCP servers → `hatago.config.json` + `.mcp.json` (unchanged)
4. **NEW:** Read each recipe's `Dockerfile`, strip the `FROM` line, collect the body. Verify each
   `git clone` / package install in the body is **pinned** (tag/SHA/exact version) — a floating
   `--branch main` / unpinned ref is a validation error.
5. **NEW:** Emit `profiles/<stack>/Dockerfile.harnessed-<stack>` with `HARNESS` passed as a build
   ARG so each recipe's installer targets the stack's harness:
   ```dockerfile
   # Generated by harnessed assemble — do not edit.
   FROM harnessed-<agent>:latest
   ARG HARNESS=<agent>

   # ── recipe: time ──
   COPY skills/time-helper /home/harnessed/.claude/skills/time-helper

   # ── recipe: gstack (pinned, --host ${HARNESS}) ──
   ARG GSTACK_REF=v1.4.0
   RUN git clone --branch ${GSTACK_REF} --depth 1 https://github.com/garrytan/gstack.git \
       ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup --host ${HARNESS}
   ```
6. Emit profile (config files only: `.mcp.json`, `settings.json`)
7. **NEW:** Host runs `podman build --build-arg HARNESS=<agent> -f Dockerfile.harnessed-<stack> -t harnessed-<stack> .`
8. **NEW:** Supply-chain gate — scan the built `harnessed-<stack>` image (see §8); fail the build
   on high-severity findings.

**Build context:** the recipe Dockerfiles may `COPY` from their own directory or `RUN git clone`
from the internet. The build context is the repo root (so `COPY recipes/<name>/...` works) — the
assembler sets up the context correctly.

**Recipe Dockerfile FROM stripping:** the assembler reads each recipe Dockerfile, removes the
`FROM ...` line (keeping everything after), and concatenates the bodies in recipe order under a
single `FROM harnessed-<agent>:latest`. Comments (`#`) are preserved for traceability.

### 6. Capability Test (Combined: Structured Probe + Un-Primed Ask-the-Agent)

**Two oracles, by capability type — they prove different things:**
- A **structured probe** proves a capability is *present/connected* (deterministic, free, no model
  call). This is the right oracle for **MCP servers**.
- The **running agent** proves a capability was actually *loaded/perceived* — a file on disk that
  the agent never loaded is a real failure a filesystem scan misses. This is the right oracle for
  **skills/tools**, which load by description and have no reliable structured list.

Use both; neither alone is sufficient.

**MCP servers → structured probe.** Hit hatago's `/servers` resource (or `claude mcp list`) and
assert the manifest's servers are connected. Deterministic, offline, no session.

**Skills / tools → ask the agent, un-primed.** Naming the expected skills in a "respond YES" prompt
**primes the model** — it can confirm capabilities it never loaded, and the test passes for the
wrong reason. Defeat this with a **negative control**: mix the real `expect:` entries with one
decoy capability that was deliberately *not* installed, and require the agent to identify which it
has and which it lacks. A run that claims the decoy is present is **invalid** (priming/sycophancy
detected), not a pass.

```bash
podman exec <container> claude -p 'You have a set of skills and tools available. For EACH name below, answer "have" or "missing" — do not assume; check what is actually loaded.

office-hours, plan-ceo-review, review, qa, ship, browse, <decoy-not-installed>

Respond as JSON: {"have": [...], "missing": [...]}.'
```

**Assertion (skills/tools):**
- the decoy MUST be in `missing` — else the test is **invalid** (priming detected), report and fail;
- every `expect:` entry MUST be in `have` → pass; any in `missing` → fail, agent's own line is the
  diagnostic.

**Why this shape:**
- No per-harness path map and no filesystem scan — the agent reports its own perception.
- The negative control closes the priming hole the bare "respond YES" prompt left open.
- `expect:` is a **smoke check** (did the install land), not a completeness oracle — a framework
  shipping more than `expect:` lists is success, not failure (see Key Design Decisions).
- Self-diagnosing: the `missing` list is the diagnostic prose.

**Harness-agnostic:** swap the CLI (`omp -p`, `opencode -p`, `codex -p`), keep the prompt
identical. The stack declares which harness it uses; the test knows which CLI to invoke.

**Expectations source:** `recipe.yaml: expect:` declares the skills/tools subset to ask about;
`recipe.yaml: mcp:` declares the servers the structured probe asserts are connected.

### 7. Container-Agnostic Runtime Group

A stack is a **runtime group** of cooperating containers (harness + hatago + optional services),
not a podman pod. The grouping mechanism is abstracted by `lib/harnessed-runtime.sh`:

| Runtime | Group mechanism | Harness → hatago |
|---|---|---|
| podman | pod (shared netns) | `localhost:3535` |
| docker | shared netns (`--network container:`) | `localhost:3535` |
| Apple containers | named network (future) | DNS name / `host.containers.internal` |

**Future portability fix (noted, not blocking this milestone):** the hatago endpoint is currently
hardcoded to `localhost:3535` in `emit.py`. For Apple containers (no shared netns), this must
become a runtime-resolved endpoint. That's a separate change to the profile's `.mcp.json` + the
harness config baking — not a change to what a stack IS.

### 8. Supply-Chain Gate

The Dockerfile-recipe model **runs the framework's own installer at build time** — arbitrary
upstream code (`./setup`, `pip install`, `cargo install`) pulling arbitrary deps. The old
"scan the vendored deps before committing the profile" gate no longer fits (nothing is vendored;
the install happens inside the build). The gate moves to match the new model:

1. **Pin every recipe source to a tag/SHA.** Enforced by the assembler (§5 step 4): a floating
   `--branch main` or unpinned package install is a validation error. This is the reproducibility
   contract *and* the first supply-chain control — you build the same bytes every time, and you
   chose which bytes.
2. **Scan the built derived image.** After `podman build` (§5 step 8):
   - **osv-scanner V2 (always-on, credential-free):**
     ```bash
     osv-scanner scan image harnessed-<stack>:latest
     ```
     Fails on high-severity findings. Never requires a token.
   - **Snyk container scan (warn-and-skip if `SNYK_TOKEN` absent):**
     ```bash
     snyk container test harnessed-<stack>:latest --severity-threshold=high
     ```
     If `SNYK_TOKEN` is not set: log "SNYK_TOKEN not set — skipping Snyk scan" and continue.
     Never prompts; build stays non-interactive. Token set via `harnessed auth snyk`.
   - **Socket.dev (warn-and-skip if `SOCKET_SECURITY_API_KEY` absent):**
     Runs Socket CLI analysis on the derived image's package trees when the key is present.
     If absent: log and skip. Token set via `harnessed auth socket`.
3. **Nightly rescan.** The existing systemd-timer pattern re-scans built stack images so a CVE
   disclosed *after* build still surfaces. Extended to cover `harnessed-<stack>` images in
   addition to base images.

**Known limitation (state it, don't paper over it).** A framework's `./setup` that shells raw
`npm install` does **not** honor the base's pnpm supply-chain config (`minimumReleaseAge`, lifecycle
default-deny) — that policy only governs installs *we* drive. Closing that fully would require
reinterpreting the install, which the recipe model rejects by design. The pin + image-scan +
nightly-rescan chain is the accepted mitigation; the residual (a vendor installer's own raw-npm
cooldown bypass) is documented, not pretended away.

---

## Task Breakdown

### Task 0: Architecture Specification ✅

This document. Write it first so all subagents work from the same spec.

---

### Task 1: Documentation Update

**Subagent:** docs updater
**Depends on:** Task 0 (this document)
**Scope:** Update all narrative docs to describe the new architecture. No code changes.

Files to update:
- `README.md` — image lineage (3 layers), recipe model (Dockerfile + YAML), quickstart with a
  real recipe, command surface (`harnessed build` builds agents + stacks)
- `docs/harnessed-design.md` — §6 (FROM is lineage only, recipes are Dockerfiles), §7 (recipe
  model: Dockerfile + YAML, not typed fields; supply chain = pin sources + scan the derived image,
  not scan vendored deps), §10 (repo layout: `agents/` + `recipes/`), §12 (stack manifest: no more
  `config:`, recipes reference Dockerfiles), §15 (fat base + derived images), §18 (capability test:
  structured MCP probe + un-primed ask-the-agent with a negative control)
- `docs/guides/stacks.md` — recipe model, the `agents/` vs `recipes/` split, the Dockerfile recipe
- `docs/guides/recipe-authoring.md` — how to write a recipe (Dockerfile + recipe.yaml): the
  `harnesses:` field, `expect:` as a smoke check, pinning sources to a tag/SHA, `--host ${HARNESS}`,
  and the "run the framework's installer" principle
- `CLAUDE.md` — architecture constraints, the fat-base principle, the recipe = Dockerfile model
- `AGENTS.md` — setup instructions (build base, build agent, build stack)

Key terminology:
- "Agent" = a harness base image (claude, omp). Built once, cached.
- "Recipe" = a framework capability (gstack, time). Dockerfile + YAML. Composes into stacks.
- "Stack" = a runtime group (harness + hatago + services). The running thing.
- Drop all "isolated" / "transparent" terminology (already removed from code).
- Drop "pod" as a generic term — use "runtime group" (pod is the podman implementation).

---

### Task 2: Agent Image Rebuild

**Subagent:** agent builder
**Depends on:** Task 0
**Scope:** Restructure the image lineage and create the two agent recipes.

#### 2a: Fatten `harnessed-base`

Update `base/Dockerfile.harnessed-base`:
- **Add** to the `mise use -g` block: `bun`, `rust`, `go` (so recipe Dockerfiles can build anything)
- **Remove** the harness CLI installs from the base (lines that install `npm:opencode-ai`,
  `npm:@openai/codex`, `npm:@google/gemini-cli` via mise). These move to their respective agent
  images (out of scope for this milestone — only claude and omp agents are built here).
- Keep everything else (apt deps, 1Password, pnpm config, common tools, user setup, bashrc)

#### 2b: Create `agents/claude/`

```
agents/claude/
  recipe.yaml     ← type: agent, harness: claude
  Dockerfile      ← FROM harnessed-base + curl claude.ai/install.sh | bash
```

The Dockerfile is essentially today's `base/Dockerfile.harnessed-claude` content, moved to
`agents/claude/Dockerfile` with `FROM harnessed-base:latest`.

#### 2c: Create `agents/omp/`

```
agents/omp/
  recipe.yaml     ← type: agent, harness: omp
  Dockerfile      ← FROM harnessed-base + omp CLI + claude-hooks-bridge + pi-adapter
```

The Dockerfile installs omp and its bridge. Reference the existing `base/Dockerfile.harnessed-omp`
and the `recipes/omp/recipe.yaml` for the bridge package.

#### 2d: Update the assembler (ASM-01 / ASM-02 / ASM-03)

Full spec: §5 "Assembler Changes". Summary of what must be implemented:

**ASM-01 — Harness-compatibility check** (`tools/harnessed/assemble.py`):
- Before emitting any Dockerfile, for each recipe in the stack check that `stack.harness` is in
  `recipe.harnesses`. Fail with a clean error (e.g. `"recipe gstack supports [claude], cannot
  compose onto harness omp"`) — not a cryptic mid-build failure.
- Acceptance: `harnessed build bad-stack` (omp + gstack) exits non-zero with the recipe name and
  its `harnesses:` list in the error message. No Dockerfile is emitted.

**ASM-02 — Pin validation**:
- Scan each recipe Dockerfile body for floating refs: `--branch main`, `--branch master`,
  unversioned `latest` in package installs. Any floating ref is a validation error.
- Acceptance: a recipe Dockerfile with `git clone --branch main` fails `harnessed build` with
  the offending line identified before `podman build` starts.

**ASM-03 — Derived Dockerfile emission + HARNESS build ARG**:
- Emit `profiles/<stack>/Dockerfile.harnessed-<stack>`:
  - First line: `FROM harnessed-<agent>:latest`
  - Second line: `ARG HARNESS=<agent>` (value from stack.yaml `harness:`)
  - Then each recipe Dockerfile body in recipe order (FROM line stripped, comment header added)
- The generated launcher script runs:
  `podman build --build-arg HARNESS=<agent> -f Dockerfile.harnessed-<stack> -t harnessed-<stack> .`
- Acceptance: `profiles/gstack-time/Dockerfile.harnessed-gstack-time` contains `ARG HARNESS=claude`
  and the gstack recipe body; `harnessed build gstack-time` completes and `podman images` lists
  `harnessed-gstack-time`.

**Build system plumbing**:
- `harnessed build` (bare) builds: `harnessed-base` + all `agents/*/Dockerfile` + `hatago`
- `harnessed build <stack>` triggers the assembler, then the host builds the derived image
- Move `base/Dockerfile.harnessed-claude` / `base/Dockerfile.harnessed-omp` → `agents/`
- `lib/harnessed-common.sh` image-name constants update to reflect the new paths

#### 2e: Update the launcher (MNT2-01 through MNT2-06)

Full spec: §4 "Profile Mount Model Change". Summary of what must be implemented:

**MNT2-01 — Surgical config-file mount** (not whole-dir):
- Remove the `copy-on-start` / whole-dir bind-mount of `~/.claude/` (or equivalent).
- Mount only the specific config files from the profile: `.mcp.json` and `settings.json` for
  claude; per-harness equivalents for omp/opencode/etc (see §4 per-harness table).
- Acceptance: after `harnessed gstack-time`, `ls ~/.claude/skills/` inside the container shows
  gstack skills (image-baked); host `~/.claude/skills/` is unchanged.

**MNT2-02 — Path mirroring**:
- Set `--workdir $HOST_PWD` in the launcher (pass `HOST_PWD` from the host env).
- Acceptance: inside the running container, `pwd` equals the host project path byte-for-byte.
  After a session, the host gains `~/.claude/projects/-home-mcrowe-…-code-container/<uuid>.jsonl`
  (the `-home-mcrowe-…` slug, not a `-container-mcrowe-…` slug).

**MNT2-03 — Claude Code history surfacing**:
- rw-mount (per-project / UUID-keyed, collision-free):
  `projects/<project-slug>/`, `file-history/`, `tasks/`, `session-env/`, `todos/`
- Guarded teardown merge for `history.jsonl` (ships **disabled**; no-op on schema mismatch).
- Never mount: `skills/`, `commands/`, `hooks/`, `rules/`, `plugins/`, cache, `.credentials.json`.
- Acceptance: after a throwaway session, host has a new `~/.claude/projects/<slug>/<uuid>.jsonl`;
  host `~/.claude/skills/` is unchanged.

**MNT2-04 — omp history surfacing**:
- rw-mount: `agent/sessions/<project-slug>/`; optionally `agent/blobs/`.
- Guarded teardown for `history.db` by `cwd` (ships **disabled**).
- **Never** mount `agent.db` (co-locates `auth_credentials`).
- Acceptance: after a throwaway omp session, host has a new
  `~/.omp/agent/sessions/<slug>/<ts>_<uuid>.jsonl`; `~/.omp/agent.db` is unchanged.

**MNT2-05 — antigravity history surfacing**:
- rw-mount: `antigravity-cli/conversations/`, `antigravity-cli/brain/`, `antigravity-cli/implicit/`
  (UUID-namespaced, WAL-safe).
- Guarded teardown for `history.jsonl` + `cache/projects.json` + `cache/last_conversations.json`
  (ships **disabled**).
- Never mount `antigravity-oauth-token`, `bin/`, `log/`, or parent `~/.gemini/`.
- Acceptance: after a throwaway antigravity session, host has a new
  `~/.gemini/antigravity-cli/conversations/<cid>.db` and `brain/<cid>/`.

**MNT2-06 — Data-driven mount manifests**:
- All mount paths and teardown-merge targets live in a structured per-harness config (not inline
  `-v` flags). The launcher reads this config to build its `podman run` mount args.
- Acceptance: no mount paths are hardcoded in the launcher bash; changing a harness's paths
  requires editing one config entry.

**Other launcher changes**:
- Use `harnessed-<stack>` (the derived image) instead of `harnessed-<harness>`
- `ensure_images` / `ensure_claude_image` / `ensure_omp_image` update to build from `agents/`

**Acceptance (Task 2 combined):**
- `harnessed build` produces `harnessed-base`, `harnessed-claude`, `harnessed-omp`, `hatago`
- `harnessed-base` has bun, rust, go on PATH; does NOT have claude/codex/gemini CLIs
- `harnessed-claude` has the claude CLI; `harnessed-omp` has the omp CLI
- Incompatible recipe composition exits non-zero with a clean error before any build
- Floating ref in a recipe Dockerfile exits non-zero with the offending line identified
- Derived `Dockerfile.harnessed-<stack>` contains `ARG HARNESS=<agent>` and concatenated bodies
- Container `pwd` matches host project path; Claude slug is `-home-mcrowe-…` not `-container-mcrowe-…`
- Image-baked skills visible inside the container; host `~/.claude/skills/` unchanged after session

---

### Task 3: gstack Recipe

**Subagent:** recipe author
**Depends on:** Task 2 (the claude agent image must exist as a FROM target)
**Scope:** Create the gstack recipe as the proof-of-concept for the Dockerfile-recipe model.

```
recipes/gstack/
  recipe.yaml
  Dockerfile
```

**`recipes/gstack/recipe.yaml`:**
```yaml
name: gstack
description: >
  Garry Tan's Claude Code framework — 23 specialist skills (/review, /qa, /ship,
  /office-hours, ...) plus the browse browser-automation tool. No MCP servers.

harnesses: [claude]            # installer's --host values; assembler refuses other stacks

# Smoke check (a stable subset, not the full 23) — confirms the install landed.
expect:
  skills: [office-hours, plan-ceo-review, review, qa, ship]
  tools: [browse]
```

**`recipes/gstack/Dockerfile`:**
```dockerfile
FROM harnessed-claude:latest
ARG HARNESS=claude
ARG GSTACK_REF=v1.4.0          # pin to a real tag/SHA — never a floating branch
RUN git clone --branch ${GSTACK_REF} --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack \
    && cd ~/.claude/skills/gstack && ./setup --host ${HARNESS} --quiet
```

That's it. The recipe runs gstack's own setup script — pinned and harness-parameterized. No
reinterpretation. (Confirm the actual latest gstack tag at authoring time; `v1.4.0` is a
placeholder.)

**Also create a stack that uses gstack:**
```yaml
# stacks/gstack-time/stack.yaml
name: gstack-time
harness: claude
recipes: [gstack, time]
```

This stack composes gstack (skills + browse) with the time recipe (MCP server), proving that
recipe Dockerfile bodies concatenate and MCP declarations merge.

**Acceptance:**
- `harnessed build gstack-time` emits `Dockerfile.harnessed-gstack-time` (FROM harnessed-claude +
  gstack body + time body) and builds it
- The derived image has gstack skills baked at `~/.claude/skills/gstack*` and the browse binary on PATH
- `hatago.config.json` declares the time MCP server (from recipe.yaml, not the Dockerfile)

---

### Task 4: Recipe Test Framework

**Subagent:** test builder
**Depends on:** Task 0
**Scope:** Extend the capability test with two probes — a structured MCP probe and an un-primed
ask-the-agent probe with a negative control (see §6).

#### 4a: MCP probe — structured (`tools/harnessed/capability.py`)

Assert the manifest's MCP servers are connected via hatago's `/servers` resource (or
`claude mcp list`). Deterministic, no model call. Sourced from `recipe.yaml: mcp:`.

#### 4b: Skills/tools probe — un-primed ask-the-agent with a negative control

```python
def probe_agent_capabilities(runtime, container, harness, expected):
    """Ask the agent which capabilities it actually loaded — with a decoy as a negative control.

    Returns (passed: bool, invalid: bool, diagnostic: str).
    invalid=True  → the agent claimed the decoy is present (priming/sycophancy) — result is void.
    passed=True   → decoy correctly 'missing' AND every expect: entry 'have'.
    """
    cli = HARNESS_CLI[harness]
    real = expected.skills + expected.tools
    decoy = make_decoy(real)               # a name guaranteed NOT installed
    names = shuffle(real + [decoy])        # mix in, don't label which is which
    prompt = (
        "You have a set of skills and tools available. For EACH name below, answer "
        '"have" or "missing" — do not assume; check what is actually loaded.\n\n'
        + ", ".join(names) +
        '\n\nRespond as JSON: {"have": [...], "missing": [...]}.'
    )
    resp = parse_json(runtime.exec(container, [cli, "-p", prompt]))
    invalid = decoy in resp["have"]        # negative control failed → priming detected
    passed = (not invalid) and all(c in resp["have"] for c in real)
    return passed, invalid, format_diag(resp, real, decoy)
```

#### 4c: Source expectations from `recipe.yaml`

Skills/tools from `expect:` (the smoke-check subset), MCP servers from `mcp:`. `expect:` is a
liveness check that the install landed — not a completeness list.

#### 4d: Update the markdown report

- MCP: ✓/✗ connected (structured probe)
- Skills/tools: ✓/✗ per `expect:` entry (agent's have/missing)
- **INVALID** banner if the negative control failed (decoy reported present) — distinct from a
  plain ✗, because it means the *test* can't be trusted, not that a capability is missing

#### 4e: Update `harnessed test <stack>` flow

1. Ensure the derived image is built (`harnessed build <stack>` if missing)
2. Launch headless (the runtime group: harness + hatago)
3. Run the structured MCP probe
4. Run the un-primed ask-the-agent probe (with decoy)
5. Tear down
6. Emit report; exit non-zero on failure **or** on an invalid (priming) result

**Acceptance:**
- `harnessed test gstack-time` runs both probes and reports ✓/✗ per capability
- The negative control catches a primed/sycophantic YES (decoy-present → INVALID, non-zero exit)
- A missing skill produces a clear diagnostic (the agent's `missing` entry), not a filesystem error
- The MCP probe confirms `time` connected without a model call
- The test works with `--fresh` (clean launch) and without (reused state)

---

### Task 5: Coordinator (Build + Test + Rework)

**Role:** the coordinator (main agent) waits for Tasks 1–4 to complete, then:

1. **Build:** `harnessed build` (base + agents + hatago) → `harnessed build gstack-time` (derived;
   includes the §8 supply-chain scan of the derived image — fails on high-severity)
2. **Test:** `harnessed test gstack-time`
3. **Evaluate:** did the test pass?
   - **Pass** → milestone complete. Write a summary, update STATE.md.
   - **Fail** → read the diagnostic, identify the failing task, rework it (up to 2 iterations):
     - **Rework round 1:** fix the identified issue, rebuild, retest
     - **Rework round 2:** if still failing, escalate — broader fix, rebuild, retest
     - **Still failing after 2 reworks:** stop, document the blocker, hand off

**Rework loop:**
```
for attempt in 1..=2:
    build → test → pass? done : diagnose → rework the failing task
still failing? → document blocker, stop
```

---

## Acceptance Criteria (Milestone-Level)

The milestone is complete when ALL of the following are true:

1. **Fat base:** `harnessed-base` has bun, rust, go, node@24, python, pnpm on PATH. No harness CLIs.
2. **Agent images:** `harnessed-claude` and `harnessed-omp` build FROM base with their CLI installed.
3. **Recipe model:** a recipe is a Dockerfile + recipe.yaml. The assembler concatenates Dockerfile
   bodies into a derived `harnessed-<stack>` image.
4. **gstack recipe:** `recipes/gstack/` has a Dockerfile that runs gstack's setup (pinned to a
   tag/SHA, `--host ${HARNESS}`) and a recipe.yaml with `harnesses:` and `expect:` declarations.
5. **Profile mount:** the launcher mounts individual config files (`.mcp.json`, `settings.json`),
   not the whole `~/.claude/` dir. Image-baked skills survive.
6. **Supply-chain gate:** the assembler rejects unpinned recipe sources; `harnessed build
   gstack-time` scans the derived image (osv-scanner) and fails on high-severity findings.
7. **Capability test:** `harnessed test gstack-time` runs the structured MCP probe and the un-primed
   ask-the-agent probe (with negative control) and passes — and a primed/sycophantic YES is caught
   as INVALID.
8. **Docs:** all narrative docs describe the new architecture (fat base, Dockerfile recipes, pinned
   sources + image scan, combined capability test). No "isolated" or "transparent" terminology
   remains.

---

## Key Design Decisions (Reference)

These are the settled decisions from the design conversation. Subagents should treat them as
constraints, not open questions.

1. **Recipes are Dockerfiles, not typed-field YAML.** The recipe runs the framework's own installer.
   The assembler doesn't reinterpret the install. (Settled: "you are not reinterpreting the
   install/layout, you are installing it.")

2. **recipe.yaml is for MCP + expect, not skills.** MCP servers need typed declaration (hatago
   merges them). Skills/tools/plugins are installed by the Dockerfile and validated by
   ask-the-agent. (Settled: "maybe the fields are used for MCP only.")

3. **Agents are recipes with `type: agent`.** Same mechanism, different handling by the assembler.
   (Settled: "maybe they are simply a recipe with a type: agent?")

4. **Fat base is the feature.** All runtimes pre-installed so recipes never install runtimes.
   (Settled: "those images will have bun, node24, rust, python, go installed so child derivatives
   can build anything.")

5. **Profile mount is surgical, not dir-replace.** Individual config files mounted; image-baked
   skills survive. (Forced by the recipe-Dockerfile model — skills are in the image, not the profile.)

6. **Container-agnostic runtime group.** Stack ≠ pod. The networking abstraction handles podman,
   docker, and (future) Apple containers. (Settled: "we are container agnostic.")

7. **We version the recipe's tag, not the vendor's data.** The reproducibility unit is *which
   version* a recipe installs (pinned tag/SHA), not a committed copy of the vendor's skills. The
   earlier "repackage vendor skills into a git-controlled tree" was the actual mistake — it required
   surveilling every recipe's install destinations forever, which isn't realistic. (Settled: "we
   don't version control their data. We version control their tag/version for reproducibility.")

8. **Supply chain moves to pin + scan-the-image, not scan-the-vendored-deps.** Nothing is vendored;
   the installer runs at build. The gate is: assembler rejects unpinned sources, osv-scanner scans
   the derived image, nightly rescan. Residual (a vendor `./setup` shelling raw npm bypasses pnpm
   cooldown) is documented, not pretended away. (§8.)

9. **The recipe knows how to install; the harness is parameterized.** `--host ${HARNESS}`, not a
   hardcoded harness. The recipe declares the harnesses its installer supports (`harnesses:`); the
   assembler refuses an unsupported composition with a clean error. The Dockerfile is the escape
   hatch for any per-harness tweak. (Settled: "the recipe needs to understand how to install. The
   harness can be parameterized. The assembler needs to understand cross-harness capabilities.")

10. **`expect:` is a smoke check, not a completeness oracle.** It confirms the install *landed* — a
    stable subset the agent must report as present. A package growing from 3 skills to 5 and the
    test still confirming 3 is success, not rot. (Settled: "that's not rot. That's confirming the
    install completed successfully.")

11. **Capability test combines two oracles, and the agent probe is un-primed.** Structured probe for
    MCP (present/connected); ask-the-agent for skills/tools (loaded/perceived). The agent prompt
    carries a negative control (a decoy not installed) so a primed/sycophantic YES is caught as
    INVALID rather than passing. (Refines the bare "respond YES" probe, which could pass for the
    wrong reason.)
`````

## File: docs/guides/secrets.md
`````markdown
# Secrets setup (opt-in varlock + 1Password)

`harnessed` works fully without any secrets backend. This guide is for operators who
*want* 1Password-backed secrets resolved into their stacks at launch — opt-in, env-only,
never baked into an image or committed file. For the *why* (threat model, design rationale),
see [docs/harnessed-design.md §16](../harnessed-design.md#16-proposed-secrets--varlock--1password-optional).

## What this does

With a `.env.schema` present, secrets resolve from 1Password via [varlock](https://varlock.dev)
and reach the pod members as **environment variables only** — never written to a profile, a
container image layer, or a repo file. Absent the schema, `harnessed` is bit-for-bit today's
behavior: varlock is never invoked, no `op` call, no env mutation. The opt-in switch is a
single filesystem test.

## Quickstart

```bash
# 1. Copy the shipped template into your XDG harnessed config dir.
mkdir -p ~/.config/harnessed
cp .env.schema.example ~/.config/harnessed/.env.schema

# 2. Edit the op:// refs to match your 1Password vault items.
#    Example (Private vault, items named "Snyk" and "SocketDev", field "credential"):
#       SNYK_TOKEN=op(op://Private/Snyk/credential)
#       SOCKET_SECURITY_API_KEY=op(op://Private/SocketDev/credential)
$EDITOR ~/.config/harnessed/.env.schema

# 3. Launch any stack. Resolved secrets reach the pod as env only.
harnessed tracer-time
```

The `.env.schema.example` shipped at the repo root is the canonical template — copy it,
don't author from scratch. The `@plugin(@varlock/1password-plugin@1.2.0)` +
`@initOp(allowAppAuth=true)` decorators are required (they wire the `op(op://…)` resolver
and tell varlock to use the mounted agent socket for app-auth).

## How resolution works

`harnessed` runs `varlock` **on the host** to resolve `op://` refs. This is required, not a
preference: 1Password's desktop app authorizes the `op` CLI by **calling application** (your
terminal), so app-auth (`@initOp(allowAppAuth=true)`) works on the host but **cannot** work
from inside a container — there the desktop app has no host app to bind the grant to, and `op`
fails with *"cannot connect to 1Password app"* no matter which socket is mounted. (The
`~/.1password/agent.sock` mounted into every stack is the **SSH agent**, for git signing — not
the `op` app-auth transport.)

1. The launcher detects `~/.config/harnessed/.env.schema` (one `[ -f ]` test — inert when
   absent; with no schema, `varlock` is never invoked).
2. It runs `varlock load --format env` **on the host**, in the schema's directory. The first
   run prompts the 1Password desktop app to **Authorize** your terminal for CLI access —
   approve it once and the grant persists.
3. The resolved dotenv is captured into a **mode-0600 temp `--env-file`** under `$TMPDIR`.
4. That `--env-file` is spread into the launched container(s) — **both pod members**,
   the **sidecar** (`svc up`), and the **scan step**
   (`harnessed build`) — so resolved secrets reach the container as **env only**, never a
   profile, image layer, or repo file (T-05-05).
5. The temp file is **unlinked** after launch (T-05-06).

This needs `varlock` on the host (`npm i -g varlock`); `op` (already on most 1Password hosts) is
driven by varlock via app-auth. The "podman-only host" invariant still holds for the
**no-secrets** path — varlock is never touched without a schema. Hosts without host `varlock`
fall back to the headless path below.

## Headless / CI fallback (`OP_SERVICE_ACCOUNT_TOKEN`)

For environments without the 1Password desktop app **or** without host `varlock` (CI, the
nightly re-scan timer, a headless server), set `OP_SERVICE_ACCOUNT_TOKEN` in the launcher env.
With a service-account token, resolution runs in a throwaway `harnessed-tools` container (HTTPS
bearer auth — no desktop app, no app-auth, no socket). `harnessed` forwards the token only when
it is already set — it never prompts and never echoes.

> **Caution (per CLAUDE.md "What NOT to Use"):** a visible service-account token leaks into
> any process sharing the env. **Scope it narrowly to the invocation** — prefix it on the
> command line (`OP_SERVICE_ACCOUNT_TOKEN=… harnessed tracer-time`) or inject via your CI
> secret store. Do **not** `export` it in your shell profile or `~/.bashrc`, and do not
> leave it in a long-lived shell session.

## Per-service secrets

Sidecar services (hindsight, openbrain, …) can declare their own schemas at
`~/.config/<service>/.env.schema` — e.g. `~/.config/hindsight/.env.schema` for the hindsight
sidecar. The schema syntax is identical; see the `.env.schema.example` header comment.

## Scanner tokens

`harnessed build` runs the supply-chain scanners (snyk, Socket.dev) when their tokens are
present and warns-and-skips otherwise. Two ways to provide a token:

1. **Via `.env.schema` (this guide)** — the `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` refs
   resolve from 1Password and reach the build-time scan step via the same host-resolved
   `--env-file` path (`build_stack` calls `resolve_secret_env` before the scan). Recommended for
   operators already using varlock. Get a **Snyk** token at
   <https://app.snyk.io/account/personal-access-tokens> (Account settings → Personal Access
   Tokens → Generate); a **Socket** key from <https://socket.dev> → Settings → API tokens.
2. **Via the launcher env directly** — for a one-off without varlock/1Password, export the token
   before building. The build scan is env-gated on `SNYK_TOKEN`, and `build_stack` forwards it:

   ```bash
   SNYK_TOKEN='<token>' harnessed build tracer-time     # scoped to the one invocation
   ```
3. **Via `harnessed auth snyk|socket`** — persists the token to host config
   (`~/.config/configstore/snyk.json` for snyk), for **interactive `snyk`/`op` use inside the
   tools container**. This does **not** feed `harnessed build`'s scan step — that gate is the
   `SNYK_TOKEN` env var, not configstore — so use path 1 or 2 for the build scan:

   ```bash
   harnessed auth snyk      # opens a browser flow at a TTY; writes configstore/snyk.json
   harnessed auth socket    # prompts for the API token; stores in socket's config
   ```

## Verification

After launching with a schema present, confirm secrets reached the pod **and** did not leak:

```bash
# 1. The value reached the pod env (replace <instance> + <KEY> with your own):
podman exec <instance> env | grep SNYK_TOKEN
# expected: SNYK_TOKEN=<the resolved value>

# 2. The value is NOT in the committed profile:
grep -r SNYK_TOKEN profiles/    # expected: no matches

# 3. The value is NOT baked into the image:
podman history harnessed-hatago:latest | grep -i snyk    # expected: no matches

# 4. The temp env-file is gone after launch:
ls /tmp/harnessed-env.* 2>/dev/null    # expected: no matches (unlinked post-launch)
```

If `podman exec … env | grep <KEY>` returns nothing but you expected it to, check that:
- `~/.config/harnessed/.env.schema` exists and has a non-`@optional` entry for `<KEY>`.
- The 1Password desktop app is running and unlocked (the agent socket must be live for
  app-auth), OR `OP_SERVICE_ACCOUNT_TOKEN` is set in the launcher env.
- The `op(op://Vault/Item/field)` ref points at a real vault item.

## See also

- [docs/harnessed-design.md §16](../harnessed-design.md#16-proposed-secrets--varlock--1password-optional) — the design rationale (the *why*).
- [docs/harnessed-design.md §7](../harnessed-design.md) — supply-chain scanners + the warn-and-skip contract.
- [.env.schema.example](../../.env.schema.example) — the canonical schema template.
`````

## File: docs/guides/service-authoring.md
`````markdown
# Authoring shared services

A **shared service** is a heavy or stateful sidecar (hindsight = postgres+MCP, openbrain, a custom
MCP tool) that runs as its **own** image/container/volume on the shared network, with a lifecycle
**independent of any instance**. Multiple instances attach to one running service concurrently;
`claude+hindsight` and `omp+hindsight` read and write **one** memory (design §3, §9).

For the *why* (why services are service-scoped, why they outlive instances, why they're separate
images), read [docs/harnessed-design.md §3 & §9](../harnessed-design.md). This guide shows the *how*
with a worked example from [`services/ping/`](../../services/ping/).

## What a service is

A service lives at `services/<name>/` and ships **three** things:

| File | Role |
| --- | --- |
| `services/<name>/service.yaml` | the manifest: `name`, `image`, `port`, `volume`, `healthcheck` |
| `services/<name>/Dockerfile` | the service's **own** image lineage (independent of the harness images) |
| the server itself (e.g. `server.py`) | the actual MCP server (Streamable HTTP) |

You manage services by name with `harnessed svc up|down|list` (see [lib/harnessed-services.sh](../../lib/harnessed-services.sh)), and a stack references one by listing it under `services:`.

## The `service.yaml` manifest

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`ServiceDef`).
Flat scalars:

```yaml
name: <service>                       # required
image: <name>:<tag>                   # required — the service's own image
volume: <volume-name>                 # optional — service-scoped named volume (survives svc down)
port: <port>                          # required — the port the server listens on
healthcheck: "<cmd>"                  # optional — readiness probe for `svc up` to poll
```

A recipe references a service via `mcp.servers[].service: <name>`; the assembler resolves that to a
hatago URL-proxy entry pointing at `http://<name>:<port>/mcp` (see *Attaching from a recipe* below).

## Worked example: the `ping` service

`ping` is the smallest shared-service sidecar — one `ping` MCP tool over Streamable HTTP, no
external state. All three files:

### `services/ping/service.yaml`

```yaml
name: ping
image: harnessed-ping:latest
volume: ping-data
port: 8080
healthcheck: "curl -sf http://localhost:8080/health || exit 1"
```

- `image: harnessed-ping:latest` — `svc up` builds this from the service's own `Dockerfile` on first
  use (and the build-time BLD-02 image scan gates it).
- `volume: ping-data` — service-scoped; it **survives** `svc down` by default (that's the value — one
  memory across instances). `--purge` is the explicit destroy.
- `healthcheck` — what `svc up` polls to confirm readiness before returning.

### `services/ping/Dockerfile`

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "mcp[cli]"
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1
CMD ["python", "/app/server.py"]
```

The service has its **own** image lineage (`FROM python:3.12-slim`) — it is not built `FROM` any
harness image. The `HEALTHCHECK` mirrors the manifest's `healthcheck` so `podman` and `svc up` agree
on readiness.

### `services/ping/server.py`

A FastMCP server over **Streamable HTTP**, with a `/health` route alongside the MCP endpoint:

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.routing import Route

mcp = FastMCP("ping")
# FastMCP's DNS-rebinding protection rejects the podman host-gateway Host header by default,
# so allow it alongside the localhost defaults (the service is proxied via host.containers.internal).
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "host.containers.internal:*"],
)

@mcp.tool()
def ping() -> str:
    """Return pong."""
    return "pong"

async def _health(_request):
    return PlainTextResponse("ok")

# FastMCP.streamable_http_app() serves the MCP endpoint at /mcp; add /health on the same port.
app = mcp.streamable_http_app()
app.router.routes.insert(0, Route("/health", _health, methods=["GET"]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

- **Streamable HTTP** — one endpoint (`/mcp`), `POST` + optional `GET`/SSE stream. **SSE is
  deprecated** in the current MCP spec (2025-06-18) and in Claude Code; do not author new SSE
  servers (see the "What NOT to Use" table in [`CLAUDE.md`](../../CLAUDE.md)).
- A separate `/health` route lets the container `HEALTHCHECK` (and `svc up`) probe readiness without
  speaking MCP.
- The `allowed_hosts` entry for `host.containers.internal` matters on the default rootless
  networking model (see below).

## Lifecycle

`harnessed svc up|down|list` manages shared services by name — independent of any instance
([lib/harnessed-services.sh](../../lib/harnessed-services.sh)):

```bash
harnessed svc up ping        # build image (first use) + create volume + run -d + wait for healthcheck
harnessed svc list           # enumerate running harnessed-managed services
harnessed svc down ping      # stop + remove the container (volume KEPT)
harnessed svc down ping --purge   # stop + remove the container AND the volume
```

The service is labelled `harnessed-service=<name>` and runs on the shared network; it is **not** a
pod member. A stack that declares the service **auto-starts** it on launch:

```yaml
# stacks/ping-time/stack.yaml
name: ping-time
config: isolated
harness: claude
recipes: [time, ping]
services: [ping]            # ← the isolated launcher runs ensure_service_up(ping) on launch
```

The service outlives the instance — stop the stack and the sidecar keeps running, so the next
instance (or another stack) attaches to the same state.

## Attaching from a recipe

A recipe references a service via `mcp.servers[].service`. The assembler resolves the name to a
hatago URL-proxy entry, so hatago proxies the network-native server:

```yaml
# recipes/ping/recipe.yaml
mcp:
  servers:
    - name: ping
      service: ping        # ← resolved to http://ping:8080/mcp
      transport: http
```

**Networking note:** by default stacks use rootless (pasta) networking, so pod members reach
a shared service via the host gateway `host.containers.internal:<port>`. That is why `server.py`
adds `host.containers.internal` to FastMCP's allowed hosts. On hosts that support rootless bridges,
set `HARNESSED_NET=<name>` and members resolve the service by DNS name instead (`http://<name>:<port>`).

## See also

- [docs/harnessed-design.md §3 & §9](../harnessed-design.md) — the *why* (runtime pod, service-scoped state & lifecycle).
- [Recipe-authoring guide](recipe-authoring.md) — the service-ref MCP shape (`service:` / `transport: http`).
- [Stacks guide](stacks.md) — declaring `services:` in a stack manifest.
- [`services/ping/`](../../services/ping/) — the worked example (manifest + image + server).
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `ServiceDef` model.
`````

## File: docs/guides/troubleshooting.md
`````markdown
# Troubleshooting & ops

Operational guidance for `harnessed`: podman setup, first-run builds, sessions, secrets, and the
nightly re-scan timer. For the *why* behind any of this, see
[docs/harnessed-design.md §15 & §17](../harnessed-design.md); for the secrets workflow specifically,
see [secrets.md](secrets.md).

## podman / rootless setup

`harnessed` is **host-native**: every `podman`/`docker` command runs on the host directly. There is
**no daemon-in-container, no Docker-out-of-Docker, and no rootless API socket mounted**
([design §15](../harnessed-design.md)). The `harnessed-tools` assembler image only **emits files**
(Dockerfile + profile + launcher); the host then runs ordinary `podman build` / `podman run`.

- You do **not** need to `systemctl --user enable --now podman.socket` for harnessed's core flow. The
  socket is only relevant if a container must *drive* the host engine — and harnessed never does.
- Run rootless (`--userns=keep-id` is applied automatically) so file ownership works without host root.
- `podman` ≥ 5.6 is recommended (current 5.8.x). Docker works as a fallback (the egress firewall is
  tested on Podman).

## Container runtimes (podman / Docker / Apple `container`)

`harnessed` is provider-agnostic. The harness stack — the harness container + the hatago hub sharing
one `localhost:3535` — is expressed per-runtime by [`lib/harnessed-runtime.sh`](../../lib/harnessed-runtime.sh):

- **podman** — a pod (`pod create` + `run --pod`); rootless uid mapping via `--userns=keep-id`.
- **Docker** — a shared network namespace: hatago runs first, the harness joins it with
  `--network container:<hatago>` (same localhost); rootless Docker remaps uids daemon-side (no
  `--userns` flag). The two members are flat containers (`<instance>` + `<instance>-hatago`).
- **Apple `container`** — not yet supported (one lightweight VM + IP per container, no shared
  netns / `--network container:`); tracked as a follow-up (needs a named-network + a non-localhost
  MCP endpoint).

`detect_runtime` prefers podman, else docker. Force one with `CONTAINER_RUNTIME=docker harnessed …`.

### Full UAT on a fresh host (e.g. a Docker NAS)

After `git pull` on the target host:

```bash
cd /path/to/code-container
harnessed build                 # build the shared base + claude + hatago images on this runtime
./tools/uat/run-uat.sh 6        # the HARNESS MATRIX: build + capability-test every harness
# …or one harness end to end:
harnessed build codex-time && harnessed test codex-time
# …or only the fast checks (manifests + harness validation, no containers):
./tools/uat/run-uat.sh 6 --quick
```

The matrix builds each `<harness>-time` proof stack, launches it `--fresh` headless, asserts the
`time` MCP server is reachable through hatago **and** the `time-helper` skill is present, then tears
it down. A green matrix proves that runtime drives **every** harness (claude, omp, opencode, gemini,
antigravity, codex) correctly. Add a harness → add a line to `UAT_MATRIX` in
[`tools/uat/phase-06.sh`](../../tools/uat/phase-06.sh).

### Docker caveats

- **Egress firewall** needs rootless `NET_ADMIN` + iptables in the shared netns. If it can't apply,
  the launcher warns and continues; pass `--no-firewall` to skip it explicitly.
- **File ownership** — rootless Docker remaps uids daemon-side (there is no `--userns=keep-id`). If
  mounted project/profile files end up unwritable inside the container, configure the daemon's
  `userns-remap`, or run the build/UAT as the same uid that owns the repo.
- **Shared service sidecars** (`services:` / `harnessed svc`) are **not wired for Docker yet** — the
  hatago proxy resolves them via `host.containers.internal`, a podman-only name. The harness-matrix
  proof stacks declare no services, so the UAT itself is unaffected.

## First-run build issues

Images build on the host via `podman build` the first time they're needed. If a build fails:

- **podman version / disk / context** — confirm `podman --version` ≥ 5.6, that you have disk space,
  and that you're running from the repo root (the build context).
- **The tools image is the longest build.** `harnessed-tools` pulls Node/pnpm + the supply-chain
  scanners + varlock + `op` (Phase 5). First-run latency here is expected; later runs are cache hits.
- **`harnessed build` aborts on HIGH** — see [Supply-chain scan failures](#supply-chain-scan-failures).
- **A `harnessed` upgrade that touched `tools/harnessed/*.py` is not picked up by `rescan`.**
  `ensure_tools_image` is a build-if-missing guard, **not** a staleness guard. After upgrading, rebuild
  the tools image so the assembler/scanner entrypoints are current:

  ```bash
  podman build -t harnessed-tools:latest -f tools/Dockerfile tools/
  ```

- **Running an unbuilt stack** errors with `Stack '<stack>' has no assembled profile (run:
  harnessed build <stack>)`. Build it first:

  ```bash
  harnessed build <stack> && harnessed <stack>
  ```

## `~/.claude.json` onboarding prompt

A stack instance authenticates by mounting `~/.claude/.credentials.json` read-only plus a
**generated, token-free `.claude.json` stub** that boots headlessly with no onboarding/login prompt
(AUTH-02).

- **If `claude` prompts for onboarding in a stack instance**, the stub is missing a required
  field. The proven field set (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`,
  `oauthAccount`, `userID`) is sufficient for a headless no-prompt boot; a re-build regenerates it.
- When running with host config mounted live, the host `.claude.json` is never rw-mounted — it uses a **copy-on-start**
  per-instance copy (MNT-03). If the host file is the source of trouble, the per-instance copy is
  unaffected.

## `--fresh` clean-room runs

`harnessed <stack> --fresh` tears down any existing pod/instance for the project, wipes the
per-instance state dir, and reseeds it from the committed profile — a true clean-room run with no
state bleed (design §9, [lib/harnessed-isolated.sh](../../lib/harnessed-isolated.sh)):

```bash
harnessed tracer-time --fresh      # wipe + reseed, then attach
```

A **normal** run (no `--fresh`) **reuses** the accumulated per-instance `.claude` (projects/,
history.jsonl, …) — that is the point of a memory system. `--fresh` is meaningfully distinct from a
normal run: it wipes; a normal run accumulates.

## Host-persisted sessions

By default a stack instance persists harness session state (`projects/` + `history.jsonl`) to a
harnessed-owned dir on the host under a **legible, flattened project path** (STA-02):

```
$XDG_STATE_HOME/harnessed/<flattened-project-path>/<stack>/.claude
# default XDG: ~/.local/state/harnessed/<flattened-project-path>/<stack>/.claude
```

`<flattened-project-path>` is the home-relative project path with `/` → `-` (e.g.
`projects-personal-code-container`), so the slug is readable — not the opaque hash instance name.
Sessions survive instance recreation and stay inspectable. `state.session_state: volume` in the stack
manifest opts into a throwaway per-instance volume instead.

## Nightly re-scan timer (SEC-04)

A systemd **user** timer re-runs osv-scanner **online** against installed harnessed images so a CVE
disclosed *after* build still surfaces. The static unit files live at
[`systemd/harnessed-rescan.{timer,service}`](../../systemd/).

> **Prerequisite (Pitfall 5): enable lingering.** Without it the user systemd instance is torn down
> on logout and the timer **never fires overnight**. This is the single most common "my nightly scan
> silently stopped" cause.

```bash
# 1. Enable lingering (HARD prerequisite) and confirm it:
loginctl enable-linger "$USER"
loginctl show-user "$USER" --property=Linger      # expect: Linger=yes

# 2. Install the user units + enable the timer:
mkdir -p ~/.config/systemd/user
cp systemd/harnessed-rescan.timer systemd/harnessed-rescan.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now harnessed-rescan.timer
```

The timer (`OnCalendar=daily`, `Persistent=true`) drives `harnessed-rescan.service`
(`Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan`) — so the manual trigger and the nightly
trigger exercise the **identical** code path. Ensure the launcher is on PATH at
`~/.local/bin/harnessed` (`harnessed install` shim, or a symlink).

**Diagnostics:**

```bash
systemctl --user list-timers harnessed-rescan.timer               # is it scheduled?
systemctl --user start harnessed-rescan.service                   # run it now (one-shot)
journalctl --user -u harnessed-rescan.service --no-pager          # what did it find?
```

**Network:** the nightly re-scan uses the **online** osv.dev database — it requires network egress
to `osv.dev` at scan time. (The build-time gate uses the **offline** DB by design, for determinism;
the nightly cannot.)

**Warning sign — "0 findings forever" (Pitfall 6):** if the nightly *always* reports clean even
after a widely-disclosed CVE, confirm the scan is using **`scan-image-online`** (online), not
`scan-image` (offline). The online variant deliberately drops the `--offline` flags so osv-scanner
sees newly-disclosed advisories — using the offline DB here would defeat the entire purpose (it only
knows about CVEs at build time). You can see the contrast directly:

- offline build-time scan: `Supply-chain image scan clean (HIGH < CVSS 7.0)`
- online nightly scan: `Supply-chain image scan clean (HIGH < CVSS 7.0; online)` — note the `(online)` marker.

## Secrets / varlock

The opt-in secrets workflow is documented in **[secrets.md](secrets.md)**. Common issues:

- **`op://` refs unresolved / "cannot connect to 1Password app"** — resolution runs `varlock`
  **on the host** (the desktop app authorizes your terminal; an in-container `op` cannot be
  authorized — that error is expected from inside a container). Check, in order: (1) host
  `varlock` is installed — `command -v varlock` (`npm i -g varlock`); (2) the 1Password desktop
  app is running, unlocked, with **Settings → Developer → "Integrate with 1Password CLI"**
  enabled; (3) you **Authorized** your terminal at the 1Password prompt on first use. For
  headless/CI (no desktop app), set a narrowly-scoped `OP_SERVICE_ACCOUNT_TOKEN` instead — see
  [secrets.md](secrets.md) "Headless / CI fallback".
- **Resolved value missing from the pod env** — confirm `~/.config/harnessed/.env.schema` exists and
  has a non-`@optional` entry for the key; the schema's `op(op://Vault/Item/field)` ref must point at
  a real vault item.
- **A resolved value reached the pod with surrounding quotes** — this was a fixed bug (varlock's
  `--format env` quoting); update to the current launcher.

## Supply-chain scan failures

`harnessed build` runs osv-scanner + pip-audit (always) and snyk/Socket.dev (token-gated), and
**fails on HIGH**:

- **Read the finding.** The abort names the finding id (e.g. a GHSA). The intentional regression
  fixture `tools/test-fixtures/vuln-stack` demonstrates the abort path.
- **snyk / Socket.dev warn-and-skip without a token** (SEC-02) — if you expected them to run, check
  that `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` is in the launcher env (or resolved via varlock /
  `harnessed auth snyk|socket`). Without a token you'll see `warning: snyk skipped (no SNYK_TOKEN)`
  — that is correct non-interactive behavior, not a failure.
- **Build-time scan vs nightly scan** — the build-time gate uses the **offline** osv DB
  (deterministic); the nightly timer uses the **online** DB (fresh). A CVE disclosed *after* you
  built won't fail the build but will surface in the nightly — see [Nightly re-scan timer](#nightly-re-scan-timer-sec-04).

## See also

- [docs/harnessed-design.md §15 & §17](../harnessed-design.md) — the *why* (host-native execution, docs cadence).
- [secrets.md](secrets.md) — the opt-in varlock + 1Password workflow.
- [README.md](../../README.md) — the command surface and quickstart.
`````

## File: docs/harnessed-design.md
`````markdown
# harnessed — Isolated, Composable Harness Stacks

> **Status:** Design spec (resolved via discuss/grill session). Architecture decisions
> (§2–§9) are **confirmed**. Schemas, repo layout, and CLI (§10–§13) are **proposed**
> and open for review. Items in §14 are **to verify during execution**.
>
> **Names:** the executable is **`harnessed`**; what it launches is a **stack** — a podman pod with
> the harness container + hatago + shared services. The existing `container` SKU folds in as the
> built-in `transparent` stack (§2); `container` remains a thin alias → `harnessed transparent`.

## 1. Problem

`container` (this repo's existing tool) builds an isolated container that **mirrors the
host's tool setup** — auth, config, skills, MCP, plugins all bind-mounted from `~`. That is
the right SKU for "my laptop, sandboxed."

It is the wrong SKU for *experimenting* with commands/skills/plugins/memory systems, because
it drags every host default into the container. A prior attempt to instead **merge** a curated
set into the host config (`~/.agents` + `sync-plugin-links` + universal-hooks) failed: a single
shared host namespace (`~/.claude`, `~/.agents`) cannot hold every experiment at once —
openbrain and hindsight collide, per-runtime `settingSources` drift, and vendored deps pollute
`~`.

**Insight:** do the merge **per container**, where each stack is isolated, so the collision
that killed the host merge disappears by construction.

## 2. One engine, two config modes

There is **one** executable, `harnessed`. Every stack shares the same base image, the same
host-integration mounts (§4), the same project mount, and host auth. Stacks differ on a
single axis — **where the config layer (skills/commands/hooks/MCP) comes from**:

| Mode | Config source | Mental model |
|---|---|---|
| **`transparent`** | host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`) bind-mounted live | "my laptop, sandboxed" — the current `container` SKU |
| **`isolated`** | auth seeded + the assembled stack **profile** mounted; nothing from host config | "clean room with exactly what I picked" |

`transparent` is just a built-in stack (`stacks/transparent/`) that sets `config: transparent`
and mounts host skills/hooks/commands wholesale. `isolated` stacks embed recipe-composed
skills/hooks/commands. The old `container` command becomes an alias for `harnessed transparent`
(see §14 — keep alias vs remove).

## 3. Core model: stack = harness container + hatago + shared services

A running **stack** is composed **at runtime**, in a podman **pod** on a shared network — **not**
at build time. (`FROM` is linear inheritance + multi-stage `COPY --from`; it cannot union two
sibling systems. See §6.)

> **Provider abstraction.** The shared-netns group is runtime-abstracted by
> `lib/harnessed-runtime.sh` (`rt_*` helpers): podman uses a **pod** (`pod create` + `run --pod`,
> rootless uid via `--userns=keep-id`); docker uses a **shared-netns pair** — hatago runs first,
> the harness joins with `--network container:<instance>-hatago` (rootless docker remaps uids
> daemon-side, no `--userns`). Apple `container` has no shared-netns equivalent (one VM+IP per
> container) and is a **tracked follow-up** (needs a named network + non-localhost MCP endpoint),
> not yet supported.

            podman pod: harnessed-<stack>-<proj>
        ┌──────────────────────────────────────────────┐
        │  [ harnessed-<harness> ]  ──→  [ hatago ]      │
        │    mounts cwd + profile      MCP hub · HTTP    │
        └───────────────────────────────────────┬───────┘
                                                 │ MCP over host.containers.internal (HARNESSED_NET: opt-in)
                          ┌──────────────────────┴──────────────────────┐
                          ▼                                              ▼
                   [ hindsight ]                               [ openbrain ]
                   shared · service-scoped                     shared · service-scoped
                   own image · volume · lifecycle              own image · volume · lifecycle
```

- **harness container** — runs the harness (`claude`/`omp`/`opencode`/`gemini`/`antigravity`/`codex`), auth seeded, current folder mounted,
  stack profile mounted into the harness config dir.
- **hatago** — MCP hub. Aggregates all of the stack's MCP servers behind **one** HTTP endpoint;
  the harness container's `.mcp.json` points at `localhost:<port>`. Light `npx`/`uvx` stdio servers run as
  hatago's children (baked into the hatago image); heavy services are proxied over the network.
- **shared services** — heavy/stateful systems (hindsight = postgres+MCP, openbrain). Each is
  its **own** image/container/volume, **service-scoped and harness-independent**, with a
  lifecycle independent of any instance. Multiple harnessed instances attach to the **same** running service concurrently.

**Transparent mode is the degenerate case:** harness container only — no hatago, no services. Host
config is mounted live, so MCP comes from the host's own `.mcp.json`/`.claude.json`. The pod,
hatago, and shared-service machinery above apply only to `isolated` stacks.

## 4. Mounts: shared host-integration layer + per-mode config source

Two distinct mount layers. The first is **identical for every stack**; the second is the only
thing `transparent` and `isolated` disagree on.

### 4a. Host-integration layer (shared by ALL stacks)

Ported verbatim from `container.sh`'s `start_new_container` — these are credentials, signing,
and agents, *not* the config-experiment surface, so they belong in every instance:

- 1Password SSH agent socket (`SSH_AUTH_SOCK`)
- GPG agent SSH socket + `~/.gnupg` (ro) — YubiKey SSH / commit signing
- YubiKey USB device passthrough (`--device`)
- `~/.ssh` (ro), git config (ro), `/etc/machine-id` (ro)
- `~/.zai.json` (ro) and per-tool `~/.config/<tool>` dirs (editor configs, etc.)
- egress firewall (`--cap-add NET_ADMIN`, `egress-firewall.sh`)
- the current project folder, mounted at the work dir

### 4b. Config source — surgical per-file mounts

**`transparent`:** bind-mount host config live (like today's `container`, with one safety fix —
the `.claude.json` caveat below):

- `~/.claude` mounted rw for live skills/commands/settings (per-path dirs + append-mostly → low race risk)
- **`~/.claude.json` is NOT rw-bind-mounted.** It's a single whole-file blob Claude rewrites
  constantly (see host `~/.claude/backups/*.backup.*`). A shared rw mount races with host claude
  (lost writes / corruption) and merges container state back into the host file — the differing
  project path only spares the path-keyed `projects` subtree, not the whole-file rewrite or the
  top-level fields. Seed a **writable per-instance copy** at start (copy-on-start), or relocate via
  `CLAUDE_CONFIG_DIR` (§14): container reads host state, writes only its own copy.
- `~/.codex`, `~/.config/opencode`, `~/.gemini` (rw)
- MCP comes from host config as-is; no hatago, no profile, no auth stub.

**`isolated`:** auth seeded, config from the profile via **surgical per-file mounts** — the core
isolation trick:

- The real credential is **`~/.claude/.credentials.json`** (OAuth token). Mount it read-only.
  Auth credential mounts are handled by the §4a host-integration layer — never by the per-harness
  manifest (manifests list only config/skill files, never auth credential paths).
- **`~/.claude.json`** is *not* auth — it's `oauthAccount` metadata + ~450 KB of config/state
  (`projects`, `mcpServers`, caches). **Do not mount it.** **Generate** a minimal stub with only
  the fields needed to skip onboarding (see §14 — exact set to verify).
- **Surgical per-file mounts via `lib/manifests/<harness>.yaml`.** Profile assets are NOT mounted
  as a whole `profiles/<stack>/` directory. Each harness has a YAML manifest
  (`lib/manifests/claude.yaml`, `lib/manifests/omp.yaml`, etc.) with two top-level keys:
  - `profile_files`: individual filenames (e.g. `.mcp.json`, `settings.json`) mounted read-only
    from `profiles/<stack>/` into the container's harness config dir. The bash helper
    `lib/harnessed-manifest-mounts.sh` reads the manifest at launch time and applies harness-aware
    container target paths: claude/omp/opencode mount profile files to `~/.claude/<f>`;
    gemini/antigravity/codex skip profile file mounting (their MCP config is image-baked).
  - `history_dirs`: `$HOME`-relative paths bind-mounted read-write for history surfacing (e.g.
    `.claude/projects`, `.claude/todos`, `.claude/tasks` for claude).

  Why surgical? Mounting a whole directory lets host defaults (other skills, stale config, personal
  CLAUDE.md) bleed into the container — exactly the "no host defaults" invariant §4 protects.
  Individual per-file mounts make the container's config surface exactly what the profile declares,
  no more.
- Session state — `~/.claude/projects/` + `history.jsonl` — persists to the **host** by default,
  so sessions survive instance recreation and stay inspectable. The project is mounted at a stable
  in-container path (e.g. `/home/harnessed/<relpath>`) so Claude's slug is legible
  (`-home-harnessed-<relpath>`), under a harnessed-owned dir so it never pollutes the host's own
  `~/.claude`. `session_state: volume` (§12) opts into a throwaway per-instance volume instead.

Net: `isolated` is authenticated but carries **no host defaults**; `transparent` is the full
host mirror. Same engine, same operational mounts, one switch.

## 5. Composition unit: recipes (hand-authored, not dynamic)

A **recipe** is a hand-authored integration definition for **one** project (hindsight, gsd,
caveman, headroom, …). A **stack** is a harness + a chosen set of recipes. Nothing is resolved
at runtime; recipes are assembled ahead of time into committed artifacts.

A recipe can contribute to **two layers**:
- **MCP layer** → server entries merged into the stack's hatago config (and/or a shared service ref).
- **File-extension layer** → `skills`/`commands`/`agents`/`hooks`/`rules` in Claude-canonical form.

## 6. Image tier — `FROM` is for base lineage only

`FROM` gives **linear** inheritance; multiple `FROM`s = multi-stage build whose **last** stage is
the image, with `COPY --from=…` pulling artifacts from earlier stages. There is **no** "union two
images" operator. So systems are **not** combined via `FROM`; they are combined at runtime (§3).

Legitimate build-time images:

- `harnessed-base` — mise/node/python + common tooling → `FROM harnessed-base` → **`harnessed-claude`**, **`harnessed-omp`**, **`harnessed-opencode`**, **`harnessed-gemini`**, **`harnessed-antigravity`**, **`harnessed-codex`**.
- `hatago` — the hub + the *light* `npx`/`uvx` stdio MCP servers baked in.
- **Per heavy service** — `services/hindsight/Dockerfile`, `services/openbrain/Dockerfile`, each
  standalone, independently versioned, reusable across stacks.

## 7. Assembly — Dockerfile recipe model + supply-chain gate

A **recipe** contributes a `Dockerfile` (no `FROM` line) that the assembler concatenates into the
derived stack Dockerfile. The recipe's `recipe.yaml` carries metadata only — MCP server declarations,
harness compatibility, and a smoke-check list. Build steps live in the Dockerfile, not in YAML fields.

### Recipe = Dockerfile body

Each recipe's `Dockerfile` declares `ARG HARNESS=<default-harness>` at the top. This lets the body
reference `${HARNESS}` for harness-specific installs (e.g. `pnpm dlx @gstack/install --host ${HARNESS}`).
The assembler:

1. Strips each recipe's `ARG HARNESS` declaration (and any `FROM` line — recipes must not have one).
2. Emits `FROM harnessed-${HARNESS}:latest` as the derived Dockerfile header.
3. Concatenates recipe bodies in declaration order under that header, annotated with recipe names as comments.
4. Writes the result to `profiles/<stack>/Dockerfile.harnessed-<stack>`.

Example emitted derived Dockerfile:
```dockerfile
# Generated by harnessed assemble — do not edit.
FROM harnessed-claude:latest
ARG HARNESS=claude

# ── recipe: time ──
# (time MCP server is baked into the hatago config — no RUN steps needed)

# ── recipe: gstack (pinned) ──
ARG GSTACK_REF=v1.4.0
RUN git clone --branch ${GSTACK_REF} --depth 1 https://github.com/garrytan/gstack.git \
    ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup --host ${HARNESS}
```

### recipe.yaml declares metadata, not build steps

`recipe.yaml` carries:
- `name`, `description` — identity.
- `harnesses:` — the harnesses this recipe's installer supports. The assembler refuses to compose
  the recipe onto a stack whose harness is not listed (clean error, not a cryptic build failure).
- `mcp.servers:` — MCP server entries merged into `hatago.config.json` across all recipes in the stack.
- `expect:` — a smoke-check subset of skills/tools the capability test (§18) asks the agent about.
  Not a completeness oracle; `expect:` confirms the install landed, not that nothing extra was added.

The prior assembly model — which resolved plugins, fanned skills/commands trees into the profile, and
committed them — is superseded. Skills are image-baked by recipe Dockerfiles; the profile carries
only assembler-generated config files (`.mcp.json`, `settings.json`).

### Supply chain = pin sources in Dockerfiles + scan the derived image

**Two non-negotiables on every recipe Dockerfile:**

1. **Pin every source.** A floating ref (`--branch main`, unversioned `pnpm dlx @pkg`) is a
   validation error — the assembler refuses before any build starts. Acceptable pins: `--branch v1.4.0`,
   `pnpm dlx @pkg@1.2.3`, `ARG PKG_REF=abc123def` (commit SHA).

2. **Scan the built derived image.** After `podman build` produces `harnessed-<stack>:latest`:
   - **osv-scanner V2 (always-on, credential-free):** `osv-scanner scan image harnessed-<stack>:latest`.
     Fails on high-severity findings. Catches transitive CVEs that a source-only scan misses — the
     recipe model runs arbitrary upstream installers, so scanning the derived image is the only gate
     that sees what actually landed.
   - **Snyk container scan (warn-and-skip if no `SNYK_TOKEN`):** `snyk container test harnessed-<stack>:latest --severity-threshold=high`.
     Never prompts; build stays non-interactive.
   - **Socket.dev (warn-and-skip if no `SOCKET_SECURITY_API_KEY`):** source-scan coverage (Socket
     has no container-image mode; the recipe Dockerfile source directories are the scan target).

`harnessed build` fails on high-severity findings. A nightly job (the systemd-timer pattern) can
re-scan installed `harnessed-<stack>` images so a CVE disclosed after build still surfaces.

### Assembler output

For each stack build the assembler produces:
- `profiles/<stack>/Dockerfile.harnessed-<stack>` — the concatenated derived Dockerfile.
- `profiles/<stack>/hatago.config.json` — MCP server config assembled from `recipe.yaml mcp.servers`
  entries across all recipes.
- `profiles/<stack>/.mcp.json` and `profiles/<stack>/settings.json` — per-stack config files mounted
  surgically into the container at launch (§4b).

The host then runs `podman build --build-arg HARNESS=<agent> -t harnessed-<stack>:latest -f profiles/<stack>/Dockerfile.harnessed-<stack> .`.

### Scanner credentials (snyk / Socket.dev)

Only the credentialed scanners need this; `osv-scanner` and `pip-audit` use public DBs. Same rule
as Claude auth: **reference host creds, never bake or commit them.**

- **Present → use, silently.** Sources, in order: raw `SNYK_TOKEN` / `SOCKET_SECURITY_API_KEY` env
  or host config (`~/.config/configstore/snyk.json`); **or**, if you use varlock (§16, optional), an
  `op(op://…)` ref in `~/.config/harnessed/.env.schema`. Either way it reaches `harnessed-tools` at
  launch — never an image layer.
- **Missing → warn and skip that scanner**, not an interactive prompt. `harnessed build` must stay
  non-interactive / reproducible (CI, the nightly timer), and a typed token must never land in a
  repo or image layer. The credential-free `osv-scanner` + `pip-audit` remain the baseline gate.
- **Opt-in setup:** `harnessed auth snyk|socket` runs the CLI's own `auth` inside the tool
  container and persists to the mounted host config — so a token is set deliberately, once.

### pnpm everywhere (supply-chain policy)

All JavaScript installs — **global, per-recipe, and hatago's bundled servers** — use **pnpm**, not
npm/npx. Rationale: <https://pnpm.io/supply-chain-security>. A managed pnpm config (shipped in
`harnessed-base` / `lib/`) enables:

- **`minimumReleaseAge`** — quarantine newly published versions (cooldown) so a compromised
  release isn't installed the moment it lands.
- **lifecycle scripts default-denied** — `strictDepBuilds` (live in the global config) makes
  pnpm exit non-zero on any unreviewed postinstall/build script. The curated `allowBuilds`
  except-list is **project-scoped** (pnpm-workspace.yaml / config-dependencies): pnpm v11
  rejects it from the global config, so it is deferred until a build-script package (e.g.
  esbuild) actually needs to run.
- **store integrity verification** + content-addressed store.

`minimumReleaseAge`, `strictDepBuilds`, and store-integrity ship in the managed global
`~/.config/pnpm/config.yaml` (shipped from `lib/pnpm/config.yaml`) — **not** `.npmrc`, which
is auth/registry-only in v11. (`allowBuilds` is the one exception: it belongs in each
project's `pnpm-workspace.yaml`, not the global config — verified in the phase-3 checkpoint.)

`npx <pkg>` → `pnpm dlx <pkg>`; `npm install` → `pnpm install`. **Recipe validation** (part of
`harnessed build`) flags any raw `npm`/`npx` in a recipe Dockerfile and points at the pnpm
equivalent.

## 8. Canonical format = Claude Code; omp via bridge

Claude Code format is the **single source of truth** for skills/commands/hooks/plugins. Other
harnesses adapt *out* of it:

- **claude** — native; mount directly.
- **omp** — consumes Claude-format hooks/skills at runtime via
  `claude-hooks-bridge` (`~/Programming/AI/omp-extensions/claude-hooks-bridge`) +
  `lib-pi-adapter.sh`. **No re-authoring.** The `omp` base recipe pulls these in.
- **opencode** — consumes the **same** Claude-canonical profile: it reads `.claude/skills/**/SKILL.md`
  and `~/.claude/CLAUDE.md` natively (no bridge, no re-authoring). MCP is wired via the image-baked
  `~/.config/opencode/opencode.json`, which declares one remote (Streamable-HTTP) MCP server pointing
  at the hatago hub — opencode **ignores `.mcp.json`**. Caveat: `.claude/commands` and `.claude/agents`
  are NOT consumed (skills + CLAUDE.md/AGENTS.md port directly).
- **gemini** — mounts the **same** `.claude/` profile as claude/omp/opencode (`HARNESS_CONFIG_DIR["gemini"] = ".claude"`)
  but does NOT natively consume Claude skills/commands (its native asset format differs). Capability wiring is MCP via the
  image-baked `~/.gemini/settings.json`, whose `mcpServers` points one remote (Streamable-HTTP) server at the hatago hub.
- **antigravity (agy)** — mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["antigravity"] = ".claude"`) but likewise
  does NOT natively consume Claude skills/commands. Capability wiring is MCP via the image-baked
  `~/.gemini/config/mcp_config.json`, whose `mcpServers` points one remote server (`serverUrl`) at the hatago hub.
- **codex (OpenAI Codex CLI)** — mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["codex"] = ".claude"`) but likewise
  does NOT natively consume Claude skills/commands (it reads `AGENTS.md` + its own `~/.codex/prompts` format). Capability wiring is MCP via the
  image-baked `~/.codex/config.toml`, whose `[mcp_servers.hatago]` entry points one remote (Streamable-HTTP) server at the hatago hub
  (`url = "http://localhost:3535/mcp"` — codex 0.139+ natively supports remote Streamable-HTTP MCP, no stdio bridge).

**One harness per stack.** A stack targets exactly one of `claude`, `omp`, `opencode`, `gemini`, `antigravity`, *or* `codex`, never two at once.

## 9. State & lifecycle

- **Default persistent, `--fresh` to wipe.** Accumulation is the *value* of a memory system;
  `--fresh` gives a clean-room comparison run (throwaway volume).
- **Service volumes are service-scoped & harness-independent** — `hindsight-data`, not
  `harnessed-data-<stack>`. This is what lets `claude+hindsight` and `omp+hindsight` share **one**
  memory.
- **Shared instance, concurrent.** One long-lived `hindsight` container, owned by the *service*
  not any instance; postgres serves both instances at once. An instance starts it if absent; it
  outlives instances (`harnessed svc up/down`). The service **publishes its port to `0.0.0.0`**
  and peers reach it via the podman host gateway **`host.containers.internal:<port>`** (the
  primary reachability model); the `harnessed-net` bridge + DNS-by-name is the **`HARNESSED_NET`
  opt-in** for bridge-capable hosts (a rootless bridge is unsupported on most hosts — netavark
  "Operation not supported").
- **Harness-state** — `projects/` + `history.jsonl` persist to the **host** by default
  (harnessed-scoped, path-mirrored for a stable slug; `session_state: volume` for throwaway).
  Other ephemeral state (`sessions/`, caches) stays in a per-instance volume.

### Operator prerequisites for the host-gateway reachability model

The publish + host-gateway model above depends on two operator-side controls that already ship
in the repo. They are documented here as **prerequisites**, not implementation details:

1. **Egress-firewall allow rule for `host.containers.internal`.** Rootless podman exposes the
   host gateway at `host.containers.internal` (`169.254.1.2`). `lib/egress-firewall.sh:55-63`
   computes `PODMAN_GW=$(getent ahosts host.containers.internal …)` and adds an iptables allow
   rule for it — distinct from the default-route gateway. Without this rule the proxy path is
   blocked (iptables is netns-wide, so it gates hatago too).
2. **FastMCP `allowed_hosts`.** A Streamable-HTTP service proxied over
   `host.containers.internal` MUST add it to `TransportSecuritySettings.allowed_hosts`, or
   FastMCP's DNS-rebinding protection returns `421 Misdirected Request`. Canonical implementation:
   `services/ping/server.py:19-25` (commit `6f6c1b3`); see also the "Networking note" in
   `docs/guides/service-authoring.md`.

---

## 10. Proposed: repo layout

```
code-container/
  harnessed                    # thin host bash bootstrap → host podman build/run; drives the assembler (§15)
  container                    # back-compat alias → `harnessed transparent` (see §14)
  .env.schema.example          # varlock secrets template → ~/.config/harnessed/.env.schema (§16)
  tools/                       # harnessed-tools: the assembler image — emits Dockerfile+profile+launcher (Python)
    Dockerfile                 # python + rich/textual + yq/jq + git + pnpm + scanners + varlock + op
    pyproject.toml
    harnessed/                 # cli, assemble, vendor, sync-links, validate, emit Dockerfile/launcher
  base/
    Dockerfile.harnessed-base    # mise/node/python + common tooling
    Dockerfile.harnessed-claude  # FROM harnessed-base + claude install
    Dockerfile.harnessed-omp     # FROM harnessed-base + omp install
    Dockerfile.hatago          # hatago + light pnpm-dlx/uvx MCP servers
  services/                    # heavy/stateful sidecars, each its own image
    hindsight/Dockerfile
    openbrain/Dockerfile
  recipes/                     # hand-authored per-integration definitions
    omp/recipe.yaml            # base recipe: claude-hooks-bridge + pi-adapter
    hindsight/recipe.yaml
    gsd/recipe.yaml
    caveman/recipe.yaml
  stacks/                      # authored stack manifests (harness + recipes)
    claude-openbrain-headroom-caveman/stack.yaml
    transparent/stack.yaml     # built-in: host-mirror mode (the old `container`)
  profiles/                    # GENERATED + committed; mounted into the harness container
    claude-openbrain-headroom-caveman/
      .claude/{skills,commands,agents,hooks,rules}/
      hatago.config.json
  lib/                         # runtime bash mounted into instances (NOT the assembler — see tools/)
    mounts.sh                  # shared host-integration mount layer (§4a)
    hooks/{run-hook.sh,lib-*.sh}
```

Relationship: `recipes/` (inputs) + `stacks/<name>/stack.yaml` (composition) → **assemble** →
`profiles/<name>/` (committed output, mounted) + hatago config + ensured images.

## 11. Proposed: recipe schema (`recipes/<name>/recipe.yaml`)

```yaml
name: hindsight
description: Hindsight long-term memory (postgres + MCP)

# --- MCP layer ---
mcp:
  servers:
    - name: hindsight
      service: hindsight        # references services/hindsight → shared sidecar
      url_env: HINDSIGHT_URL    # optional env injected into the instance

    # light server alternative (hatago runs it as a child, wraps stdio→HTTP):
    # - name: fetch
    #   command: uvx
    #   args: ["mcp-server-fetch"]
    #   transport: stdio

# --- File-extension layer (Claude-canonical) ---
plugins:                        # vendored via vendor-plugin
  - marketplace: hindsight
    plugin: hindsight-memory
    # or: { url: ..., sha: ..., subdir: ... }

skills:                         # standalone skill dirs shipped by this recipe
  - path: skills/hindsight-docs

hooks:
  event_dir: hooks              # NN-name.sh handlers grouped under <Event>.d/

# Dependencies — uv for Python, pnpm for Node (never npm/npx — see §7). Usually AUTO-DETECTED
# from a vendored plugin's own files; declare here for standalone recipes / overrides.
deps:
  python: pyproject.toml        # requirements.txt → `uv pip install -r`
                                # pyproject.toml   → `uv venv` + `uv pip install -e .`
  node: package.json            # → `pnpm install` (managed supply-chain config)
```

`omp` base recipe:

```yaml
name: omp
description: omp/pi base — consume Claude-format hooks/skills

extensions:                     # omp-native extensions installed into the instance
  - package: npm:@ryan_nookpi/pi-extension-claude-hooks-bridge
```

## 12. Proposed: stack manifest (`stacks/<name>/stack.yaml`)

```yaml
# isolated stack (recipe-composed)
name: claude-openbrain-headroom-caveman
config: isolated              # isolated (default) | transparent
harness: claude               # claude | omp | opencode | gemini | antigravity | codex  (exactly one)
permissions: yolo             # prompt (default) | yolo — writes per-harness skip-permission
                              #   config (Permissions.md) into the profile; safe in an isolated instance

recipes: [openbrain, headroom, caveman]
services: [openbrain]         # shared services attached by reference

state:
  persist: true               # default; `--fresh` overrides at runtime
  session_state: host         # host (default — projects/history persist, inspectable) | volume
```

Built-in `transparent` stack (the old `container` — host-mirror, no recipes/services):

```yaml
name: transparent
config: transparent           # mount host ~/.claude, ~/.codex, ~/.config/opencode, ~/.gemini live
# harness omitted: transparent mirrors all host harness configs; pick one in the shell
```

## 13. Proposed: CLI surface

```
harnessed <stack> [path]      # start/attach a stack against cwd (or path), then exec the harness
harnessed transparent [path]  # host-mirror mode (= today's `container`); alias: `container`
harnessed build <stack>       # assemble recipes → profile + images (build-time)
harnessed install <stack>     # write ~/.local/bin/<stack> launcher shim (see below)
harnessed uninstall <stack>   # remove the launcher shim
harnessed --fresh <stack>     # start with empty state volumes
harnessed new <stack> --harness claude --recipes a,b,c   # scaffold a stack manifest
harnessed list                # stacks + running instances
harnessed stop <stack>
harnessed rm <stack>
harnessed svc up <service>    # start a shared service (publishes its port; peers reach it via host.containers.internal, or by DNS name under HARNESSED_NET)
harnessed svc down <service>
harnessed svc list
harnessed auth snyk|socket    # one-time: set a scanner token (persisted to host config)
```

**Naming/identity (proposed):**
- pod: `harnessed-<stack>-<projhash>` — same stack runnable across projects without recreate
  (bind mounts are fixed at creation, so the project is part of identity).
- shared services: global by name (`hindsight`), reached via the host gateway `host.containers.internal:<port>` (or by DNS name over the `HARNESSED_NET` bridge on bridge-capable hosts).

### Generated launcher shim (`harnessed install`)

`harnessed install <stack>` writes an executable `~/.local/bin/<stack>` so you can launch an instance
by name from anywhere (mirrors the repo's existing `install.sh`, which puts `container` on PATH):

```bash
#!/usr/bin/env bash
# generated by `harnessed install claude-openbrain-headroom-caveman`
HARNESSED_PATH=/home/you/Programming/.../harnessed     # abs path to the harnessed executable
HARNESSED_NAME=claude-openbrain-headroom-caveman       # the stack to launch
exec "$HARNESSED_PATH" "$HARNESSED_NAME" "$@"           # "$@" forwards an optional project path
```

Then `claude-openbrain-headroom-caveman [path]` from any directory starts that instance.
`harnessed uninstall <stack>` removes the shim.

## 14. Open / to verify during execution

- **Minimal `.claude.json` stub fields.** Boot an instance and confirm no re-login/onboarding prompt.
  Candidate set: `oauthAccount`, `userID`, `hasCompletedOnboarding` (+ possibly `firstStartTime`,
  `numStartups`). [INFERENCE — verify empirically.]
- **Per-server MCP transport.** Which servers already speak Streamable HTTP vs need hatago's
  stdio→HTTP wrapping (hindsight already runs as postgres+MCP, likely network-native).
- **Intra-stack collision policy.** Confirm fail-fast (reuse `sync-plugin-links`' conflict exit)
  is the desired behavior vs last-wins/namespacing when two recipes ship the same skill/command name.
- **Harness config mount points.** Exact target paths per harness (claude `~/.claude/...`;
  omp config dir) for the profile mount. *(Resolved, HRN-02)* opencode mounts the **same** `.claude/`
  profile as claude/omp (`HARNESS_CONFIG_DIR["opencode"] = ".claude"`), plus a baked
  `~/.config/opencode/opencode.json` MCP config and a read-only `~/.local/share/opencode/auth.json`.
- *(Resolved, HRN-03 — gemini)* gemini mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["gemini"] = ".claude"`); the
  gemini-cli is already installed and working in `harnessed-base` (v0.46.0, pure-JS, no broken postinstall), so the
  `harnessed-gemini` image just bakes a global `~/.gemini/settings.json` whose `mcpServers` points one remote (Streamable-HTTP)
  server at `http://localhost:3535/mcp`. Auth: host `~/.gemini` OAuth creds (mounted) or `GEMINI_API_KEY`/`GOOGLE_API_KEY` env.
- *(Resolved, HRN-04 — antigravity)* antigravity mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["antigravity"] = ".claude"`); the
  `agy` CLI is installed via the official vendor curl installer (`curl -fsSL https://antigravity.google/cli/install.sh | bash` — a standalone Go binary in `~/.local/bin`). The `harnessed-antigravity` image bakes a `~/.gemini/config/mcp_config.json` whose `mcpServers` points one
  remote server (`serverUrl`) at `http://localhost:3535/mcp`. Auth: `ANTIGRAVITY_API_KEY` env or one-time OAuth creds.
- *(Resolved, HRN-05 — codex)* codex mounts the **same** `.claude/` profile (`HARNESS_CONFIG_DIR["codex"] = ".claude"`); codex-cli
  is already installed and working in `harnessed-base` (v0.139.0, `npm:@openai/codex` ships platform binaries as optionalDependencies —
  no blocked postinstall), so the `harnessed-codex` image just bakes a global `~/.codex/config.toml` whose `[mcp_servers.hatago]` entry
  points one remote server (`url = "http://localhost:3535/mcp"`) at the hatago hub (codex 0.139+ natively supports remote Streamable-HTTP MCP —
  no stdio bridge). Auth: host `~/.codex/auth.json` (mounted ro) or `OPENAI_API_KEY` env.
- **`container` alias.** Keep `container` as a thin alias → `harnessed transparent` for muscle
  memory, or remove once `harnessed` lands. (Recommendation: keep — zero cost.)
- **hatago placement.** Confirmed: in the pod over HTTP (not stdio inside the harness container) to keep npx/uvx out of
  the harness container — re-verify once a real stack is built.
- **Editor/tool configs in isolated mode.** §4a mounts `~/.config/<tool>` (nvim, etc.) for all
  stacks as operational. Confirm that's wanted in `isolated` instances, or gate behind a flag if a
  truly empty environment is ever needed.
- **Host-projects scope.** Does `session_state: host` write the host's own `~/.claude/projects/`
  (full continuity with host claude) or a harnessed-owned dir (`~/.harnessed/projects/`) to keep
  instance sessions separate? (Recommendation: harnessed-owned.)
- **Container home path.** `/home/harnessed/<relpath>` (vs `container.sh`'s `/container/$USER`)
  for a legible, stable project slug — confirm it doesn't break the harness installs.
- **pnpm rollout (resolved, phase 3).** mise routes its `npm:` backend through pnpm
  (`npm.package_manager=pnpm`, confirmed in the harnessed-base build). `minimumReleaseAge=1440`
  + `strictDepBuilds` (default-deny) ship in the global config. `allowBuilds` is project-scoped
  (pnpm-workspace.yaml) — v11 rejects it globally — so the allowlist is deferred until a
  build-script package (esbuild) actually needs to run.
- **`CLAUDE_CONFIG_DIR` relocation.** Verify whether it relocates `~/.claude.json` (not just the
  `.claude/` dir). If yes, both modes can point Claude at a per-instance config dir instead of
  copy-on-start, fully decoupling container state from the host file. [INFERENCE — verify.]

## 15. Proposed: implementation — single dependency, containerized assembler

**Goal: the only host dependency is podman/docker.** No host Python/node/uv version roulette.

Two phases, and the host runs podman **natively** throughout — the container only emits files, it
never drives the daemon (so there is no Docker-out-of-Docker):

- **Assemble (build time) — `harnessed-tools`, the assembler image (built first run / `--build`).**
  Python + `rich` (and `textual` if a TUI lands) + `yq`/`jq` + `git` + `pnpm` + the supply-chain
  scanners (+ varlock/`op`). Holds *all* assembly logic: parse/validate YAML, vendor
  (`vendor-plugin`), `sync-plugin-links` (already Python), merge `hatago.config.json`, generate the
  `.claude.json` stub, write yolo configs, scan. The host bootstrap runs it as
  `podman run -v <build-dir> harnessed-tools …`; it **only reads/writes the mounted dir and emits
  files** — a `Dockerfile` (+ build context) per image, the committed `profiles/<stack>/`,
  `hatago.config.json`, and a generated launcher. It does **not** run podman. (This is
  "tool-in-a-container", like running a linter in a container — not DooD.)
- **Build → install → launch (host).** The **host** runs `podman build` on the emitted Dockerfiles
  → pinned images. `harnessed install <stack>` writes the generated launcher to `~/.local/bin/<stack>`.
  That launcher is plain **host bash**: it computes the §4a conditional mounts on the host (like
  today's `container.sh`) and runs the pod via host `podman pod`/`podman run`, attaching with
  `podman exec -it`. `harnessed <stack>` and `container` delegate to it.
- **`harnessed` — thin host bootstrap (bash, dependency-free).** Detects the runtime; for
  `harnessed build` it ensures the assembler image exists then drives assemble → `podman build`; for
  `harnessed <stack>` (run) it invokes the generated host launcher.

This supersedes the earlier "bash orchestrator + Python assembler" split *and* the interim "one image
that drives the host daemon" idea: assembly logic consolidates into one container image that emits
files; building and launching are ordinary host podman commands. (Testing is integration-only — see
§18 — not assembler unit tests.)

**Why no DooD.** Separating "generate the build/run inputs" (the assembler, needs Python) from
"execute `podman build`/`podman run`" (the host, needs the daemon) removes every cost of driving the
daemon from inside a container:

- **No API socket to mount, no `CONTAINER_HOST`/`DOCKER_HOST`.** podman is invoked directly on the host.
- **No host-absolute-path footgun.** The launcher runs on the host, so `$HOME`/`$PWD`/project paths
  are host-native by construction — the classic DooD bind-path gotcha cannot occur.
- **Clean TTY for free.** The launcher is host bash, so the interactive `podman exec -it` attach is
  host-native with no tunneling.
- **First-run build latency** — mitigate by pinning the assembler image and optionally publishing a
  prebuilt one; later runs are cache hits.

`transparent` is the degenerate case: no recipes → no assembler and no `harnessed-tools` image. It is
just a host launcher running the prebuilt `harnessed-claude` image with the §4a mounts +
`.claude.json` copy-on-start. The assembler image is only needed once you assemble an `isolated` stack.

Net install: `git clone` + symlink the `harnessed` bootstrap; first `build` builds the assembler
image. Podman/docker is the only thing the user must have.

**Runtime abstraction (provider-agnostic isolated mode).** The shared-netns group is abstracted
by `lib/harnessed-runtime.sh` (`rt_*`): podman → pod; docker → shared-netns pair
(`--network container:<hatago>`); Apple `container` not yet (tracked). The harness-matrix UAT —
`tools/uat/phase-06.sh`, run via `./tools/uat/run-uat.sh 6` (`--quick` = manifest/validation only) —
is the systematic cross-harness proof and the regression gate for the provider port: one capability
test per supported harness over the `<harness>-time` proof stacks, plus a fast manifest check.

## 16. Proposed: secrets — varlock + 1Password (optional)

**varlock is optional — harnessed works fully without it.** It's an opt-in secrets source: if you
use it, secrets resolve from **1Password** instead of loose files. varlock reads a `.env.schema`
(`@env-spec` DSL) whose secret values are `op(op://Vault/Item/field)` references, validates them, and
injects the resolved values into a process (`varlock run -- <cmd>`, or `varlock load --format env`
to emit the dotenv, which is what harnessed uses — see below). Copying the shipped
`.env.schema.example` is what turns it on; users who skip it lose nothing else.

**Schema locations (XDG):**

- `~/.config/harnessed/.env.schema` — harnessed-level secrets (e.g. `SNYK_TOKEN`,
  `SOCKET_SECURITY_API_KEY`). The repo ships **`.env.schema.example`** to copy here.
- `~/.config/<service>/.env.schema` — per-service secrets (e.g. `~/.config/hindsight/.env.schema`),
  loaded when that service starts (`harnessed svc up <service>`).
- (optional, later) per-stack overrides referenced from `stack.yaml`.

**How harnessed uses it:**

- On launch, `harnessed` checks for a relevant `.env.schema`. **Present (opt-in) →** resolution runs
  `varlock load --format env` **on the host**; the resolved dotenv is written to a mode-0600 temp
  env-file that the launcher spreads into the container (`--env-file`, unlinked after launch). This
  reaches **all four** launch paths — the isolated pod, the transparent instance, per-service sidecars
  (`~/.config/<service>/.env.schema`), and the build scan. **Absent (the default) →** plain host env
  passthrough (the §7 scanner present/skip logic still applies); with no schema, varlock is never
  invoked.
- **App-auth runs on the host, not in the container.** 1Password's desktop app authorizes the `op` CLI
  by *calling application* — the user's terminal. An `op` running inside a throwaway container has no
  host app to bind the grant to, so app-auth (`@initOp(allowAppAuth=true)`) fails there ("cannot
  connect to 1Password app") regardless of which socket is mounted. The `~/.1password/agent.sock`
  mounted in §4a is the **SSH agent** (for git commit signing), **not** the `op` app-auth transport.
  So varlock + `op` run on the host; the resolved env is what crosses into the container.
- The in-container path is the **headless fallback**, used only when the host has no `varlock` (e.g.
  CI, the nightly timer): there the schema resolves inside a `--rm` tools container with
  `OP_SERVICE_ACCOUNT_TOKEN` (HTTPS bearer auth — no desktop app, no app-auth, no socket). It stays
  **inert unless a schema exists.**
- Resolved secrets are injected as **env only** — never written to the repo, a committed profile, or
  an image layer (same rule as Claude auth).

## 17. Proposed: documentation (first-class deliverable)

Docs are a **gated deliverable, not an afterthought** — `harnessed` is a tool other people (and
future-you) must operate. Required surface, by audience:

- **README.md** — what `harnessed` is, the two modes, install (`git clone` + bootstrap), first-run
  build, a 60-second quickstart. Updated alongside the existing `container` README.
- **docs/harnessed-design.md** (this file) — architecture + decisions; the source of truth for *why*.
- **Recipe authoring guide** — writing `recipes/<name>/recipe.yaml`: MCP servers, file extensions,
  deps, the Claude-canonical rule, the pnpm rule — with one worked example end to end.
- **Stack guide** — composing recipes into `stacks/<name>/stack.yaml`; `transparent` vs `isolated`;
  `permissions` / `session_state`; `harnessed install`.
- **Secrets setup** — varlock + 1Password (§16): copying `.env.schema.example`, `op(op://…)` refs.
- **Service authoring** — adding a heavy sidecar under `services/` (image + `.env.schema`).
- **Troubleshooting / ops** — podman socket, first-run build, auth/onboarding, `--fresh`,
  inspecting host-persisted sessions.

Cadence: each section lands **with** the feature it documents (a feature isn't "done" until its docs
exist), per this repo's existing AGENTS.md / README conventions. This design spec stays current as
decisions change (as it has through this session).

## 18. Testing — integration only, behavior through the instance

Per the project's TDD philosophy (`tdd` skill): **test behavior through the public interface, and
write tests that survive refactors.** For harnessed the public interface is the **running instance**, and
the behavior is "the instance exposes exactly the MCP servers / skills / commands its stack declares."

- **No assembler unit tests.** Testing assembler internals couples to implementation and breaks on
  refactor — the anti-pattern the TDD skill warns against. The assembler is covered *transitively*:
  wire the wrong thing and the capability test fails.
- **The stack manifest is the test oracle.** Expected capabilities (`recipes` → MCP servers +
  skills/tools; `services`) are derived from `stack.yaml` + its recipes; the test asserts the live
  instance matches. It reads like a spec: "`gstack-time` exposes MCP `time` and skills `review`, `qa`."

**Two-oracle capability test (per stack):**

The capability test uses two complementary oracles that prove different things:

**Oracle 1 — Structured MCP probe (deterministic).** Hit hatago's `hatago://servers` resource — a
JSON snapshot of the connected child servers behind the hub — and/or `claude mcp list`. Assert that
every `mcp.servers` entry declared in the stack's recipes appears as connected. No model call; fast
and deterministic.

**Oracle 2 — Un-primed agent probe (behavioral).** Ask the harness, headless, what capabilities it
has — deliberately NOT priming it with the expected list. The prompt names the `expect:` skills/tools
from the recipe PLUS a **decoy** capability (a name that exists in neither the recipe nor the image).
The agent must report which it has and which it lacks, without the test telling it which are real.

```bash
podman exec <container> claude -p 'You have a set of skills and tools available. For EACH name below, answer "have" or "missing" — do not assume; check what is actually loaded.

office-hours, plan-ceo-review, review, qa, ship, browse, <decoy-not-installed>

Respond as JSON: {"have": [...], "missing": [...]}'
```

**Negative control (anti-sycophancy gate).** The decoy MUST appear in `missing`. If the agent
claims the decoy is present, the test exits with status **INVALID** — distinct from a normal
capability-failure non-zero exit. INVALID means priming/sycophancy was detected: the model is
hallucinating agreement, not reporting what it actually loaded. An INVALID result causes the run to
fail regardless of how all other capabilities scored.

Why un-primed with a negative control? Naming expected capabilities in a "respond YES" prompt primes
the model to confirm capabilities it never loaded. The decoy closes that hole: a model that actually
checked its loaded skills gets the decoy right; a model hallucinating agreement claims it.

**Assertion logic:**
1. Oracle 1: assert each `mcp.servers` entry appears in `hatago://servers` — fail if not connected.
2. Oracle 2: assert decoy is in `missing` → INVALID if it is in `have`; assert each `expect:` entry is in `have` — fail any that appear in `missing`.

**Capability report — the test output is a user artifact.** `harnessed test <stack>` writes
`profiles/<stack>/capability-report.md` after every run, rendering a per-capability table showing
✓/✗ for each MCP server and `expect:` entry, plus an INVALID banner when priming is detected:

```
## gstack-time — capability report
| capability      | kind  | status      |
|-----------------|-------|-------------|
| time            | mcp   | ✓ connected |
| office-hours    | skill | ✓ present   |
| plan-ceo-review | skill | ✓ present   |
| review          | skill | ✓ present   |
| qa              | skill | ✓ present   |
| ship            | skill | ✓ present   |
| browse          | tool  | ✓ present   |

INVALID: agent claimed decoy capability '<decoy>' — sycophancy/priming detected.
```

`harnessed build` renders it with `rich` (already in the tools image; markdown → terminal); CI
consumes the same structured result as the assertion. One mechanism, two audiences — the user sees
how complete/healthy the build is, CI sees green/red.

**Build harnessed itself in vertical slices** (tracer bullets, not horizontal): the first slice is a
minimal stack — one harness + one MCP server + one skill — with its capability test green end to end
(assemble → run → assert). Then add recipes one at a time, each with its own red→green capability
test. Never "write all recipes, then all tests."

**Honest tradeoff:** integration-only means an assembler bug surfaces as a capability failure, not a
pinpointed unit failure — coarser to debug. Mitigate with clear assembler errors (e.g. pin-validation
rejections with the offending line) so a failed build says *what* it couldn't wire.
`````

## File: README.md
`````markdown
<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### harnessed — Composable harness stacks (Claude Code / omp / opencode / gemini / antigravity / codex + an MCP hub + optional shared services)

> [!WARNING]
> **⚠️ ALPHA SOFTWARE — not production-ready.** harnessed is under active development and the field
> of agentic AI security is very young. Expect breaking changes, rough edges, and incomplete
> features. **Use at your own risk.**
>
> **Container runtimes — all WIP:**
>
> | Runtime | Status | Notes |
> | --- | --- | --- |
> | **podman** (rootless) | 🧪 **in testing** | The reference runtime (pods). Most complete path — verify your host with `./tools/uat/run-uat.sh 6`. |
> | **Docker** | ⏳ **pending** | A shared-network-namespace path exists (`--network container:`) but is **not yet verified**. Egress firewall needs rootless `NET_ADMIN` (best-effort — `--no-firewall` to skip); shared **service sidecars** aren't wired (no `host.containers.internal`). |
> | **Apple `container`** | ⏳ **pending** | Tracked follow-up. One VM/IP per container, no shared netns — needs a different networking story. |
>
> Runtime differences are abstracted by [`lib/harnessed-runtime.sh`](lib/harnessed-runtime.sh). See [troubleshooting](docs/guides/troubleshooting.md).

You can read my [announcement here](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/)

> Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and extended significantly for rootless Podman, hardware authentication (YubiKey, 1Password), seamless Claude Code auth, composable harness stacks, and alternative AI providers.

---

`harnessed` is **one executable** that launches **composable harness stacks** — each a
podman pod running an AI coding harness (`claude`, `omp`, `opencode`, `gemini`, `antigravity`, or `codex`) plus an MCP hub (hatago) plus optional
shared services (hindsight, openbrain, …). You compose a named stack (one harness + chosen recipes)
and launch an authenticated instance that exposes **exactly** the skills/commands/MCP/
services it declares — nothing from the host config — reproducibly, with **podman as the only host
dependency**.

It's for developers who want to compose and trial harness configurations — different
skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent environments
without dragging every host default into the container or polluting `~`. The existing `container`
"my laptop, sandboxed" behavior folds in as the built-in `transparent` stack; `container` remains a
thin alias for `harnessed transparent`.

> The full architecture and design rationale live in **[docs/harnessed-design.md](docs/harnessed-design.md)**
> (§1–§18 — the *why*). This README is the *how*: install, build, and run.

## One engine, two modes

Every stack shares the same base image, the same host-integration mounts (1Password/GPG agents,
YubiKey, SSH/git config, egress firewall, the project folder), and the same host auth. Stacks differ
on exactly **one axis** — where the config layer (skills/commands/hooks/MCP) comes from:

| Mode | Command | Config source | When to use |
| --- | --- | --- | --- |
| **`transparent`** | `harnessed transparent [path]` (or just `harnessed [path]`) | host `~/.claude` (+ `.codex`/`.config/opencode`/`.gemini`) bind-mounted live | "My laptop, sandboxed" — your own config, firewalled. This is the old `container`. |
| **`isolated`** | `harnessed <stack> [path]` | auth seeded + an assembled **stack profile** mounted; nothing from host config | "Clean room with exactly what I picked" — experiment with curated skill/MCP/service combos per container. |

Same engine, same operational mounts, one switch. `transparent` is the degenerate case — harness
container only, host config mounted live (no pod, no hatago, no assembler). `isolated` is
authenticated but carries **no host defaults**. See [design §2](docs/harnessed-design.md).

## Install

**Podman (rootless) is the only host dependency** — it's the reference runtime (Docker support is pending; see the runtime table above). No host Python/node/uv is required —
all assembly logic lives in a containerized `harnessed-tools` image ([design §15](docs/harnessed-design.md)).

```bash
curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash
```

The installer clones the repo to `~/.local/share/code-container` (or pulls latest if already
installed) and symlinks `harnessed` — plus the `container` back-compat alias — onto your PATH
(`~/.local/bin` if it's on PATH, else `/usr/local/bin` via sudo). The installer is fully verbose.

To uninstall, remove the symlinks and the cloned directory.

> **Linux** — tested on Manjaro; should work on any systemd distro. macOS/WSL untested.

## First-run build

Images are built on the host with `podman build` the first time they're needed. The image lineage is three layers:

- **Layer 1 — `harnessed-base`**: fat toolchain image (mise, node@24, python, pnpm; no harness CLI).
- **Layer 2 — `harnessed-<harness>`**: FROM `harnessed-base` + harness CLI installed (one image per harness: `harnessed-claude`, `harnessed-omp`, `harnessed-opencode`, `harnessed-gemini`, `harnessed-antigravity`, `harnessed-codex`).
- **Layer 3 — `harnessed-<stack>`**: derived stack image built by `harnessed build <stack>` — FROM `harnessed-<harness>` + recipe Dockerfiles concatenated (e.g. `harnessed-gstack-time` FROM `harnessed-claude`).

Supporting images (not part of the base→agent→stack lineage):

- **`hatago`** — the MCP hub (aggregates a stack's MCP servers behind one HTTP endpoint; light `pnpm dlx`/`uvx` servers baked in).
- **`harnessed-tools`** — the emit-only assembler image (Python + scanners + pnpm + varlock + `op`). Needed for stack assembly.

```bash
harnessed build          # (re)build the base/claude/hatago images
harnessed build <stack>  # assemble one stack: emit profile + build hatago (+ supply-chain scan)
```

Bare `harnessed build` rebuilds the shared base/harness/hatago images. `harnessed build <stack>`
runs the assembler (emit-only), a scoped source/dependency scan, the host hatago image build, and an
image scan — producing a committed `profiles/<stack>/` tree. Expect first-run latency (images build
via host `podman build`); later runs are cache hits.

## Quickstart

**1. Transparent mode** — your host config, sandboxed (the old `container`):

```bash
cd /path/to/project
harnessed transparent      # or: container   (launches the harness with host config mounted live)
```

**2. Isolated mode** — a curated stack, built then run:

```bash
cd /path/to/project
harnessed build tracer-time && harnessed tracer-time
```

`tracer-time` is the smallest end-to-end stack slice: the `claude` harness + the `time` recipe
(one light stdio MCP server + one standalone skill), composed into a committed profile and run as a
pod (harness + hatago). Running an unbuilt stack errors and tells you to `harnessed build` it first.

After building, verify the stack's declared capabilities with the capability test:

```bash
harnessed test tracer-time
```

`harnessed test` launches the stack headless, runs the two-oracle capability check, and writes a per-capability report to `profiles/tracer-time/capability-report.md` (✓ connected / ✗ missing).

## Command surface

| Command | What it does |
| --- | --- |
| `harnessed [stack] [path]` | Launch a stack against cwd (default stack: `transparent`) |
| `harnessed transparent [path]` | Host-mirror stack: live host config + project |
| `harnessed <stack> [path] [--fresh]` | Isolated stack: assembled profile + pod (harness + hatago) |
| `harnessed build [<stack>]` | Build the base/harness/hatago images, or assemble + build one stack |
| `harnessed test <stack>` | Capability test: launch `--fresh` headless + assert declared capabilities (markdown report) |
| `harnessed svc up \| down \| list <service>` | Manage shared service sidecars (own image + volume) |
| `harnessed list` | List authored stacks + running instances |
| `harnessed stop \| rm <stack>` | Stop / remove every instance of a stack |
| `harnessed new <stack> [--harness claude\|omp\|opencode\|gemini\|antigravity\|codex] [--recipes a,b,c]` | Scaffold a stack manifest |
| `harnessed install \| uninstall <stack>` | Write / remove a `~/.local/bin/<stack>` launcher shim |
| `harnessed auth snyk \| socket` | Set a scanner token (persisted to host `~/.config`; never an image layer) |
| `harnessed rescan` | Re-scan installed harnessed images online (the nightly timer's trigger) |
| `harnessed --fresh ...` | Tear down any existing pod/instance first (isolated) |
| `harnessed --no-firewall ...` | Skip the egress firewall for this run |
| `harnessed -h \| --help` | Show help |

Run `harnessed --help` for the full surface. The legacy `--list`/`--stop`/`--remove`/`--clean` flags
remain for muscle memory (they dispatch to the per-instance path).

## Guides

- **[Recipe authoring](docs/guides/recipe-authoring.md)** — writing `recipes/<name>/recipe.yaml` (MCP layer + skills/commands), with worked examples.
- **[Stacks](docs/guides/stacks.md)** — composing recipes into `stacks/<name>/stack.yaml`, scaffolding, and the build/run/test lifecycle.
- **[Service authoring](docs/guides/service-authoring.md)** — adding a shared sidecar under `services/` (image + manifest + server).
- **[Secrets setup](docs/guides/secrets.md)** — opt-in varlock + 1Password (env-only, never baked).
- **[Troubleshooting](docs/guides/troubleshooting.md)** — podman setup, first-run build, `--fresh`, host-persisted sessions, the nightly re-scan timer.
- **[Architecture & design](docs/harnessed-design.md)** — the *why* behind every decision (§1–§18).

## Supply chain & security

- **pnpm everywhere** — every JavaScript install (global, per-recipe, hatago's bundled servers) uses **pnpm**, never `npm`/`npx`; `pnpm dlx` replaces `npx`. A managed supply-chain config applies `minimumReleaseAge` cooldowns and lifecycle-script default-deny. Recipe validation flags raw `npm`/`npx` and points at the pnpm equivalent ([design §7](docs/harnessed-design.md)).
- **Build-time scan gate** — `harnessed build` runs **osv-scanner** + **pip-audit** (credential-free, always) and **snyk**/**Socket.dev** when a token is present (warn-and-skip otherwise, so the build stays non-interactive). It **fails on high-severity** findings. See [BLD-02/SEC-02](.planning/REQUIREMENTS.md).
- **Opt-in secrets** — varlock + 1Password resolve `op://` refs into the pod as **env only** (never a profile, image layer, or repo file). Copy `.env.schema.example` to `~/.config/harnessed/.env.schema` to turn it on. See **[docs/guides/secrets.md](docs/guides/secrets.md)**.
- **Nightly re-scan** — a systemd user timer re-runs osv-scanner **online** against installed images so a CVE disclosed *after* build still surfaces. See **[troubleshooting](docs/guides/troubleshooting.md#nightly-re-scan-timer-sec-04)** for setup (including the `loginctl enable-linger` prerequisite).
- **Secrets/auth referenced, never baked** — Claude OAuth, scanner tokens, and 1Password secrets reach the instance as env or read-only mounts; never an image layer.

> All examples in this repo use placeholder values only (`op(op://Private/Snyk/credential)`, dummy
> tokens) — never real credentials.

## How harnessed is built (in practice)

- **A/B two memory systems.** Run `claude+hindsight` and `claude+openbrain` as separate stacks side by side; neither touches your host config or the other's state.
- **Compare harnesses on equal footing.** Point `claude+hindsight` and `omp+hindsight` at the **same** service-scoped memory volume and judge which harness drives it better — same data, different engine.
- **Clean-room a flaky plugin.** `harnessed <stack> --fresh` reproduces from zero state, then tears down leaving no residue in `~`.
- **Proof it built right.** Each stack ships a capability test: bring the instance up headless and assert it exposes exactly the MCP servers/skills/commands its manifest declares — rendered as a per-capability markdown report (✓ connected / ✗ missing).

## The `container` back-compat alias

`container` keeps working as a thin alias for `harnessed transparent` (the host-mirror sandbox). If
you only ever wanted "my laptop, sandboxed", `container` is unchanged. `harnessed` is the engine it
folds into.

---

### Which container solution is right for you?

Three projects solve adjacent problems — pick the one that matches your threat model and workflow:

|                      | This project                                         | [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)                  | [Anthropic devcontainer](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo) | [Trail of Bits](https://github.com/trailofbits/claude-code-devcontainer) |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Primary use case** | Power-user daily driver across multiple AI harnesses | Enterprise sandboxing with policy enforcement                            | VS Code team dev environments                                                                             | Security auditing of untrusted code                                      |
| **Auth model**       | Seamless — host credentials shared into container    | Credential providers inject keys; never exposed in sandbox               | Per-container setup                                                                                       | Fully isolated                                                           |
| **Threat model**     | Contain the AI, not the repo                         | Full defense-in-depth (filesystem, network, process, inference)          | Consistent team environments                                                                              | Malicious repos / adversarial input                                      |
| **Runtime**          | Podman (rootless); Docker pending                    | K3s (Kubernetes) inside Docker                                           | Docker / Dev Containers spec                                                                              | Docker                                                                   |
| **AI harnesses**     | Claude, omp (via bridge), opencode, gemini, antigravity, codex   | Claude, OpenCode, Codex, Copilot                                           | Claude                                                                                                    | Claude                                                                   |

**Use this project** if you want composable experimentation across skill/MCP/memory combinations,
without the friction of re-authentication or tool switching every session.

**Use [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)** if you need enterprise-grade sandboxing with declarative security policies, a privacy-aware LLM proxy, and Kubernetes orchestration for multi-agent environments.

**Use [Trail of Bits' devcontainer](https://github.com/trailofbits/claude-code-devcontainer)** if you're doing security audits or reviewing untrusted repos — their threat model explicitly accounts for malicious code trying to escape the container.

**Use Anthropic's official devcontainer** if you're on a team that wants a standardised, VS Code-integrated development environment with Claude Code.
`````

## File: .planning/PROJECT.md
`````markdown
# harnessed

## What This Is

`harnessed` is one executable that launches **containerized, composable harness stacks** — each
a podman pod running an AI coding harness (`claude`/`omp`/`opencode`/`gemini`/`antigravity`/`codex`)
plus an MCP hub (hatago) plus optional shared services. A **stack** is one harness + chosen
recipes; a **recipe** is a Dockerfile + a YAML manifest that runs a framework's own installer
(pinned to a tag/SHA). Each stack produces a separate derived image (`harnessed-<stack>`), so
`claude+gstack` and `claude+gsd` coexist without conflict.

It is for developers (initially the author) who want to compose and trial harness configurations
— different skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent
environments without dragging every host default into the container or polluting `~`.

## Current State: v2.0 Shipped 2026-06-24

**Shipped:** 3-layer image lineage (harnessed-base → harnessed-<harness> → harnessed-<stack>);
Dockerfile recipe model (recipes run frameworks' own installers, pinned to tag/SHA); surgical profile
mounts (.mcp.json + settings.json only, image-baked skills survive); osv-scanner V2 supply-chain gate;
per-harness YAML mount manifests; full architecture documentation updated.

**Deferred to next milestone:** Phase 10 (opencode/codex history investigation + two-oracle capability test).

**Next milestone:** To be defined via `/gsd-new-milestone`. Key work: Phase 10 completion (TST2-01/02/03, MNT2-07) + additional harness support.

## Previous Milestone: v2.0 Recipe Architecture & Agent Rebuild ✅

**Goal:** Replace the typed-YAML recipe model with a Dockerfile-based model where recipes run frameworks' own installers, rebuild the image lineage into 3 layers (base → agent → stack), and validate with a combined capability test backed by a supply-chain gate.

**Target features:**
- Fat base (`harnessed-base`): all runtimes pre-installed (node@24, bun, rust, go, python, pnpm@11); NO harness CLIs in base
- `agents/` directory: `type:agent` recipes that build standalone cached harness images (`harnessed-claude`, `harnessed-omp`)
- Dockerfile-based recipe model: `recipe.yaml` (`harnesses:`, `mcp:`, `expect:`) + `Dockerfile` that runs the framework's own installer, pinned to a tag/SHA, with `--host ${HARNESS}`
- Assembler: harness-compatibility check, pin validation, Dockerfile body concatenation, `HARNESS` build ARG injection
- Surgical profile mount: `.mcp.json` + `settings.json` only — image-baked skills survive
- Supply-chain gate: assembler rejects unpinned sources; osv-scanner V2 scans derived image post-build; nightly rescan continues
- Combined capability test: structured MCP probe (deterministic) + un-primed ask-the-agent with negative control (decoy)
- Proof-of-concept: `recipes/gstack/` + `stacks/gstack-time/` verified green end-to-end

## Core Value

You can compose a named stack (one harness + chosen recipes) and launch an isolated, authenticated
instance that exposes **exactly** the skills/commands/MCP/services it declares — nothing from the
host config — reproducibly, with podman as the only host dependency.

## Requirements

### Validated

<!-- Already shipped/working in the existing `container` tool; folds in as `transparent`. -->

- ✓ Host-mirror sandbox: bind-mount host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`), project, and host auth into an isolated container — existing (`container.sh`)
- ✓ Host-integration mount layer: 1Password SSH agent, GPG/YubiKey signing, `~/.ssh` (ro), git config (ro), egress firewall, project mount — existing (`container.sh` `start_new_container`)
- ✓ Installer + PATH symlink + image build/list/stop/remove/clean lifecycle — existing (`install.sh`, `container.sh`)
- ✓ `harnessed transparent` + `container` alias: host-mirror sandbox via the host-native harnessed engine (bash bootstrap + base/claude images, `podman build` on the host) — Phase 1
- ✓ `~/.claude.json` corruption fixed: per-instance copy-on-start (host whole-file blob never rw-bind-mounted) — Phase 1

### Active

<!-- v2.0 scope. Hypotheses until shipped and validated. -->

- [ ] **IMG-01**: Fat `harnessed-base` with all runtimes pre-installed (node@24, bun, rust, go, python, pnpm@11) — NO harness CLIs in base (harnesses move to per-agent images)
- [ ] **IMG-02**: `agents/` directory — `type:agent` recipes that build standalone cached harness images (`harnessed-claude`, `harnessed-omp`) via `FROM harnessed-base + one harness CLI`
- [ ] **IMG-03**: `harnessed-<stack>` derived image: `FROM harnessed-<agent>` + recipe Dockerfile bodies concatenated by the assembler; one per stack, built by the host
- [ ] **RCP-01**: Recipe is a `Dockerfile` + `recipe.yaml` (`harnesses:`, `mcp:`, `expect:`); `Dockerfile` runs the framework's own installer, parameterized by `--host ${HARNESS}`, pinned to a tag/SHA
- [ ] **RCP-02**: `harnesses:` field in `recipe.yaml` declares which harnesses the recipe's installer supports; assembler refuses unsupported compositions with a clean error
- [ ] **RCP-03**: `expect:` is a smoke-check subset (stable entries confirming the install landed, not a completeness oracle); assembled and passed to the capability test
- [ ] **ASM-01**: Assembler harness-compatibility check (recipe `harnesses:` vs stack `harness:`) before any Dockerfile emission
- [ ] **ASM-02**: Assembler pin validation — floating `--branch main` / unpinned package refs are a validation error; `git clone --branch <tag>` or exact version required
- [ ] **ASM-03**: Assembler emits `profiles/<stack>/Dockerfile.harnessed-<stack>` with `ARG HARNESS=<agent>` and concatenated recipe bodies; host runs `podman build --build-arg HARNESS=<agent>`
- [ ] **MNT-01**: Surgical profile mount — launcher mounts individual config files (`.mcp.json`, `settings.json`) not the whole `~/.claude/` dir; image-baked skills survive (no dir-replace)
- [ ] **SC-01**: Supply-chain gate on `harnessed build <stack>`: assembler rejects unpinned sources (ASM-02); osv-scanner V2 scans the derived image post-build; fail on high-severity
- [ ] **SC-02**: Nightly rescan timer rescans built stack images (existing systemd-timer pattern continues); residual known-limitation documented
- [ ] **TST-01**: Structured MCP probe: assert manifest's MCP servers connected via hatago `/servers` (deterministic, no model call)
- [ ] **TST-02**: Un-primed ask-the-agent skills/tools probe with negative control: a decoy entry mixed into the prompt; agent claimed-decoy-present → INVALID (priming detected), non-zero exit
- [ ] **TST-03**: Markdown capability report: ✓/✗ per MCP server (structured) and per `expect:` entry (agent); INVALID banner on priming detection
- [x] **DOC-01**: All narrative docs updated to new architecture — fat base, Dockerfile recipes, pinned sources, combined capability test; no "isolated"/"transparent" terminology remains — Validated in Phase 11: architecture-documentation

### Out of Scope

- Combining two harness systems via Docker `FROM` — `FROM` is linear inheritance, not a union operator; systems are combined at runtime in a pod (§6)
- More than one harness per stack — a stack targets exactly one harness, never two (§8)
- A second config canonical format — Claude Code format is the single source of truth; omp adapts out of it via bridge (§8)
- npm/npx for JavaScript installs — pnpm everywhere for supply-chain safety (§7)
- Assembler unit tests — testing internals couples to implementation; behavior is verified transitively through the running instance (§18)
- Requiring host Python/node/uv — podman/docker is the only host dependency (§15)
- Baking or committing credentials (Claude auth, scanner tokens, 1Password secrets) — referenced from host, injected as env only (§7, §16)
- Reinterpreting vendor framework installers — recipes run the framework's own `./setup`; the assembler does not parse skill trees or understand the framework's layout
- Version-controlling vendor skill data — the reproducibility unit is the pinned tag/SHA in the recipe, not a committed copy of the vendor's installed files
- Closing the pnpm-cooldown gap for vendor `./setup` scripts — a vendor installer shelling raw `npm install` bypasses our pnpm policy; documented known limitation, not a blocking issue (§8 supply-chain gate)
- `completeness oracle` capability tests — `expect:` is a smoke check (stable subset confirming install landed), not an enumeration of everything a framework ships

## Context

- **Existing repo:** `container.sh` (host-mirror sandbox), `Dockerfile`, `install.sh`,
  `egress-firewall.sh`, `Permissions.md`, `.env.schema.example`. The new tool ports and supersedes
  much of this; `container` becomes an alias.
- **Prior art to port** (from host): `~/.agents/bin/vendor-plugin` (plugin resolve/install),
  `~/.agents.20260603/bin/sync-plugin-links` (fan skills/commands into harness paths, conflict
  reporting), universal-hooks `run-hook.sh`/`lib-pi-adapter.sh` (per-runtime hook dispatch),
  `~/.config/dorothy/commands/nightly-updates` (supply-chain audit suite + systemd-timer pattern).
- **Failed prior approach:** merging a curated set into the host config (`~/.agents` +
  `sync-plugin-links` + universal-hooks) failed because a single shared host namespace can't hold
  every experiment at once (openbrain/hindsight collide, `settingSources` drift, vendored deps
  pollute `~`). The per-container merge is the fix.
- **Harness config layout grounded in real `~/.claude`:** credential is
  `~/.claude/.credentials.json` (OAuth); `~/.claude.json` is metadata + ~450 KB state, not auth —
  do not mount, generate a stub.
- **Design source of truth:** `docs/harnessed-design.md` — architecture decisions (§2–§9)
  confirmed; schemas/repo-layout/CLI (§10–§13) proposed; §14 items to verify during execution.
- **Bridge dependency:** `claude-hooks-bridge` lives at
  `~/Programming/AI/omp-extensions/claude-hooks-bridge`.

## Constraints

- **Tech stack**: Host bootstrap in dependency-free bash; all logic in a containerized
  `harnessed-tools` Python image (rich/textual + yq/jq + git + pnpm + scanners + varlock + op) — keep host deps to podman/docker only (§15)
- **Architecture**: Stacks composed at runtime in a podman pod, never via build-time `FROM` union (§3, §6)
- **Execution model**: the `harnessed-tools` container emits files only (Dockerfile + profile + launcher); the **host** runs `podman build` and the generated host-bash launcher runs the pod via host `podman` — no daemon-in-container, no API socket, no host-absolute-path footgun, host-native TTY (§15)
- **Canonical format**: Claude Code format is the single source of truth; other harnesses adapt out of it (§8)
- **Supply chain**: pnpm everywhere (no npm/npx); build-time scan gate fails on high-severity; credentials referenced from host, never baked/committed (§7)
- **Security/secrets**: auth and scanner/1Password secrets are env-only, never an image layer or repo file; varlock + 1Password are optional opt-in (§16)
- **Compatibility**: keep `container` working as an alias for muscle memory (§14, recommendation: keep)
- **Testing**: integration-only, behavior asserted through the running instance against the stack manifest as oracle; build harnessed itself in vertical slices (§18)
- **Docs**: each documentation section lands with the feature it documents — a feature isn't done until its docs exist (§17)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| One engine, two config modes (`transparent`/`isolated`) | Same base image/mounts/auth; differ only on config source — minimal surface, `transparent` = old `container` | ✓ transparent shipped (P1); isolated pending |
| Per-container merge, not host merge | Isolation removes the collision that killed the host-merge attempt | — Pending |
| Compose stacks at runtime in a podman pod | `FROM` can't union two sibling systems; runtime pod can | — Pending |
| hatago in the pod over HTTP (not stdio in harness container) | Keeps `npx`/`uvx` out of the harness container; one MCP endpoint | — Pending |
| Shared services are service-scoped, harness-independent | Lets `claude+hindsight` and `omp+hindsight` share one memory volume | — Pending |
| Claude Code format canonical; omp via bridge | Single source of truth, no re-authoring; one harness per stack | — Pending |
| Hand-authored recipes assembled ahead of time (not dynamic) | Reproducible, committed artifacts; "not dynamic" | — Pending |
| Split output: committed→mounted profile (files) + baked→images (MCP deps) | Editable/versioned extensions; clean/pinned host | — Pending |
| pnpm everywhere with managed supply-chain config | Quarantine new releases, deny lifecycle scripts, store integrity | — Pending |
| `harnessed-tools` is a file-emitting assembler; host runs podman build/run | Only host dep is podman/docker; avoids DooD (no socket, no host-path footgun, clean TTY) | ✓ host-native transparent shipped (P1) |
| Default persistent, `--fresh` to wipe | Accumulation is the value of memory systems; `--fresh` for clean-room runs | — Pending |
| Integration-only testing, manifest as oracle | Tests survive refactors; capability report doubles as user artifact | — Pending |
| varlock + 1Password optional (opt-in) | Works fully without it; copy `.env.schema.example` to turn on | — Pending |
| Bash launchers run under `set -euo pipefail`; fallible probes use `local var=$(…)` or `\|\| true` | A bare `var=$(pipeline)` aborts the launcher when the pipeline fails (e.g. YubiKey/jq probe with no match) — caught live in P1 | ✓ Good (P1 bugfix `a963a69`) |
| Recipes are Dockerfiles, not typed-YAML skill trees | "Run the framework's installer" — the assembler doesn't reinterpret the install/layout. Assembler does not parse SKILL.md files or discover skill trees. | — v2.0 |
| We version the recipe's tag, not the vendor's data | Pinned tag/SHA in recipe.yaml is the reproducibility unit; committed vendored skill trees were a mistake (required surveilling every install destination) | — v2.0 |
| Supply chain: pin + scan-the-image (not scan-vendored-deps) | Nothing is vendored; installer runs at build; gate = assembler rejects unpinned + osv-scanner V2 image scan + nightly rescan | — v2.0 |
| Harness is parameterized in recipe Dockerfiles (`--host ${HARNESS}`) | Recipe declares `harnesses:` it supports; assembler injects `ARG HARNESS` and refuses unsupported compositions with a clean error | — v2.0 |
| Capability test: two oracles, un-primed | Structured probe for MCP (deterministic); ask-the-agent for skills/tools with a negative control (decoy) to detect priming/sycophancy | — v2.0 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-23 — milestone v2.0 started (Recipe Architecture & Agent Rebuild). NOTE: the Active/Validated split from v1.0 was not fully migrated phase-by-phase — a full milestone review (`/gsd-complete-milestone`) should move v1.0 shipped items Active → Validated after v2.0 ships.*
`````

## File: docs/guides/recipe-authoring.md
`````markdown
# Authoring recipes

A **recipe** is a hand-authored integration definition for **one** capability bundle (an MCP server,
a set of skills, a vendored plugin, …). A **stack** composes a harness plus a chosen set of recipes
([stacks guide](stacks.md)). Recipes are assembled **ahead of time** into a committed, version-
controlled profile — nothing is resolved at container start (design §5, §11).

For the *why* (why recipes exist, why Claude-canonical is the single format, why pnpm), read
[docs/harnessed-design.md §5 & §11](../harnessed-design.md). This guide shows the *how* with worked
examples from this repo's `recipes/`.

## What a recipe is

A recipe lives at `recipes/<name>/recipe.yaml`. It can contribute to three things:

- **MCP layer** — server entries (under `mcp.servers`) merged into the stack's hatago config.
- **File-extension layer** — `skills` / `commands` (and `agents`/`hooks`/`rules` via plugins) in
  Claude-canonical form, fanned into harness-native profile paths.
- **Dockerfile body** — installation steps appended to the derived stack image; the primary way to
  install tooling, frameworks, or CLIs into the stack. The assembler concatenates Dockerfile bodies
  in recipe order to build the derived `harnessed-<stack>` image.

A recipe may have any combination of these, or (like `recipes/omp`, `recipes/opencode`, `recipes/gemini`,
`recipes/antigravity`, and `recipes/codex`) none — it can exist only to declare a runtime contract. Only the fields the recipe exercises are required; the assembler parses the rest
forward.

## The `recipe.yaml` schema

The typed model lives in [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) (`Recipe`,
`McpServer`, `FileExt`). Key fields:

```yaml
name: <recipe-name>            # required
description: <one-liner>        # optional
harnesses: [claude]             # optional — harnesses this recipe is compatible with (e.g. [claude],
                                # [claude, omp]). Omit to allow all harnesses. The assembler rejects
                                # composing a claude-only recipe onto an omp stack with a validation
                                # error before emitting any Dockerfile.
expect: [skill-name]            # optional — capabilities the Oracle 2 capability test must confirm
                                # present after a successful build; checked by `harnessed test`.

# --- MCP layer (optional) ---
mcp:
  servers:
    - name: <server>            # required
      command: <cmd>            # stdio servers only — hatago spawns this as a child (stdio→HTTP)
      args: [<arg>, ...]        # optional
      transport: stdio          # stdio (default) | http
      # network-native (transport: http) — instead of `command`, reference a URL or a service:
      url: <http-url>           # optional, direct URL
      service: <service-name>   # optional, references services/<name>/service.yaml (resolved to a URL)
      url_env: <ENV>            # optional, env injected into the instance
      env: {<k>: <v>}           # optional
      headers: {<k>: <v>}       # optional

# --- File-extension layer (optional) ---
skills:                         # standalone skill dirs shipped by this recipe
  - path: skills/<skill-name>   # relative to the recipe dir; leaf name = harness-native target
commands:                       # same shape as skills
  - path: commands/<cmd-name>
```

Notes:

- `transport` is **explicit** (design RESEARCH Pitfall B). A `stdio` server (with `command`) is run
  by hatago as a child and must be available inside the hatago image; the harness never speaks to
  this command directly. A network-native server (`transport: http`) is proxied by hatago by URL.
- The assembler **fans** each skill/command dir into the harness-native profile path
  (`.claude/skills/<leaf>`, `.claude/commands/<leaf>`) and **fails fast on name collision**
  (design §7).
- Forward-parsed fields (`plugins`, `deps`, `hooks`, `extensions`) are accepted but only exercised
  where relevant; see [`recipes/omp/recipe.yaml`](../../recipes/omp/recipe.yaml) for `extensions`.

If a recipe needs to install tooling into the stack image, it ships a `Dockerfile` alongside
`recipe.yaml`. The assembler concatenates the Dockerfile bodies of all recipes in the stack's recipe
order, prepends `FROM harnessed-${HARNESS}:latest`, and builds the derived `harnessed-<stack>`
image from the result. See "Worked example 3" for the full pattern.

## Worked example 1: the `time` recipe (stdio MCP + a standalone skill)

[`recipes/time/recipe.yaml`](../../recipes/time/recipe.yaml) is the tracer bullet — exactly one
light stdio MCP server and one standalone skill:

```yaml
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

- `command: uvx`, `args: [mcp-server-time]` — a light **Python** MCP server run via `uvx` (the uv
  runner; see *Supply-chain rules* below). hatago spawns `uvx mcp-server-time` as a child and wraps
  its stdio into the single HTTP endpoint the harness talks to.
- `transport: stdio` is explicit: the harness never runs `uvx` itself; it reaches hatago.
- `skills/time-helper` is a standalone skill dir shipped by this recipe; it lands at
  `.claude/skills/time-helper` in the assembled profile.

A stack that references it (`stacks/tracer-time`, `stacks/claude-multi`) builds + runs it via:

```bash
harnessed build tracer-time && harnessed tracer-time
harnessed test tracer-time      # capability report: ✓ time (mcp) connected, ✓ time-helper (skill) present
```

## Worked example 2: the `ping` recipe (a service reference, no command)

[`recipes/ping/recipe.yaml`](../../recipes/ping/recipe.yaml) is the other MCP shape — a
**network-native** server referenced by service, with no `command`:

```yaml
name: ping
description: Tracer shared service — a network-native ping MCP server.

mcp:
  servers:
    - name: ping
      service: ping
      transport: http
```

- No `command`: this is a **service reference**, not a stdio child. The assembler resolves
  `service: ping` → a hatago URL-proxy entry pointing at the running sidecar
  (`http://ping:8080/mcp`). hatago proxies it; the service runs as its own container on the shared
  network (design §3, §9).
- `transport: http` because the server is already network-native (Streamable HTTP).
- The sidecar itself is authored under [`services/ping/`](../../services/ping/) — see the
  [service-authoring guide](service-authoring.md).

Contrast: `time` (stdio child hatago must bake + spawn) vs `ping` (HTTP sidecar hatago proxies by
URL). Use stdio for light, dependency-free servers you want baked in; use a service for stateful or
shared systems that outlive any instance.

## Worked example 3: a Dockerfile recipe (installs a framework CLI)

[`recipes/gstack/`](../../recipes/gstack/) exercises the Phase 8 Dockerfile recipe model — a recipe
that installs tooling via a Dockerfile body, with no MCP server or standalone skill dir.

### recipe.yaml

```yaml
name: gstack
description: Installs the gstack tooling via its framework installer.
harnesses: [claude]
expect: [gstack-skill]
```

- `harnesses: [claude]` — this recipe is claude-only. Composing it onto an `omp` or `opencode`
  stack is a validation error; the assembler rejects the combination before emitting any Dockerfile.
- `expect: [gstack-skill]` — after a successful `harnessed build gstack-time`, the capability test
  (`harnessed test gstack-time`) must confirm that `gstack-skill` is present in the running
  instance. Use this field to declare the capabilities your Dockerfile install step is expected to
  deliver.

### Dockerfile

```dockerfile
# No FROM line — the assembler prepends `FROM harnessed-${HARNESS}:latest` when concatenating.
ARG HARNESS=claude

# "Run the framework's own installer" — let the framework install itself, pinned to an exact version.
RUN pnpm dlx @gstack/install@1.2.3 --host ${HARNESS}
```

Rules for recipe Dockerfiles:

- **No `FROM` line.** The assembler supplies `FROM harnessed-${HARNESS}:latest` as the header;
  adding your own `FROM` produces a malformed concatenated Dockerfile.
- **`ARG HARNESS=claude` at the top.** The `ARG` is stripped during concatenation but is required
  so standalone Docker builds can resolve `${HARNESS}` references in the body.
- **Pinned installs only.** Floating refs (`@latest`, `--branch main`, `--branch master`) are
  rejected by the assembler's pin validation (`PinValidationError`). Every downloadable resource
  must carry an exact version pin (e.g. `@1.2.3`, `--version 1.2.3`).

### "Run the framework's own installer" principle

Recipe Dockerfiles do not manually copy files, vendor deps, or reconstruct what a framework's
installer already knows how to do. Instead they invoke the framework's published installer at an
exact version:

```bash
pnpm dlx @framework/install@<version> --host ${HARNESS}
```

The `--host ${HARNESS}` flag lets the installer configure itself for the target harness (e.g. claude
vs omp). This keeps recipes thin: the recipe declares *what* to install and *at which version*; the
framework controls *how* it is installed.

### Pin discipline

`ARG` declarations are the standard way to express version pins in a recipe Dockerfile:

```dockerfile
ARG GSTACK_VERSION=1.2.3
RUN pnpm dlx @gstack/install@${GSTACK_VERSION} --host ${HARNESS}
```

The assembler validates that every downloadable resource has a pinned version. Floating refs
(`@latest`, `--branch main`) fail the build — `PinValidationError` is raised before any image
layer is written.

### Build-and-test lifecycle

```bash
harnessed build gstack-time   # assembles gstack + time recipes into harnessed-gstack-time image,
                               # runs osv-scanner + pip-audit supply-chain gate on derived image
harnessed gstack-time         # launch the stack (podman pod: harness + hatago)
harnessed test gstack-time    # capability report: ✓ gstack-skill (expect), ✓ time (mcp)
```

## Transports

| Transport | When | Notes |
| --- | --- | --- |
| **stdio** | light server hatago runs as a child | hatago wraps stdio→HTTP; bake the server into the hatago image via `pnpm dlx` (Node) / `uvx` (Python). The harness only sees hatago's HTTP endpoint. |
| **streamable-http** | a network-native server (your own service, or a remote) | One endpoint, `POST` + optional `GET`/SSE stream. Reference by `url:` or `service:`. |
| ~~SSE~~ | **deprecated** | SSE is deprecated in the current MCP spec (2025-06-18) and in Claude Code. Use **Streamable HTTP** for new servers. |

See the "What NOT to Use" table in [`CLAUDE.md`](../../CLAUDE.md).

## Supply-chain rules

Two hard rules, both enforced by the build ([design §7](../harnessed-design.md)):

1. **pnpm everywhere (no `npm`/`npx`).** Every JavaScript install — global, per-recipe, hatago's
   bundled servers — uses **pnpm**; `pnpm dlx` replaces `npx`. A managed supply-chain config applies
   `minimumReleaseAge` cooldowns and lifecycle-script default-deny. **Recipe validation** (part of
   `harnessed build`, BLD-03) flags any raw `npm`/`npx` in a recipe's scripts/deps and points at the
   pnpm equivalent — the build fails fast until you fix it.
2. **`uvx` for Python MCP servers.** Light Python servers (like `mcp-server-time`) run via `uvx`,
   the uv runner. Python dependencies declare `deps.python` (`pyproject.toml` → `uv venv` +
   `uv pip install -e .`, or `requirements.txt` → `uv pip install -r`).

`harnessed build` then scans recipe sources + dependencies with osv-scanner + pip-audit
(credential-free, always) and snyk/Socket.dev when a token is present — **failing on high-severity**
findings. See the [troubleshooting guide](troubleshooting.md) for scan-failure diagnostics.

## Adding a recipe to a stack

Author `recipes/<name>/recipe.yaml`, then reference it from a stack's `recipes:` list. See the
[stacks guide](stacks.md) for composition, scaffolding (`harnessed new`), and the full build → run →
test lifecycle.

## See also

- [docs/harnessed-design.md §5 & §11](../harnessed-design.md) — the *why* (composition unit, recipe schema, dependency model).
- [Stacks guide](stacks.md) — compose recipes into a stack.
- [Service-authoring guide](service-authoring.md) — author the `ping`-style sidecar a service-ref recipe points at.
- [`tools/harnessed/schema.py`](../../tools/harnessed/schema.py) — the typed `Recipe` / `McpServer` / `FileExt` models.
`````

## File: .planning/STATE.md
`````markdown
---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Recipe Architecture & Agent Rebuild
status: archived
last_updated: 2026-06-24T00:00:00.000Z
last_activity: 2026-06-24 -- Milestone v2.0 archived
progress:
  total_phases: 11
  completed_phases: 10
  total_plans: 14
  completed_plans: 14
  percent: 100
stopped_at: Milestone v2.0 archived — next milestone pending
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-14)

**Core value:** Compose a named stack and launch an isolated, authenticated instance that exposes exactly the skills/commands/MCP/services it declares — nothing from host config — reproducibly, podman the only host dependency.
**Current focus:** Milestone complete

## Current Position

Phase: 11
Plan: Not started
Phase: 08 — not yet started
Last activity: 2026-06-24

## Performance Metrics

**Velocity:**

- Total plans completed: 18
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 2 | 3 | - | - |
| 03 | 2 | - | - |
| 06 | 3 | - | - |
| 09 | 4 | - | - |
| 11 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- Init: One engine, two config modes (transparent/isolated); same base image/mounts/auth, differ only on config source
- Init: Compose stacks at runtime in a podman pod (FROM can't union sibling systems)
- Init: Single containerized Python tool image; host bash is a thin bootstrap (podman the only host dep)
- 05-02: resolve_secret_env is opt-in via a single `[ -f $HARNESSED_SCHEMA ]` test (no schema → varlock NEVER invoked, no behavior change); throwaway tools container with -e HOME=$CONTAINER_HOME so op resolves the mounted agent socket; resolved env reaches pod/build via mode-0600 --env-file (unlinked after launch). Quote-stripping sed needed because podman --env-file treats varlock's `KEY="value"` literally
- 05-02: auth_scanner drives snyk auth / socket login in a --rm -it tools container with -e HOME=$CONTAINER_HOME + ~/.config rw-mounted → token persists to host config (e.g. ~/.config/configstore/snyk.json), never an image layer (T-05-07)
- 05-02: mise shims break under the non-native HOME ($CONTAINER_HOME=/home/harnessed vs the tools image's native /home/tools); fixed by prepending /home/tools/.local/share/mise/installs/node/latest/bin to PATH inside the throwaway resolve/auth containers so the pnpm-global CLIs (varlock/snyk/socket) find node directly
- 05-02: SEC-01 + SEC-03 marked complete (code + INERTNESS + structure verified; live op resolution + interactive snyk auth = operator-confirmed — needs 1Password desktop app + browser flow)
- 05-03: run_image_scan_online is run_image_scan MINUS the --offline/--offline-vulnerabilities flags (the build-time gate stays offline-deterministic; the nightly is online-fresh — Pitfall 6). Keeps exit-128 investigate-branch + gate() HIGH check + ScanError. scan-image-online CLI subcommand exposes it
- 05-03: harnessed rescan iterates podman images --filter reference='harnessed-*', podman save each, scan-image-online per image in a throwaway tools container; safe exit capture (`|| img_rc=$?`) so a finding on one image sets rc=1 but does NOT abort scanning the rest (each image independent). Process-substitution loop so rc mutations escape the body
- 05-03: systemd USER units (rootless; not system units) — timer OnCalendar=daily + Persistent=true, service Type=oneshot ExecStart=%h/.local/bin/harnessed rescan. loginctl enable-linger $USER is a HARD prerequisite (Pitfall 5; Linger=no on host) — documented in unit comments + carried to 05-04 troubleshooting
- 05-03: SEC-04 marked complete (all 6 checkpoint steps verified real: rescan exit 0 on 6 images online; online-vs-offline contrast proves online sees Debian ecosystem the offline DB lacks; timer scheduled; service journal shows full path; build-time offline scan unchanged). Operational note: rebuild harnessed-tools after a tools/harnessed/*.py upgrade (ensure_tools_image is build-if-missing, not staleness-aware)

### Pending Todos

- Persist agy auth via in-pod keyring (`.planning/todos/pending/2026-06-21-persist-agy-auth-via-in-pod-keyring.md`) — antigravity OAuth persistence (Option 2; host-keyring mount rejected)

### Blockers/Concerns

- Phase 1: Verify `CLAUDE_CONFIG_DIR` relocates `.claude.json` (top-level file) vs only `.claude/` — choose copy-on-start otherwise (research flag)
- Phase 2: RESOLVED — the `.claude.json` stub field set (hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount, userID) is proven sufficient for a headless no-prompt boot (gate 2: `claude -p` returned success with no prompt). Pin as a snapshot fixture in a later phase.
- Phase 6 (SC-1 gap): verification found stale bridge-as-default `harnessed-net` assertions in files plan 06-01 did NOT cover (its `files_modified` listed 6; 06-RESEARCH Item B grep wasn't truly repo-wide). Confirmed against HEAD: `services/ping/server.py:6-7` (docstring contradicts its own :19-25 impl), `tools/harnessed/schema.py:128-131` (ServiceDef docstring — same B1+B4 pattern fixed in 3 peer files but left here), `CLAUDE.md:153` ("pod on harnessed-net" vs pasta default), plus `docs/codebase/INTEGRATIONS.md` (:100,:103,:112-113,:270). Root cause = planning under-inclusion, NOT executor error. Close via `/gsd-plan-phase 6 --gaps` → gap_closure plans → `/gsd-execute-phase 6 --gaps-only`.

## Deferred Items

Items acknowledged and carried forward from v2.0 milestone close (2026-06-24):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Phase | Phase 10: opencode/codex investigation + combined capability test (TST2-01/02/03, MNT2-07) | Not started | 2026-06-24 |
| Verification | Phase 08: 08-VERIFICATION.md human_needed (container-runtime tests) | human_needed | 2026-06-24 |
| Todo | apple-container named-network MCP endpoint investigation | Pending | 2026-06-24 |
| Todo | persist antigravity auth via in-pod keyring | Pending | 2026-06-24 |

## Session Continuity

Last session: 2026-06-24T11:53:03.969Z
Stopped at: Phase 09 context gathered
Resume file: .planning/phases/09-surgical-profile-mount-history-surfacing/09-CONTEXT.md
`````

## File: .planning/ROADMAP.md
`````markdown
# Roadmap: harnessed

## Overview

harnessed grows from this repo's `container` tool into a launcher for isolated, composable harness
stacks. The journey starts at the foundation (a host bash bootstrap/launcher + host `podman build`,
and the `transparent` stack that re-delivers `container` with zero regression), proves the
core value on one thin isolated tracer-bullet stack (assemble → run → assert green), hardens the
build with a supply-chain gate, then adds shared services, recipe breadth, and the full operable CLI,
and finishes with opt-in secrets and the gated documentation surface. Each phase delivers an
observable end-to-end capability (vertical-MVP mode).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Containerized Engine + Transparent Stack** - Host bash bootstrap/launcher + host `podman build`; `harnessed transparent`/`container` re-delivers the host-mirror sandbox (completed 2026-06-15)
- [x] **Phase 2: Isolated Tracer-Bullet Stack** - One harness + one MCP server + one skill, isolated and reproducible, asserted green by the capability test (completed 2026-06-15)
- [x] **Phase 3: Supply-Chain Gate + pnpm-Everywhere** - `harnessed build` vets every dependency before it is committed or baked (completed 2026-06-15)
- [x] **Phase 4: Shared Services + Recipe Breadth + Full CLI** - Concurrent service sidecars, more recipes, and the full operable command/lifecycle surface (completed 2026-06-16)
- [x] **Phase 5: Secrets, Hardening + Docs Completeness** - Opt-in varlock/1Password secrets, token-gated scanners, nightly re-scan, and the gated doc set (completed 2026-06-21; all 7 requirements VERIFIED live — HV-1..HV-4 all PASS, snyk browser auth landed via the --network=host callback fix)
- [x] **Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene** - Clear post-v1.0 tech debt: remove dead `harnessed-net` (podman network) code, correct stale comments, normalize `*-SUMMARY.md` frontmatter (planned; inserted 2026-06-21) (completed 2026-06-21)

## v2.0 Phases — ✅ SHIPPED 2026-06-24

> See [.planning/milestones/v2.0-ROADMAP.md](.planning/milestones/v2.0-ROADMAP.md) for full phase details and milestone summary.

- [x] **Phase 7: Fat Base + Agent Images** - Fat harnessed-base (all runtimes, no harness CLIs); agents/ directory with cached harnessed-claude/omp images (completed 2026-06-23)
- [x] **Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate** - Recipes are Dockerfiles; assembler emits harnessed-<stack>; pin validation + osv-scanner V2 gate (completed 2026-06-23)
- [x] **Phase 9: Surgical Profile Mount + History Surfacing** - Mount only .mcp.json + settings.json; image-baked skills survive; per-harness history via YAML manifests (completed 2026-06-24)
- [⏭] **Phase 10: opencode/codex Investigation + Combined Capability Test** - Deferred: opencode/codex history layouts + two-oracle capability test (TST2-01/02/03, MNT2-07)
- [x] **Phase 11: Architecture Documentation** - All narrative docs updated to new architecture; "isolated"/"transparent" removed (completed 2026-06-24)

## Phase Details

### Phase 1: Containerized Engine + Transparent Stack

**Goal**: Stand up the dependency-free `harnessed` bash bootstrap, build the base/claude images via host `podman build`, and deliver the `transparent` stack (= today's `container`, host-mirror) as a host launcher with the `.claude.json` safety fix and zero behavioral regression. (No daemon-in-container — the `harnessed-tools` assembler arrives in Phase 2.)
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: ENG-01, ENG-02, ENG-03, MODE-01, MODE-02, AUTH-01, MNT-01, MNT-02, MNT-03
**Success Criteria** (what must be TRUE):

  1. Running `harnessed transparent` (and `container`) in a project opens an interactive harness with the host config mounted live and the project mounted
  2. The instance has a working SSH agent, GPG/YubiKey commit signing, and the egress firewall (the shared host-integration layer)
  3. On a machine with only podman installed, the first run builds the images and launches — no host Python/node/uv required
  4. A run never corrupts the host `~/.claude.json` (per-instance copy or `CLAUDE_CONFIG_DIR` relocation, verified)

**Plans**: 3 plans

Plans:

- [x] 01-01: `harnessed` bash bootstrap (detect runtime, ensure images) + base/claude image lineage (`/home/harnessed` home) built via host `podman build`
- [x] 01-02: §4a host-integration mount layer (auth/SSH/GPG/YubiKey/git/machine-id) + project mount + egress firewall (host launcher building blocks)
- [x] 01-03: `transparent` host launcher (live host config) + `container` alias + `~/.claude.json` copy-on-start safety

### Phase 2: Isolated Tracer-Bullet Stack

**Goal**: Prove the core value on the smallest end-to-end isolated slice — one harness + one MCP server + one skill — via recipe/stack schema, the build-time assembler, isolated auth seeding, runtime pod composition with hatago, and the capability test/report.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: MODE-03, AUTH-02, RCP-01, RCP-02, RCP-03, RCP-04, MCP-01, MCP-02, MCP-03, TST-01, TST-02
**Success Criteria** (what must be TRUE):

  1. `harnessed build <stack>` assembles a one-harness/one-MCP-server/one-skill recipe into a committed `profiles/<stack>/` tree + baked images, failing fast on a name collision
  2. `harnessed <stack> --fresh` launches an isolated pod (harness + hatago) that boots headlessly with no onboarding/login prompt
  3. The instance exposes exactly the declared MCP server and skill, reached through hatago's single Streamable-HTTP endpoint
  4. The per-stack capability test passes and renders a markdown report showing the declared capabilities present

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 02-01: Recipe + stack schema and the build-time assembler (vendor + sync-links fan with fail-fast collisions + hook wiring + hatago config merge)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02: Isolated auth seeding (`.credentials.json` ro + generated `.claude.json` stub, headless no-prompt test) + runtime pod composition (harness + hatago on harnessed-net)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03: Per-stack capability test + `rich` markdown capability report

### Phase 3: Supply-Chain Gate + pnpm-Everywhere

**Goal**: As a stack author, I want to build stacks knowing `harnessed build` enforces pnpm-everywhere managed config and a credential-free HIGH-severity scan gate, so that no dependency with a high-severity vulnerability is committed or baked into an image.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: BLD-01, BLD-02, BLD-03
**Success Criteria** (what must be TRUE):

  1. `harnessed build` fails when a vendored dependency has a high-severity vulnerability (osv-scanner / pip-audit)
  2. All JavaScript installs go through pnpm with the managed supply-chain config (`minimumReleaseAge`, lifecycle default-deny, store integrity) active
  3. A recipe using raw `npm`/`npx` is flagged by validation with the pnpm equivalent

**Plans**: 2 plans

Plans:

- [x] 03-01: pnpm-everywhere managed config (BLD-01) — ship lib/pnpm/config.yaml, pin pnpm@11, route mise through pnpm, COPY config into base/hatago/tools/legacy images; correct design §7 + CLAUDE.md stale claims
- [x] 03-02: credential-free scan gate (BLD-02) + raw npm/npx recipe lint (BLD-03) — osv-scanner offline DB + pip-audit with a CVSS>=HIGH Python gate wired into build_stack (scoped source scan + host image scan); validate_no_raw_npm in the assembler fail-fast path

### Phase 4: Shared Services + Recipe Breadth + Full CLI

**Goal**: As a stack operator, I want to run concurrent harness instances that share service-scoped sidecars and operate the full stack, instance, and session lifecycle through the `harnessed` CLI, so that multiple instances can run together over a shared network, I can add more recipes to a stack, and every lifecycle action works predictably by name with default persistence and clean-room `--fresh` runs.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: SVC-01, SVC-02, SVC-03, STA-01, STA-02, CLI-01, CLI-02, CLI-03, HRN-01
**Success Criteria** (what must be TRUE):

  1. `harnessed svc up <service>` starts a service-scoped shared sidecar that two concurrent instances attach to over `harnessed-net`
  2. A second recipe added to a stack is exposed by the running instance and verified by its own capability test
  3. `harnessed list|stop|rm`, `new`, and `install`/`uninstall` shims operate stacks and instances by name
  4. Stacks persist by default and `--fresh` yields a clean-room run; harness session history persists host-side with a legible slug
  5. An `omp` stack runs the same Claude-canonical recipes via `claude-hooks-bridge` + pi-adapter

**Plans**: 4 plans (3 planned + 1 gap-closure)

Plans:

- [x] 04-01: Shared service sidecars (image/volume/lifecycle) + `svc up/down/list` + concurrent attach over harnessed-net
- [x] 04-02: State persistence + `--fresh` + full CLI (`list`/`stop`/`rm`/`new`/`install`/`uninstall` shims)
- [x] 04-03: omp harness support via bridge + a second recipe with its own capability test
- [x] 04-04: UAT gap closure — bare `harnessed` shows help (gap 6B) + legible path-based state-dir slug (gap 6)

### Phase 5: Secrets, Hardening + Docs Completeness

**Goal**: Land the perimeter/policy and the gated documentation surface — opt-in varlock/1Password secrets, token-gated scanners, the auth command, a nightly re-scan timer, and the full doc set.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, DOC-01, DOC-02, DOC-03
**Success Criteria** (what must be TRUE):

  1. With a `.env.schema` present, secrets resolve from 1Password and reach the build/instance as env only; absent, varlock is never invoked
  2. `harnessed build` runs token-gated scanners (snyk/Socket.dev) when a token is present and warns-and-skips otherwise without prompting
  3. `harnessed auth snyk|socket` persists a token to host config (never an image layer), and a nightly timer re-scans installed images for new CVEs
  4. README + recipe/stack guides + secrets/service/troubleshooting docs exist and match shipped behavior

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 05-01-PLAN.md — Scanner CLIs baked into tools image (Node+varlock+op+snyk+socket) + token-gated snyk/socket invokers in scan.py + build_stack token forwarding (SEC-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 05-02-PLAN.md — Opt-in varlock/1Password secrets (resolve_secret_env + --env-file to pod) + `harnessed auth snyk|socket` + docs/guides/secrets.md (SEC-01, SEC-03, DOC-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 05-03-PLAN.md — Nightly re-scan timer: scan-image-online + `harnessed rescan` + systemd user-timer units (SEC-04)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 05-04-PLAN.md — Documentation surface: README + recipe-authoring/stacks/service-authoring/troubleshooting guides + AGENTS.md reconciliation (DOC-01, DOC-02, DOC-03)

### Phase 6: Address tech debt: dead harnessed-net code + stale comments + SUMMARY frontmatter hygiene

**Goal**: Clear accumulated tech debt after the v1.0 milestone — remove dead `harnessed-net` (podman network) code, correct stale comments across code and docs that no longer match shipped behavior, and normalize the `*-SUMMARY.md` frontmatter.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: _(pending planning)_
**Success Criteria** (what must be TRUE):

  1. No dead `harnessed-net` code remains — every reference is live and reachable, or removed
  2. Stale comments (code + docs) that contradict shipped behavior are corrected
  3. Every phase `*-SUMMARY.md` carries consistent, well-formed frontmatter

**Plans**: _(pending planning — phase inserted, not yet planned)_

Plans:

- _(to be defined during planning)_

---

## v2.0 Phase Details

### Phase 7: Fat Base + Agent Images

**Goal**: Rebuild `harnessed-base` as a fat toolchain image (all runtimes pre-installed, no harness CLIs) and create the `agents/` directory with standalone cached images for the claude and omp harness CLIs.
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: IMG-01, IMG-02
**Success Criteria** (what must be TRUE):

  1. `harnessed-base` has bun, rust, go, node@24, python, pnpm@11 on PATH (`podman run harnessed-base mise ls` confirms); does NOT have claude, omp, codex, or gemini CLIs (IMG-01 complete)
  2. `harnessed-claude` builds `FROM harnessed-base` and passes `claude --version` inside the container without re-downloading runtimes
  3. `harnessed-omp` builds `FROM harnessed-base` and passes `omp --version` inside the container
  4. `harnessed build` (bare, no stack argument) produces `harnessed-base`, `harnessed-claude`, and `harnessed-hatago`; `harnessed-omp` is lazy-built on first omp stack launch (HRN-01 contract)

**Plans**: 2 plans
Plans:

- [x] 07-01-PLAN.md — Rebuild Dockerfile.harnessed-base: node@24, bun, rust, go; strip harness CLIs (IMG-01)
- [x] 07-02-PLAN.md — agents/ directory (claude + omp agent.yaml) + build_images() wiring for bare build (IMG-02)

### Phase 8: Dockerfile Recipe Model + Assembler + Supply-Chain Gate

**Goal**: Replace the typed-YAML recipe model with a Dockerfile-based model where recipes run frameworks' own installers; update the assembler to perform harness-compat checks, pin validation, and Dockerfile body concatenation that emits a derived `harnessed-<stack>` image; gate every derived build on pin validation and an osv-scanner V2 image scan.
**Depends on**: Phase 7
**Requirements**: RCP2-01, RCP2-02, RCP2-03, ASM-01, ASM-02, ASM-03, IMG-03, SC-01, SC-02, SC-03, SC-04
**Success Criteria** (what must be TRUE):

  1. `harnessed build gstack-time` emits `profiles/gstack-time/Dockerfile.harnessed-gstack-time` with `ARG HARNESS=claude` and concatenated recipe bodies, then builds the derived image `harnessed-gstack-time`
  2. Composing a claude-only recipe (e.g. gstack) onto an omp stack produces a clean validation error before any Dockerfile is emitted or build step runs
  3. A recipe Dockerfile with a floating `--branch main` ref is rejected by the assembler with a pin-validation error; a pinned tag/SHA passes cleanly
  4. `harnessed build gstack-time` scans the derived image with osv-scanner V2 and fails the build on HIGH-severity CVEs; the nightly rescan timer covers `harnessed-<stack>` images; snyk/socket container scans run when tokens are present and warn-and-skip (without prompting) when absent

**Plans**: 3 plans

Plans:
**Wave 1** *(parallel)*

- [x] 08-01-PLAN.md — Python assembler layer: schema (harnesses/expect/validators), emit (write_derived_dockerfile), assemble wiring, snyk container scan (RCP2-01..03, ASM-01..03, SC-03)
- [x] 08-02-PLAN.md — Test artifacts: gstack recipe, gstack-time stack, rejection fixtures (RCP2-01..03, ASM-01..02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-03-PLAN.md — Build pipeline: build_stack() IMG-03+SC-01+SC-03+SC-04 + Phase 8 UAT suite (IMG-03, SC-01..04)

### Phase 9: Surgical Profile Mount + History Surfacing

**Goal**: Stop mounting the whole `~/.claude/` profile directory; mount only individual config files (`.mcp.json`, `settings.json`, and per-harness equivalents) so image-baked recipe skills survive; surface per-harness project history for claude, omp, and antigravity back to the host via data-driven mount manifests.
**Depends on**: Phase 8
**Requirements**: MNT2-01, MNT2-02, MNT2-03, MNT2-04, MNT2-05, MNT2-06
**Success Criteria** (what must be TRUE):

  1. A running `gstack-time` instance shows gstack skills loaded — recipe-installed skills are visible because the profile dir-mount no longer overwrites the image's `~/.claude/skills/`
  2. `profiles/gstack-time/` contains only `.mcp.json` and `settings.json`; no `.claude/` directory tree is committed to the profile
  3. After a session, new claude project history entries appear on the host at `~/.claude/projects/<slug>/` without modifying the host `~/.claude.json` or credentials
  4. After a session, omp session history appears on the host at `~/.omp/agent/sessions/<slug>/` without touching `agent.db` (which co-locates auth credentials)
  5. After a session, antigravity conversation history appears on the host at `~/.gemini/antigravity-cli/conversations/` without touching the OAuth token or `~/.gemini/` settings proper
  6. Each harness's mount and teardown set is encoded in a structured per-harness manifest file — changing a path is a one-line manifest edit, not a search-and-replace through launcher code

**Plans**: 4 plans

Plans:
**Wave 1** *(parallel)*

- [x] 09-01-PLAN.md — YAML mount manifests (6 files) + harnessed-manifest-mounts.sh helper (MNT2-06, MNT2-03/04/05)
- [x] 09-02-PLAN.md — Python assembler refactor: emit.py + assemble.py fan-out removal (MNT2-01 assembler side)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 09-03-PLAN.md — Launcher surgery: harnessed-isolated.sh guard + copy-mount removal + workdir/mcp_cfg fix (MNT2-01/02)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 09-04-PLAN.md — Phase 9 UAT suite (MNT2-01 through MNT2-06 smoke + integration tests)

### Phase 10: opencode/codex Investigation + Combined Capability Test

**Goal**: Investigate opencode and codex home-folder history layouts to produce classified path inventories and mount manifests (unblocking future stack support); replace the v1 capability test with the two-oracle approach — a deterministic structured MCP probe plus an un-primed ask-the-agent probe with a negative control that catches sycophantic priming.
**Depends on**: Phase 9
**Requirements**: MNT2-07, TST2-01, TST2-02, TST2-03
**Success Criteria** (what must be TRUE):

  1. `docs/research/home-folder-opencode-requirements.md` and `docs/research/home-folder-codex-requirements.md` exist with classified path inventories (history / config / cache / auth) and proposed mount manifests following the cross-harness invariants
  2. `harnessed test gstack-time` confirms the `time` MCP server is connected via hatago without making a model call (structured MCP probe passes deterministically)
  3. `harnessed test gstack-time` passes the agent probe: gstack skills confirmed present; the decoy capability is in `"missing"` (agent correctly reports it absent)
  4. A simulated test run where the agent claims the decoy present exits non-zero with status INVALID — distinct from a capability-failure non-zero exit — and the capability report shows the INVALID banner
  5. `profiles/gstack-time/capability-report.md` is written after every test run showing ✓/✗ per MCP server and per `expect:` entry, plus the INVALID banner when priming is detected

**Plans**: TBD

### Phase 11: Architecture Documentation

**Goal**: Update all narrative docs to describe the new architecture — 3-layer image lineage, Dockerfile recipe model, pinned sources, surgical profile mounts, combined capability test — and remove any remaining stale or obsolete terminology.
**Depends on**: Phase 10
**Requirements**: DOC2-01
**Success Criteria** (what must be TRUE):

  1. README describes the 3-layer image lineage (base → agent → stack), the Dockerfile + recipe.yaml recipe model, and a working quickstart that builds a stack and runs the capability test
  2. `docs/harnessed-design.md` §7 describes recipe = Dockerfile (not typed-YAML fields), supply chain = pin sources + scan the derived image (not scan vendored deps); §18 describes the two-oracle capability test with the negative control
  3. The recipe-authoring guide shows a complete worked example: `harnesses:`, `expect:` smoke check, pinned `git clone`, `--host ${HARNESS}`, and the "run the framework's installer" principle
  4. `rg -r "isolated|transparent" docs/ README.md CLAUDE.md AGENTS.md` returns no narrative usage of those terms in the updated docs

**Plans**: 4 plans

Plans:
**Wave 1** *(all parallel — no shared files)*

- [x] 11-01-PLAN.md — README 3-layer image lineage + quickstart capability test + CLAUDE.md/AGENTS.md narrative cleanup
- [x] 11-02-PLAN.md — docs/harnessed-design.md §7 (Dockerfile recipe model) + §18 (two-oracle capability test)
- [x] 11-03-PLAN.md — docs/guides/recipe-authoring.md Dockerfile recipe model + harnesses:/expect: worked example
- [x] 11-04-PLAN.md — docs/guides/troubleshooting.md + service-authoring.md + secrets.md narrative cleanup

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Containerized Engine + Transparent Stack | 3/3 | Complete   | 2026-06-15 |
| 2. Isolated Tracer-Bullet Stack | 3/3 | Complete    | 2026-06-15 |
| 3. Supply-Chain Gate + pnpm-Everywhere | 2/2 | Complete    | 2026-06-16 |
| 4. Shared Services + Recipe Breadth + Full CLI | 4/4 | Complete   | 2026-06-17 |
| 5. Secrets, Hardening + Docs Completeness | 4/4 | Complete   | 2026-06-21 |
| 6. Address tech debt: harnessed-net code, stale comments, SUMMARY frontmatter | 3/3 | Complete    | 2026-06-21 |
| 7. Fat Base + Agent Images | 3/3 | Complete   | 2026-06-23 |
| 8. Dockerfile Recipe Model + Assembler + Supply-Chain Gate | 3/3 | Complete   | 2026-06-23 |
| 9. Surgical Profile Mount + History Surfacing | 4/4 | Complete    | 2026-06-24 |
| 10. opencode/codex Investigation + Combined Capability Test | 0/TBD | Not started | - |
| 11. Architecture Documentation | 4/4 | Complete    | 2026-06-24 |
`````
