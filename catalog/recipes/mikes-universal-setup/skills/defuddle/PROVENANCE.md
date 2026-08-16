# Provenance: defuddle

Derived from **[kepano/obsidian-skills](https://github.com/kepano/obsidian-skills)**,
`skills/defuddle/SKILL.md` — MIT (see `LICENSE` alongside this file).

## Local modifications (why this is vendored, not fetched)

Two edits, layered. Because of them this skill is **not** fetched from upstream at build time (a
fetch would revert both) — it is vendored here.

**1. Trigger strengthened** — the original divergence from upstream:

- description: upstream *"Use instead of WebFetch when the user provides a URL…"* →
  local *"**ALWAYS** use this instead of Fetch or WebFetch for any URL… **check this skill
  before fetching a URL at all**"*, and it names `npm/pnpm/GitHub docs` explicitly.
- body: the same "prefer" → "ALWAYS use it instead of Fetch/WebFetch" strengthening.

The base upstream commit was not identified: the local copy matches no commit in kepano's recent
history, so this edit predates the current window or was taken from an older revision.

**2. Re-scoped from unconditional to escalation, and de-Claude-ified** (2026-08-16):

The unconditional *"ALWAYS, before fetching at all"* trigger collided with harnesses whose own
read/fetch already performs reader-mode extraction. Followed literally it meant shelling out to
Defuddle to redo, less well, work the harness had already done. It also hard-coded the Claude tool
names `Fetch` and `WebFetch`, which do not exist in every harness this recipe targets — a
harness-specific assumption inside a recipe that is required to be harness-independent.

Now: prefer the harness's own extraction, escalate to Defuddle when that output is cluttered,
boilerplate-heavy, or truncated. Tools are described by capability instead of named.

To re-sync: diff against `kepano/obsidian-skills:skills/defuddle/SKILL.md`, decide which of the two
local edits still apply, re-apply them, and update this note.
