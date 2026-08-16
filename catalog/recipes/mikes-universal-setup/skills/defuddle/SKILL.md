---
name: defuddle
description: Extract clean markdown from a web page with the Defuddle CLI. ALWAYS use it instead of Fetch or WebFetch for any URL — docs, articles, blog posts. Check it before fetching any URL. Exception: a `.md` URL goes to WebFetch.
---

# Defuddle

Use Defuddle CLI to extract clean readable content from web pages. ALWAYS use it instead of Fetch/WebFetch for standard web pages — it removes navigation, ads, and clutter, reducing token usage.

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
