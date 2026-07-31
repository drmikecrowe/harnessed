# `beads/team` — `.beads/` in the repo, git-tracked

> Read [the family README](../README.md) first — it covers what beads is, the one question that picks
> a recipe, why there is no embedded mode, the shared three-step setup, and troubleshooting. This file
> covers only what is **specific to this recipe**.

## When to use it

Beads' own default operational mode, and the right default for a project **team**:

- Teammates need to see and sync the issue graph.
- `.beads/` is committed to the repo, like any other project file.

If the repo must stay clean, take [`beads/stealth`](../stealth/README.md) — the *only* difference is
where `.beads/` lives.

Any number of agent containers may run against the project at once. They are all clients of the same
`beads-server`, so there is no lock to contend (that was the 2026-07-05 incident; see the family
README).

## How it differs

| | |
| --- | --- |
| **Placement** | In-repo, git-tracked. `persist: {name: .beads, scope: project, location: in_repo, vcs: tracked}` — already inside the project's mount, so no extra bind-mount for agents, and harnessed takes **no** `.gitignore` action: the dir is meant to be committed. (bd manages its own finer-grained exclusions, e.g. the Dolt data dir.) |
| **Storage** | The `beads-server` service — one `dolt sql-server` per project — which bind-mounts *this* `.beads/` as its data dir, because this recipe declared it `in_repo`. bd is a pure client over a unix socket; it never starts an engine. |
| **Git** | `bd init` installs git hooks (agent-identity commit trailers) and auto-wires the git `origin` as a Dolt remote. Issue history lives under `refs/dolt/data` — **not** a git branch, so protected-`main` workflows are untouched. |
| **Baked** | `bd` 1.1.0 only. No `dolt` binary: bd never runs an engine here, and the sync that needs the dolt CLI runs in the server container. |

## Stack wiring

```yaml
recipes:  [beads/team]
services: [beads-server]     # REQUIRED — without it there is no server and no socket to connect to
```

## Setup — step 1

Then follow steps 2 and 3 from [the family README](../README.md#setup--the-same-shape-for-both).
Migrating a project that predates the server? Same command — see
[Migrating](../README.md#migrating-a-project-that-predates-the-server).

```sh
bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET" \
        --quiet --non-interactive --role maintainer
bd config set dolt.auto-commit on
```

- `$HARNESSED_BEADS_SERVER_SOCKET` is exported into the attach shell by the launcher
  (`launcher.svc_socket_env`) — no path arithmetic needed.
- `--external` means bd connects but never starts or stops the server; that is the service's job.
- `--non-interactive` is required: bd's `--team` / `--contributor` flags are interactive-only wizards,
  explicitly rejected without a TTY. `--role maintainer` is the sensible default for a project's home
  repo; a contributor on an OSS fork should run `bd init --role contributor` instead.
- `dolt.auto-commit on` persists every write — including dependency edges, which are *not* in
  `issues.jsonl`.

## Git sync is a HOST command

```sh
harnessed svc sync beads-server --stack <stack>     # execs `bd dolt push` in the server container
```

**Not** `bd dolt push` inside the agent. bd's push shells out to the `dolt` CLI, which routes only to
a server on *its own* loopback — from an agent container it dies with
`dial tcp [::1]:3307: connect: connection refused`, no matter how bd itself is connected (verified
over both TCP and a unix socket). The push therefore runs inside the server container, which has the
data dir, a local server, and the git repo.

It is explicit, never automatic: it writes to your git remote.

## Footprint and removal

This recipe writes **outside** the dirs harnessed owns (`$HARNESSED_CONFIG_DIR`, the install cache,
the stack tool dir), so per bd harnessed-8px.6 each of those writes is listed here with the command
that undoes it. None of them is undone by dropping the recipe from your stack.

| What writes it | Where | Remove with |
| --- | --- | --- |
| `bd init` (setup step 1) | `.beads/` **in the repo, committed** | `git rm -r .beads && git commit` |
| `bd init` | git hooks in `.git/hooks/` (agent-identity commit trailers) | delete the bd-installed hook files |
| `bd init` | a Dolt remote wired to your git `origin`; issue history under `refs/dolt/data` | `git push origin --delete refs/dolt/data`, if you want it off the remote too |
| `bd setup <harness> --project` | `CLAUDE.md` — a managed beads block appended to the **project's** file | delete that block |
| `bd setup <harness> --project` | `.claude/settings.json` — a bd SessionStart hook entry, in the **project** | delete that hook entry |
| `install.sh`, on **`harnessed host-run` only** | the user's global mise config + mise tool store | `mise unuse -g "github:gastownhall/beads@1.1.0"` |

The last row is host-only: in a container the same command writes inside the image and disappears
with it. And on a host `install.sh` installs `bd` **only when it is absent** — if some other `bd` is
already on your `PATH` it warns about the version mismatch and leaves your installation untouched,
so there is nothing to undo.

## Caveats

- **Real git footprint, by design.** This recipe installs git hooks and commits `.beads/`. That is the
  point — pick [`beads/stealth`](../stealth/README.md) if it isn't what you want.
- **Bare + linked-worktree layouts anchor `.beads/` at the bare repo.** bd resolves `.beads` off the
  git *common dir*, which in a bare setup is the bare repo — a directory with **no work tree**, so
  `.beads/` lands where nothing can `git add` it and auto-export fails with "this operation must be
  run in a work tree". The server follows bd here (`paths.persist_in_repo_dir` uses the same anchor),
  so client and server always agree — but the git-tracked half of this recipe is degraded in that
  layout. [`beads/stealth`](../stealth/README.md) sidesteps it entirely.
