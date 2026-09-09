---
name: search-tools
description: Bound a text search or file listing before it burns the context window. Load before searching a source tree, listing files, or writing a subagent brief that will search. Covers rg, fd, and result-set caps.
---

# Search Tools

The always-on floor is [[denied-commands]]: never run the `grep` or `find` binaries. This skill is
the rest of it — which tool to reach for, and how to bound what comes back.

## Text Search: Search Tool First, Then rg

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

## File Discovery: Glob Tool First, Then fd

Find paths with the harness's glob or file-discovery tool first. Shell out only when it cannot
express the query, then use `fd`, never the `find` binary (see [[denied-commands]]). That ban names
the shell binary only; built-in file tools are not shell `find`.

```bash
# Wrong
find . -name "*.ts" -type f

# Right
fd -e ts
```

Narrow at the source: `-e <ext>`, a starting path, `--max-depth`. `fd -H` includes hidden files.

Still large → wrap it in `rtk find`, which takes native `find` flags and prints a compact tree.

A listing you need to question rather than read → `ctx_batch_execute`, with SPECIFIC queries. A
broad query matches every section and re-emits the whole listing, once per query. A narrow one never
surfaces the section you asked for. See [[ctx-routing]].

## Subagents

Subagents inherit none of this. A prompt that will search a tree must say so. Quote it: *prefer the
harness search and glob tools; if you shell out, use `rg`/`fd`, never the `grep`/`find` binaries.*
Carry the output bound across too: *scope to a path, bound the result set (`-l`, `-c`, `-m`), route
the rest through `ctx_batch_execute`.* Told only "use rg", a subagent returns the whole dump.
