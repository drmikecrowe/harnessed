# superpowers recipe — implementation plan (upstream: Superpowers)

Goal: make **Superpowers** (Jesse Vincent / Prime Radiant) available in a stack as a
**composable software-development methodology skill suite** — TDD, systematic debugging,
brainstorming, planning, subagent-driven development, code review, git-worktree workflow — so
every harness an agent runs under carries the same 14 Claude-canonical skills.

Upstream: <https://github.com/obra/superpowers> · MIT · a multi-harness **plugin** repo whose
top-level `skills/<name>/SKILL.md` trees are already Claude-canonical. Latest tag **v6.0.3**
(commit `896224c4b1879920ab573417e68fd51d2ccc9072`, published 2026-06-18); `main` HEAD floats
and is rejected by the pin gate.

> **Not in the stress-test doc.** `docs/todos/2026-06-27-recipe-stress-test.md` has no
> Superpowers section (it postdates that doc), so this is fresh analysis — no snippets to
> reconcile.

## Recipe shape

**Dockerfile recipe** (clone the pinned tag, copy the upstream's Claude-canonical `skills/`
tree into `~/.claude/skills/`), declared via `expect:`. **No MCP, no service, no
startup-hooks.** Mirrors `catalog/recipes/gstack/` and `catalog/recipes/caveman/`.

Why this shape (each choice grounded in the upstream install docs + repo layout):

- **Deliverables are already Claude-canonical.** The repo top level is a ready-to-fan
  `skills/<name>/SKILL.md` tree (14 skills, each with its `SKILL.md` + sibling references and
  on-demand scripts). Copying `skills/*` into `~/.claude/skills/` is exactly the file layout a
  harness plugin install surfaces — minus the plugin-registry wrapping. Unlike caveman there is
  **no `commands/` or `agents/`** dir at the repo root, so skills are the sole file-extension
  deliverable.
- **We do NOT run any harness plugin installer.** For every supported harness the upstream
  install delegates to that harness's own plugin/extension system — Claude Code
  `/plugin install superpowers@…`, Antigravity `agy plugin install`, Gemini
  `gemini extensions install`, OpenCode `plugin: ["superpowers@git+https://…#vX"]`, Codex /
  Cursor / Copilot / Kimi / Pi / Factory Droid likewise. Those (a) bypass the assembler's
  harness-independent fan-out — every harness consumes the same `~/.claude/` profile, (b) need
  network + the harness binary at *build* time, and (c) wire `settings.json`/plugin hooks
  harnessed can't express today (GAP 2, below). Replicating the installer's **result**
  deterministically is the faithful move — this is the `caveman` decision applied verbatim.
- **No build-time Node / apt / pnpm.** The skills are pure Markdown (+ opt-in JS scripts run
  on demand during specific workflows). Nothing in install or session-start needs a runtime.
  So no `USER root` phase — the whole body runs as `USER harnessed`, the lightest possible
  Dockerfile.
- **Clone+copy over vendoring.** 14 skills (some with multi-file reference/script subtrees) and
  frequent releases (v3 → v6). A pinned clone stays in sync by bumping one `ARG`; re-vendoring
  ~40+ files on every release is error-prone.

```
catalog/recipes/superpowers/
  recipe.yaml
  Dockerfile          # clone pinned tag → copy skills/ into ~/.claude/skills/
  PLAN.md
```

### recipe.yaml

```yaml
name: superpowers
description: superpowers — composable software-development methodology skill suite (TDD, systematic debugging, brainstorming, planning, subagent-driven development, code review, git worktrees). 14 Claude-canonical skills (upstream Superpowers, Jesse Vincent / Prime Radiant).
expect:
  skills:
    - brainstorming
    - dispatching-parallel-agents
    - executing-plans
    - finishing-a-development-branch
    - receiving-code-review
    - requesting-code-review
    - subagent-driven-development
    - systematic-debugging
    - test-driven-development
    - using-git-worktrees
    - using-superpowers
    - verification-before-completion
    - writing-plans
    - writing-skills
```

- `expect:` (not `skills:` declarations) because the Dockerfile `RUN` bakes the tree directly
  into `~/.claude/skills/` — the assembler can't see what a RUN step drops, so it lists the
  skills for the capability test to probe (the gstack pattern). All 14 are stable names that
  the README enumerates and that have not churned across v3–v6; listing the full set gives a
  complete install probe.
- No `mcp:` (Superpowers is not an MCP server — no stdio child, no service, no URL). No
  `commands:`/`agents:` (the repo ships none at its root).
- No `hooks:` — see GAP 2 below.

### Dockerfile

```dockerfile
# Superpowers' deliverables are a Claude-canonical skills/<name>/SKILL.md tree (14 skills).
# Clone the pinned release tag and copy them into ~/.claude/skills/ — the layout every harness
# plugin install surfaces, minus the plugin-registry wrapping and the Claude-tool SessionStart
# hook (GAP 2; see PLAN Phasing). We deliberately do NOT run any harness plugin installer: each
# delegates to a per-harness plugin system that bypasses the assembler's harness-independent
# fan-out and wires settings.json hooks harnessed can't express. No Node needed at build —
# skills are pure Markdown (the per-skill JS scripts are opt-in, run on demand at runtime).
USER harnessed
ARG SUPERPOWERS_REF=v6.0.3    # real release tag; pin gate accepts tags (and SHAs), rejects main/HEAD
# Privacy + egress: Superpowers' brainstorming visual companion pings primeradiant.com for a
# versioned logo by default. Disable that non-essential telemetry for the baked image.
ENV SUPERPOWERS_DISABLE_TELEMETRY=1
RUN set -eu; \
    git clone --quiet --depth 1 --branch "${SUPERPOWERS_REF}" \
        https://github.com/obra/superpowers.git /tmp/superpowers && \
    mkdir -p ~/.claude/skills && \
    cp -r /tmp/superpowers/skills/. ~/.claude/skills/ && \
    rm -rf /tmp/superpowers
# (body ends as USER harnessed — nothing here needs root)
```

Notes for the implementer:

- `--branch v6.0.3` is a **pinned tag** (passes the assembler pin gate). For maximum
  reproducibility use fetch-by-SHA as gstack does:
  `SUPERPOWERS_REF=896224c4b1879920ab573417e68fd51d2ccc9072` with
  `git init … && git remote add … && git fetch --depth 1 origin ${SUPERPOWERS_REF} &&
  git checkout -q FETCH_HEAD`.
- The copy lands each skill at `~/.claude/skills/<name>/` **with its sibling references and
  `scripts/`** intact (the trailing-slash `cp -r …/.` form copies the *contents* of
  `skills/`, not a nested `skills/skills/`). `using-superpowers`'s relative links to
  `references/*-tools.md`, and `systematic-debugging`/`brainstorming`/`writing-skills`'s
  sibling `.md` + `scripts/` all resolve.
- No `FROM`, no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
  re-declares `ARG HARNESS`.
- Entirely as `USER harnessed` (writes only to `~/.claude/` + `/tmp`); confirm `~/.claude` is
  pre-created/writable in the base image (gstack assumes the same).

### (no service.yaml)

N/A — Superpowers has no long-running process, no port, no volume, no data store. (The
brainstorming skill *can* launch an opt-in local "visual companion" HTTP server on demand at
runtime — `skills/brainstorming/scripts/start-server.sh` — but that is a per-invocation helper
the agent starts/stops itself, not a stack service.)

### Hooks: the SessionStart bootstrap (GAP 2) and the skill-driven fallback

**The hook, and why it is load-bearing.** Superpowers ships a Claude Code **`SessionStart`
tool-hook** at `hooks/hooks.json`:

```json
{ "hooks": { "SessionStart": [{ "matcher": "startup|clear|compact",
  "hooks": [{ "type": "command",
    "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd\" session-start", "async": false }] }] } }
```

`hooks/session-start` reads `skills/using-superpowers/SKILL.md`, JSON-escapes it, and emits it
as `hookSpecificOutput.additionalContext` — i.e. it **forces the full bootstrap content into the
session context on startup, on `/clear`, and on compaction**. That injection is what makes
Superpowers "active from the first message": it tells the agent, up front and persistently, to
check for and invoke skills before any response. Unlike caveman (whose SessionStart hook is a
convenience auto-activator), **here the hook is core to the methodology**, not a nicety.

**This is GAP 2.** The harnessed assembler fans `skills`/`commands`/`plugins` into the
Claude-canonical profile, but it does **not** install Claude Code's own tool-hooks
(`SessionStart`/`PreToolUse`/`PostToolUse`/`UserPromptSubmit`) from a plugin — the recipe model
has no field that wires the `hooks` key of `~/.claude/settings.json`. So we cannot faithfully
replicate the forced injection today.

> **Do not conflate hook kinds.** There is a *separate* **startup-hooks** feature
> (`docs/todos/2026-06-29-startup-hooks.md`) — launcher lifecycle hooks
> (`new_session`/`pre_agent`/`pre_session`) that run via `<rt> exec` at instance create /
> attach. It is a distinct mechanism and does **not** solve this: (a) it fires at launcher
> lifecycle points, not on Claude Code's `startup|clear|compact` matcher, and (b) its output is
> not injected into Claude Code's system-prompt context the way `additionalContext` is. Don't
> reach for startup-hooks here.

**Skill-driven fallback (Phase 1).** The bootstrap is itself a skill — `using-superpowers` —
and we *do* bake it into `~/.claude/skills/using-superpowers/`. Its frontmatter
`description: Use when starting any conversation - establishes how to find and use skills,
requiring skill invocation before ANY response including clarifying questions` is exactly the
trigger Claude Code's skill-metadata discovery surfaces at session start, so a well-behaved
agent is nudged to invoke it; the other 13 skills load on demand as their triggers fire. The
full methodology is usable — what is **missing by design** is the *forced* injection of the
bootstrap into every session (so an agent that ignores skill-metadata discovery won't be
auto-bootstrapped), and re-injection after `/clear`/compaction.

**Optional deterministic nudge (bake-time).** To approximate the hook's "bootstrap from turn 1"
effect through the instruction channel the agent already reads, the Dockerfile may append a
one-line directive to the user-level instruction file — idempotently, so re-builds don't
duplicate it:

```dockerfile
# Optional: nudge the agent to self-bootstrap, approximating the SessionStart injection (GAP 2).
RUN mkdir -p ~/.claude && grep -q 'using-superpowers' ~/.claude/CLAUDE.md 2>/dev/null \
    || printf '\n## Superpowers\nAt the start of every session, before your first response, invoke the `using-superpowers` skill and follow its skill-check discipline.\n' >> ~/.claude/CLAUDE.md
```

Caveat: harnessed has no merge mechanism for `~/.claude/CLAUDE.md` across recipes, so two
recipes both appending can collide; the `grep` guard keeps *this* recipe idempotent but not
composition-safe with others. Treat as optional — the skill-driven fallback above is the
primary path.

## Test stack

```yaml
# catalog/stacks/claude_superpowers/stack.yaml
name: claude_superpowers
harness: claude
recipes: [superpowers]
```

## Build / test lifecycle

```bash
harnessed build claude_superpowers   # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_superpowers         # launch the instance (harness + hatago)
harnessed test  claude_superpowers   # capability report: ✓ all 14 declared skills present
```

Manual verification (the capability test only checks presence — verify the *behavior*):

- In the instance, `ls ~/.claude/skills` shows all 14 names; spot-check that a multi-file skill
  kept its subtree, e.g. `ls ~/.claude/skills/using-superpowers/references` (6 `*-tools.md`)
  and `ls ~/.claude/skills/systematic-debugging` (root-cause-tracing.md, find-polluter.sh, …).
- Attach and ask "tell me about your superpowers" / "what skills do you have" → the agent
  invokes `using-superpowers` and lists/summarizes the suite (this is Superpowers' own
  documented smoke-test phrase).
- Drive one workflow end-to-end, e.g. "let's build a small X" → the agent should invoke
  `brainstorming`; "write a failing test first" → `test-driven-development`.
- **Confirm what's *missing* by design:** the bootstrap is not *forced* into turn 1 (no
  SessionStart injection = GAP 2) and is not re-injected after `/clear` or compaction. With the
  optional CLAUDE.md nudge, the agent self-bootstraps on its first reply; without it, the agent
  must be prompted to invoke `using-superpowers` (then it takes over).

## Phasing

1. **Now (no feature):** ship recipe.yaml + Dockerfile as above. All 14 skills are present and
   invokable via the `Skill` tool; `using-superpowers` is discoverable via its
   "starting any conversation" description. The methodology is fully usable on demand — the
   forced first-message injection and `/clear`/compaction re-injection are the only gaps.
   Include the optional CLAUDE.md nudge if the stack wants self-bootstrap from turn 1.
2. **When Claude-tool-hooks support lands (GAP 2):** the recipe gains a hook declaration for
   the upstream `SessionStart` hook. At that point switch the Dockerfile to the **full
   plugin-dir** layout — keep the pinned clone at `~/.claude/plugins/superpowers/` (so
   `${CLAUDE_PLUGIN_ROOT}` resolves as upstream expects) and either symlink
   `~/.claude/skills/<name>` → `~/.claude/plugins/superpowers/skills/<name>` for each skill, or
   let the plugin's own skill discovery surface them. Copy `hooks/{session-start,run-hook.cmd,
   hooks.json}` into the plugin dir and declare the `SessionStart` hook. This restores exact
   upstream behaviour (forced injection on `startup|clear|compact`). The hook is pure
   bash (`session-start`) + a Windows polyglot (`run-hook.cmd`) — no Node, so it works in any
   harness image with a shell.

> Note (repeat): the startup-hooks feature (`new_session`/`pre_agent`/`pre_session`) is a
> different mechanism and is **not** the vehicle for this — see the GAP 2 note above.

## Risks / checks

- **Pin gate:** confirm `--branch v6.0.3` (or the SHA fetch form) passes the assembler's
  `PinValidationError` — it must (tags/SHAs are accepted; `main`/`HEAD`/`@latest` rejected);
  verify at first `build`.
- **Layout vs. capability test:** the copy must put `skills/using-superpowers` →
  `~/.claude/skills/using-superpowers` (not `~/.claude/skills/superpowers/skills/…`). The
  `cp -r …/.` trailing-slash form does this; double-check the 14 probe paths in `expect:`
  resolve.
- **Multi-file skill subtrees:** confirm sibling resources copied intact —
  `using-superpowers/references/*`, `systematic-debugging/{root-cause-tracing,defense-in-depth,
  condition-based-waiting}.md` + `find-polluter.sh`, `writing-skills/{anthropic-best-practices.md,
  persuasion-principles.md, render-graphs.js, examples/}`, `subagent-driven-development/scripts/`,
  `brainstorming/scripts/`. A shallow `SKILL.md`-only copy would break relative links.
- **Runtime deps of opt-in scripts:** the skills are Markdown, but on-demand helpers need a
  runtime when actually invoked — the brainstorming *visual companion* server
  (`scripts/server.cjs`, a zero-dep Node server per upstream spec
  `2026-03-11-zero-dep-brainstorm-server`) and `writing-skills/render-graphs.js` need **Node**
  (present in the `claude` base; add via the recipe body for a Node-less harness). Flag in the
  skill behaviour if a script errors in a Node-less image rather than silently no-oping.
- **GAP 2 impact is higher than for caveman:** because the SessionStart hook injects the
  *bootstrap* (not a convenience flag), the degradation is "discoverable, not forced." The
  CLAUDE.md nudge mitigates it for cooperative agents; full fidelity waits on GAP 2.
- **Telemetry / egress:** `ENV SUPERPOWERS_DISABLE_TELEMETRY=1` is set by default (the visual
  companion otherwise fetches a versioned logo from primeradiant.com). If a stack wants the
  visual companion telemetry, drop that `ENV`; the egress firewall governs actual outbound
  either way.
- **`.superpowers/` scratch state:** subagent-driven-development writes task briefs / implementer
  reports / a progress ledger into a self-ignoring `.superpowers/sdd/` in the project working
  tree (v6.0.3 moved it out of `.git/`, which Claude Code protects). It persists via the project
  bind-mount; note `git clean -fdx` deletes it (recover from `git log`). No recipe action needed —
  awareness only.
- **Upstream drift:** Superpowers tags frequently; bumping `SUPERPOWERS_REF` re-clones the tree.
  Re-audit `expect:` if upstream renames/adds/removes a skill (the 14 are stable across v3–v6;
  new methodology skills would appear as new `skills/<name>/` dirs).
- **Alternative shape (vendored, no Dockerfile):** carry the upstream `skills/` tree as
  committed files under the recipe dir and declare via `skills:` (file-extension layer) instead
  of a Dockerfile — same runtime, same GAP-2 gap, but requires re-vendoring ~40+ files per
  release. Dockerfile clone is recommended for lower maintenance (matches gstack/caveman).
