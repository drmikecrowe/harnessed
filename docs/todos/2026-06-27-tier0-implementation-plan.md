# TIER 0 implementation plan — CI + settings.json merge

**Date:** 2026-06-27 · **Source:** plan-eng-review of
[2026-06-27-roadmap-triage.md](2026-06-27-roadmap-triage.md) TIER 0, with cross-model outside voice.
**Decisions locked** (interactive review). Build in the order below.

Sequencing: **CI lands first**, then the settings.json fix lands as a PR gated by green CI.
Two independent lanes — see worktree strategy at the bottom.

---

## Item B (lands first) — test CI

**Goal.** Gate the 99 already-passing tests on every PR before touching launch code.

**Shape (decided):**
- New workflow `.github/workflows/test.yml`.
- Triggers: `pull_request` + `push` to `main`. **No `paths:` filter** — a path filter on a
  *required* check deadlocks PRs that don't touch the filtered paths (they never report the
  check, can never merge). Suite is small + hermetic, so always-run is cheap.
- Python **3.12** only (`requires-python = ">=3.12"`; no matrix needed yet).
- Setup via `astral-sh/setup-uv`; run `uv run --extra dev pytest`.
- **Hermetic** — no podman in CI. The 4 integration tests are gated on `HARNESSED_PODMAN=1`
  (`tests/test_recipes_integration.py:85`) and skip; 99 run.
- **No coverage fail-under gate** yet (add a threshold once there's a measured baseline).

**Manual prerequisite (NOT in the YAML — must be done in repo settings):** enable the workflow
as a **required status check** in branch protection for `main`. Until that's set, "Item A gated
by green CI" is aspirational. Flagged by the outside voice.

**Skeleton:**
```yaml
name: tests
on:
  pull_request:
  push:
    branches: [main]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv run --extra dev pytest
```

---

## Item A (lands second) — settings.json must be the post-install artifact, not a stub

**The bug.** `emit.write_settings_json` (`emit.py:104`, at *assemble* time, before the image
exists) writes a stub `{"permissions":{"allow":["mcp__hatago"]}}` to `profile/settings.json`.
The launcher bind-mounts that stub `:ro` over `~/.claude/settings.json` (`launcher.py:408-411`),
**masking** whatever a recipe/base installer wrote into the image's `~/.claude/settings.json`
(hooks, permissions). Recipes like context-mode / agentmemory / hyperpowers silently lose their
settings at runtime.

**Data flow (fixed):**
```
assemble.py:104  write_settings_json → {allow:[hatago]}   (floor / no-bake fallback)
      │
      ▼
[podman build derived image]   ← image now EXISTS; installer-written settings.json is real
      │
      ▼
launcher.py post-build (runs UNCONDITIONALLY, like _surface_scan_report:248):
   create cid from derived image
   cp  <cid>:~/.claude/settings.json  → temp
   merged = emit.merge_settings(baked=temp, required={allow:[hatago]} if servers else {})
   write merged → profile/settings.json     (overwrites the assemble-time stub)
      │
      ▼
mount profile/settings.json :ro  =  baked ⊕ hatago grant   ✓
```

### Decided design

1. **Gate (revised from "fold behind `_merge_baked_extensions`"):** the settings extraction runs
   **unconditionally** post-build — NOT behind the recipe-Dockerfile gate (`launcher.py:244`).
   Reason: settings.json can be baked by the agent **base** image with no recipe Dockerfile;
   gating on recipe-bake would leave those stacks stomped. Share the container with the existing
   unconditional `_surface_scan_report` pass (or ungate); driven by "did `cp` yield a file", not
   by recipe-bake.

2. **`emit.merge_settings(baked, required) -> dict` — a surgical patch, NOT a generic deep-merge.**
   Start from the baked file (authoritative) and apply only harnessed's required edit:
   - union + dedup `mcp__hatago` into `permissions.allow` (preserve order, no duplicate),
   - **deny conflict:** if `mcp__hatago` is in `permissions.deny`, the **required grant wins** —
     strip it from `deny`, ensure it's in `allow`, and **warn** (one line, so the recipe author
     sees the override). hatago is the only MCP path, so the grant is load-bearing.
   - touch **nothing else** — every other key (hooks, other permissions) is carried through
     verbatim. This avoids array-key corruption (`hooks`, `deny`) that a naive nested deep-merge
     would risk. Document "only `permissions.allow` is unioned" in the docstring.

3. **Fallback / error handling — distinguish the two failure modes** (outside voice):
   - `cp` exits non-zero OR no baked file → return the required stub (the existing floor). Silent.
   - `cp` succeeds but JSON parse fails → return the stub **+ warn** (a recipe wrote broken JSON;
     don't crash `harnessed build`).
   - `required` empty (`servers == []`) → no grant injected (replicate the `if servers` condition
     from `emit.py:68`).

4. **Ordering is guaranteed, state it:** `build()` runs assemble → build → post-build
   sequentially, so the post-build merge always overwrites the assemble-time stub. Add a comment
   pinning that invariant.

5. **Keep `emit.write_settings_json`** as the no-bake fallback floor — do not delete.

6. **Inline ASCII comment:** put the merge precedence (baked → +allow → −deny) as a small box in
   the `merge_settings` docstring, matching the existing rich docstrings in `emit.py`.

### Tests (in `tests/test_emit.py`, pure — no podman)

`merge_settings` unit matrix:
| Case | Assert |
|------|--------|
| baked missing / cp-fail | returns required stub |
| baked `{}` (empty) | returns stub (grant only) |
| baked malformed JSON | returns stub **+ warn**, no crash |
| baked has `hooks`, no permissions | **hooks preserved** + grant added  ← REGRESSION proof |
| baked `allow=[X]` | `allow=[X, mcp__hatago]` |
| baked `allow` already has hatago | no duplicate (dedup) |
| baked `deny=[mcp__hatago]` | stripped from deny, present in allow, warned |
| `required` empty (servers=[]) | no grant injected |
| baked nested non-permissions key | carried through verbatim |

**REGRESSION RULE (mandatory):** the "baked hook survives the merge" case proves the masking bug
is fixed — flag CRITICAL.

One `HARNESSED_PODMAN`-gated integration test: build a stack whose image bakes a `settings.json`
with a hook, assert the mounted file = baked ⊕ hatago grant. (Won't run in hermetic CI — that's
expected; the pure unit tests carry CI coverage.)

---

## Failure modes (new codepaths)

| Codepath | Realistic failure | Test | Handling | User sees |
|----------|-------------------|------|----------|-----------|
| `merge_settings` JSON parse | recipe writes malformed settings.json | yes | stub + warn | clear warn (was: **silent build crash**) |
| grant condition | servers present, grant dropped | yes | n/a | "MCP tool failed" prompts |
| deny conflict | hatago in allow+deny | yes | required wins + warn | clear warn |
| cp non-zero vs absent | transient cp error downgrades real file | yes | cp-fail → stub silently; treat absent == fail | (no false downgrade) |

No remaining failure mode is both untested AND silent. The malformed-JSON build crash (critical
gap if unhandled) is closed by the fallback rule.

---

## NOT in scope
- Unifying the 3 post-build `podman create` passes → separate TODO
  ([2026-06-27-unify-postbuild-podman-passes.md](2026-06-27-unify-postbuild-podman-passes.md)).
- ruff/mypy/recipe-lint CI job → considered, not scheduled (pytest likely exercises the
  validators; revisit after TIER 0).
- Coverage fail-under gate → defer until a baseline exists.
- TIER 1+ (persist, schema `--strict`, capability.py oracle) → later, per roadmap.

## What already exists (reuse, don't rebuild)
- `_merge_baked_extensions` (`launcher.py:278`) — the `create`/`cp`/`rm` idiom; extend the
  post-build pass rather than writing a parallel one.
- `write_settings_json` (`emit.py:59`) — keep as fallback floor.
- `deploy-web.yml` — CI structure reference (but that job is pnpm/web; this one is uv/Python).
- `HARNESSED_PODMAN` skip marker — the hermetic/integration split already exists.

## Worktree parallelization
- `Lane A: .github/` (CI YAML) — independent.
- `Lane B: src/harnessed/{emit,launcher}.py + tests/test_emit.py` (settings merge) — independent.
- No shared modules. **Land A first** so B merges under CI protection (per sequencing decision).
