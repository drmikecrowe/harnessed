---
name: defuddle
description: Extract clean markdown from cluttered web pages with the Defuddle CLI, stripping navigation, ads, and boilerplate to save tokens. Reach for this when a page resists the harness's own fetch or read — raw HTML, heavy navigation chrome, cookie and consent walls, or a truncated extraction. If the harness already returns reader-mode markdown for a URL, use that first and escalate here only when its output is cluttered or incomplete. Never use it for URLs ending in .md, which are already markdown: read those directly.
---

# Defuddle

Defuddle extracts readable content from a web page and emits markdown. Use it when a raw HTML fetch would flood the context window, or when the harness's own reader-mode extraction comes back cluttered, boilerplate-heavy, or truncated. If that built-in extraction is already clean, you do not need Defuddle — shelling out to re-do work the harness already did costs a subprocess and buys nothing.

If not installed: `npm install -g defuddle`

## Usage

Always use `--md` for markdown output:

```bash
defuddle parse <url> --md
```

Save to file:

```bash
defuddle parse <url> --md -o content.md
```

Extract specific metadata:

```bash
defuddle parse <url> -p title
defuddle parse <url> -p description
defuddle parse <url> -p domain
```

## Output formats

| Flag | Format |
|------|--------|
| `--md` | Markdown (default choice) |
| `--json` | JSON with both HTML and markdown |
| (none) | HTML |
| `-p <name>` | Specific metadata property |
