# Phase 9: Surgical Profile Mount + History Surfacing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 09-surgical-profile-mount-history-surfacing
**Areas discussed:** Mount manifest format, Claude history target, State dir fate, Profile dir breaking change

---

## Mount Manifest Format

### Question 1: What format should the per-harness mount manifest use?

| Option | Description | Selected |
|--------|-------------|----------|
| YAML per harness | `lib/manifests/claude.yaml`, `omp.yaml`, `antigravity.yaml` — structured, yq-parsed | ✓ |
| Single combined YAML | `lib/mounts.yaml` with all harnesses as top-level keys | |
| Bash sourced file | `lib/harnessed-mount-manifest.sh` with associative arrays — zero new deps | |

**User's choice:** YAML per harness

---

### Question 2: Should the manifest encode teardown behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Config + history dirs only | Two sections: `profile_files` and `history_dirs`. Teardown logic stays in bash. | ✓ |
| Config + history + teardown hooks | Add a `teardown:` section with disabled-by-default merge entries | |
| You decide | Researcher and planner pick the schema | |

**User's choice:** Config + history dirs only

---

### Question 3: Filename only vs filename + container target path?

| Option | Description | Selected |
|--------|-------------|----------|
| Filename + container target path | `source: .mcp.json, target: ~/.claude/.mcp.json` — explicit mapping | |
| Filename only | Manifest lists file names; launcher derives container paths from harness knowledge | ✓ |

**User's choice:** Filename only
**Notes:** User confirmed: option 1 would require entering explicit paths 6 times per harness; option 2 solves it for the user.

---

## Claude History Target

### Question 1: Where should claude session history surface to?

| Option | Description | Selected |
|--------|-------------|----------|
| Real host `~/.claude/projects/<slug>/` | Direct rw-mount from host; visible in Claude.ai | ✓ |
| Harnessed state dir | `~/.local/state/harnessed/.../projects/<slug>/` — more isolated | |

**User's choice:** Real host `~/.claude/projects/<slug>/`

---

### Question 2: Path mirroring handles slug derivation (no manual slug management)?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, path mirroring handles it | `--workdir $HOST_PWD` → same slug in container as on host | ✓ |
| Explicit slug calculation | Manually derive slug before launch | |

**User's choice:** Yes, path mirroring handles it

---

### Question 3: All five MNT2-03 subdirs ship enabled?

| Option | Description | Selected |
|--------|-------------|----------|
| All five enabled | `projects/<slug>/`, `file-history/`, `tasks/`, `session-env/`, `todos/` all in Phase 9 | ✓ |
| `projects/<slug>/` only first | Start minimal, add others after validation | |

**User's choice:** All five enabled

---

## State Dir Fate

### Question 1: What happens to the whole-dir state dir?

| Option | Description | Selected |
|--------|-------------|----------|
| Remove entirely | No more copy-on-start; profile files mount directly; history mounts directly | ✓ |
| Keep but narrow | Keep for transient per-session scratch only | |
| Keep for `--fresh` isolation | Copy-on-start only for `--fresh` runs | |

**User's choice:** Remove entirely

---

### Question 2: `.claude.json` stub path stays unchanged?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, stub location is unchanged | `~/.local/state/harnessed/<instance>/claude.json` — independent of `.claude/` dir | ✓ |
| Consolidate stub into profile dir | Generate stub into `profiles/<stack>/` alongside other config files | |

**User's choice:** Yes, stub location is unchanged

---

## Profile Dir Breaking Change

### Question 1: How to handle existing profiles with `.claude/` trees?

| Option | Description | Selected |
|--------|-------------|----------|
| Rebuild required | Run `harnessed build <stack>`; launcher guard changes to check `.mcp.json` | ✓ |
| Auto-migrate on launch | Detect old-style profile, migrate on-the-fly | |
| Support both old and new | Launcher handles both profile shapes | |

**User's choice:** Rebuild required

---

### Question 2: Assembler skips fan-out entirely?

| Option | Description | Selected |
|--------|-------------|----------|
| Assembler skips fan-out entirely | No skills/commands/agents/hooks/rules written to `profiles/<stack>/` | ✓ |
| Fan-out runs but files not committed | Assembler generates to temp dir, bakes into image, doesn't write to profiles/ | |

**User's choice:** Assembler skips fan-out entirely

---

## Claude's Discretion

No areas deferred to Claude — all decisions made by user.

## Deferred Ideas

None — discussion stayed within phase scope.
