---
name: context-mode
description: Save and recall short project context notes that persist across fresh-container launches. Use when the user asks to remember a fact about this project, jot a note, or recall earlier notes.
---

# Context Mode

A minimal context-notes skill — the project-scoped persist spike. It writes a per-project notes log
to `~/.context-mode/notes.md` inside the container. That folder is declared as project-scoped
`persist:` by the recipe, so harnessed mounts it from a per-project host dir and the notes survive a
`harnessed --fresh` (fresh-container) launch. This is a tracer, not a full indexing engine.

## Saving a note

When the user asks to remember something about this project, append a timestamped line to the notes
log (creating the dir + file on first use):

```bash
mkdir -p ~/.context-mode
printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<the note>" >> ~/.context-mode/notes.md
```

Confirm briefly what was saved.

## Recalling notes

When the user asks what was remembered, read the log back and summarise it:

```bash
cat ~/.context-mode/notes.md 2>/dev/null || echo "No context notes saved yet."
```

Keep responses short and natural. The whole point is to prove that `~/.context-mode` persists across
launches — if notes from an earlier session are still there, persist worked.
