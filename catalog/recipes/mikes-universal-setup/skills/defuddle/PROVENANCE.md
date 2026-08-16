# Provenance: defuddle

Derived from **[kepano/obsidian-skills](https://github.com/kepano/obsidian-skills)**,
`skills/defuddle/SKILL.md` — MIT (see `LICENSE` alongside this file).

## Local modifications (why this is vendored, not fetched)

Three edits, layered. Because of them this skill is **not** fetched from upstream at build time (a
fetch would revert all three) — it is vendored here.

**1. Trigger strengthened** — the original divergence from upstream:

- description: upstream *"Use instead of WebFetch when the user provides a URL…"* →
  local *"**ALWAYS** use it instead of Fetch or WebFetch for any URL… **check it before
  fetching any URL**"*.
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

**3. Cut to the house style** (#404, merged into this branch):

`#404` cut the description from 86 words to 40 for `harnessed-tools lint-prose`. Its own provenance
note recorded that the ALWAYS-strengthening survived the cut. In this merge it does not: edit 2
removed ALWAYS deliberately, and edit 3 is now only the word budget applied to edit 2's wording. The
dropped words were the `npm/pnpm/GitHub docs` example list and a restatement of the Fetch-first
prohibition, and neither returns.

To re-sync: diff against `kepano/obsidian-skills:skills/defuddle/SKILL.md`, decide which of the three
local edits still apply, re-apply them, and re-run `harnessed-tools lint-prose` on the result.
