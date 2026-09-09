---
name: commit-hygiene
description: Write a commit message. Load before `git commit`, when asked to commit, or when composing a PR title. Type vocabulary comes from the repository's own log; one change per commit; the body says why.
---

# Commit Hygiene

- `type(scope): description` — imperative, lowercase, no trailing period.
- Take the type vocabulary from the repository's own log, never a memorised list. Read
  `git log --format=%s` before inventing one.
- One change per commit. Never bundle an unrelated fix, a format pass, or a dependency bump.
- The body says WHY. The diff already says what.
- Never mention AI, an agent, a model, or "generated" in a commit message, PR title, or PR body.

Issue linkage and closing keywords are project policy — see the repository's own docs.
