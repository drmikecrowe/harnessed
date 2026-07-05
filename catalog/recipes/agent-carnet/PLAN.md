# agent-carnet recipe — implementation plan

Goal: make `agent-carnet` available in a stack as a **shared, auto-expiring markdown notebook**
for the launched agent, with `.carnet/` living in the user's project folder and no git side effects.

Upstream: <https://github.com/yamadashy/agent-carnet> · npm `agent-carnet` (latest 0.1.5, MIT,
pure-JS bundled `.mjs`, no native binary). Node CLI (not an MCP server, not a daemon).

See `README.md` (this dir) for *why* each choice was made. This file is the *how*. Closest model:
`catalog/recipes/beads/PLAN.md` — the shapes are near-identical (CLI + skill + per-project state
dir + one-time `init:`).

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

Dockerfile recipe (bake the `agent-carnet` CLI **and** install its bundled upstream skill) + an
`init:` block that bootstraps `.carnet/` once per project. **No MCP, no service** — agent-carnet is
a CLI, not an MCP server.

```
catalog/recipes/agent-carnet/
  recipe.yaml
  Dockerfile            # bake the pinned agent-carnet CLI + install its bundled upstream skill
  PLAN.md  README.md
```

### recipe.yaml

```yaml
name: agent-carnet
description: agent-carnet — shared, auto-expiring file-based markdown notebook (.carnet/) for AI agents.
expect:
  skills: [agent-carnet]       # installed by the Dockerfile (upstream-bundled) — NOT recipe-authored
init:
  marker:
    scope: workspace
    location: in_repo
    name: .carnet
  run: agent-carnet init
```

This used to be a `hooks: new_session: {script, when_missing}` block — the **startup-hooks**
design (`docs/todos/2026-06-29-startup-hooks.md`), which was never implemented (no launcher code
ever consumed `hooks.new_session`; it only round-tripped as a forward-parsed field). `init:`
(marker + run, `src/harnessed/schema.py`/`launcher.py`) is the mechanism that actually runs —
`_run_init_for_stack` executes `run` in a one-shot transient container whenever the marker path is
absent, both from `harnessed init <stack>` and automatically on every `harnessed launch`. Beads
made the identical migration first; this recipe follows the same shape. (`hooks:` is no longer a
free-form forward field either — it's now typed for GAP 2, Claude-native `settings.json` hooks
invoked by Claude Code itself every time an event fires, a different mechanism from this
host-side, once-per-project `init:`.)

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
# references/{cookbook,frontmatter}.md). Copy it verbatim from the just-pinned global package into
# the container's ~/.claude/skills/agent-carnet — no second source, no floating ref.
#
# `pnpm root -g` does NOT contain a flat `agent-carnet/` subdir — pnpm's global store nests the
# package under a hashed import-context dir plus its own `node_modules/` (a symlink into pnpm's
# content-addressable store). Glob + take the first match rather than assume exactly one
# import-context hash; `cp -rL` dereferences the symlink into a real copy.
RUN mkdir -p "$HOME/.claude/skills" \
 && skill_src=$(printf '%s\n' "$(pnpm root -g)"/*/node_modules/agent-carnet/skills/agent-carnet | head -1) \
 && cp -rL "$skill_src" "$HOME/.claude/skills/agent-carnet" \
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

### Init: `agent-carnet init`, via `init:`

The `run` command is just `agent-carnet init` — no wrapper script needed (unlike beads, which
branches on `${HARNESS}` for its `bd setup <tool>` step). Git-free + non-touching: plain
`agent-carnet init` creates `.carnet/` and writes NO `.gitignore` entry, no git hooks, no repo
discovery — the `--gitignore` flag is intentionally omitted (mirrors beads' `--stealth` posture).
Idempotent, and the `.carnet` marker means a second launch against the same project skips the step
entirely.

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
save/find/read/used usage but does **not** teach `agent-carnet init`. Init is therefore `init:`'s
job, not the skill's. `--agent` is free-form CLI metadata (not enum-validated), so non-Claude
harnesses work functionally despite the Claude-centric skill text.

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
harnessed init  claude_carnet   # one-time bootstrap: runs `agent-carnet init` in the project (also
                                 # runs automatically on the first `harnessed launch`)
harnessed claude_carnet         # launch
harnessed test  claude_carnet   # capability report: ✓ agent-carnet (skill) present
```

Manual verification (the capability test only checks the skill is present — verify the *behaviour*):

- After launch against a fresh project dir, `.carnet/` exists in that dir on the **host** (persists
  via the project bind-mount) and is empty aside from the prune sweep's lazily-created `.trash/`.
- Re-launching the same project does NOT re-init (the `.carnet` marker is present) and does not
  touch git (`git status` clean; no `.gitignore` mutation; no hooks installed).
- `agent-carnet save … ` / `agent-carnet find … ` / `agent-carnet list` work inside the instance with
  zero git calls; a saved note's file is visible on the host at `<project>/.carnet/<cat>/<slug>.md`.

## Risks / checks

- **Node version gate:** the package requires `node >=22.13.0`. Confirm the base harness image's Node
  satisfies this at `harnessed build`; if a harness ships an older Node, the global add or runtime
  fails. This is the main build risk.
- **pnpm global bin on PATH:** verify `agent-carnet` resolves for the `harnessed` user after
  `pnpm add -g` (the `RUN agent-carnet --version` check exists for this). If pnpm's global bin isn't
  on PATH for `harnessed`, a `pnpm setup` / `PNPM_HOME` step may be needed (same class of risk beads
  flags).
- **`init` idempotency:** plain `agent-carnet init` must be a no-op when `.carnet/` already exists
  (the `init:` marker gate makes this belt-and-braces — a second launch skips the command entirely —
  but confirm `init` itself doesn't error or rewrite if ever invoked directly on an existing
  `.carnet/`). Verified-safe behaviour, not assumed.
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
