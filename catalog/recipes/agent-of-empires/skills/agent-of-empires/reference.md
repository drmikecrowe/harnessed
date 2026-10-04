# agent-of-empires reference

## Verified AOE behaviour (aoe 1.16.1)

| Command | Effect |
| --- | --- |
| `aoe group create wave-1 --parent proj` | makes `proj/wave-1`. Creating an existing group exits 1. |
| `aoe group list` | prints an indented tree. A nested group shows only its last segment. |
| `aoe add <root>/main -w <branch> -t <title> -g <group> --cmd-override <cmd>` | creates `<root>/<slug of title>` and records `worktree_info.managed_by_aoe: true`. The worktree is git-locked. |
| `aoe session rename <id> -t <new>` | renames the row. With `session.tie_workdir_to_name` it also moves a managed worktree, and git's record of it. |
| `aoe group move <id> <group>` | moves the row between waves. The folder stays. |
| `aoe session archive <id>` | stops the panes. Sets `archived_at`. Keeps the worktree and branch. |
| `aoe remove <id> --delete-worktree` | moves the worktree to `<root>/.aoe-trash/<id>` and sets `trashed_at`. Keeps the branch. |
| `aoe session restore <id>` | moves the worktree back, uncommitted files included. |
| `aoe session import <path> --dry-run` | lists Claude conversations recorded at or under `<path>`. |

- `aoe list --json` gives `group`, `path` and `state` (`live`, `archived`, `trashed`). It omits
  `worktree_info`. The script reads `sessions.json` for that.
- A row's `status` is unreliable for "is it running". A never-started row reads `idle` or `error`. The
  script scans `/proc/*/cwd` instead.
- `--cmd` silently replaces a command AOE does not know. Always use `--cmd-override`.
- `aoe add -w` on a branch that already has a worktree records `managed_by_aoe: false`. Removal then
  keeps the folder. The script says so.

## The incident behind the safety rules (2026-10-04)

At about 06:50 the AOE trash was emptied or purged. That deleted the worktrees of GH-95, GH-88 and gh-84.
GH-88 held a day of unpushed work. Only `worktree.delete_branch_on_cleanup = false` saved the branch.

## Test harness

Use a throwaway repository and a separate AOE profile. Never touch the `harnessed` profile.

```bash
T=$(mktemp -d)
git init -q --bare -b main "$T/origin.git"
git -C "$T" init -q -b main src && git -C "$T/src" commit -q --allow-empty -m init
git -C "$T/src" push -q "$T/origin.git" main
git clone -q --bare "$T/origin.git" "$T/root/.bare"
echo "gitdir: ./.bare" > "$T/root/.git"
git -C "$T/root/.bare" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$T/root" fetch -q origin
git -C "$T/root" worktree add -q "$T/root/main" main
export AGENT_OF_EMPIRES_PROFILE=skilltest   # aoe and the script both read it
aoe profile create skilltest
aoe group create proj
aoe add "$T/root/main" -t main -g proj --cmd-override bash   # the script finds the group here
cd "$T/root/main"
aoe-sessions new feat-x --cmd bash
aoe-sessions wave create 1 GH-1:test GH-2:second --cmd bash
# ... exercise list, rename, move, archive, check, remove, restore, recover, wave move ...
aoe remove <id> --delete-worktree --purge --force   # throwaway rows only
echo y | aoe profile delete skilltest
```

- `--cmd bash` forces plain rows. No harnessed wrapper sits in this `main/`, so none would be found anyway.
- The bare `origin.git` lets a test push, so `check` sees both pushed and unpushed branches.
- A `bash` pane dies a few seconds after `aoe session start`. Test a running-session refusal inside
  that window.
