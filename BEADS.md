# Beads integration — the model, the constraints, and what harnessed owes the user

Companion to [ARCHITECTURE.md](ARCHITECTURE.md). This is the *why* behind the beads recipes, the
`beads-server` service, and the launch-time guards in `launcher.py`.

It exists because the same failure recurred three times on harnessed's own checkout and was
misdiagnosed each time — the symptom always lands on the client, always says "database not found",
and never names the thing that is actually wrong. Everything below marked **verified** was checked
against a running system on 2026-07-24/25; everything marked **open** is not settled.

---

## 1. Requirements

1. **harnessed understands beads and manages the database for the user.** The user should not have
   to reason about data dirs, server modes, ports, or sockets.
2. **`beads/team` shares the database.** Every user of the repo shares issues — and this must not
   require them to run harnessed. A teammate with plain `bd` has to work.
3. **`beads/stealth` puts the database in a comparable place, invisible to the repo.** Ignored and
   transparent; no collaborator sees that beads is in use.
4. **If the user starts in the wrong mode, launch aborts.** Never silently produce a second, empty
   workspace.

Requirements 2 and 3 together imply a fifth: **harnessed initializes the workspace, in the correct
mode, when it does not exist yet.** That is a deliberate reversal — see §6.

**Requirement 2 is the constraint that binds.** harnessed does not get to invent placement or
layout: whatever bd's convention is, harnessed conforms to it, because a non-harnessed teammate is
a first-class user. harnessed's job is to *conform and protect*, never to *place*.

---

## 2. bd's conventions (not harnessed's)

**Workspace location — `{git_common_dir}/.beads`.** Verified with `bd where` in a bare +
linked-worktree checkout: it resolves to `<...>/.bare/.beads`, not `<worktree>/.beads`. Every
worktree of one checkout therefore shares one workspace, and `paths.persist_in_repo_dir` matches
this deliberately rather than inventing an anchor.

**What is shared vs. what is machine-local.** bd ships its own `.beads/.gitignore` (39 rules). It
ignores runtime state and tracks configuration:

| Tracked (bd's shared surface) | Ignored (machine-local runtime) |
| --- | --- |
| `metadata.json` | `dolt/`, `embeddeddolt/`, `proxieddb/` |
| `config.yaml` | `backup/`, `*.lock`, `dolt-server.{pid,log}` |
| `issues.jsonl` (passive export) | `sync-state.json`, `last-touched`, `export-state/` |

**Issue data does not travel in the directory.** It syncs through `refs/dolt/data` on the git
remote (`bd dolt push` / `bd dolt pull`). The local Dolt store is runtime state that is *rebuilt*
from the remote, which is why bd's own error text says "the Dolt database is runtime state, not in
git" and suggests `bd bootstrap`.

**Dolt's data-dir shape.** A `dolt sql-server --data-dir D` serves the *subdirectories* of `D` as
databases. The project database therefore lives at `<data>/dolt/<dbname>/`, and `<data>/dolt/`
itself must never be a repo.

---

## 3. The constraints harnessed cannot design around

**bd auto-starts a server whenever it cannot reach one** — chdir'd into its data dir, with no
`--data-dir`. This is not configurable away:

- `bd dolt set data-dir` is **rejected in server mode**: `setting data-dir in server mode is not
  supported (GH#2438). In server mode, the database is determined by the 'database' config key, not
  the local data directory.`
- `dolt.data-dir` in `config.yaml` is silently ignored. `dolt.port` in the same file *is* honoured,
  which makes the omission easy to miss.

**Socket mode is the only configuration that disables auto-start.** Verified: a workspace whose
`metadata.json` carries `dolt_server_socket` refuses to spawn a server against an absent socket —
twice in a row, host process count unchanged — and says so: *"Auto-start is not supported in socket
mode."*

**Socket-mode `bd init` requires the server already listening.** Verified: it cannot bootstrap
itself against a socket nobody is serving. This forces the ordering in §6.

---

## 4. The central tension: `metadata.json` is tracked, but the socket path is machine-local

This is the unresolved conflict at the heart of the integration, and it is **open**.

- bd's convention (§2): `metadata.json` is **tracked** and shared with the team.
- harnessed's mechanism (§3): socket mode is the only safe mode, and it works by writing
  `dolt_server_socket` into `metadata.json` — an **absolute host path**
  (`/home/<user>/<project>/.bare/.beads/run/mysql.sock`).
- The `beads-server` entrypoint rewrites that key on **every** startup.

So in a `beads/team` placement on a normal checkout, harnessed mutates a tracked file with
machine-local data every time it launches. Committed, it hands every teammate a socket path that
does not exist on their machine — and because socket mode disables auto-start, they do not fall back
gracefully. They are hard-blocked, which violates requirement 2 outright.

harnessed's own checkout does not show this, and that is an accident of layout: `location: in_repo`
anchors at the git **common dir**, which here is `.bare/` — inside the git directory, where nothing
is trackable. Verified: `git ls-files .beads` returns only the worktree stub's `.gitignore` and
`interactions.jsonl`; the real workspace at `.bare/.beads` is untracked in its entirety. A normal
single-checkout project would place `.beads/` in the working tree and expose the conflict immediately.

Directions, none chosen:

1. Keep `dolt_server_socket` out of tracked state — a machine-local override file bd consults, if
   one exists or can be added upstream.
2. Treat `metadata.json` as machine-local in harnessed-managed repos (add it to `.gitignore`),
   accepting divergence from bd's convention and losing whatever bd intends to share through it.
3. Have harnessed rewrite the socket to a **relative** or `$VAR`-based path, if bd will resolve one.

Until this is settled, `beads/team` on a normal checkout is not safe to commit after a harnessed
launch. **Do not commit `metadata.json` containing a `dolt_server_socket`.**

---

## 5. What harnessed guards at launch

All host-side and filesystem-only — no server, no client, no connection. See
`launcher.py` alongside `_assert_data_dir_unlocked`.

| Guard | State |
| --- | --- |
| `_assert_data_dir_unlocked` | A host process already holds the data dir's exclusive lock; the sidecar would die on startup. |
| `_assert_data_dir_not_self_served` | A host auto-start initialized `<data>/dolt/` itself as a repo. Keys on `.dolt/repo_state.json` — **not** on `.dolt/` existing, because a healthy sql-server creates that directory too (for `sql-server.info` and `tmp/`). Keying on the directory alone rejects every healthy launch. |
| `_assert_named_database_present` | `metadata.json` names a database that is not under `<data>/dolt/`. The sidecar starts clean and every client gets errno 1049. |
| `_assert_placement_matches` | A stealth (`host`) launch over a checkout that already carries an in-repo (`team`) workspace. |

Recovery for the third is `harnessed svc migrate <service> --stack <stack>`, which copies (never
moves) a database into the sidecar's data dir.

**Requirement 4 is only half-met.** `_assert_placement_matches` detects stealth-over-team but not
team-over-stealth: the team dir is at a known recipe-independent path, while a stealth dir is keyed
by recipe name plus a project hash, so a team launch cannot enumerate where a stealth workspace might
be. Closing it needs harnessed to **record the active placement** in a marker — which requirement 4
now justifies. **Open.**

---

## 6. First-time initialization

Requirements 2 and 3 mean harnessed must create the workspace in the right mode when it is absent.
This **reverses** the recipes' current stance, which is explicit that beads is not auto-initialized
because `bd setup` writes into the project (`.claude/settings.json` + `CLAUDE.md` on bd 1.1.0) and
could not be made reliably idempotent or footprint-free. That reversal is deliberate; the recipes'
`No init:` comments should be updated when it lands, not left to contradict the behaviour.

Ordering is forced by §3 — socket-mode init cannot precede the server:

1. Ensure the `beads-server` sidecar is up and healthy.
2. If the workspace has no `metadata.json`, run the placement's init:
   - team: `bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET"`
   - stealth: the same, plus `--stealth`
3. `bd setup <harness> --project [--stealth]`.

**Stealth's footprint becomes harnessed's problem at this point.** While init was a deliberate user
action, the recipe could fairly say the user "opts into that footprint knowingly". Once harnessed
runs it automatically, harnessed owns the `.claude/settings.json` + `CLAUDE.md` that bd leaves
outside its own stealth exclude list, and adding them to the git common dir's `info/exclude` becomes
justified. Note the hazard that makes this a decision rather than a detail: `info/exclude` entries
are **path patterns**, not provenance — excluding `/CLAUDE.md` suppresses any future `CLAUDE.md` the
user writes themselves, in a repo that does not already track one. Scope it accordingly. **Open.**

---

## 7. Known gaps

`beads/*` under `harnessed host-run` cannot work today. Filed:

| Issue | |
| --- | --- |
| `harnessed-2sm` | `host-run` never starts sidecars — `_launch_host` has no `_ensure_services` call, while `launch` does. |
| `harnessed-162` | `HARNESSED_<SVC>_SOCKET` is exported only in container mode, so the recipes' `:?` guard always fires host-side. |
| `harnessed-5ek` | `_service_data_dir` returns the **container** path for `location: host`; blocks `harnessed-162`, since relaxing the mode gate alone would export a path that does not exist on the host. |

---

## 8. Incident record — 2026-07-19 → 2026-07-25

Kept because each misdiagnosis was reasonable given what the system reports.

- **07-16** A "shared reinit" repointed the workspace at bd's own multi-project server
  (`~/.beads/shared-server/dolt`, serving six other projects). `metadata.json` lost its
  `dolt_server_socket`, re-enabling auto-start.
- **07-19 16:22** A host `bd` auto-started a server chdir'd into `.beads/dolt` with no `--data-dir`,
  initializing that directory as a repo. One minute later: `database not found:
  programming_personal_harnessed`. It stayed broken for five days and three server restarts.
- **07-24** Diagnosed. The bytes were intact the whole time in
  `~/.beads/shared-server/dolt/programming_personal_harnessed/` — 46 open issues, last written that
  morning. Nothing was ever lost. `bd bootstrap`, which bd's own error suggests, could not have
  helped: it clones from `refs/dolt/data`, and this workspace had never pushed.
- **07-25** Repaired to socket mode with the database at the per-project path. Guards added.

Three readings the symptom invites, all wrong: *the server is down* (it was running and healthy);
*the database was lost* (it was intact elsewhere); *the port is wrong* (it was, twice, but that was
downstream). The one thing the error never says is that the data dir is the wrong shape.
