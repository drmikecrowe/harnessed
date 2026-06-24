# Mission

You are a senior software architect conducting a comprehensive review of the **`harnessed`** project — a bash + Python tool that launches isolated, composable AI-coding-harness stacks (Claude Code, omp, opencode, gemini, antigravity, codex) as podman pods with an MCP hub (hatago) and optional shared services.

Your single deliverable: **a comprehensive remediation plan** that gets the project's code, documentation, and architecture "under control." This may culminate in a redesign, or it may be incremental cleanup — **you decide based on the evidence**, not on any presumption.

# Inputs

Two consolidated files (Repomix exports of the repo):
- **`all-documentation.md`** — every documentation / policy / planning markdown file merged into one document.  These will not be in as good a shape as the source files below. However, they are attempting to track where we're trying to go.  
- **`all-source-code.json`** — every source file as structured JSON (top-level keys: `fileSummary`, `directoryStructure`, `files[]`). Treat these as the source of truth for *what currently exists*. 

Cross-check claims against each other; where the two disagree with each other or with reality, that disagreement is itself a finding.

# What harnessed is (essential context)

- **One executable, `harnessed`** (host bash) plus a **Python assembler** (`tools/harnessed/`: `schema.py`, `assemble.py`, `emit.py`, `scan.py`). The assembler *emits files only* (Dockerfiles + profiles); the host runs `podman build` / `run`. No daemon-in-container, no Docker-out-of-Docker.
- **Architecture in two tiers:** the **bash tier** orchestrates podman (launch pods, mount config, attach the harness); the **Python tier** owns structured logic (recipe/stack schema, assembly, supply-chain scanning, the capability test).
- **`stacks/<name>/stack.yaml`** = authored input (one harness + recipes + services). **`profiles/<name>/`** = generated output (`.mcp.json`, `settings.json`, `hatago.config.json`, `Dockerfile.harnessed-<stack>`, skills/) that the launcher mounts into the container.
- **11 development phases** have shipped (v1.0 + v2.0 milestones). Phases 1–9 and 11 are complete; Phase 10 (opencode/codex history investigation + combined capability test) is not started.

For concrete examples of what to look for, see the docs/RECIPE-STRESS-TEST.md -- this illustrates repos that will become recipes.  These will be used to verify that the assembler is correctly emitting the expected Dockerfiles and profiles (and will be used by the end users).  All documentation and source code will drive to supporting these recipes in production.

# Known issues to verify and expand (NOT exhaustive)

These were surfaced in a prior review session. **Treat them as a starting checklist — confirm each against the files, then go beyond them.** Do not limit your review to this list.

**1. A removed feature ("transparent" mode) still ghosts across the docs.** Transparent mode was deleted from the code (commit `9a4ae2c`: `lib/harnessed-transparent.sh`, `lib/harnessed-claude-config.sh`, `stacks/transparent/stack.yaml`, and the `container` alias are all gone; the launcher now unconditionally calls `harnessed_isolated`). But the documentation was never fully swept:
   - `README.md` still presents transparent as a co-equal mode, including a **broken quickstart** (`harnessed transparent` now errors "Unknown stack: transparent"; the `container` binary no longer exists).
   - `docs/harnessed-design.md` §1–§4 still describe the "two config modes" transparent/isolated split.
   - The entire `docs/codebase/` auto-generated map (ARCHITECTURE, CONVENTIONS, STACK, STRUCTURE, INTEGRATIONS, TESTING, CONCERNS) references the deleted files and the transparent dispatch — it was last regenerated 2026-06-22 and never refreshed.
   - Phase 11 ("Architecture Documentation") partially cleaned the guides (`docs/guides/*`) but missed README, the design doc, and the codebase map.
   → *Quantify every stale reference; propose a cleanup/regeneration strategy that won't rot again next phase.*

**2. Generated build output (`profiles/`) was committed and is now stale/broken.** `profiles/<stack>/` is the assembler's output and the launcher's runtime mount source (the is-built guard is `[ -f "$profile_dir/.mcp.json" ]` at the profile *root*). All 8 *tracked* profiles predate Phase 9 and have the old shape (`.mcp.json` inside `.claude/`, not at the root) — **so every committed profile fails the current guard and forces a rebuild anyway.** A gitignore + untrack was decided. The deeper question: **where should generated profiles live?** For a user who installs via `git clone` (the actual install model), generated output accumulating inside the cloned source tree is a smell — the install location should contain only immutable shipped source. Runtime state already routes to `$XDG_STATE_HOME/harnessed/`; generated build output arguably belongs in `$XDG_DATA_HOME` / `$XDG_CACHE_HOME`.
   → *Decide the profile lifecycle: in-tree-ignored vs user-space, and design the path resolution accordingly.*

**3. Path & state resolution is scattered with no single source of truth.** `profile_dir`, per-instance state dirs, and instance naming are string-concatenated across 5+ sites (`lib/harnessed-isolated.sh`, `tools/harnessed/emit.py`, `lib/harnessed-manifest-mounts.sh`, the capability-test path in `harnessed`, the `--root` fixture logic). Moving the profile location (item 2) threads through all of them.
   → *Design a single source of truth for all path/state resolution.*

**4. Architectural strain in the bash launcher — possibly outgrowing bash.** The launcher is accumulating config/resolution/state logic that fights bash's lack of modules, types, and centralization. Symptoms: YAML parsing via `sed`/`grep` in the launcher (flagged as fragile — breaks on quoted values; increasingly shelled out to `yq`); no unit-test layer for launch logic; path resolution that can't be centralized cleanly. The core orchestration (`podman build`/`run`/`exec`/pod composition) is still genuinely shell-native and clean, and the zero-dependency bootstrap ("podman is the only host dependency") is a real product property.
   → *Assess honestly: is the bash tier still the right tool, or has the boundary moved? Weigh (A) re-drawing the boundary — centralize resolution, keep bash orchestrating; (B) migrating the launcher to Python (unify with the existing assembler); (C) a compiled rewrite (Go/Rust). Give a clear, evidence-based recommendation. Do NOT default to "rewrite" unless the evidence earns it, and do NOT avoid one out of inertia.*

**5. Systemic documentation drift.** Beyond transparent (item 1): `docs/comprehensive-development-plan.md` claims "Phase 9/10 are unbuilt" (both effectively shipped); `docs/recipe-adoption-gap-analysis.md` references a `cp -a` whole-dir mount that Phase 9 removed; there are untracked planning/research docs under `docs/` and `docs/research/`. The `docs/codebase/` map appears to be a one-shot generation with no regeneration step wired into the build.
   → *Propose a doc-accuracy mechanism (regeneration step, ownership model, or a structural change) so docs stop rotting each phase.*

**6. Anything else you find.** Code that contradicts docs, dead code, duplicated conventions, untracked files that should be tracked (or vice versa), schema/validator gaps, untested branches, security/correctness issues, etc. Be exhaustive.

# Deliverable: the comprehensive plan

Produce a single plan document structured as:

1. **Executive summary** — the state of the project in 3–5 sentences, and your top-level verdict (healthy-with-cleanup / needs-significant-work / needs-redesign).
2. **Findings** — every issue, each with: severity (blocker / high / medium / low), evidence (file:line or doc section), impact, and why it matters. Group by theme (doc accuracy, build-artifact lifecycle, architecture, code quality, …).
3. **Recommendations** — for each finding or theme, the proposed fix. For the architecture question (item 4), a decisive recommendation with rationale, plus the alternatives you rejected and why.
4. **Sequenced work plan** — ordered phases/waves with dependencies, so it is executable as-is. Distinguish **stop-the-bleeding** (quick wins that prevent active harm — e.g. the broken README quickstart) from **structural** (the profile-location + resolution + architecture work).
5. **Risk & blast-radius notes** — for the structural changes, exactly what they touch and what could break.
6. **Open decisions** — anything you cannot resolve from the files alone and would need a human to decide, stated explicitly with the tradeoff.

# Rules

- **Evidence-grounded.** Every claim cites a file/section. Mark anything you infer-but-cannot-confirm as `[INFERENCE]`.
- **Review everything — do not just confirm the seed list.** The six items above are a floor, not a ceiling.
- **Decide redesign-or-not from the evidence.** Show the reasoning; justify any change to a sound existing decision.
- **Plan only — do not implement or edit files.** Your output is the plan.
- **Respect the project's sound existing decisions** (the Python assembler tier, the emit-only / host-builds split, podman-first, pnpm-everywhere). Propose changing one only with strong justification.
