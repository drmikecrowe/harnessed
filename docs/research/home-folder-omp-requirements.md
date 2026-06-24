# Surfacing omp (`~/.omp`) project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Companion to:** [home-folder-claude-requirements.md](home-folder-claude-requirements.md)
**Decision:** Surface per-project history by mounting the **file-based** `agent/sessions/<slug>/`
tree (mirrors the Claude `projects/` approach). The **SQLite** stores are handled by a guarded
teardown export filtered on `cwd` — **never bind-mount `agent.db`** (it co-locates auth
credentials). Run the container at the host project path (path mirroring), same as Claude.

## Headline difference from Claude Code

Claude stores all per-project history as **files** (`projects/<slug>/*.jsonl` + UUID-keyed dirs).
omp is a **hybrid**:

- Per-project conversation transcripts + tool logs are **files** under `agent/sessions/<slug>/` —
  cleanly mountable per-project. ✅
- Global prompt history, the resume/thread index, auth, settings, usage, and cache live in
  **shared SQLite DBs** (`history.db`, `agent.db`, `models.db`) with WAL. You **cannot** slice one
  project's rows out of a shared DB with a bind-mount, and one of those DBs (`agent.db`) holds
  **auth credentials** next to the thread index. ⚠️

So: mount the files, export the DB slices.

## Layout of `~/.omp` (skimmed 2026-06-22)

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `agent/sessions/<slug>/` | History — rollout `<ts>_<uuid>.jsonl` transcripts + per-session tool-log subdirs (`N.read.log`, `N.bash.log`, `N.async.log`, named `.jsonl`) | **project path slug** (`$HOME`-relative) | **Yes — mount** |
| `agent/blobs/` | History-adjacent — content-addressed pasted-image store (`<sha>` + `<sha>.webp/png/jpg`), referenced by transcripts | content hash (global, shared) | Optional (mount whole if you want image refs to resolve) |
| `history.db` (+ `-shm`/`-wal`) | History — global prompt log: `(prompt, created_at, cwd, session_id)` + FTS5 | shared DB, `cwd` column | **Yes — teardown export by `cwd`**, not mount |
| `agent.db` (+ `-shm`/`-wal`) | **MIXED** — `threads` (resume index: `id, rollout_path, cwd, source_kind`), **`auth_credentials`**, `settings`, `usage_*`, `cache`, `jobs`, `model_usage`, `stage1_outputs` | shared DB | **No — never bind-mount** (auth co-located). See thread-index note. |
| `models.db` (+ `-shm`/`-wal`) | Model catalogue cache | — | No |
| `agent/config.yml`, `agent/mcp.json`, top-level `mcp.json` | Config | — | No (profile provides these) |
| `agent/skills` | Config — **symlink** → `../../.agents/skills` (host shared skills) | — | No (and a symlink that would dangle in-container) |
| `agent/terminal-sessions/pts-N` | Ephemeral tty session state | pts/tty number | No |
| `context-mode/` | context-mode MCP plugin's own session DBs | hash | No (plugin-managed) |
| `logs/`, `natives/`, `gpu_cache.json`, `install-id` | Logs / native-binary cache / GPU cache / install identity | — | No |

## Keying details (verified)

### Slug derivation is `$HOME`-relative, not absolute

omp strips `$HOME` from the cwd, then maps `/`→`-`. Evidence from `agent/sessions/`:

```
/home/mcrowe/Programming/Personal/code-container  →  -Programming-Personal-code-container
/tmp                                              →  -tmp   (no $HOME prefix → kept absolute)
```

Consequence: as long as the project sits at the **same path relative to `$HOME`** inside the
container, the slug matches the host's — even if container `$HOME` differs. But the rollout
transcripts still embed the **absolute** cwd (confirmed:
`"cwd":"/home/mcrowe/Programming/Personal/code-container"` inside a `sessions/.../*.jsonl`), so for
host-coherent file references the same path-mirroring decision as Claude applies: **run the
container at the identical absolute host path.** That makes both the slug *and* every embedded path
line up.

### The SQLite stores are genuinely shared (multi-project)

- `history.db`: **501 rows across 13 distinct `cwd`s** on this host — one global table, filterable
  by `cwd`. The omp analogue of Claude's global `history.jsonl`.
- `agent.db` `threads`: index of `(id, rollout_path, cwd, source_kind)` — maps a thread to its
  rollout file and project. **Currently 0 rows on this host**, i.e. per-project resume operates off
  the on-disk `sessions/<slug>/` rollouts, not this index. (If a future omp build populates and
  *requires* `threads` for resume, surfacing history would also need a `cwd`-filtered export of
  thread rows — see Risks.)
- `agent.db` `auth_credentials`: **3 rows** — confirms secrets live in the same file as the thread
  index. This is why `agent.db` must never be bind-mounted to surface history.

## Why the DBs are export-not-mount

1. **No per-project slice.** A bind-mount surfaces a whole file; you can't expose only this
   project's rows of a shared table.
2. **Auth co-mingling** (`agent.db`). Mounting it rw would surface/persist credentials and merge
   container auth state into the host store — exactly the kind of leak the design forbids.
3. **WAL corruption risk.** These DBs run in WAL mode (`-shm`/`-wal` present). Bind-mounting a live
   SQLite file into a second writer (container omp while host omp may also run) risks corruption —
   the same hazard that rules out rw-mounting Claude's `.claude.json` and `history.jsonl`.

## Implementation guidance

1. **Path mirroring** (same decision as Claude): run the container working dir at the identical
   host absolute path. Slug + embedded cwd both line up.

2. **Mount the file-based per-project history** — same-path → same-path, no remap:
   ```
   --workdir /home/mcrowe/Programming/Personal/code-container \
   -v $HOST_OMP/agent/sessions/-Programming-Personal-code-container \
      :$CONTAINER_OMP/agent/sessions/-Programming-Personal-code-container:rw
   ```
   Surfaces rollout transcripts + per-session tool logs.

3. **(Optional) Mount `agent/blobs/` whole, rw** — content-addressed and collision-free, like
   Claude's UUID-keyed dirs. Only needed if you want pasted-image references inside surfaced
   transcripts to resolve. Read-side visibility of other projects' blobs is the only cost.

4. **`history.db` → guarded teardown export by `cwd`**, not a mount. After the session, copy this
   project's rows out and merge into the host `history.db` (e.g. `INSERT … SELECT … WHERE cwd =
   '<project>'`). Wrap so a schema mismatch logs and no-ops rather than corrupting the host DB —
   parallel to Claude's guarded `history.jsonl` merge. Ship disabled until the schema is pinned.

5. **`agent.db` → do not mount; do not auto-export.** It is auth + settings + usage + (empty)
   thread index. Leave the container with its own fresh `agent.db` (auth seeded by the profile's
   own mechanism). Revisit only if a future omp build makes `threads` mandatory for resume.

6. **Data-driven mount manifest + §18 oracle test**, same as Claude: list the omp paths in config,
   and after a throwaway session assert the host now has a new
   `agent/sessions/<slug>/<ts>_<uuid>.jsonl`. A silent upstream layout change then fails CI instead
   of losing data.

## Risks / open questions

- **Thread index may become load-bearing.** `agent.db.threads` is empty today, so file-based resume
  works. If omp starts requiring it, file-only surfacing would list transcripts the harness can't
  resume — would need a `cwd`-filtered thread-row export added to teardown.
- **Concurrent host omp.** If the user runs omp on the host while a container omp runs the same
  project, the teardown `history.db` merge must tolerate concurrent writers (transaction + retry).
  The file `sessions/` mounts are append-only-by-new-file, so they don't race.
- **`models.db`** intentionally not surfaced — it's a cache; the container rebuilds it.

## Verification done

- `fd` skim of `~/.omp` to depth 3.
- Confirmed `agent/sessions/<slug>/` holds `<ts>_<uuid>.jsonl` rollouts + per-session tool-log
  subdirs; slug is `$HOME`-stripped (`-Programming-…`, `-tmp`).
- Confirmed rollout `.jsonl` embeds absolute `"cwd"`.
- `history.db`: schema `(prompt, created_at, cwd, session_id)` + FTS; 501 rows / 13 cwds (global,
  filterable).
- `agent.db`: `threads` schema `(id, updated_at, rollout_path, cwd, source_kind)`, **0 rows**;
  `auth_credentials` **3 rows** (secrets co-located).
- `agent/skills` is a symlink to host `.agents/skills`.
