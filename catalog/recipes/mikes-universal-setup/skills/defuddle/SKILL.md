---
name: defuddle
description: Extract clean markdown from a cluttered web page with the Defuddle CLI. If the harness read returns raw HTML, navigation chrome, or a truncated page, escalate here. Never use it for a `.md` URL; read that directly.
---

# Defuddle

Defuddle extracts readable content from a web page and emits markdown. Use it when a raw HTML fetch would flood the context window. Use it when the harness read returns clutter, boilerplate, or a truncated page. If that read is already clean, skip Defuddle: a second subprocess buys nothing.

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
