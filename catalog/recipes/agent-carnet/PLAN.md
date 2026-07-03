# agent-carnet recipe — implementation plan

Goal: make `agent-carnet` available in a stack as a **shared, auto-expiring markdown notebook**
for the launched agent, with `.carnet/` living in the user's project folder and no git side effects.

Upstream: <https://github.com/yamadashy/agent-carnet> · npm `agent-carnet` (latest 0.1.5, MIT,
pure-JS bundled `.mjs`, no native binary). Node CLI (not an MCP server, not a daemon).

See `README.md` (this dir) for *why* each choice was made. This file is the *how*. Closest model:
`catalog/recipes/beads/PLAN.md` — the shapes are near-identical (CLI + skill + per-project state
dir + one-time init hook).

## Host-vs-recipe distinction (resolve up front)

`agent-carnet` **already exists as a host-level skill** at `~/.claude/skills/agent-carnet/` in this
harness — that is the *host* integration: the harness that is *planning this recipe* uses it on the
host machine. It does **not** propagate into a launched agent stack: a launched instance has its own
isolated `~/.claude/` assembled from the stack's recipe profile. This recipe's role is therefore to
**compose agent-carnet into a launched agent's container** — bake the CLI into the agent image,
install the **upstream-bundled skill** (shipped inside the pinned npm tarball) into the container's
`~/.claude/skills/agent-carnet`, and one-time-init `.carnet/` in the mounted project. It is not a
duplication of the host skill and not a recipe-authored mirror; it is the verbatim upstream skill, placed into the
different `~/.claude` namespace a launched agent actually sees. No `agent-carnet` recipe exists in
`catalog/recipes/` today (no overlap to merge away).

## Recipe shape

Dockerfile recipe (bake the `agent-carnet` CLI **and** install its bundled upstream skill) + a `new-session` hook that inits
`.carnet/`. **No MCP, no service** — agent-carnet is a CLI, not an MCP server.

```
catalog/recipes/agent-carnet/
  recipe.yaml
  Dockerfile            # bake the pinned agent-carnet CLI + install its bundled upstream skill
  hooks/
    new-session.sh      # agent-carnet init  (runs once, when .carnet/ is absent)
  PLAN.md  README.md
```

### recipe.yaml

```yaml
name: agent-carnet
description: agent-carnet — shared, auto-expiring file-based markdown notebook (.carnet/) for AI agents.
expect:
  skills: [agent-carnet]       # installed by the Dockerfile (upstream-bundled) — NOT recipe-authored
hooks:
  new_session:
    script: hooks/new-session.sh
    when_missing: .carnet      # fire only when the project has no .carnet/ yet
```

> `hooks.new_session` depends on the **startup-hooks** feature
> (`docs/todos/2026-06-29-startup-hooks.md`). If that feature is not yet built, init must be
> triggered out-of-band until it lands (see "Phasing").

### Dockerfile (bake `agent-carnet`)

agent-carnet is a **pure-JS Node CLI** bundled to `dist/bin/agent-carnet.mjs` — there is **no native
binary** release, so the npm/pnpm path is the *only* install path (simpler than beads, which also had
a release-binary option). The published tarball already ships `dist/`, so no build scripts are needed.

```dockerfile
# Pure JS — no apt/system deps, so the whole body runs as the unprivileged user (no USER root needed).
USER harnessed
# Pin to the exact published version (no @latest — assembler rejects floating refs). pnpm only.
ARG AGENT_CARNET_VERSION=0.1.5
RUN pnpm add -g agent-carnet@${AGENT_CARNET_VERSION}
# Verify the global bin resolves on PATH for the harnessed user before the layer is trusted.
RUN agent-carnet --version
# Install the skill agent-carnet BUNDLES in its npm tarball (skills/agent-carnet/: SKILL.md +
# references/{cookbook,frontmatter}.md). Copy it verbatim from the just-pinned global package into the
# container's ~/.claude/skills/agent-carnet — no second source, no floating ref. `pnpm root -g`
# resolves the global node_modules the line above populated; $HOME is the unprivileged user's.
RUN mkdir -p "$HOME/.claude/skills" \
 && cp -r "$(pnpm root -g)/agent-carnet/skills/agent-carnet" "$HOME/.claude/skills/agent-carnet" \
 && test -f "$HOME/.claude/skills/agent-carnet/SKILL.md"
```

Supply-chain notes:

- **Pinning** is the `@0.1.5` version; npm-registry integrity is enforced by pnpm itself, so there is
  no separate `checksums.txt` step (unlike the beads binary path). The package publishes **SLSA
  provenance attestations** from 0.1.1 onward (`registry.npmjs.org/agent-carnet` metadata) — a
  supply-chain plus; confirm the attestation is present at the pinned version if you want to assert it.
  The 0.1.5 tarball's `gitHead` is `1e12629d6bfb9bd35e859b5dedd62aa64d6b7616` (provenance only — the
  npm version is the load-bearing pin; no separate git clone, hence no floating-ref surface).
- **Skill source = the pinned tarball.** `agent-carnet@0.1.5` ships `skills/agent-carnet/` (SKILL.md +
  references/{cookbook,frontmatter}.md) inside the published package, so the same `@0.1.5` pin covers
  CLI *and* skill from one immutable npm artifact — strictly better than a separate
  `git clone yamadashy/agent-carnet` (a second ref to pin + a second integrity boundary) or
  `pnpm dlx skills add yamadashy/agent-carnet` (fetches by org/repo, a floating ref the assembler pin
  gate rejects). The `cp -r` above is deterministic: pnpm resolves the global install to exactly 0.1.5,
  then copies the bundled dir verbatim.
- **`emit` lint rejects raw `npm`/`npx`** — use `pnpm` everywhere, including in comments.
- **Engine gate:** the package declares `engines.node >=22.13.0`. Confirm the base harness image's
  Node meets this (see Risks). agent-carnet uses `--run`-style modern Node scripts upstream; an older
  Node will fail the global add or the runtime.

### hooks/new-session.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
# Runs once, in the mounted project dir ($PWD = project root), the first time this project is opened
# (when .carnet/ is absent). Git-free + non-touching: plain `agent-carnet init` creates .carnet/ and
# writes NO .gitignore entry, no git hooks, no repo discovery — the --gitignore flag is intentionally
# omitted (mirrors beads' --stealth posture). Idempotent — and additionally gated by when_missing, so
# re-launches never reach here.
agent-carnet init
```

### Skill (installed, not authored)

The recipe does **not** ship a recipe-local skill — a recipe MUST NOT author or mirror one. agent-carnet
**bundles** its Claude skill in the npm tarball at `skills/agent-carnet/` (`SKILL.md` +
`references/{cookbook,frontmatter}.md`), and the Dockerfile above installs it **verbatim from the
pinned `agent-carnet@0.1.5` package** into `~/.claude/skills/agent-carnet/`. There is nothing to write
here: the `expect: { skills: [agent-carnet] }` capability test resolves the dir the Dockerfile
populates, and one immutable npm artifact is both the CLI pin and the skill pin (no second git clone,
no floating `skills add yamadashy/agent-carnet` ref).

A note on what the upstream skill contains (so the recipe's other sections stay honest about it): it
is a Claude-Code-first skill — its hard rules and examples pass `--agent claude-code`, and it covers
save/find/read/used usage but does **not** teach `agent-carnet init`. Init is therefore the
new-session hook's job (see "Phasing" for the no-hooks case). `--agent` is free-form CLI metadata
(not enum-validated), so non-Claude harnesses work functionally despite the Claude-centric skill text.

## Test stack

```yaml
# catalog/stacks/claude_carnet/stack.yaml
name: claude_carnet
harness: claude
recipes: [agent-carnet]
```

## Build / test lifecycle

```bash
harnessed build claude_carnet   # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_carnet         # launch; new-session hook runs `agent-carnet init` in the project
harnessed test  claude_carnet   # capability report: ✓ agent-carnet (skill) present
```

Manual verification (the capability test only checks the skill is present — verify the *behaviour*):

- After launch against a fresh project dir, `.carnet/` exists in that dir on the **host** (persists
  via the project bind-mount) and is empty aside from the prune sweep's lazily-created `.trash/`.
- Re-launching the same project does NOT re-init (sentinel present) and does not touch git
  (`git status` clean; no `.gitignore` mutation; no hooks installed).
- `agent-carnet save … ` / `agent-carnet find … ` / `agent-carnet list` work inside the instance with
  zero git calls; a saved note's file is visible on the host at `<project>/.carnet/<cat>/<slug>.md`.

## Phasing

1. **If startup-hooks is built:** ship recipe.yaml + Dockerfile + `hooks/new-session.sh`. Init is
   automatic and deterministic; the Dockerfile installs the CLI and the verbatim upstream skill.
2. **If not yet:** the recipe genuinely depends on startup-hooks for init — the upstream skill covers
   save/find/read/used usage but does **not** teach `agent-carnet init`, and we install it verbatim
   (so we cannot inject that instruction). Ship the Dockerfile + recipe.yaml and trigger init
   out-of-band (a one-shot `agent-carnet init` in the project, or the harness's own first-run) until
   the hook feature lands; add the hook the moment startup-hooks ships.

## Risks / checks

- **Node version gate:** the package requires `node >=22.13.0`. Confirm the base harness image's Node
  satisfies this at `harnessed build`; if a harness ships an older Node, the global add or runtime
  fails. This is the main build risk.
- **pnpm global bin on PATH:** verify `agent-carnet` resolves for the `harnessed` user after
  `pnpm add -g` (the `RUN agent-carnet --version` check exists for this). If pnpm's global bin isn't
  on PATH for `harnessed`, a `pnpm setup` / `PNPM_HOME` step may be needed (same class of risk beads
  flags).
- **`init` idempotency:** plain `agent-carnet init` must be a no-op when `.carnet/` already exists
  (the `when_missing` gate makes this belt-and-braces, but confirm `init` doesn't error or rewrite on
  a second run). Verified-safe behaviour, not assumed.
- **`--agent` is Claude-centric in the upstream skill text:** the verbatim upstream skill lists
  `--agent claude-code` as a hard rule and uses it in every example, and the recipe installs it
  unmodified (a recipe MUST NOT author/mirror the skill — upstream ships it). Functionally this is
  fine for non-Claude harnesses: `--agent` is free-form metadata the CLI does **not** validate against
  an enum, so omp/opencode/gemini/antigravity/codex can pass their own identity. The only residual is
  cosmetic — the skill's instructional text reads Claude-first. Do not fork the skill to "fix" it.
- **Concurrency:** agent-carnet is a per-command CLI with no daemon and no lock server (unlike beads'
  embedded-Dolt single-writer lock). Two instances writing the **same** slug could race on the file
  write; different slugs are independent. Lower risk than beads; no hardening is needed for the normal
  one-instance-per-project case (the risk is documented here — the verbatim upstream skill does not cover it).
- **Auto-prune side effect:** every CLI invocation sweeps `.carnet/` and may move notes to `.trash/`.
  For a *shared, git-tracked* notebook this can silently drop other contributors' idle notes; upstream
  recommends `AGENT_CARNET_AUTO_PRUNE=false` + `agent-carnet prune --auto` from CI for that mode. The
  recipe ships the default (auto-prune on) — appropriate for a single-agent-per-project harness; note
  the alternative if a project commits `.carnet/`.
