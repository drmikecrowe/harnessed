# Token & Context Budget

**PROTECT THE CONTEXT WINDOW. EVERY TOKEN SPENT IS GONE.**

- Search before read. The harness's search tool first, `rg`/`fd` only when you must shell out. Open a file only when search cannot answer the question.
- Read minimally. Bound every read to the lines you need — a range selector or `offset`/`limit`, whichever your harness takes. Never read a whole file to find one function. Skip files over 100KB unless required.
- One capture, many queries. Pipe expensive commands to `/tmp/` once. Never re-run to filter differently.
- Delegate broad exploration. If understanding a subsystem requires reading more than three files, dispatch a read-only subagent and take back only the compressed finding.
- Digest, not output. For background processes, use a digest/summary form (~30 tokens) not full output (~2000 tokens).
- Read existing files before writing. Never re-read to confirm a write that already succeeded: an editing tool reports its own failure, so a confirming read buys nothing. Inspect the diff or specific lines only when the change itself needs verifying.
- No speculative reads. Do not open files "just in case." Know why you need a file before reading it.
- Thorough in reasoning, concise in output. Tight narration — one sentence per update, no restating what tool output already says.
- No sycophantic openers or closing fluff. No emojis. No em-dashes. This is a style floor for prose you author — chat replies, commit messages, PR bodies, docs you write — not a licence to rewrite quoted text, existing files, or a source you are only citing.
- Do not guess APIs, versions, flags, commit SHAs, or package names. Verify by reading code or docs before asserting.

Violating these rules wastes the user's money and shortens the session. Treat the context window as a scarce, non-renewable resource.
