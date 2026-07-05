# caveman recipe — implementation plan

Goal: make caveman available in a stack as an **output-compression skill** — the agent speaks
terse "caveman" (drops articles/filler/pleasantries, keeps full technical accuracy), cutting
~75% of output tokens. On-demand via `/caveman` or natural-language triggers; intensity levels
`lite | full | ultra | wenyan-*`.

Upstream: <https://github.com/JuliusBrussee/caveman> · MIT · JavaScript repo (Node installer +
JS hooks, but the *deliverables* are pure Markdown/TOML). Latest tag **v1.9.0**
(commit `32f37af81a02a4b91c107b768f1365848e5bf005`); `main` HEAD floats and is rejected by the
pin gate.

> **Stress-test correction.** `docs/todos/2026-06-27-recipe-stress-test.md` §9 calls caveman
> "pure skills, no MCP, no hooks — cleanest possible recipe." That understates it: caveman ships
> as a full **Claude Code plugin** whose `.claude-plugin/plugin.json` declares `SessionStart` +
> `UserPromptSubmit` **hooks** (`src/hooks/caveman-activate.js`, `caveman-mode-tracker.js`). The
> skills themselves are hook-free and work on demand; the hooks only provide **auto-activation**
> (write a `.caveman-active` flag so the agent grunts from turn 1) + stats/statusline. Those are
> **Claude-tool-hooks = GAP 2** (settings.json/plugin hooks) — see Phasing for current status
> (GAP 2 is now implemented; this recipe uses it for a first-run reminder, not full parity yet).

## Recipe shape

**Dockerfile recipe** (clone the pinned tag, copy the upstream's Claude-canonical
`skills/` + `commands/` + `agents/` trees into `~/.claude/`), declared via `expect:`. **No MCP,
no service, no startup-hooks.** Mirrors `catalog/recipes/gstack/`.

Why this shape (each choice grounded in the upstream install docs):

- **Deliverables are already Claude-canonical.** The repo top level contains ready-to-fan
  `skills/<name>/SKILL.md` (7 skills), `commands/<name>.toml` (4 commands), `agents/<name>.md`
  (3 cavecrew subagents). Copying them into `~/.claude/{skills,commands,agents}` is exactly the
  file layout `claude plugin install caveman@caveman` drops — minus the plugin-registry wrapping.
- **We do NOT run the upstream installer (`bin/install.js`).** For each harness it delegates to a
  per-harness plugin system (`claude plugin marketplace add` / `gemini extensions install` /
  `npx skills add`/opencode native plugin). Those (a) bypass the assembler's harness-independent
  fan-out — every harness consumes the same `~/.claude/` profile, (b) need network + the harness
  binary at *build* time, and (c) wire `settings.json`/`plugin.json` hooks harnessed can't express
  today (GAP 2). Replicating the installer's **result** deterministically is the faithful move.
- **No Node needed.** The skills/commands/agents are pure Markdown/TOML. Only the JS hooks need
  Node, and we omit those (GAP 2). So no `apt`, no `pnpm`, no runtime dep — the lightest possible
  Dockerfile body.
- **Clone+copy over vendoring.** caveman ships ~14 files across 3 dirs and releases often
  (v1.0→v1.9). A pinned clone stays in sync by bumping one `ARG`; re-vendoring 14 files on every
  release is error-prone. (Vendored file-extension shape is a valid lighter alternative — see
  Risks.)

```
catalog/recipes/caveman/
  recipe.yaml
  Dockerfile          # clone pinned tag → copy skills/commands/agents into ~/.claude/
  PLAN.md
```

### recipe.yaml

```yaml
name: caveman
description: caveman — output-compression skill; agent speaks terse "caveman", ~75% fewer output tokens, full technical accuracy. Levels lite/full/ultra/wenyan.
expect:
  skills:   [caveman, caveman-compress, caveman-commit, caveman-review, caveman-stats]
  commands: [caveman]
```

- `expect:` (not `skills:`/`commands:` declarations) because the Dockerfile `RUN` bakes the trees
  directly into `~/.claude/` — the assembler can't see what a RUN step drops, so it lists a stable
  handful for the capability test to probe (exactly the gstack pattern). The full install also
  lands `caveman-help`, `cavecrew` (skill), `caveman-init`/`caveman-commit`/`caveman-review`
  (commands), and the 3 `agents/cavecrew-*` subagents.
- No `mcp:` (caveman is not an MCP server; the separate `caveman-shrink` npm proxy is opt-in and
  out of scope). No `hooks:` (GAP 2 — see Phasing).

### Dockerfile

```dockerfile
# caveman's deliverables are Claude-canonical skills/ + commands/ + agents/ trees. Clone the
# pinned release tag and copy them into ~/.claude/ — the exact layout `claude plugin install`
# drops, minus the plugin-registry wrapping and the Claude-tool hooks (GAP 2; see Phasing).
# We deliberately do NOT run bin/install.js: it delegates to per-harness plugin systems that
# bypass the assembler's harness-independent fan-out and wires settings.json hooks harnessed
# can't express. No Node needed — skills/commands/agents are pure Markdown/TOML.
USER harnessed
ARG CAVEMAN_REF=v1.9.0          # real release tag; pin-gate accepts tags (and SHAs), rejects main/HEAD
RUN set -euo pipefail; \
    git clone --quiet --depth 1 --branch "${CAVEMAN_REF}" \
        https://github.com/JuliusBrussee/caveman.git /tmp/caveman && \
    mkdir -p ~/.claude/skills ~/.claude/commands ~/.claude/agents && \
    cp -r /tmp/caveman/skills/.   ~/.claude/skills/ && \
    cp -r /tmp/caveman/commands/. ~/.claude/commands/ && \
    cp -r /tmp/caveman/agents/.   ~/.claude/agents/ && \
    rm -rf /tmp/caveman
# (body ends as USER harnessed — nothing here needs root)
```

Notes for the implementer:
- `--branch v1.9.0` is a **pinned tag** (passes the assembler pin gate). For maximum
  reproducibility use fetch-by-SHA as gstack does: `CAVEMAN_REF=32f37af81a02a4b91c107b768f1365848e5bf005`
  with `git init … && git remote add … && git fetch --depth 1 origin ${CAVEMAN_REF} && git checkout -q FETCH_HEAD`.
- No `FROM`, no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
  re-declares `ARG HARNESS`.
- Entirely as `USER harnessed` (writes only to `~/.claude/` + `/tmp`); no system install, so no
  `USER root` phase is needed. Confirm `~/.claude` is pre-created/writable in the base image
  (gstack assumes the same).

### (no service.yaml)

N/A — caveman has no long-running process, no port, no volume, no data store.

### (no hooks / skills content authored here)

The skills/commands/agents are vendored verbatim from upstream by the Dockerfile; this recipe
authors none of its own. The core `skills/caveman/SKILL.md` frontmatter already carries the
trigger phrases ("caveman mode", "talk like caveman", "less tokens", `/caveman`), so Claude
loads it on demand without any hook.

## Test stack

```yaml
# catalog/stacks/claude_caveman/stack.yaml
name: claude_caveman
harness: claude
recipes: [caveman]
```

## Build / test lifecycle

```bash
harnessed build claude_caveman   # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_caveman         # launch the instance (harness + hatago)
harnessed test  claude_caveman   # capability report: ✓ caveman (+ siblings) (skill) present, ✓ caveman (command) present
```

Manual verification (the capability test only checks presence — verify the *behavior*):

- In the instance, `ls ~/.claude/skills` shows `caveman caveman-compress caveman-commit caveman-help caveman-review caveman-stats cavecrew`; `ls ~/.claude/commands` shows the 4 `.toml` files.
- Attach and say "talk like caveman" or `/caveman` → the agent replies in terse fragments; code/
  error strings stay verbatim. `/caveman ultra` tightens further; "normal mode" reverts.
- **Confirm what's *missing* by design:** the agent does **not** auto-grunt from turn 1 (no
  `caveman-activate.js`-equivalent), and there is no `[CAVEMAN]` statusline badge or per-session
  stats counter. GAP 2 (the mechanism) now exists, but this recipe only uses it for a lightweight
  first-run reminder (below) — full upstream parity is a further step, see Phasing.
- **First-run reminder (GAP 2, now shipped):** on a fresh project, the first `SessionStart` prints
  a one-time nudge to run `/caveman-init`. Verify: launch against a brand-new project dir → the
  reminder appears once; re-launch (or a `SessionStart: resume/clear`) → silent, because
  `.claude/.caveman-notified` now exists in the project (check on the **host** — the project is
  bind-mounted, so this file is visible/inspectable there too).

## Phasing

1. **Shipped:** recipe.yaml + Dockerfile as above, PLUS a declarative `hooks: SessionStart:` entry
   (GAP 2 — `docs/todos/2026-06-27-recipe-stress-test.md`, implemented in `schema.py`/`emit.py`)
   that prints a one-time "run /caveman-init" reminder, gated by a marker file in the project (not
   the upstream JS hook — a plain `bash -lc` one-liner, no Dockerfile change, no Node dependency).
   caveman otherwise still activates **on demand** via `/caveman` or its trigger phrases.
2. **Future (full upstream parity, now unblocked but not done):** replicate the upstream
   SessionStart hook (`src/hooks/caveman-activate.js`, writes `.caveman-active` to auto-grunt from
   turn 1) + UserPromptSubmit hook (`src/hooks/caveman-mode-tracker.js`) + statusline
   (`caveman-statusline.{sh,ps1}`) verbatim. This needs the Dockerfile to additionally copy
   `src/hooks/*.js` into `~/.claude/hooks/` and declare both hooks in `recipe.yaml`, plus **Node at
   runtime** (present in the `claude` base image; other harnesses would need it added via the
   recipe body). Bigger lift than the reminder above for marginal behavioral gain — do this only if
   the on-demand + reminder combination proves insufficient in practice.

> Note: there is a **separate, unrelated** startup-hooks design (`docs/todos/2026-06-29-startup-hooks.md`,
> abandoned/never implemented — superseded by the working `init:` mechanism, see beads/agent-carnet).
> Don't confuse it with GAP 2: `init:` runs a command once, host-side, before the agent ever
> attaches; the `hooks:` field above is *Claude Code's own* hook runner, invoked from inside the
> instance every time the event fires.

## Risks / checks

- **Pin gate:** confirm `--branch v1.9.0` (or the SHA fetch form) passes the assembler's
  `PinValidationError` check — it must, tags/SHAs are accepted, but verify at first `build`.
- **Layout vs. capability test:** the copy must put `skills/caveman` → `~/.claude/skills/caveman`
  (not `~/.claude/skills/caveman/skills/caveman`). The `cp -r …/.` trailing-slash form does this;
  double-check the probe paths in `expect:` resolve.
- **No hidden runtime deps:** confirm none of the copied skills/commands needs Node at runtime.
  Only the hooks (omitted) and `caveman-stats` (reads the Claude Code session log + writes the
  statusline via JS) do — `/caveman-stats` will degrade without GAP 2; flag it in the skill if it
  errors rather than silently no-ops.
- **Harness portability:** skills are Markdown (universal). The `.toml` slash-commands are
  Claude-Code-shaped; a non-Claude harness that consumes `~/.claude/commands` in a different
  format may ignore them — the core skill still loads via its trigger phrases. Verify per harness
  if shipping a non-`claude` stack.
- **Upstream drift:** caveman tags frequently; bumping `CAVEMAN_REF` re-clones the latest trees —
  re-audit `expect:` if upstream renames/adds/removes a skill (the repo currently has 7 skills;
  the stress-test's `[caveman, caveman-compress, caveman-stats]` was a partial list).
- **Alternative shape (vendored, no Dockerfile):** if a zero-build recipe is preferred, carry the
  upstream `skills/`/`commands/`/`agents/` trees as committed files under the recipe dir and
  declare them via `skills:`/`commands:` (file-extension layer) instead of a Dockerfile — same
  runtime, same GAP-2 gap, but requires re-vendoring ~14 files per release. Dockerfile clone is
  recommended for lower maintenance.
