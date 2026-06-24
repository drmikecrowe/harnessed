# Surfacing harness project history — cross-harness overview & plan

**Status:** living index
**Date:** 2026-06-22
**Scope:** how each AI-coding harness stores per-project history in the user's home dir, and how an
**isolated** harnessed stack surfaces that history back to the host's global store (the harness's
config stays isolated; only *history* is surfaced).

This is the index for the per-harness research docs and the playbook for onboarding new harnesses.

## Documents

| Harness | Home root | Doc | Status |
|---------|-----------|-----|--------|
| Claude Code | `~/.claude/` | [home-folder-claude-requirements.md](home-folder-claude-requirements.md) | ✅ researched |
| omp | `~/.omp/` | [home-folder-omp-requirements.md](home-folder-omp-requirements.md) | ✅ researched |
| antigravity | `~/.gemini/antigravity-cli/` | [home-folder-antigravity-requirements.md](home-folder-antigravity-requirements.md) | ✅ researched |
| opencode | `~/.config/opencode/` + `~/.local/share/opencode/` (to confirm) | _this doc, §Planned_ | ⏳ to investigate |
| codex | `~/.codex/` | _this doc, §Planned_ | ⏳ to investigate |
| gemini-cli | `~/.gemini/` (proper) | — | ⏳ if surfaced (note: antigravity nests *under* this but is separate) |
| _future_ | — | — | follow §Onboarding |

## The invariant decisions (apply to every harness)

These held across all three researched harnesses and are the defaults for any new one.

1. **Path mirroring.** Run the container working dir at the **identical absolute host path**. Every
   harness embeds the cwd somewhere that matters — in the project-slug (Claude), in transcript
   `cwd` fields (all three), or as the `workspace` key (antigravity, omp `history`). Mirroring makes
   the slug/key line up *and* keeps embedded paths host-valid (clickable refs, actionable rewind),
   *and* makes DooD `-v $PWD:$PWD` translation-free (§15). Decided once, applies everywhere.

2. **Classify every path into exactly one of: history / config / cache / auth.** Only **history** is
   surfaced. Config comes from the committed profile; cache/runtime is rebuilt in-container; auth is
   seeded separately and **never** surfaced.

3. **Mount files; export databases.** A bind-mount exposes a whole file with no per-project slice.
   - **File-per-unit, UUID/content-namespaced** (Claude `file-history/`, `projects/<slug>/`; omp
     `sessions/<slug>/`; antigravity `conversations/`, `brain/`, `implicit/`) → **whole-parent-dir
     rw mount is safe**: the container only ever writes *new* namespaced entries, never a second
     writer on an existing file. Also WAL-safe for per-unit SQLite.
   - **Shared single file** — a DB holding many projects' rows (omp `history.db`, `agent.db`) or a
     whole-file-rewrite/append JSON (`.claude.json`, `history.jsonl`, antigravity `cache/*.json`) →
     **never rw-mount** (lost-write race / WAL corruption / cross-project leak). Surface via a
     **guarded teardown merge/export** filtered by the project key, that **no-ops on schema
     mismatch** instead of corrupting the host store. Ship disabled until the format is pinned.

4. **Never bind-mount a store that co-locates auth.** omp's `agent.db` mixes `auth_credentials` with
   the thread index — the canonical trap. Verify each DB's tables before mounting.

5. **Make the mount/export set data-driven** — a per-harness manifest (host source → container dest,
   plus teardown-merge targets), not inline `-v` flags. An upstream layout change becomes a one-line
   manifest edit.

6. **Add a §18 oracle test per harness.** After a throwaway session, assert the host gained the
   expected new history artifact (new transcript file / DB / appended history line). Silent upstream
   renames then fail CI instead of silently losing data.

## Keying models compared

The single biggest cross-harness difference — it dictates the mount shape.

| Harness | Project key | Per-unit history storage | Surfacing shape |
|---------|-------------|--------------------------|-----------------|
| Claude | project-path slug (`-home-mcrowe-…`) | files: `projects/<slug>/*.jsonl` + UUID-keyed sibling dirs (`file-history/`, `tasks/`, …) | mount slug dir (remapped→mirrored) + whole UUID dirs; merge `history.jsonl` |
| omp | `$HOME`-relative path slug (`-Programming-…`) | files: `sessions/<slug>/` **+ shared SQLite** (`history.db`, `agent.db`) | mount `sessions/<slug>/`; export `history.db` by `cwd`; **never** touch `agent.db` (auth) |
| antigravity | `workspace` path string | **one SQLite file per conversation** (`conversations/<cid>.db`) + `brain/<cid>/` + `implicit/<cid>.pb` | whole-dir mount of those three (UUID-safe); merge `history.jsonl` + `cache/*.json` |
| opencode | _TBD_ | _TBD_ | _TBD_ |
| codex | _TBD_ | _TBD_ | _TBD_ |

Observations that likely generalize:
- A **global prompt log** keyed by cwd/workspace recurs in every harness (Claude `history.jsonl`,
  omp `history.db`, antigravity `history.jsonl`). Expect one; expect to merge it by project key.
- **Auth is always its own concern** — sometimes a discrete file (Claude `.credentials.json`,
  antigravity `antigravity-oauth-token`), sometimes fused into a DB (omp `agent.db`). Always locate
  it first.
- "rollout" + `<timestamp>_<uuid>.jsonl` (omp) is **OpenAI Codex lineage** — codex likely shares
  this format, so omp's findings are the best prior for codex (see Planned).

## Mount-decision flowchart (per path)

```
For each path under the harness home root:
  ├─ Is it auth/secret?            → DO NOT surface (seed separately)
  ├─ Is it config?                 → DO NOT surface (profile provides)
  ├─ Is it cache/log/runtime?      → DO NOT surface (rebuilt in-container)
  └─ Is it history?
       ├─ file-per-unit, UUID/content-namespaced?  → whole-parent-dir rw mount (safe)
       ├─ project-path-keyed dir?                  → mount that dir, mirrored path (safe)
       └─ shared single file (DB or rewrite/append JSON)?
            ├─ co-locates auth?  → NEVER mount; export only the project's rows on teardown
            └─ else             → guarded teardown merge/export, filtered by project key
```

## Planned harnesses

> Treat the layouts below as **hypotheses to verify**, not facts. Known config/auth paths come from
> the project's CLAUDE.md harness wiring; history layout is unconfirmed until investigated.

### opencode (`~/.config/opencode/` + likely `~/.local/share/opencode/`)

- **Known (config/auth):** MCP wired via image-baked `~/.config/opencode/opencode.json` → hatago.
  Consumes `.claude/skills/**` + `~/.claude/CLAUDE.md` natively (no bridge). Auth typically
  `~/.local/share/opencode/auth.json` *(verify)*.
- **To investigate:** where session/message history lives (suspected `~/.local/share/opencode/` —
  opencode keeps project storage there, possibly SQLite or per-project JSON). Confirm project keying
  (path slug vs id), whether auth is a discrete file vs DB-fused, and the global-history location.

### codex (`~/.codex/`)

- **Known (config/auth):** `~/.codex/config.toml` (MCP `[mcp_servers.hatago]` → Streamable-HTTP),
  `~/.codex/auth.json` (mounted ro), `~/.codex/prompts` (its prompt format).
- **To investigate (strong prior = omp, which is Codex-lineage):** expect rollout transcripts at
  `~/.codex/sessions/…/rollout-<ts>-<uuid>.jsonl` (possibly date-bucketed) and a global
  `~/.codex/history.jsonl`. Confirm whether sessions are date-bucketed or path-slug-keyed (decides
  whether per-project filtering needs a `cwd` scan, as omp's empty-`threads` case showed), and
  whether any SQLite index co-locates auth.

### Investigation command template (run per new harness)

Same pattern used for the three researched harnesses (adapt `ROOT`; prepend `ssh <host>` if remote,
run via the `!` prefix since `ssh` is permission-denied to the agent):

```
ROOT=~/.codex   # or ~/.config/opencode, ~/.local/share/opencode, …
echo "=== tree (depth 3) ==="; find $ROOT -maxdepth 3 2>/dev/null | head -100
echo "=== 15 newest files ==="; find $ROOT -type f -printf "%TY-%Tm-%Td %TH:%TM  %p\n" 2>/dev/null | sort -r | head -15
echo "=== any SQLite? list tables (watch for auth_* alongside history) ==="; \
  for db in $(find $ROOT -name '*.db' 2>/dev/null); do echo "-- $db"; sqlite3 "$db" ".tables"; done
echo "=== global prompt log? does it carry cwd/workspace? ==="; \
  find $ROOT -name 'history*.jsonl' -exec head -2 {} \;
```

Then write `home-folder-<harness>-requirements.md` following the established template (Tell /
Keying model / Layout table / Mount guidance / Risks / Verification done) and add a row to the
Documents table above.

## Onboarding checklist for a new harness

1. Locate the home root and run the investigation template.
2. Compare newest mtimes across sibling trees to catch shared-vs-separate state (the antigravity
   "tell").
3. **Find auth first** — discrete file or DB-fused? Mark it never-surface.
4. Classify every path (history / config / cache / auth).
5. Identify the **project key** (path slug? id? `workspace` string?) and the **per-unit storage**
   (files? per-unit DB? shared DB?).
6. Apply the flowchart → produce the mount list + teardown-merge list.
7. Add the data-driven manifest entry + the §18 oracle assertion.
8. Write the per-harness doc; update this index.
