# hyperpowers recipe — implementation plan

Goal: make **hyperpowers** (Ryan Stortz / withzombies) available in a stack as a
**markdown-first software-development workflow skill suite** — brainstorming → planning →
TDD execution → review → verification, grounded in repo-local task docs under
`plans/active/<slug>/` — so the agent carries the same skills, slash commands, and subagents
the upstream Claude Code plugin ships, minus the Claude-tool hooks (deferred, GAP 2).

Upstream: <https://github.com/withzombies/hyperpowers> · MIT · Shell/Markdown repo shipped as a
**Claude Code plugin** (`.claude-plugin/plugin.json`, current version **2.8.3**). The repo
publishes **no git tags and no GitHub releases**, so the pin is the full 40-char commit SHA of
`main` HEAD: **`7905547b6eb0665d631dd1e4f557e3863cd7a1b4`** (2026-03-30,
"fix: make task plans local-only and bump plugin to 2.8.3"). A floating `--branch main` clone
is rejected by the assembler pin gate, and there is no tag to pin instead — fetch-by-SHA is the
only valid pin.

> **Stress-test correction.** `docs/todos/2026-06-27-recipe-stress-test.md` §11 calls hyperpowers
> a "skills + hooks recipe" whose install is "Claude Code plugin marketplace or git clone into
> `.agents/skills/`," and sketches a Dockerfile that `cp -r .agents/skills/*`. That understates
> it on two counts:
> 1. **It is a full Claude Code plugin**, not just a skills folder. `.claude-plugin/plugin.json`
>    + `marketplace.json` wrap it; the Claude-canonical deliverables live at the repo **top
>    level** — `skills/` (22 skills), `commands/` (10 `.md` slash commands), `agents/` (5
>    subagents) — with a *mirrored* `.agents/skills/` tree (the OpenAI/Codex convention) alongside.
>    The snippet's `.agents/skills/*` source is the Codex mirror; the Claude-canonical source is
>    top-level `skills/`.
> 2. **The hooks are Claude Code tool-hooks** (`hooks/hooks.json`: SessionStart / PreToolUse /
>    UserPromptSubmit / PostToolUse / Stop), not launcher startup-hooks. That is **GAP 2**
>    (settings.json tool-hooks, currently unsupported) — see Phasing. They are not the same
>    mechanism as the planned startup-hooks feature (`docs/todos/2026-06-29-startup-hooks.md`).

## Recipe shape

**Dockerfile recipe** — clone the pinned SHA, copy the upstream's Claude-canonical
`skills/` + `commands/` + `agents/` trees into `~/.claude/`, declared via `expect:`. **No MCP,
no service, no startup-hooks.** Mirrors `catalog/recipes/gstack/`, `catalog/recipes/caveman/`,
and `catalog/recipes/Superpowers/`.

Why this shape (each choice grounded in the upstream install docs + repo layout):

- **Deliverables are already Claude-canonical.** The repo top level is a ready-to-fan
  `skills/<name>/SKILL.md` tree (22 skills, many with sibling `resources/`/`references/`),
  plus `commands/<name>.md` (10) and `agents/<name>.md` (5 subagents). Copying them into
  `~/.claude/{skills,commands,agents}` is exactly the file layout `claude plugin install
  hyperpowers@withzombies-hyper` drops — minus the plugin-registry wrapping and the Claude-tool
  hooks (GAP 2).
- **We do NOT run the plugin installer** (`/plugin marketplace add withzombies/hyperpowers` →
  `/plugin install hyperpowers@withzombies-hyper`). For Claude Code that path (a) bypasses the
  assembler's harness-independent fan-out — every harness consumes the same `~/.claude/`
  profile, (b) needs network + the `claude` binary at *build* time, and (c) wires
  `settings.json`/plugin hooks harnessed can't express today (GAP 2). The Codex path
  (`.agents/skills/`) is a different harness's convention. Replicating the installer's **result**
  deterministically is the faithful move — this is the `caveman`/`Superpowers` decision applied
  verbatim.
- **No build-time Node / apt / pnpm.** The skills/commands/agents are pure Markdown. Nothing in
  install or (Phase-1) session-start needs a runtime. So no `USER root` phase — the whole body
  runs as `USER harnessed`, the lightest possible Dockerfile.
- **Clone+copy over vendoring.** 22 skills (several multi-file) across 3 dirs, with active
  development (v2.8.x). A pinned clone stays in sync by bumping one `ARG` (the SHA);
  re-vendoring ~50+ files on every release is error-prone.
- **SHA pin, not a tag.** Upstream publishes no tags/releases. `--branch main` is a floating ref
  the pin gate rejects (`PinValidationError`); fetch-by-SHA is mandatory (the gstack form).

```
catalog/recipes/hyperpowers/
  recipe.yaml
  Dockerfile          # clone pinned SHA → copy skills/commands/agents into ~/.claude/
  PLAN.md
```

### recipe.yaml

```yaml
name: hyperpowers
description: hyperpowers — markdown-first dev-workflow skill suite (brainstorming, planning, TDD, execution, review, verification) with repo-local task-doc tracking. Claude Code plugin skills/commands/agents baked in; Claude-tool hooks deferred (GAP 2).
expect:
  skills:
    - brainstorming
    - writing-plans
    - executing-plans
    - review-implementation
    - verification-before-completion
    - managing-task-docs
    - test-driven-development
    - debugging-with-tools
    - fixing-bugs
    - using-hyper
  commands:
    - brainstorm
    - write-plan
    - execute-plan
    - review-implementation
```

- `expect:` (not `skills:`/`commands:` declarations) because the Dockerfile `RUN` bakes the trees
  directly into `~/.claude/` — the assembler can't see what a RUN step drops, so it lists a stable
  probe set for the capability test (the gstack pattern). The full install lands **22 skills**
  (`analyzing-test-effectiveness`, `brainstorming`, `building-hooks`, `debugging-with-tools`,
  `dispatching-parallel-agents`, `executing-plans`, `finishing-a-development-branch`, `fixing-bugs`,
  `managing-task-docs`, `refactoring-design`, `refactoring-diagnosis`, `refactoring-safely`,
  `review-implementation`, `root-cause-tracing`, `skills-auto-activation`, `sre-task-refinement`,
  `test-driven-development`, `testing-anti-patterns`, `using-hyper`, `verification-before-completion`,
  `writing-plans`, `writing-skills`), **10 commands** (`analyze-tests`, `brainstorm`,
  `execute-plan`, `refactor-design`, `refactor-diagnose`, `refactor-execute`,
  `review-implementation`, `sre-task-refinement`, `update-task-docs`, `write-plan`), and **5
  agents** (`code-reviewer`, `codebase-investigator`, `internet-researcher`,
  `test-effectiveness-analyst`, `test-runner`). The probe lists the README's "Core workflow
  skills" + the `using-hyper` bootstrap + a few stable supporting skills.
- There is **no `agents:` probe kind** in the `expect:` model (`expect:` covers
  skills/commands/plugins/mcp). The 5 agents are baked but not smoke-tested; verify them
  manually (see Build / test lifecycle).
- No `mcp:` (hyperpowers is not an MCP server — no stdio child, no service, no URL). No `hooks:`
  (GAP 2 — see Phasing).

### Dockerfile

```dockerfile
# hyperpowers' deliverables are a Claude-canonical skills/ + commands/ + agents/ tree (22 skills,
# 10 commands, 5 subagents). Clone the pinned commit and copy them into ~/.claude/ — the exact
# layout `claude plugin install` drops, minus the plugin-registry wrapping and the Claude-tool
# hooks (GAP 2; see PLAN Phasing). We deliberately do NOT run the plugin installer: it bypasses
# the assembler's harness-independent fan-out, needs the claude binary + network at build time,
# and wires settings.json hooks harnessed can't express. No Node/apt needed — deliverables are
# pure Markdown.
USER harnessed
# Upstream publishes NO tags/releases, so pin to the full SHA of main HEAD (fetch-by-SHA). A
# floating `--branch main` clone fails the assembler pin gate.
ARG HYPERPOWERS_REF=7905547b6eb0665d631dd1e4f557e3863cd7a1b4
RUN set -euo pipefail; \
    git init -q /tmp/hp && cd /tmp/hp \
    && git remote add origin https://github.com/withzombies/hyperpowers.git \
    && git fetch --depth 1 origin "${HYPERPOWERS_REF}" && git checkout -q FETCH_HEAD \
    && mkdir -p ~/.claude/skills ~/.claude/commands ~/.claude/agents \
    && cp -r /tmp/hp/skills/.   ~/.claude/skills/ \
    && cp -r /tmp/hp/commands/. ~/.claude/commands/ \
    && cp -r /tmp/hp/agents/.   ~/.claude/agents/ \
    && rm -rf /tmp/hp
# (body ends as USER harnessed — nothing here needs root)
```

Notes for the implementer:

- **fetch-by-SHA is the pin.** `${HYPERPOWERS_REF}` is a full 40-char commit SHA (passes the
  assembler pin gate; the gate accepts SHAs and tags, rejects `main`/`HEAD`/`@latest`). This is
  mandatory because the repo has no tags — there is no `--branch <tag>` alternative.
- **Source is the repo TOP LEVEL**, not `.agents/skills/`. `.agents/skills/` is the OpenAI/Codex
  mirror (each skill carries an `agents/openai.yaml`); the Claude-canonical source the plugin
  surfaces is top-level `skills/`. harnessed is runtime-agnostic and every harness consumes the
  same `~/.claude/` profile, so top-level `skills/`/`commands/`/`agents/` is correct for any
  harness. Do not copy `.agents/`.
- The trailing-slash `cp -r …/.` copies the *contents* of each dir (so `skills/brainstorming`
  lands at `~/.claude/skills/brainstorming`, not `~/.claude/skills/skills/brainstorming`).
- **Upstream quirk — `skills/commands/` and `skills/common-patterns/`.** The `skills/` tree also
  contains a nested `commands/` (`brainstorm.md`, `execute-plan.md`, `write-plan.md` — stale
  duplicates of top-level commands) and `common-patterns/` (shared reference `.md` files, no
  `SKILL.md`). The blanket `cp -r skills/.` copies both. Claude Code ignores a skill dir that
  lacks `SKILL.md`, so `common-patterns/` is harmless; the nested `skills/commands/` is
  cosmetically messy but inert (verify it does not shadow the real `~/.claude/commands/` fan-out;
  if it does, exclude it with a targeted `cp` of SKILL.md-bearing dirs instead).
- **Do NOT copy the repo-root `CLAUDE.md` / `AGENTS.md`.** Those are the plugin's *own*
  authoring instructions (for developing hyperpowers itself), not meant for the user's
  `~/.claude/CLAUDE.md`. Only `skills/`/`commands/`/`agents/` are copied. (The optional
  bootstrap nudge below writes to the user's own `~/.claude/CLAUDE.md` as a separate, idempotent
  step.)
- No `FROM`, no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
  re-declares `ARG HARNESS`.
- Entirely as `USER harnessed` (writes only to `~/.claude/` + `/tmp`); confirm `~/.claude` is
  pre-created/writable in the base image (gstack/caveman assume the same).

### (no service.yaml)

N/A — hyperpowers has no long-running process, no port, no volume, no data store. (Task docs
live in the mounted project at `plans/active/<slug>/` — see Data model below.)

### (no hooks / skills content authored here)

The skills/commands/agents are vendored verbatim from upstream by the Dockerfile; this recipe
authors none of its own. The bootstrap skill `using-hyper` (`SKILL.md` frontmatter: *"Use when
starting any conversation - establishes skill selection and the local task-doc workflow"*) carries
the session-start trigger, so a well-behaved agent is nudged to invoke it; the other 21 skills
load on demand as their triggers fire. No hook is needed for on-demand use — only for the
*forced* bootstrap + guardrails (GAP 2).

## Hooks: the tool-hook suite (GAP 2) and the skill-driven fallback

**The hooks, and why several are load-bearing.** hyperpowers ships a Claude Code **tool-hook**
suite at `hooks/hooks.json`, all referencing `${CLAUDE_PLUGIN_ROOT}/hooks/…`:

| Kind | Matcher | Script | Effect |
| --- | --- | --- | --- |
| `SessionStart` | `startup\|resume\|clear\|compact` | `session-start.sh` | Injects `using-hyper` guidance + an `AGENTS.md` reminder + the live `plans/active/` dir listing into session context |
| `UserPromptSubmit` | (all) | `user-prompt-submit/10-skill-activator.js` | Suggests relevant skills/agents from `skill-rules.json` |
| `PreToolUse` | `Edit\|Write` | `pre-tool-use/01-block-pre-commit-edits.py` | **Blocks** direct edits to `.git/hooks/pre-commit` |
| `PostToolUse` | `Edit\|Write` | `post-tool-use/01-track-edits.sh` | Tracks edited files for stop-time reminders |
| `PostToolUse` | `Edit\|Write\|MultiEdit\|Bash` | `post-tool-use/02-block-task-doc-truncation.py` | **Blocks** truncated writes to active `plan/context/tasks.md` |
| `PostToolUse` | `Bash` | `post-tool-use/03-block-pre-commit-bash.py` | **Blocks** shell-based pre-commit bypass |
| `PostToolUse` | `Bash` | `post-tool-use/04-block-pre-existing-checks.py` | **Blocks** "were these errors pre-existing?" checkout workflows |
| `Stop` | (all) | `stop/10-gentle-reminders.sh` | Non-blocking reminders if tests/verification/task-doc updates were skipped |
| `Stop` | (all) | `stop/20-block-completion-with-active-plans.py` | **Blocks** completion/merge claims while `plans/active/` task dirs still exist |

**This is GAP 2.** The harnessed assembler fans `skills`/`commands`/`plugins` into the
Claude-canonical profile, but it does **not** install Claude Code's own tool-hooks
(`SessionStart`/`PreToolUse`/`PostToolUse`/`UserPromptSubmit`/`Stop`) — the recipe model has no
field that wires the `hooks` key of `~/.claude/settings.json`. So none of the above fires today.

> **Do not conflate hook kinds.** There is a *separate* **startup-hooks** feature
> (`docs/todos/2026-06-29-startup-hooks.md`) — launcher lifecycle hooks
> (`new_session`/`pre_agent`/`pre_session`) that run via `<rt> exec` at instance create / attach.
> It is a distinct mechanism and does **not** solve this: (a) it fires at launcher lifecycle
> points, not on Claude Code's `startup|resume|clear|compact` matcher, (b) its output is not
> injected into Claude Code's context the way SessionStart's `additionalContext` is, and (c) it
> cannot express PreToolUse/PostToolUse/Stop blocking at all. Don't reach for startup-hooks here.
> (A launcher `new_session`/`pre_session` hook *could* approximate the "list `plans/active/`"
> part of SessionStart as a printed nudge, but that is a pale substitute and out of scope for
> this recipe.)

**Impact of the gap (differentiated).** The hooks split into two tiers:

- **Core methodology, degraded but usable:** the `SessionStart` forced bootstrap + the
  `UserPromptSubmit` skill-activator are *conveniences that make skills active from turn 1*. The
  skills themselves (baked into `~/.claude/skills/`) work fully on demand; what is missing is the
  *forced* injection of `using-hyper` into every session and re-injection after `/clear`/compact.
- **Hard guardrails, fully missing:** the PreToolUse/PostToolUse **blockers** (pre-commit
  tamper, task-doc truncation, pre-commit bash bypass, pre-existing-checks checkout) and the Stop
  **blocker** (completion-with-active-plans) are *enforcement* that does not exist at all without
  the hooks. An agent can — and will — do exactly what they forbid. Surface this honestly: Phase 1
  ships the *workflow skills*, not the *workflow enforcement*.

**Skill-driven fallback (Phase 1).** The full methodology is usable on demand: the agent invokes
`brainstorming` → `writing-plans` → `executing-plans` → `review-implementation` →
`verification-before-completion` when prompted or when its triggers fire, and `using-hyper` is
discoverable via its "starting any conversation" description. What is missing by design is (1)
forced bootstrap from turn 1 + re-injection after `/clear`/compact, and (2) the hard guardrails.

**Optional deterministic nudge (bake-time).** To approximate SessionStart's "bootstrap from turn
1" through the instruction channel the agent already reads, the Dockerfile may append a one-line
directive to the user-level instruction file — idempotently, so re-builds don't duplicate it:

```dockerfile
# Optional: nudge the agent to self-bootstrap, approximating the SessionStart injection (GAP 2).
RUN mkdir -p ~/.claude && grep -q 'hyperpowers' ~/.claude/CLAUDE.md 2>/dev/null \
    || printf '\n## Hyperpowers\nAt the start of every session, before your first response, invoke the `using-hyper` skill and follow its task-doc workflow. Keep substantial work grounded in local `plans/active/<slug>/` docs; delete the finished directory when the work is complete.\n' >> ~/.claude/CLAUDE.md
```

Caveat: harnessed has no merge mechanism for `~/.claude/CLAUDE.md` across recipes, so two recipes
both appending can collide; the `grep` guard keeps *this* recipe idempotent but not
composition-safe with others. Treat as optional — the skill-driven fallback is the primary path.

## Data model

Task docs are **local working state in the mounted project**: `plans/active/<slug>/plan.md`
(approved spec), `context.md` (discoveries/resume notes), `tasks.md` (rolling backlog: Now/Next/
Later/Blocked/Done). v2.8.3 made these explicitly **local-only** — upstream's own `.gitignore`
excludes `plans/active/*/`, and finished directories are *deleted*, not archived. They persist via
the project bind-mount (rw); no external store, no recipe action needed. Note `git clean -fdx`
deletes them (recover from `git log` of tracked `plans/` scaffolding only).

## Test stack

```yaml
# catalog/stacks/claude_hyperpowers/stack.yaml
name: claude_hyperpowers
harness: claude
recipes: [hyperpowers]
```

## Build / test lifecycle

```bash
harnessed build claude_hyperpowers   # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_hyperpowers         # launch the instance (harness + hatago)
harnessed test  claude_hyperpowers   # capability report: ✓ declared skills + commands present
```

Manual verification (the capability test only checks presence — verify the *behavior*):

- In the instance, `ls ~/.claude/skills` shows all 22 names; spot-check that a multi-file skill
  kept its subtree, e.g. `ls ~/.claude/skills/debugging-with-tools/resources` (debugger-reference.md),
  `ls ~/.claude/skills/refactoring-diagnosis/references` (smell-catalog.md, test-smells.md, …),
  `ls ~/.claude/skills/building-hooks/resources` (hook-examples/patterns/testing-hooks.md).
- `ls ~/.claude/commands` shows the 10 `.md` files; `ls ~/.claude/agents` shows the 5 subagents.
- Attach and ask "what skills do you have" / "tell me about hyperpowers" → the agent invokes
  `using-hyper` and lists/summarizes the suite.
- Drive one workflow end-to-end against a throwaway project dir: "let's build a small X" →
  `brainstorming` → it creates `plans/active/<slug>/plan.md`; "write a failing test first" →
  `test-driven-development`; on completion it should delete the finished `plans/active/<slug>/`
  directory (v2.8.3 local-only behaviour).
- **Confirm what's *missing* by design:** no SessionStart forced bootstrap (the agent
  self-bootstraps only with the optional CLAUDE.md nudge, else must be prompted to invoke
  `using-hyper`), and **none of the guardrails fire** — the agent is *not* blocked from editing
  `.git/hooks/pre-commit`, truncating task docs, or claiming completion with active task dirs.
  Both are GAP 2.

## Phasing

1. **Now (no feature):** ship recipe.yaml + Dockerfile as above. All 22 skills + 10 commands + 5
   agents are present and invokable. `using-hyper` is discoverable via its "starting any
   conversation" description; the rest load on demand. The workflow is fully usable on demand —
   the forced first-message bootstrap + re-injection after `/clear`/compact, and **all hard
   guardrails**, are the gaps. Include the optional CLAUDE.md nudge if the stack wants
   self-bootstrap from turn 1.
2. **When Claude-tool-hooks support lands (GAP 2):** the recipe gains a `hooks:` declaration for
   the five upstream hook groups. At that point extend the Dockerfile to also copy `hooks/` into
   a stable location (e.g. `~/.claude/plugins/hyperpowers/hooks/`) plus its data file
   `hooks/skill-rules.json`, and declare the hooks pointing at the **absolute** baked paths
   (rewriting `${CLAUDE_PLUGIN_ROOT}` — since we don't use the plugin system, that variable is
   unset; bake the real path into each hook command). Mind the runtimes: hook scripts are
   `.sh` (bash, ubiquitous), `.py` (python3 — ensure present; add via the recipe body if a
   harness image lacks it), and one `.js` (`user-prompt-submit/10-skill-activator.js` — needs
   Node, present in the `claude` base; add for Node-less harnesses). Mind the failure policy:
   PreToolUse/PostToolUse/Stop `block-*` hooks are **blocking** (exit non-zero to deny); the
   Stop `gentle-reminders` and SessionStart/UserPromptSubmit are non-blocking (emit context).
   This restores exact upstream behaviour.

> Note (repeat): the startup-hooks feature (`new_session`/`pre_agent`/`pre_session`) is a
> different mechanism and is **not** the vehicle for this — see the GAP 2 note above.

## Risks / checks

- **Pin gate:** confirm the fetch-by-SHA form passes the assembler's `PinValidationError` — it
  must (SHAs are accepted; `main`/`HEAD` rejected); verify at first `build`. There is **no tag
  fallback** — if the SHA pin is ever unwanted, the only options are a different commit SHA or
  waiting for upstream to tag. Flag the no-tags reality to the operator.
- **Layout vs. capability test:** the copy must put `skills/brainstorming` →
  `~/.claude/skills/brainstorming` (not `~/.claude/skills/hyperpowers/skills/…`). The
  `cp -r …/.` trailing-slash form does this; double-check the probe paths in `expect:` resolve.
- **Multi-file skill subtrees:** confirm sibling resources copied intact —
  `debugging-with-tools/resources/`, `refactoring-{design,diagnosis}/references/`,
  `refactoring-safely/resources/`, `building-hooks/resources/`, `skills-auto-activation/resources/`,
  `test-driven-development/resources/`, `writing-skills/{anthropic-best-practices.md,
  persuasion-principles.md, graphviz-conventions.dot, resources/}`. A shallow `SKILL.md`-only
  copy would break relative links.
- **Nested `skills/commands/` quirk:** verify the blanket `skills/.` copy does not shadow the
  real `~/.claude/commands/` fan-out (see Dockerfile notes); exclude it if it does.
- **No hidden runtime deps in Phase 1:** confirm none of the copied skills/commands needs Node or
  Python at runtime for their *on-demand* operation (the per-skill `agents/openai.yaml` under
  `.agents/` is Codex-only and not copied). Only the omitted hooks need those runtimes.
- **Harness portability:** skills are Markdown (universal). The `.md` slash-commands are
  Claude-Code-shaped; a non-Claude harness consuming `~/.claude/commands` in a different format
  may ignore them — the core skills still load via triggers. Verify per harness if shipping a
  non-`claude` stack.
- **GAP 2 impact is higher than for caveman, comparable to Superpowers:** the SessionStart hook
  injects the *bootstrap* (not a convenience flag), and several hooks are *hard blockers*. The
  degradation is "skills usable on demand, but no forced bootstrap and no enforcement." The
  CLAUDE.md nudge mitigates bootstrap for cooperative agents; full fidelity waits on GAP 2.
- **`plans/active/` is the user's project tree:** the skills write task docs into the mounted
  project. That is by design (local working state) but means hyperpowers *mutates the project
  dir* more than most skill recipes — operators should expect `plans/active/<slug>/` dirs (and,
  without the GAP-2 gitignore hook, they are NOT auto-gitignored outside a hyperpowers-aware
  repo). Note this in the stack description.
- **Upstream drift:** no tags means drift tracking is commit-by-commit; bumping
  `HYPERPOWERS_REF` re-clones the tree. Re-audit `expect:` if upstream renames/adds/removes a
  skill (the 22 are stable at v2.8.3; new skills appear as new `skills/<name>/SKILL.md` dirs).
- **Alternative shape (vendored, no Dockerfile):** carry the upstream `skills/`/`commands/`/
  `agents/` trees as committed files under the recipe dir and declare via `skills:`/`commands:`
  (file-extension layer) instead of a Dockerfile — same runtime, same GAP-2 gap, but requires
  re-vendoring ~50+ files per release. Dockerfile clone is recommended for lower maintenance
  (matches gstack/caveman/Superpowers).
