# beads recipe — design choices

This recipe makes `bd` ([beads](https://github.com/gastownhall/beads)) available in a stack as
**local-first, git-free** persistent task memory for agents, with `.beads/` living in the user's
project folder. This file records the decisions and *why*; `PLAN.md` is the implementation how-to.

## What beads is

`bd` is a CLI graph issue tracker for coding agents — dependency-aware tasks, auto-ready detection,
hash-based IDs, and persistent project memory (`bd remember` / `bd prime`). It is **not** an MCP
server; it is a binary the agent shells out to. Storage is [Dolt](https://github.com/dolthub/dolt)
(a versioned SQL DB), bundled into the binary.

## Decisions

### Embedded mode, no Dolt server

beads' default and recommended mode runs Dolt **in-process** (data in `.beads/embeddeddolt/`,
single-writer file lock) — no external `dolt sql-server`. This matches harnessed's one-instance-
per-project model. Server mode would force a long-lived `dolt sql-server` sidecar (a harnessed
`service:` with its own port + healthcheck) to buy multi-writer concurrency we do not need.
**Chosen: embedded.** Trade-off: single-writer — two instances on the same project dir contend.

### Git-free + stealth, `.beads/` in the project folder

The harnessed launcher bind-mounts the project root at its host path
(`launcher.py` "Path mirroring"), so a `.beads/` created at runtime in the project dir **persists on
the host across instance teardown** — persistence with nothing baked into an image. We run
`bd init --quiet --stealth`: `--stealth` sets `no-git-ops: true`, disabling git hook installation,
git operations, and (per beads' docs) the default `AGENTS.md` mutation. We set
`BEADS_DIR="$PWD/.beads"` to pin the location deterministically and bypass git repo discovery.

Why git-free:
- The user's git history and hooks stay clean; beads' git machinery can't collide with harnessed's
  own git / egress-firewall setup.
- `.beads/` is the agent's private, project-local task memory. The user gitignores it.

### Init via a `new-session` hook, not the agent, not Claude's hooks

`bd init` must run **at runtime against the mounted project** (the project isn't mounted at build
time, so a Dockerfile `RUN bd init` is impossible and would bake a stale `.beads`). Three ways to
trigger it:

1. **`new-session` startup hook (chosen).** The launcher runs `hooks/new-session.sh` once, the first
   time a project is opened (gated on `.beads/` being absent). Init is **deterministic** — it does
   not depend on the LLM choosing to run a command. Requires the startup-hooks feature
   (`docs/todos/2026-06-29-startup-hooks.md`); beads is its first consumer.
2. *Agent-driven (fallback).* The agent has the `bd` CLI available and runs `bd init` on first use.
   Works with zero core changes but is nondeterministic — the agent might not. Used only until the
   hook lands.
3. *Claude `SessionStart` hook (rejected).* beads' own `bd setup claude` installs Claude hooks, but
   that binds the recipe to one harness and fights harnessed's managed `settings.json`. Recipes are
   harness-independent; the launcher-level hook runs via `bash` regardless of agent — the right
   layer.

### No skill shipped

`bd` ships no standalone Claude skill — its agent-discovery mechanism is `AGENTS.md` mutation,
which `--stealth` suppresses (and we never write into the user's `AGENTS.md` from a recipe). This
recipe therefore authors no skill: the agent has the `bd` CLI and runs it directly (`bd help`,
`bd prime`). A user may add a workflow skill later if they want to teach the workflow explicitly.

### Install: pin everything

The upstream `curl install.sh | bash` pulls "latest" — a floating ref the assembler's pin gate
rejects, and poor hygiene. We pin to an exact version. Preferred: download the **pinned release
binary and verify its checksum** against the release `checksums.txt` (deterministic, and it matches
beads' own security guidance). Alternative: `pnpm add -g @beads/bd@<version>` (pnpm per repo
convention) — with the caveat that pnpm may skip the package's binary-fetch postinstall, so the
build must verify `bd` actually runs.

### No MCP, no service

beads is a CLI. The recipe contributes a Dockerfile body (bake `bd`) and a hook — no `mcp:` block,
no hatago entry, no `service:` sidecar.

## Caveats

- **Single-writer:** embedded Dolt locks the file; one instance per project dir.
- **Idempotency:** the `new-session` hook is idempotent (`bd init` no-ops if `.beads/` exists), so
  re-creates (`--fresh`) are safe.
- **Stealth scope:** verify `--stealth` fully suppresses git side effects in a project that is a git
  repo (the mounted project usually carries `.git`).

## References

- Upstream README & docs: <https://github.com/gastownhall/beads>
- Storage modes (embedded vs server): README "Storage Modes"
- Git-free usage (`BEADS_DIR`, `--stealth`): README "Git-Free Usage"
- Startup-hooks feature this recipe drives: `docs/todos/2026-06-29-startup-hooks.md`
- Recipe authoring model: `docs/guides/recipe-authoring.md`
