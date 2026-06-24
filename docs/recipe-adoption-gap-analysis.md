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
