# Surfacing antigravity (`~/.gemini/antigravity-cli`) project history out of an isolated container

**Status:** research / decided
**Date:** 2026-06-22
**Companions:** [home-folder-claude-requirements.md](home-folder-claude-requirements.md),
[home-folder-omp-requirements.md](home-folder-omp-requirements.md)
**Investigated on:** `osmc` (antigravity runs there as **root**, workspace `/root`).
**Decision:** Surface the per-conversation file stores under `~/.gemini/antigravity-cli/`
(`conversations/`, `brain/`, `implicit/`) plus the global `history.jsonl` and the `cache/` index.
Per-conversation DBs are **one file each, UUID-namespaced** → whole-parent-dir mount is
collision-free and WAL-safe (closer to Claude's model than omp's). Path-mirror so the `workspace`
key matches. **`~/.gemini` proper belongs to a different harness — do not surface it for
antigravity.**

## The "tell": antigravity is self-contained; `~/.gemini` proper is gemini-cli

The user's hypothesis was that if antigravity's latest dates show up in `~/.gemini` files, the two
share state. They **don't**:

| Tree | Newest write |
|------|-------------|
| `antigravity-cli/` | **2026-06-21 19:53** (active session) |
| everything else in `~/.gemini/` | **2026-06-17 12:04**; actual chats 06-05 → 06-17 |

The 06-21 antigravity session left no trace outside `antigravity-cli/`. The parent `~/.gemini`
(`history/`, `tmp/root/chats/session-*.jsonl`, `state.json`, `oauth_creds.json`, `projects.json`)
is the **gemini-cli** harness's store — a sibling tool nesting under the same dir. antigravity even
has its own auth token (`antigravity-cli/antigravity-oauth-token`, 06-21 19:51), so it doesn't read
the shared `oauth_creds.json`.

**One soft cross-link:** `antigravity-cli/cache/projects.json` maps workspace `/root` → projectId
`6523305a-…`, and a record for that id exists at the *shared* `~/.gemini/config/projects/6523305a-….json`
(last written 06-17, **not** rewritten during the 06-21 session). antigravity carries the
workspace→projectId map locally, so history surfacing does **not** require the shared file. Noted as
a risk, not a dependency.

**Conclusion: the antigravity surface is entirely `~/.gemini/antigravity-cli/`.**

## Keying model — a *third* variant

| Harness | Project key | Per-unit history |
|---------|-------------|------------------|
| Claude | project-path slug (`projects/<slug>/`) | files (`.jsonl` + UUID dirs) |
| omp | `$HOME`-relative path slug (`sessions/<slug>/`) | files **+ shared SQLite** |
| **antigravity** | **`workspace` path string** (the cwd) | **one SQLite file per conversation**, UUID-named |

There is **no per-project directory**. The project↔conversation association lives in index files:

- `cache/projects.json` → `{"<workspace>": "<projectId>"}` — e.g. `{"/root": "6523305a-…"}`
- `cache/last_conversations.json` → `{"<workspace>": "<conversationId>"}` — only the **latest**
  conversation per workspace
- `history.jsonl` → every prompt line tagged `"workspace":"/root"` (filterable by project)

Per-conversation data is keyed by **conversation UUID** (`cid`):
- `conversations/<cid>.db` — SQLite trajectory/transcript (tables: `steps`, `trajectory_meta`,
  `trajectory_metadata_blob`, `gen_metadata`, `executor_metadata`, `parent_references`,
  `battle_mode_infos`)
- `brain/<cid>/.system_generated/` — agent working memory: `logs/transcript.jsonl`,
  `transcript_full.jsonl`, `tasks/`, `messages/`, plus generated `.md` reports + `.metadata.json`
- `implicit/<cid>.pb` — per-session implicit context (protobuf, opaque)

## Layout of `~/.gemini/antigravity-cli/` (skimmed 2026-06-22)

| Path | Kind | Keyed by | Surface? |
|------|------|----------|----------|
| `conversations/<cid>.db` | History — per-conversation transcript/trajectory | conversation UUID | **Yes — mount** |
| `brain/<cid>/` | History — per-conversation agent memory (transcripts, tasks, messages, reports) | conversation UUID | **Yes — mount** |
| `implicit/<cid>.pb` | History — per-session implicit context (protobuf) | conversation UUID | Yes (opaque blob) |
| `history.jsonl` | History — global prompt log, each line tagged `workspace` | global, `workspace` field | **Yes — guarded merge** |
| `cache/last_conversations.json` | Index — workspace → latest conversation id | workspace | Yes — merge (needed for resume-last) |
| `cache/projects.json` | Index — workspace → projectId | workspace | Yes — merge |
| `cache/onboarding.json` | Cache | — | No |
| `mcp_config.json`, `mcp/<server>/*.json` | Config — MCP defs + tool cache | — | No (profile provides) |
| `settings.json`, `keybindings.json` | Config | — | No |
| `builtin/skills/`, `builtin/.checksum`, `knowledge/knowledge.lock` | Builtin config | — | No |
| `antigravity-oauth-token` | **Auth secret** | — | No (auth-seeded separately) |
| `bin/` (`agentapi`, `webm_encoder`) | Native binaries | — | No |
| `log/cli-*.log`, `cli.log` | Logs | — | No |
| `updater/`, `last_check.timestamp`, `installation_id` | Runtime / identity | — | No |

## Why this is the easy one: per-conversation DBs

Unlike omp (one shared `agent.db` mixing auth + all projects), antigravity gives each conversation
its **own** `conversations/<cid>.db`. That means:

- **Whole-dir mount of `conversations/` is collision-free and WAL-safe** — the container only ever
  writes *new* `<cid>.db` files (new conversations = new UUIDs); it never opens a host conversation's
  DB as a second writer. Same fail-safe property as Claude's UUID-keyed dirs.
- Same for `brain/<cid>/` and `implicit/<cid>.pb`.
- **No auth comingling** — the oauth token is a separate file, excluded by construction.

The only shared-file hazards are the small JSON indexes (`cache/*.json`) and `history.jsonl`
(append-only) — both whole-file-rewrite/append, so handle by **guarded teardown merge**, not rw
bind-mount (same rule as Claude's `.claude.json`/`history.jsonl`).

## Implementation guidance

1. **Path mirroring.** antigravity keys history by the `workspace` *string* (the cwd). Run the
   container at the same absolute path so `workspace` matches the host's project key. (On osmc the
   workspace is `/root` because it runs as root — in the container it's the mirrored project path.)

2. **Mount the per-conversation history dirs whole, rw** (collision-free, WAL-safe):
   `conversations/`, `brain/`, `implicit/`. On a single-workspace host this surfaces exactly that
   workspace's history; on a multi-workspace host it also exposes other workspaces' conversations
   (read-side visibility only — low concern for personal tooling).

3. **`history.jsonl` → guarded teardown merge filtered by `workspace`** (not rw-mount). Append the
   project's lines into the host file; no-op on schema mismatch. Ship disabled until pinned.

4. **`cache/projects.json` + `cache/last_conversations.json` → teardown merge** (small JSON maps,
   merge the project's key). Needed so the host can list the project and resume its latest
   conversation. Do **not** rw-mount (whole-file rewrite race).

5. **Never surface** `antigravity-oauth-token` (auth-seeded by the profile mechanism), `bin/`,
   `log/`, `updater/`, config files, or the parent `~/.gemini/` tree.

6. **Data-driven manifest + §18 oracle test**, as with the other harnesses: after a throwaway
   session, assert a new `conversations/<cid>.db` and `brain/<cid>/` appeared on the host, and that
   `history.jsonl` gained a line for the workspace.

## Risks / open questions

- **No complete workspace→conversation index.** `cache/last_conversations.json` records only the
  *latest* conversation per workspace. To enumerate *all* of a workspace's conversations for
  precise per-project filtering (multi-workspace hosts), you'd scan each `conversations/<cid>.db`
  trajectory metadata for the workspace — **unverified that the DB stores the workspace**; confirm
  on a multi-workspace host. On single-workspace hosts (osmc = `/root`) this is moot; whole-dir
  mount is exact.
- **Shared projectId record** at `~/.gemini/config/projects/<projectId>.json`. antigravity has the
  workspace→projectId map locally, so resume shouldn't need it — but confirm before assuming the
  shared `~/.gemini/config/` can be fully ignored.
- **`implicit/<cid>.pb`** is protobuf — surfaced as an opaque blob; not human-inspectable without
  the schema.
- **Runs as root on osmc.** The workspace key `/root` is an artifact of that. In the container the
  workspace is the mirrored project path; the keying logic is identical (string match on cwd).

## Verification done

- `find` skim of `~/.gemini` + `~/.gemini/antigravity-cli` (depth 3) on osmc.
- Compared newest mtimes: antigravity-cli **06-21 19:53** vs rest of `~/.gemini` **06-17 12:04** →
  not mirrored; parent tree is gemini-cli.
- `cache/projects.json` = `{"/root":"6523305a-…"}`; `cache/last_conversations.json` =
  `{"/root":"39279a69-…"}`.
- `history.jsonl` lines carry `"workspace":"/root"`.
- `conversations/<cid>.db` schema captured (per-conversation SQLite; `steps` + `trajectory_*`).
- antigravity has its own `antigravity-oauth-token` (self-contained auth).
- `sqlite3` present on osmc (`/usr/bin/sqlite3`).
- **Not** verified: whether a conversation DB stores its `workspace` (needed only for
  multi-workspace per-project filtering); whether `~/.gemini/config/projects/<id>.json` is required
  for resume.
