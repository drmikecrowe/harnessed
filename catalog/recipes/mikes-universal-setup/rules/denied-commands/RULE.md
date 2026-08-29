# Denied Commands

**Scope: shell commands only.** Every entry below names a binary you would run through the shell.

A harness tool that shares a name is a different thing and is never restricted here. `Grep` the tool
is not `/usr/bin/grep`; `Glob` is not `/usr/bin/find`; `Read` is not `cat`. Reach for the tool first
— the table's "use instead" column points at it.

Never run these as shell commands. A harness that denies one wastes the round-trip, and no rephrasing
gets past it.

|Never run|Use instead|
|---|---|
|`grep`, `git grep`, and any `\| grep` / `\| grep -v` segment|the harness search tool (`Grep`); `rg` when you must shell out (`rg -v` inverts) — see [[rg]]|
|`find`|the harness glob tool (`Glob`); `fd` when you must shell out (`fd -e py`, `fd -H`) — see [[fd]]|
|`rm -rf`|`rm -r` on a specific path, or `git clean`|
|`git push --force`|`git push --force-with-lease`, and only when asked|
|`sudo`, `su`, `chmod 777`, `dd`, `mkfs`, `fdisk`, `ssh`, `scp`, `rsync`|ask the user to run it|

## The compound-command trap

The matcher inspects **every segment**. One denied word kills the whole chain, including the allowed
segments.

- Never bury a denied binary in a pipe or `&&` chain. `rg foo | grep -v test` is denied even though
  `rg` alone is fine — filter inside `rg`.
- Split destructive+benign compounds. `rm -rf docs/x && mkdir -p docs/x` dies as a unit.
- Never bundle a git write with anything else. Commit, push, and PR-create are *three* calls. A
  denial on the push segment throws away the commit too. Push and `gh pr create` need confirmation
  first anyway — see [[stop-and-ask]].

## Subagents

Subagents inherit none of this. A prompt that will search a tree must say so. Quote it: *prefer the
harness search and glob tools; if you shell out, use `rg`/`fd`, never the `grep`/`find` binaries.*
Carry the output bound across too: *scope to a path, bound the result set (`-l`, `-c`, `-m`), route
the rest through `ctx_batch_execute`.* Told only "use rg", a subagent returns the whole dump.
