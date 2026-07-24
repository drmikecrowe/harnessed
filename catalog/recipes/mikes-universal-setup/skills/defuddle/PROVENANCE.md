# Provenance: defuddle

Derived from **[kepano/obsidian-skills](https://github.com/kepano/obsidian-skills)**,
`skills/defuddle/SKILL.md` — MIT (see `LICENSE` alongside this file).

## Local modification (why this is vendored, not fetched)

The trigger language was **strengthened** relative to upstream so the skill fires more
aggressively in this setup:

- description: upstream *"Use instead of WebFetch when the user provides a URL…"* →
  local *"**ALWAYS** use this instead of Fetch or WebFetch for any URL… **check this skill
  before fetching a URL at all**"*, and it names `npm/pnpm/GitHub docs` explicitly.
- body: the same "prefer" → "ALWAYS use it instead of Fetch/WebFetch" strengthening.

Because of that edit it is **not** fetched from upstream at build time (a fetch would revert
the customization) — it is vendored here verbatim. The base upstream commit was not identified:
the local copy matches no commit in kepano's recent history, so the edit predates the current
window or was taken from an older revision.

To re-sync: diff against `kepano/obsidian-skills:skills/defuddle/SKILL.md`, re-apply the
trigger strengthening, and update this note.
