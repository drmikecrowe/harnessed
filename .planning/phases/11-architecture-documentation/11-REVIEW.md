---
phase: 11-architecture-documentation
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - README.md
  - CLAUDE.md
  - AGENTS.md
  - docs/harnessed-design.md
  - docs/guides/recipe-authoring.md
  - docs/guides/troubleshooting.md
  - docs/guides/service-authoring.md
  - docs/guides/secrets.md
findings:
  critical: 1
  warning: 5
  info: 3
  total: 9
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Eight documentation files reviewed for accuracy, consistency, completeness, and stale
terminology. The `isolated`/`transparent` mode terminology is used consistently across all
reviewed files and maps directly to `config: isolated | transparent` literal values in the
stack manifest schema — these are intentional architectural terms, not stale remnants to
remove.

The most significant finding is a factual inaccuracy in the recipe-authoring guide: it
describes the superseded "fan into profile paths" skill model as current, directly
contradicting design §7 which explicitly marks that model as superseded by image-baking via
Dockerfiles. A developer following the guide would have the wrong mental model of how skills
land in a stack.

Secondary findings: two `npx` references in the design doc contradict the explicit
pnpm-everywhere policy; a `config/opencode` path is written incorrectly in the §2 modes
table; the design doc §5 is stale about the number of recipe contribution layers; and
`npm i -g` appears in two places where pnpm should be used.

---

## Critical Issues

### CR-01: recipe-authoring.md contradicts design §7 on how skills reach the container

**File:** `docs/guides/recipe-authoring.md:18-19, 68-70`
**Issue:** The guide states that the assembler "fans each skill/command dir into the
harness-native profile path (`.claude/skills/<leaf>`, `.claude/commands/<leaf>`)". This
describes the **old** assembly model. Design §7 explicitly says:

> "The prior assembly model — which resolved plugins, fanned skills/commands trees into the
> profile, and committed them — is **superseded**. Skills are image-baked by recipe
> Dockerfiles; the profile carries **only** assembler-generated config files (`.mcp.json`,
> `settings.json`)."

A developer reading the guide believes skills land in the profile via file-copy; in reality
they land in the derived image via `RUN` steps in recipe Dockerfiles. This directly
misdirects recipe authors trying to ship skills.

**Fix:** Replace the "fanned into profile paths" description with the current model:

```markdown
- **File-extension layer** — `skills` / `commands` directories declared in `recipe.yaml`
  are **image-baked** by the recipe's Dockerfile body (not copied into the profile). The
  assembler concatenates recipe Dockerfiles to produce a derived `harnessed-<stack>` image
  where the skill/command dirs live at their harness-native paths
  (`.claude/skills/<leaf>`, `.claude/commands/<leaf>`).
```

Remove or correct lines 68-70:

```markdown
- Skill/command dirs declared in `recipe.yaml` are baked into the derived image by the
  recipe's Dockerfile. The assembler validates names and fails fast on collision across
  recipes in the same stack.
```

---

## Warnings

### WR-01: harnessed-design.md §3 and §6 use `npx` — contradicts pnpm-everywhere policy

**File:** `docs/harnessed-design.md:74, 169`
**Issue:** Two occurrences of `npx` remain in the design doc:
- §3 line 74: "Light `npx`/`uvx` stdio servers run as hatago's children"
- §6 line 169: "hatago — the hub + the *light* `npx`/`uvx` stdio MCP servers baked in."

The project's CLAUDE.md "What NOT to Use" table explicitly bans `npm`/`npx` in favor of
`pnpm`/`pnpm dlx`. README.md line 86 correctly uses `pnpm dlx`/`uvx` in the parallel
description. The design doc is the authoritative *why* document and should not advertise
a banned tool.

**Fix:** Replace `npx` with `pnpm dlx` at both locations:
- Line 74: "Light `pnpm dlx`/`uvx` stdio servers run as hatago's children (baked into the hatago image)"
- Line 169: "hatago — the hub + the *light* `pnpm dlx`/`uvx` stdio MCP servers baked in."

---

### WR-02: harnessed-design.md §3 — orphaned closing ``` breaks markdown rendering

**File:** `docs/harnessed-design.md:68`
**Issue:** The pod architecture diagram (lines 57–67) is rendered as an indented markdown
code block (4+ spaces), which is valid. However, line 68 contains a lone closing ` ``` `
with no matching opening fence. In GitHub-flavored markdown this lone ` ``` ` is interpreted
as the **start** of a new fenced code block, which then swallows all following text until the
next ` ``` ` or end-of-file. The rendered output after the diagram is garbled.

**Fix:** Replace the indented code block with an explicit fenced block:

```markdown
```
        podman pod: harnessed-<stack>-<proj>
    ┌──────────────────────────────────────────────┐
    │  [ harnessed-<harness> ]  ──→  [ hatago ]      │
    ...
```
```

Remove the stray closing ` ``` ` that currently sits alone on line 68, and add a proper
opening fence immediately before line 57.

---

### WR-03: harnessed-design.md §2 modes table uses wrong opencode path (`.opencode`)

**File:** `docs/harnessed-design.md:36`
**Issue:** The §2 modes table lists the `transparent` config source as:
```
host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`) bind-mounted live
```
`.opencode` does not exist — the correct path is `~/.config/opencode` (XDG config dir).
This is used correctly in §4b line 113 (`~/.codex`, `~/.config/opencode`, `~/.gemini`) and
in README.md line 52 (`.codex`/`.config/opencode`/`.gemini`). The §2 table is the only
place the wrong path appears.

**Fix:**
```markdown
| **`transparent`** | host `~/.claude` (+ `.codex`/`.config/opencode`/`.gemini`) bind-mounted live | ...
```

---

### WR-04: harnessed-design.md §5 says recipes contribute to "two layers" — now three

**File:** `docs/harnessed-design.md:155-157`
**Issue:** §5 states:
> "A recipe can contribute to **two layers**: MCP layer → ...; File-extension layer → ..."

Phase 8 added a third contribution type — the Dockerfile body. `docs/guides/recipe-authoring.md`
correctly documents "three things" (MCP layer, File-extension layer, Dockerfile body) and
calls Worked Example 3 "a Dockerfile recipe." The design doc §5 is stale and will mislead
anyone reading it as the authoritative architecture reference.

**Fix:** Update §5 to list three contribution layers:
```markdown
A recipe can contribute to **three layers**:
- **MCP layer** → server entries merged into the stack's hatago config (and/or a shared service ref).
- **File-extension layer** → `skills`/`commands`/`agents`/`hooks`/`rules` in Claude-canonical form.
- **Dockerfile body** → installation steps concatenated into the derived stack image (the primary
  way to bake tooling, frameworks, or CLIs into the stack).
```

---

### WR-05: `npm i -g varlock` in two docs contradicts pnpm-everywhere policy

**File:** `docs/guides/secrets.md:61`, `docs/guides/troubleshooting.md:186`
**Issue:** Both files instruct users to install varlock via `npm i -g varlock`. The project's
"pnpm everywhere" policy (CLAUDE.md, design §7) prohibits `npm`/`npx` and uses `pnpm`/`pnpm dlx`
for all JavaScript installs, including globals. These instructions set a contrary example at
precisely the point where users are learning the tool's conventions.

**Fix:** Use pnpm in both files:
- `secrets.md:61`: `pnpm add -g varlock`
- `troubleshooting.md:186`: `command -v varlock` (`pnpm add -g varlock`)

---

## Info

### IN-01: service-authoring.md Dockerfile uses raw `pip install` instead of `uv pip`

**File:** `docs/guides/service-authoring.md:66`
**Issue:** The ping service Dockerfile example uses `pip install --no-cache-dir "mcp[cli]"`.
Services have their own image lineage (`FROM python:3.12-slim`, not `FROM harnessed-base`), so
`uv` is not available in the base layer. However, the project recommends `uv` for all Python
package management (CLAUDE.md recommended stack: "uv + pyproject.toml for deps"). Adding a
`uv` install step would align the example with project conventions and is the pattern that
service authors will copy for real services.

**Fix:** Either document that service Dockerfiles use plain pip because they have their own
lineage (not harnessed-base), or install uv and use it:
```dockerfile
RUN pip install --no-cache-dir uv && uv pip install --system "mcp[cli]"
```

---

### IN-02: harnessed-design.md §11 recipe schema shows superseded `plugins:` field

**File:** `docs/harnessed-design.md:411-427`
**Issue:** The §11 "Proposed: recipe schema" example includes a `plugins:` block. Design §7
explicitly states: "The prior assembly model — which resolved plugins, fanned skills/commands
trees into the profile, and committed them — is **superseded**." Showing `plugins:` in the
canonical schema example will lead recipe authors to attempt the old plugin-vendor model.
(Recipe-authoring.md does note these are "accepted but only exercised where relevant" — but
that's a footnote, not the schema example itself.)

**Fix:** Remove the `plugins:` block from the §11 schema example, or add a clear "deprecated"
callout next to it. Add a brief Dockerfile body example to show the current model in its place.

---

### IN-03: harnessed-design.md §14 has unresolved [INFERENCE] items that may be stale

**File:** `docs/harnessed-design.md:508-551`
**Issue:** §14 "Open / to verify during execution" mixes items clearly resolved (tagged
`*(Resolved, HRN-XX)*`) with items still marked `[INFERENCE — verify]`:
- "`CLAUDE_CONFIG_DIR` relocation" (line 549) — still `[INFERENCE]`
- "Minimal `.claude.json` stub fields" (line 508) — `[INFERENCE]` but troubleshooting.md
  line 98-99 now documents the proven field set (`hasCompletedOnboarding`, `firstStartTime`,
  `numStartups`, `oauthAccount`, `userID`) as verified (AUTH-02). This item was resolved but
  the §14 entry was not updated.

This creates confusion about what has been verified in production vs what is still speculative.

**Fix:** Mark the stub-fields item resolved (the troubleshooting guide already documents the
verified set). Separately audit the `CLAUDE_CONFIG_DIR` item to confirm its actual status.
Tag all remaining unresolved items with a date or phase so readers know when they were last
assessed.

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
