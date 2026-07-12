# `beads/stealth` — outside the repo, zero git footprint, embedded engine

> Read [the family README](../README.md) first — it covers what beads is, how to choose a variety,
> the shared three-step setup, config/`metadata.json` reference, and troubleshooting. This file
> covers only what is **specific to this variety**.

## When to use it

When beads must be **completely invisible** to the repo and its collaborators:

- Personal / dogfooding use — e.g. running an agent against a repo whose contributors don't use
  beads and must not see it. (harnessed's own repo is the canonical case.)
- `.beads/` never lives in the project at all: it is host-persisted **outside** the repo and
  bind-mounted in.
- Only one `bd` is ever live against the store — no host `bd`, no second container.

If a host `bd` or a second container will also be live, take
[`beads/stealth-server`](../stealth-server/README.md): the embedded engine's exclusive file lock
cannot be shared. If teammates need the issue graph, take [`beads/team`](../team/README.md).

## How it differs

| | |
| --- | --- |
| **Placement** | Outside the repo. `persist: {name: .beads, scope: project, location: host}` — host-persisted at `$XDG_DATA_HOME/harnessed/persist/beads/<git-common-dir-hash>/.beads/`, bind-mounted at `/home/harnessed/.beads`. `scope: project` (git-common-dir keyed) shares one DB across every worktree of a checkout but **not** across clones — the right behavior for a tracker that spans branches. |
| **Storage** | bd's **embedded** Dolt engine, in-process, inside the container. No `dolt` binary, no server, no sidecar — this is the only variety that bakes `bd` alone. |
| **Git** | None. `--stealth` is passed throughout: `bd init --stealth` configures `.git/info/exclude` and disables git operations. No hooks, no Dolt remote, no `AGENTS.md` mutation. |
| **`BEADS_DIR`** | Baked as a static `ENV BEADS_DIR=/home/harnessed/.beads`. The mount target is a **fixed** container path, not `$PWD`-relative, so the ENV never varies per project. |
| **Baked** | `bd` 1.1.0 only. |

### Why a Dockerfile `ENV`, not a shell export

A shell `export BEADS_DIR=…` in a hook script only affects that script's own process tree and is
lost before `bd` ever runs. A Dockerfile `ENV` reaches every process in the container
unconditionally. The fixed mount target is what makes the static ENV safe.

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-all-four).

```sh
bd init --quiet --stealth
bd setup <harness> --project --stealth
# restart the agent
```

`--stealth` on `bd setup` changes the hook's runtime behavior (`bd prime --stealth` instead of
`--hook-json`).

## Caveats

- **⚠️ "Stealth" is not fully footprint-free on bd 1.1.0.** `bd setup <tool> --project --stealth`
  still writes `.claude/settings.json` and `CLAUDE.md` into the project, and those two files are
  **not** in bd's stealth git-exclude list — they show up as untracked in `git status`. `bd init
  --stealth` only touches `.git/info/exclude`. You opt into that knowingly by choosing this variety.
- **Single writer.** The embedded engine takes an exclusive on-disk Dolt lock. A host `bd` and a
  container `bd` can never both hold a live engine against the same host-persisted store — the
  2026-07-05 lock collision. [`beads/stealth-server`](../stealth-server/README.md) is the fix.
- **No dependency subsystem on bd 1.1.0.** The embedded engine's `bd dep add` / `close` / `delete` /
  `stats` / `sql` / `doctor` are no-ops. If you need the dependency graph, use a server variety.
