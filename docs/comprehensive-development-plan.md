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
