# Denied Commands

Never run these commands. A harness that denies one wastes the round-trip, and no rephrasing
gets past it.

| Never run | Use instead |
| --- | --- |
| `grep` — including `\| grep`, `\| grep -v`, `git grep` | the harness search tool; `rg` (`rg -v` inverts) when you must shell out — see [[rg]] |
| `find` | the harness glob tool; `fd` (`fd -e py`, `fd -H` for hidden) when you must shell out — see [[fd]] |
| `rm -rf` | `rm -r` on a specific path, or `git clean` |
| `git push --force` | `git push --force-with-lease`, and only when asked |
| `sudo`, `su`, `chmod 777`, `dd`, `mkfs`, `fdisk`, `ssh`, `scp`, `rsync` | ask the user to run it |

## The compound-command trap

**The deny matcher inspects every segment of a command.** One denied word kills the whole chain —
including the allowed segments.

- **Never bury a denied binary in a pipe or `&&` chain.** The matcher denies `rg foo | grep -v test`
  even though `rg` alone is fine. Filter inside `rg` itself.
- **Split destructive+benign compounds.** `rm -rf docs/x && mkdir -p docs/x` dies as a unit. Run the
  allowed half separately.
- **Never bundle a git write with anything else.** Commit, push, and PR-create are *three* calls,
  never one `&&` chain. A denial on the push segment throws away the commit too. Push and
  `gh pr create` are outward-facing anyway: confirm first (see [[stop-and-ask]]).

## Subagents

Subagents do not inherit these rules. If a subagent prompt will search a tree, say so explicitly:
*prefer the harness search and glob tools. If you shell out, use `rg`/`fd`, never `grep`/`find`.*
Left unsaid, subagents are the single largest source of denied calls.

Carry the output bound across too. A subagent inherits no more of [[rg]] than it does of this file.
Tell it: *scope to a path, bound the result set (`-l`, `-c`, `-m`), and route the rest through
`ctx_batch_execute`.* A subagent told only "use rg" returns the whole dump.
