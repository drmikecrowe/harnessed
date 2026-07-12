# `beads/stealth` — `.beads/` outside the repo, zero git footprint

> Read [the family README](../README.md) first — it covers what beads is, the one question that picks
> a recipe, why there is no embedded mode, the shared three-step setup, and troubleshooting. This file
> covers only what is **specific to this recipe**.

## When to use it

When beads must be **completely invisible** to the repo and its collaborators:

- Personal / dogfooding use — e.g. running an agent against a repo whose contributors don't use beads
  and must not see it. (harnessed's own repo is the canonical case.)
- `.beads/` never lives in the project at all: it is host-persisted **outside** the repo and
  bind-mounted in.

If teammates need the issue graph, take [`beads/team`](../team/README.md) — the *only* difference is
where `.beads/` lives.

Any number of agent containers may run against the project at once: they are all clients of the same
`beads-server`, so there is no lock to contend.

## How it differs

| | |
| --- | --- |
| **Placement** | Outside the repo. `persist: {name: .beads, scope: project, location: host}` — host-persisted at `$XDG_DATA_HOME/harnessed/persist/beads-stealth/<git-common-dir-hash>/.beads/`, bind-mounted at `/home/harnessed/.beads`. `scope: project` (git-common-dir keyed) shares one DB across every worktree of a checkout but **not** across clones — the right behavior for a tracker that spans branches. |
| **Storage** | The `beads-server` service — one `dolt sql-server` per project — which bind-mounts *that host dir* as its data dir, because this recipe declared `.beads` `location: host`. bd is a pure client over a unix socket; it never starts an engine. |
| **Git** | None. `--stealth` is passed throughout: `bd init --stealth` configures `.git/info/exclude` and disables git operations. No hooks, no Dolt remote, no `AGENTS.md` mutation — and so **no sync**: `harnessed svc sync beads-server` is a [`beads/team`](../team/README.md) affordance. The data lives on the host and stays there. |
| **`BEADS_DIR`** | Baked as a static `ENV BEADS_DIR=/home/harnessed/.beads`. The mount target is a **fixed** container path, not `$PWD`-relative, so the ENV never varies per project — and the server serves its socket from inside that same dir. |
| **Baked** | `bd` 1.1.0 only. No `dolt` binary — bd never runs an engine here. |

### Why a Dockerfile `ENV`, not a shell export

A shell `export BEADS_DIR=…` in a hook script only affects that script's own process tree and is lost
before `bd` ever runs. A Dockerfile `ENV` reaches every process in the container unconditionally. The
fixed mount target is what makes the static ENV safe.

## Stack wiring

```yaml
recipes:  [beads/stealth]
services: [beads-server]     # REQUIRED — without it there is no server and no socket to connect to
```

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-both).
Migrating a project that predates the server? Same command — see
[Migrating](../README.md#migrating-a-project-that-predates-the-server).

```sh
bd init --stealth --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET" \
        --quiet --non-interactive
bd setup <harness> --project --stealth
# restart the agent
```

`$HARNESSED_BEADS_SERVER_SOCKET` is exported into the attach shell by the launcher
(`launcher.svc_socket_env`). `--stealth` on `bd setup` changes the hook's runtime behavior
(`bd prime --stealth` instead of `--hook-json`).

## Caveats

- **⚠️ "Stealth" is not fully footprint-free on bd 1.1.0.** `bd setup <tool> --project --stealth` still
  writes `.claude/settings.json` and `CLAUDE.md` into the project, and those two files are **not** in
  bd's stealth git-exclude list — they show up as untracked in `git status`. `bd init --stealth` only
  touches `.git/info/exclude`. You opt into that knowingly by choosing this recipe.
- **The dependency subsystem works again.** On bd 1.1.0 the *embedded* engine's `bd dep add` / `close`
  / `delete` / `stats` / `sql` / `doctor` are no-ops. This recipe used to run embedded; it no longer
  does, so that limitation is gone — a second, independent reason the embedded engine is not shipped.
