# `beads/team` — in-repo, git-tracked, per-container Dolt server

> Read [the family README](../README.md) first — it covers what beads is, how to choose a variety,
> the shared three-step setup, config/`metadata.json` reference, and troubleshooting. This file
> covers only what is **specific to this variety**.

## When to use it

Beads' own default operational mode, and the right default for a project **team**:

- Teammates need to see and sync the issue graph.
- `.beads/` is committed to the repo, like any other project file.
- Only one `bd` at a time holds the database — a single agent instance per project checkout, no host
  `bd` running against the same store.

If a host `bd` (or a second container) will also be live against this project, take
[`beads/team-server`](../team-server/README.md) instead — an embedded engine cannot share its lock.
If the repo must stay clean, take [`beads/stealth`](../stealth/README.md).

## How it differs

| | |
| --- | --- |
| **Placement** | In-repo. `persist: {name: .beads, scope: workspace, location: in_repo, vcs: tracked}` — already inside the project's own mount, so no extra bind-mount, and harnessed takes **no** `.gitignore` action: the dir is meant to be committed. (bd manages its own finer-grained exclusions, e.g. the Dolt data dir.) |
| **Storage** | bd's **server** storage engine — a managed **per-container** `dolt sql-server` on loopback, pidfile-managed, data under `.beads/dolt/`. Not a shared service, and *not* the embedded engine. |
| **Git** | `bd init` installs git hooks (agent-identity commit trailers) and auto-wires the git `origin` as a Dolt remote, so `bd dolt push` / `bd dolt pull` sync issue data. Beads data lives under `refs/dolt/data` — **not** a git branch, so protected-`main` workflows are untouched. |
| **`BEADS_DIR`** | Not set. `.beads/` lives inside a work tree at whatever path the project is mounted at, so a static `ENV` would be wrong the moment that moved. bd's own discovery (walk up from cwd) is used. |
| **Baked** | `bd` 1.1.0 + `dolt` 2.1.10 (the server engine shells out to a real `dolt` binary). |

### Why the server engine, not embedded

On bd 1.1.0 the **embedded** engine's dependency subsystem (`bd dep add` / `close` / `delete` /
`stats` / `sql` / `doctor`) is a no-op, and its shared-file lock contends under a bare + linked-worktree
layout. The managed server engine has neither problem: dependency edges survive a server
stop/restart with `dolt.auto-commit on`. That is why the setup summary turns auto-commit on — every
write (including dependency edges, which are *not* in `issues.jsonl`) is persisted to the Dolt store.

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-all-four).

```sh
bd init --server --quiet --non-interactive --role maintainer && bd config set dolt.auto-commit on
bd setup <harness> --project
# restart the agent
```

`--non-interactive` is required: bd's `--team` / `--contributor` flags are interactive-only wizards
and are explicitly rejected without a TTY, so they cannot be scripted. `--role maintainer` is the
sensible default for a project's home repo; a contributor on an OSS fork should run
`bd init --role contributor` manually instead.

## Caveats

- **Real git footprint, by design.** This variety installs git hooks and commits `.beads/`. That is
  the point — but pick [`beads/stealth`](../stealth/README.md) if it isn't what you want.
- **Bare + linked-worktree layouts need a manual `BEADS_DIR`.** bd anchors its shared `.beads` to the
  git *common dir*, which in a bare setup is the bare repo — a directory with **no work tree**.
  `.beads/` then lands where nothing can `git add` it and auto-export fails with "this operation must
  be run in a work tree". The recipe ships no `bd-resolve-beads-dir` helper; export the path yourself
  before initializing:

  ```sh
  export BEADS_DIR=/path/to/main-worktree/.beads
  bd init --server --quiet --non-interactive --role maintainer
  ```

  [`beads/stealth`](../stealth/README.md) sidesteps this entirely by keeping `.beads` off the repo.
- **Single live engine.** The per-container server still owns the on-disk Dolt store exclusively. Two
  instances against one checkout contend — that is what [`beads/team-server`](../team-server/README.md)
  exists to fix.
