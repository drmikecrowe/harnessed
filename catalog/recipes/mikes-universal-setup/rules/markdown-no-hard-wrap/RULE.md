# Markdown: No Artificial Line Wraps

## Instructions

- **Prose paragraphs.** Keep each paragraph on one line, or join wrapped lines into one, so the renderer wraps it in the viewer. Do not break lines mid-sentence to stay under ~80 characters.
- **When hard newlines are correct:**
  - Lists: one line per list item. Keep item text on one line unless the item is genuinely multiple paragraphs.
  - Headings: a single line.
  - Fenced code blocks: preserve author intent. Do not reflow code to 80 columns.
  - Tables, block quotes, HTML: follow normal Markdown rules. Table rows may be long.
  - Poetry and intentional line breaks: keep explicit breaks where semantics require them.
- **Links and emphasis.** Do not split a paragraph so that a `[text](url)` link sits alone on a continuation line and obscures reading. The whole paragraph can be one line.
- **Rationale.** GitHub and most Markdown renderers wrap to the viewport. Fixed-width breaks in source help only in raw terminals, and they harm `git diff` and merge-conflict resolution.

## Don't

- Reformat existing Markdown by hard-wrapping every paragraph to 80 columns, unless the user explicitly asks for that style in that file.
- Apply this rule to non-Markdown formats (for example `.ts` comment blocks), unless the user asks for Markdown-style prose there.
