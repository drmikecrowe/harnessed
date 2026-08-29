# Text Search: Search Tool First, Then rg

Search with the harness's built-in search tool first — it respects ignore files and returns
line-anchored matches. Shell out only when that cannot answer the question. Then use `rg`, never the
`grep` binary (see [[denied-commands]]; that ban covers `git grep` and `| grep`, and `rg -v`
inverts). The ban names the shell binary only: a built-in search tool is not shell `grep`.

`rg` is the fallback, not the default. No search tool → `rg` by elimination, never by preference.

## Bound the result set at the source

An unbounded search over a large tree is one of the cheapest ways to burn a context window. Cap the
output at the source, never after it lands:

- Existence or location only → `rg -l` for filenames, `rg -c` for counts. Never page full matches to
  answer "does this exist".
- Cap the volume → `-m/--max-count`, and scope to a path or `-g` glob before widening.
- Could not bound it → route by what you need back:
  - **`rtk rg …`** for the matches themselves. Runs `rg` natively and compacts the result:
    whitespace stripped, long lines truncated, grouped by file. One call, no round trip. The rtk hook
    rewrites a plain `rg` too, so the prefix is optional and never doubles up.
    **Not when exact bytes matter** — the compaction is lossy. Precise whitespace, a full unbroken
    line, or a token you will copy → bounded raw `rg`.
  - **`ctx_batch_execute`** for a large match list you have specific questions about. It indexes the
    output and returns only the windows your `queries` match. See [[ctx-routing]] for the
    query-breadth trap.

Neither un-spends a result set you did not need. Bound first, then route.

## Capture once, query many

```bash
# Wrong — runs twice, output may differ
pnpm build | tail -50
pnpm build | rg error

# Right
pnpm build > /tmp/build.log 2>&1
tail -50 /tmp/build.log
rg -i error /tmp/build.log
```
