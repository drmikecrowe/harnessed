# Working Directory Stability

The session's working directory is identity, not convenience. Treat it as pinned to where the session
launched.

## The failure this prevents

Backgrounding snapshots the **live** cwd, not the launch cwd. Transcripts are keyed by that snapshot,
slugified per project. A session that wandered into a subdirectory gets backgrounded into the wrong
namespace, and resuming from the real project root cannot see it. Nothing inside a running job can
re-key it.

<!-- Observed 2026-08-17: a job drifted into a nested skills/ subdirectory while writing a skill. A
job spawned ninety seconds later froze that path as its origin. The parent session was correct;
only the child was stranded. -->

## Rules

- **Never `cd` to reach a file.** Pass an absolute path. Read, Write, Edit, `rg`, and `fd` all take
  one.
- **Never leave the shell parked elsewhere.** A command that must run from another directory gets
  `cd <dir> && <cmd>` in a single invocation. A bare `cd` persists into every later call.
- **Prefer the tool's own path argument**: `git -C <dir> status`, `fd . <dir>`, `rg <pat> <dir>`.
- **Confirm the working directory before any handoff.** Backgrounding, spawning a job, and ending a
  session are all snapshot points. Without a declared worktree switch, `pwd` reads the launch
  directory; after one, it reads the declared worktree.

A declared worktree switch is the supported way to change directory and is exempt. This rule governs
incidental drift only.

Pairs with [[execution-discipline]] (drift, generally) and [[token-efficient]] (absolute paths cost
fewer round trips).
