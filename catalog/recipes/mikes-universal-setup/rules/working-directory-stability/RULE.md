# Working Directory Stability

The session's working directory is identity, not convenience. Treat it as pinned to where the session
was launched.

## The failure this prevents

Backgrounding a session snapshots the **live** cwd, not the launch cwd. Transcripts are keyed by that
snapshot, slugified into a per-project directory. A session that wandered into a subdirectory gets
backgrounded into the wrong namespace, and resuming from the real project root cannot see it.
Nothing inside a running job can re-key it.

Observed 2026-08-17: a job launched in a project root drifted into a nested `skills/` subdirectory
while writing a skill. A job spawned ninety seconds later froze that path as its origin cwd. The
parent session was correct; only the spawned child was stranded.

## Rules

- **Never `cd` to reach a file.** Use an absolute path in the tool call. Read, Write, Edit, `rg`,
  and `fd` all take one; none of them need the shell to be standing anywhere in particular.
- **Never leave the shell parked elsewhere.** If a command genuinely must run from another directory,
  scope it to that one call: `cd <dir> && <cmd>` inside a single invocation. A bare `cd` persists
  into every later call.
- **Prefer the tool's own path argument** over shell navigation: `git -C <dir> status`, `fd . <dir>`,
  `rg <pat> <dir>`.
- **Before any handoff, confirm where you are standing.** Backgrounding, spawning a job, or ending a
  session are all snapshot points. `pwd` should read the launch directory.

## Not covered

A declared worktree switch changes the working directory deliberately and is the supported way to do
it. This rule governs incidental drift from shell navigation, never a declared switch.

Pairs with [[execution-discipline]] (drift is the general failure; this is one concrete form) and
[[token-efficient]] (absolute paths cost fewer round trips than navigating and re-navigating).
