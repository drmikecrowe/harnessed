---
name: agent-of-empires
description: Manage Agent of Empires sessions that each own a git worktree. Use to create, list, rename, move, archive, remove, restore, or recover a session, or to lay sessions out in waves.
---

# agent-of-empires

One session owns one git worktree on one branch. The repository is a bare root with sibling worktrees:
`<root>/.bare`, `<root>/main`, and one folder per session beside `main/`.

Every operation goes through one script: `scripts/aoe-sessions` in this skill's folder. Run it from
inside the repository. `aoe-sessions --help` prints the full usage.

## Discovery

Run `aoe-sessions config` first. It prints what the script found. A flag overrides each value.

| Setting | Found from | Flag |
| --- | --- | --- |
| harness, stack | the one `exec harnessed host-run` wrapper in `main/` | `--harness`, `--stack` |
| row kind | harnessed when a stack is found, else plain `aoe add -w` rows | `--cmd <command>` forces plain |
| AOE profile | `harnessed` with a stack, else `$AGENT_OF_EMPIRES_PROFILE`, else `default` | `--profile` |
| group | the group of the session at `main/`, else the root folder's name | `--group` |

If `main/` holds wrappers for several stacks, the script stops. Ask the user which stack, then pass `--stack`.

## Sessions

| Ask | Run |
| --- | --- |
| What is in flight? | `aoe-sessions list [<group>]` |
| New session for a branch | `aoe-sessions new <branch> [<title>]` |
| Rename a session | `aoe-sessions rename <target> <title>` |
| Move a session to another group | `aoe-sessions move <target> <group>` |
| Pause sessions | `aoe-sessions archive <target>...` |
| Resume paused sessions | `aoe-sessions unarchive <target>...` |
| Is it safe to remove? | `aoe-sessions check <target>...` |
| Remove sessions | `aoe-sessions remove <target>...` |
| What is in the trash? | `aoe-sessions trash` |
| Bring one back | `aoe-sessions restore <id|title>` |
| A worktree or session is gone | `aoe-sessions recover <branch> [<title>]` |
| A moved harnessed session will not start | `aoe-sessions repair <target>` |

A `<target>` is a session id, a title, a branch, or `wave-<n>`.

- `new` is idempotent. If the branch already has a session, it reuses it or names the one that exists.
- A new branch starts from `origin/main` with no upstream. The first push sets it.
- `rename` also moves the worktree folder, because AOE ties the folder name to the title.
- `move` changes the group only. The folder stays.
- `list` marks a harnessed row whose command points at a missing wrapper as `STALE COMMAND`.
- `recover` rebuilds the worktree from the branch. It then lists the Claude conversations it can import.
  Offer the printed `aoe session import` command. Never run it unasked: it creates new sessions.

## Waves (optional)

Waves are one way to lay out issue work. A wave is the group `<group>/wave-<n>`.

| Thing | Shape | Example |
| --- | --- | --- |
| title | `<wave>.<slot>-<ISSUE>-<slug>` | `2.1-GH-83-two-plugins` |
| branch | `<ISSUE>` | `GH-83` |
| worktree | the title as a slug | `<root>/2-1-gh-83-two-plugins` |

| Ask | Run |
| --- | --- |
| Start wave 2 with these issues | `aoe-sessions wave create 2 GH-83:two-plugins GH-93:feedback` |
| Move a session to wave 3 | `aoe-sessions wave move <target> 3 [<slot>]` |
| Close the slot gaps in wave 2 | `aoe-sessions wave renumber 2` |
| Show, archive, check, or remove a wave | pass `wave-<n>` as the target |

- `wave create` is idempotent. A session already in another wave is skipped, with the command to move it.
- `wave move` also adopts a session that has no wave yet. Its title becomes `<wave>.<slot>-<title>`.
- The branch never carries the wave or slot, so a reorder never renames a branch.

## Safety: non-negotiable

- Run `aoe-sessions check` before every removal. Show the user each `BLOCKED` reason.
- `remove` skips a session with uncommitted changes, commits on no remote, no upstream, or a live process
  in its worktree. It never removes the session at `main/`.
- Pass `--allow <title>` only after the user says yes to that title by name in this conversation.
- `--purge` and `--delete-branch` also need `--confirm-irreversible`. Add it only after an explicit yes.
- Never run `aoe remove --purge`, `aoe session empty-trash`, or `aoe remove --delete-branch` directly.
- Never edit `sessions.json` by hand. The script edits nothing in it; harnessed does, under AOE's lock.
- Never rename a running session. `rename`, `wave move`, and `wave renumber` refuse one; stop it first.
- `archive` skips a running session unless it gets `--allow <title>`.
- The script backs up `sessions.json` before each batch of changes, and prints the backup path.

```bash
# Wrong: removes the work it was asked to protect
aoe remove GH-88 --delete-worktree --purge --force

# Right: check, report, and remove only what is safe or approved by name
aoe-sessions check wave-2
aoe-sessions remove wave-2 --allow 2.1-GH-88-x   # only after "yes, remove 2.1-GH-88-x"
```

## Gotchas

- **History follows the folder.** Claude Code files a conversation under its working folder. After a
  rename, `/resume` in the new folder does not list the old one. Tell the user where it stays; `rename`
  prints the old path.
- **harnessed needs #544.** With a stack, the script needs a `harnessed` whose `host-run` has
  `--aoe-managed-worktree`. An older one is refused before any change. Set `HARNESSED` to use another binary.
- **harnessed uses one AOE profile.** It always registers in profile `harnessed`, so a stack forces it.
- **Older harnessed cannot see nested groups.** Its registration then fails. The script registers each
  row in the top-level group, then moves it, so every version works.
- **Two row shapes exist.** Rows from before harnessed #544 store an absolute wrapper path. A rename
  strands them. `repair` reruns harnessed, which rewrites the command in place.

[reference.md](reference.md) has the verified AOE behaviour and the throwaway test harness.
