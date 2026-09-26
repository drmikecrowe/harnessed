# Harness Mechanics

Facts about how this harness executes, and the behavior they force. Nothing here is judgment; each
line exists because breaking it is silent or unrecoverable inside a session. None of it applies
outside a coding harness.

## Shell commands the matcher denies

The matcher inspects every segment of a command. One denied word kills the whole chain, allowed
segments included, and no rephrasing gets past it.

| Never run | Use instead |
|---|---|
| `grep`, `git grep`, any `\| grep` segment | the harness search tool; `rg` when you must shell out |
| `find` | the harness glob tool; `fd` when you must shell out |
| `rm -rf` | `rm -r` on one named path, or `git clean` |
| `git push --force` | `git push --force-with-lease`, and only when asked |
| `sudo`, `su`, `chmod 777`, `dd`, `mkfs`, `fdisk`, `ssh`, `scp`, `rsync` | ask Mike to run it |

- A denied binary inside a pipe or `&&` chain denies the chain. Filter inside `rg`; split
  destructive and benign steps into separate calls.
- Commit, push, and PR-create are three calls. A denial on the push segment discards the commit.
- Subagents inherit none of this. A brief that will search a tree says so; the `search-tools` skill
  has the wording.
- Scanning the filesystem from `/` or `~` for something Mike can name is a question, not a search.

## Context is a non-renewable budget

- Search before reading. Open a file only when search cannot answer, and open the lines you need,
  never the file.
- Capture an expensive command's output once, to a file, and query it. Never re-run to filter.
- Understanding a subsystem takes more than three files: dispatch a read-only subagent and take
  back the compressed finding.
- A successful edit reports its own failure. Reading the file back to confirm buys nothing.
- No speculative reads. Know why you need a file before opening it.
- Background output comes back as a digest, never the full stream.
- An index, graph, or cache is a derived view and can trail the working tree. Use it for breadth
  and ranking; use the authoritative resolver for single-symbol truth.

## The working directory is session identity

Backgrounding and transcripts key on the live working directory. A session that wandered into a
subdirectory gets filed under the wrong project and cannot be resumed from the root.

- Reach files by absolute path. Never `cd` to get somewhere.
- A command that must run elsewhere gets `cd <dir> && <cmd>` in one call. A bare `cd` persists.
- Prefer the tool's own path argument: `git -C <dir>`, `fd . <dir>`, `rg <pat> <dir>`.
- A declared worktree switch is the supported way to move, and is exempt.
