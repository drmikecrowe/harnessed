# Denied Commands

These commands are blocked at the permission layer. A denied call is a wasted round-trip, not a
prompt you can talk your way past.

| Never run | Use instead |
| --- | --- |
| `grep` — including `\| grep`, `\| grep -v`, `git grep` | `rg` (`rg -v` inverts) — see [[rg]] |
| `find` | `fd` (`fd -e py`, `fd -H` for hidden) — see [[fd]] |
| `rm -rf` | `rm -r` on a specific path, or `git clean` |
| `git push --force` | `git push --force-with-lease`, and only when asked |
| `sudo`, `su`, `chmod 777`, `dd`, `mkfs`, `fdisk`, `ssh`, `scp`, `rsync` | ask the user to run it |

## The compound-command trap

**The deny matcher inspects every segment of a command.** One denied word kills the whole chain —
including the allowed segments.

- **Never bury a denied binary in a pipe or `&&` chain.** `rg foo | grep -v test` is denied even
  though `rg` is fine. Filter inside `rg` itself.
- **Split destructive+benign compounds.** `rm -rf docs/x && mkdir -p docs/x` dies as a unit. Run the
  allowed half separately.
- **Never bundle a git write with anything else.** Commit, push, and PR-create are *three* calls,
  never one `&&` chain. A denial on the push segment throws away the commit too. Push and
  `gh pr create` are outward-facing anyway: confirm first (see [[stop-and-ask]]).

## Subagents

Subagents do not inherit these rules. If a subagent prompt will search a tree, say so explicitly:
*use `rg`/`fd`, never `grep`/`find`.* Left unsaid, subagents are the single largest source of
denied calls.
