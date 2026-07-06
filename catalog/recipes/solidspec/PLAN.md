# solidspec recipe — implementation plan

Goal: make the `solidspec` CLI available in a stack and teach its multi-methodology
spec-driven workflow, with `.solidspec/` + project-scoped slash commands bootstrapped once
per project. No MCP, no service.

Upstream: <https://github.com/jyjeanne/solidspec> · Rust (edition 2024) · MIT · **v0.3.0**
(the only published tag; `master` HEAD is ahead of it — there are unreleased commits). ~6
stars; **early / immature — see Risks.**

## Recipe shape

Dockerfile recipe (bake the `solidspec` CLI) + a `new-session` hook that runs
`solidspec init`. Like beads: a pure CLI is not an MCP server, but its per-project
bootstrap needs the mounted project, which a build-time Dockerfile cannot reach.

> The recipe ships no skill — upstream offers none (`init` writes slash commands + an
> AGENT.md into agent dirs, not a `~/.claude/skills` dir); a user may add one later.

- **CLI is a Rust binary** → bake at build time. The base image already ships
  `rust@1.87` via mise (`catalog/base/Dockerfile.harnessed-base:81`); edition 2024 needs
  Rust ≥ 1.85, so the toolchain is sufficient. No rustup step.
- **Per-project init** — `solidspec init --here` creates `.solidspec/`, `specs/`,
  `solidspec.toml`, an `AGENT.md`, and registers slash commands into the project's
  `.claude/commands/solidspec-*.md` (and other agent dirs it detects). That all lives in
  the **mounted project**, which is absent at build time → `new-session` hook (the agent
  runs init directly if the hook is absent — see Phasing). The stress-test verdict ("no
  hooks") was under-analyzed: init is a runtime, per-project operation, exactly the beads
  case.

```
catalog/recipes/solidspec/
  recipe.yaml
  Dockerfile
  hooks/
    new-session.sh        # solidspec init --here --no-git (once, when .solidspec/ is absent)
  PLAN.md
```

> Project-level slash commands (`.claude/commands/solidspec-*.md`) come from `solidspec init`
> at runtime, **not** from this recipe. They are project-scoped and version-controlled with
> the user's repo. The recipe ships no home-scoped skill; agent discoverability comes from
> the slash commands init drops (upstream's concern) or a skill the user adds later.

### recipe.yaml

```yaml
name: solidspec
description: solidspec — multi-methodology spec-driven development CLI (spec → plan → tasks → implement → ship).
hooks:
  new_session:
    script: hooks/new-session.sh
    when_missing: .solidspec     # fire only when the project has no .solidspec/ yet
```

> `hooks.new_session` depends on the **startup-hooks** feature
> (`docs/todos/2026-06-29-startup-hooks.md`). If it is not yet built, the agent runs
> `solidspec init` directly on first use (no skill is shipped — see "Phasing"). There is no
> `harnesses:` field — an obsolete stress-test shape; the binary's presence is verified
> manually (the Dockerfile bakes nothing the assembler can see).

### Dockerfile (bake `solidspec`)

The README's only documented install is **build-from-source** (`git clone` +
`cargo build --release`); there are no GitHub release binaries and crates.io publish is
**not confirmed** (the README never references `cargo install solidspec`; crates.io is
anti-scrape). The pin-safe equivalent that needs no crates.io publish is
`cargo install --git … --tag`. **Pin to the exact tag `v0.3.0`** — the assembler rejects
floating refs (`@latest`/`:latest`/`--branch main`).

```dockerfile
USER root
# git2 (libgit2-sys) builds libgit2 from source at install time and needs cmake + pkg-config;
# the base image has libssl-dev + zlib1g-dev but NOT cmake/pkg-config. Without this, the
# cargo build fails resolving the git2 dependency.
RUN apt-get update && apt-get install -y --no-install-recommends cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*
USER harnessed
ARG SOLIDSPEC_REF=v0.3.0
RUN cargo install --git https://github.com/jyjeanne/solidspec --tag ${SOLIDSPEC_REF} \
    && solidspec --version
```

- `USER root` only for the apt step; drop to `USER harnessed` before `cargo install` so the
  cargo home / binary live under the unprivileged user. `cargo install` places the binary in
  `~/.cargo/bin`, already on PATH via mise's rust shim.
- `solidspec --version` after install proves the build (and exercises the binary). This is
  the build-time acceptance check; the assembler pin gate runs here too.

### hooks/new-session.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
# Runs once, in the mounted project dir ($PWD = project root), the first time a project is
# opened (when .solidspec/ is absent). Bootstraps the spec scaffolding + agent slash commands.
# --no-git: never `git init` the user's project (init does so by default on non-repos). An
#   existing git repo is untouched; solidspec's git features still work because the project
#   already has .git. mkdir .claude first so init registers slash commands — init only
#   registers into agent dirs that already exist (it warns + skips otherwise).
mkdir -p .claude
solidspec init --here --no-git
```

> init is idempotent and non-destructive (templates/constitution *preserve existing*;
> embedded scripts *always overwrite*; a `--force` flag exists), so re-runs are safe — but
> the `when_missing: .solidspec` sentinel means it only fires once anyway.

## Test stack

```yaml
# catalog/stacks/claude_solidspec/stack.yaml
name: claude_solidspec
harness: claude
recipes: [solidspec]
```

## Build / test lifecycle

```bash
harnessed build claude_solidspec   # assemble + build derived image (supply-chain pin gate + cmake/cargo build run here)
harnessed claude_solidspec         # launch; new-session hook runs `solidspec init --here --no-git` in the project
harnessed test  claude_solidspec   # capability report — no skill shipped; verify the CLI binary manually (below)
```

Manual verification (the capability report lists no skill — verify the *behavior*
directly):

- `solidspec --version` prints `0.3.0` inside the instance (proves the bake + cmake step).
- After launch against a fresh project dir, `.solidspec/`, `specs/`, and `solidspec.toml`
  exist **in that dir on the host** (persist via the project bind-mount), and
  `<project>/.claude/commands/solidspec-*.md` slash commands are present.
- Re-launching the same project does **not** re-init (`.solidspec/` sentinel present) and
  does **not** mutate git (`git status` clean; no `git init` on a repo or non-repo thanks to
  `--no-git`; the user's `AGENT.md` is the only init-created file in the project root —
  confirm that is acceptable / gitignore it if not).

## Phasing

1. **If startup-hooks is built:** ship recipe.yaml + Dockerfile + `hooks/new-session.sh`.
   Init is automatic and deterministic.
2. **If not yet:** ship recipe.yaml (no `hooks:`) + Dockerfile only; the agent runs
   `solidspec init --here --no-git` (after `mkdir -p .claude`) directly on first use of any
   `/solidspec-*` command (no skill is shipped to teach this — the agent uses the CLI/slash
   commands directly). Add the hook once the feature lands.

## Risks / checks

- **⚠ Early / immature (primary risk).** ~6 stars, a single published tag (`v0.3.0`),
  `master` HEAD ahead of the tag (unreleased work), no release binaries, and crates.io
  publish unconfirmed. Pin deliberately to `v0.3.0`; re-pin deliberately on the next tag and
  re-run `harnessed build` (the cargo build from a moving source tree can shift behavior
  between minors). Treat the API/workflow surface as unstable. The hook-driven recipe
  (Phasing 1) is the safe default; the manual-init path (Phasing 2) is the fallback if
  startup-hooks is not yet built.
- **Build deps.** The `git2 = "0.21"` dependency pulls libgit2-sys, which builds libgit2 from
  source and needs `cmake` + `pkg-config`; the base image has neither (it has `build-essential`,
  `libssl-dev`, `zlib1g-dev`). Resolve at `harnessed build` — if the cargo step fails on
  libgit2, confirm the apt line installs both and that `libssh2`/`libgit2` vendored builds
  succeed under `rust@1.87`.
- **Init side effects.** `solidspec init` runs `git init` on a non-repo by default — the hook
  passes `--no-git` so the user's project git state is never mutated. Verify on a non-git
  project that no `.git` appears, and on a git project that `git status` is clean after init.
- **Agent-dir detection.** `init` registers slash commands **only into agent dirs that already
  exist** (`.claude/`, `.cursor/`, …); with none present it warns and registers nothing. The
  hook `mkdir -p .claude` covers the claude harness (the tested path). For other harnesses the
  matching project dir differs (gemini→`.gemini`, codex→`.codex`, opencode→`.opencode`, …); the
  hook should map `${HARNESS}` → its dir once the startup-hooks env question
  (`docs/todos/2026-06-29-startup-hooks.md` open Q2) settles, defaulting to `.claude`.
- **Project vs home layering.** Do not duplicate the slash commands into this recipe's
  `commands/` dir (home-scoped, all-projects) — they are deliberately project-scoped and
  version-controlled by init. The recipe ships no home-scoped artifact at all (no skill, no
  commands); the CLI + hook are the entire recipe surface.
- **Re-runnability.** init is re-runnable (templates preserve existing, scripts overwrite,
  `--force` exists) — low risk, and the `when_missing` sentinel fires it once regardless.
