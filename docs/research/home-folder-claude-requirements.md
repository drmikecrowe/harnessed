# Surfacing Claude Code project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Decision:** Surface **everything joinable** (option 3) via targeted rw bind-mounts, with the
one format-parsing step (`history.jsonl` merge) quarantined as a guarded, disable-able teardown.
**Run the container working dir at the same absolute path as the host** (path mirroring) — this
deletes the slug-remap hazard and keeps surfaced history host-coherent (see Hazard A).

## Problem

Isolated stacks do **not** mount host `~/.claude` wholesale (no transparent-style mirror). But we
still want a project's **history** — conversation transcripts, file-rewind backups, subagent runs,
per-project memory — to persist to the host's global Claude store so it survives throwaway
containers and shows up alongside non-containerised work. The task: identify the *exact* subpaths
to bind-mount, and the keying hazards that make a naive mount wrong.

## Layout of `~/.claude` (skimmed 2026-06-22)

Top-level dirs/files, classified by whether they hold per-project **history** vs config/cache:

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `projects/<slug>/` | History — transcripts (`<uuid>.jsonl`) + `memory/` | **project path slug** | **Yes** |
| `file-history/<uuid>/` | History — pre-edit file snapshots (`<hash>@v1/@v2`), powers rewind/undo | session UUID | **Yes** |
| `tasks/<uuid>/` | History — subagent/Task run records | session UUID | **Yes** |
| `session-env/<uuid>/` | History — `sessionstart-hook-*.sh` env captures | session UUID | **Yes** |
| `todos/<uuid>…` | History — per-session todo lists (empty on this box, session-keyed by design) | session UUID | **Yes** |
| `history.jsonl` | History — every prompt typed; each line has `"project"` + `"sessionId"` | global append, project field | **Yes, guarded** |
| `plans/*.md` | History — plan-mode artifacts, named by random slug | **no on-disk key** (project only in content) | Deferred — see Ambiguous |
| `shell-snapshots/snapshot-zsh-<ts>-<rand>.sh` | History-ish — shell env snapshots | timestamp, not session | No (can't map cleanly) |
| `sessions/<number>.json` | Session group state | numeric id (terminal/tab group) | No |
| `agents/ commands/ skills/ rules/ hooks/ plugins/` | Config | — | No |
| `cache/ .search_cache/ paste-cache/ downloads/ stats-cache.json debug/ ide/ chrome/ backups/ context-mode/ sandbox/` | Cache / runtime | — | No |
| `.credentials.json settings*.json` | Secrets / config | — | No (credentials handled by existing auth-seed layer) |

## The core hazard: two join keys

Only `projects/<slug>/` is keyed **directly** by project path. Everything else historical is keyed
by **session UUID**, generated at session start *inside* the container. The UUID→project mapping
lives in two places:

- the `.jsonl` **filenames** under `projects/<slug>/` (filename = session UUID), and
- `history.jsonl` lines (`"project"` + `"sessionId"`).

### Hazard A — the project slug differs inside the container → **solved by path mirroring**

The slug is derived from the **absolute cwd**. Evidence — both already exist on this host:

```
projects/-home-mcrowe-Programming-Personal-code-container/      ← host runs   (cwd /home/mcrowe/…)
projects/-container-mcrowe-Programming-Personal-code-container/ ← container   (cwd /container/mcrowe/…)
```

Critically, the path leak is **not just the slug** — every transcript line embeds the cwd-rooted
absolute path, and so do `file-history` references. Confirmed on this host:

```
host slug transcript:      "cwd":"/home/mcrowe/Programming/Personal/code-container"
                           "file_path":"/home/mcrowe/Programming/Personal/code-container/Dockerfile"
container slug transcript: "cwd":"/container/mcrowe/Programming/Personal/code-container"
```

If the container runs at a *different* path (`/container/mcrowe/…`), the surfaced history is
internally consistent but **host-invalid**: clickable `file_path:line` refs resolve to a
non-existent `/container/…`, rewind blobs key to paths the host can't act on, and a later host
session sees its `projects/` dir split across two slugs.

**Decision: mirror the path.** Run the container working dir at the *same* absolute path as the
host (`/home/mcrowe/Programming/Personal/code-container` inside, byte-for-byte). This:
- deletes the remap entirely — the `projects/` mount becomes plain same-path → same-path, with no
  dependency on CC's path→slug algorithm;
- keeps every recorded path host-coherent;
- makes the DooD pattern clean — container `PWD` == host `PWD`, so `-v $PWD:$PWD` works with no
  translation (satisfies §15's host-absolute-path rule directly);
- coalesces transparent + isolated runs of the same project into one history — which is the goal
  ("this project's history, regardless of how it ran").

Isolation is about **config** (skills/MCP/memory/profile), not the working-dir path; mirroring the
path leaks no host config, so the isolation guarantee is intact. Only `~/.claude` config stays
synthetic — not the project path. The current `-container-mcrowe-…` behaviour is therefore a
**change to make**, not the target state.

### Hazard B — UUID-keyed dirs have no project subfolder

`file-history/`, `tasks/`, `session-env/`, `todos/` are flat `<uuid>/` at top level. You can't
pre-create a per-project mount (UUID unknown until the session starts), so you mount the **parent
dir whole**. This is collision-free (everything is UUID-namespaced; new sessions just add dirs).
Cost: the container can *read* other projects' UUID dirs — a read-side visibility leak of file-backup
blobs, not config or secrets. Accepted.

### Hazard C — `history.jsonl` is a global append-only file

Never rw-bind it (same whole-file-rewrite race we already rejected for `.claude.json`). Surface it
by **append-merging** lines filtered on `"project"` at teardown.

## Decision rationale (why option 3, not 2)

Brittleness is **not** "more mounts." A bind-mount makes zero assumptions about dir *contents*: if a
future Claude Code release renames `tasks/`, the mount becomes an inert no-op and the new dir goes
uncaptured — **silent degradation, not container failure.** So the four UUID-keyed mounts are
effectively free in fragility terms.

The **only** genuinely brittle piece is the `history.jsonl` append-merge, because it parses an
undocumented line schema. That risk is one isolated component.

Two fragilities are **shared by options 2 and 3 equally**, so they don't favour the smaller option:
the slug-remap (depends on CC's path→slug algorithm) and the UUID-keying convention.

Net: take the full surface, quarantine the one parsing step.

## Implementation guidance

1. **Run the container at the host project path** (mirroring), then mount the project dir
   same-path → same-path — no slug remap:
   ```
   --workdir /home/mcrowe/Programming/Personal/code-container \
   -v $HOST_CLAUDE/projects/-home-mcrowe-…-code-container \
      :$CONTAINER_CLAUDE/projects/-home-mcrowe-…-code-container:rw
   ```
   Slug is identical both sides. Surfaces transcripts + per-project `memory/`. (DooD rule satisfied
   — source is a **host absolute path**, and container `PWD` == host `PWD`.)

2. **Mount the four UUID-keyed parent dirs rw** (fail-safe, collision-free):
   `file-history/`, `tasks/`, `session-env/`, `todos/`.

3. **`history.jsonl` = guarded, disable-able teardown step.** Append only lines whose `"project"`
   matches the project, wrapped so a parse failure **logs a warning and no-ops** rather than
   corrupting the host file. Ship it disabled until the format is confirmed; a CC schema change can
   then only break this one feature, not the container.

4. **Make the mount set data-driven** — a list/map in config, not inline `-v` flags — so a future CC
   layout change is a one-line manifest edit, not a code change.

5. **Add a §18 oracle assertion** — after a throwaway session, assert the host now has
   `file-history/<new-uuid>/` and `projects/<slug>/<new-uuid>.jsonl`. Silent upstream renames then
   surface as a failing test (red CI) instead of silent data loss.

## Ambiguous / out of scope

- `plans/*.md` — plan-mode artifacts carry no on-disk project key (random-slug filenames; project
  only referenced in content). Surfacing would require content inspection or mtime↔session
  correlation. Deferred.
- `shell-snapshots/` (timestamp-keyed) and `sessions/<number>.json` (terminal-group-keyed) — not
  cleanly mappable to a project. Not surfaced.

## Verification done

- `fd` skim of `~/.claude` top two levels (dirs + root files).
- Confirmed session-UUID keying of `file-history/`, `session-env/`, `tasks/` by sampling entries.
- Confirmed `projects/<slug>/<uuid>.jsonl` filename = session UUID (carries `sessionId`).
- Confirmed `history.jsonl` line schema carries `"project"` + `"sessionId"`.
- Confirmed dual-slug evidence (`-home-mcrowe-…` and `-container-mcrowe-…`) in `projects/`.
- `todos/` empty on this host but session-keyed by design (noted, not assumed populated).
