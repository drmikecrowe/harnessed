# Text Search: Search Tool First, Then rg

Search with your harness's built-in search tool first. It is structured, respects ignore files, and
returns line-anchored matches that a shell pipeline cannot. Shell out only when it genuinely cannot
answer the question — then use `rg`, never `grep`, which stays denied at the permission layer (see
[[denied-commands]]).

`rg` is the shell fallback, not the default search path. A harness that offers no search tool makes
`rg` the default by elimination, not by preference.

## Bound the result set at the source

An unbounded search over a large tree is one of the cheapest ways to burn a context window, whichever
tool runs it. Cap the output where it is produced, not after it lands:

- Existence or location only: `rg -l` for filenames, `rg -c` for per-file counts. Never page full
  matches to answer "does this exist".
- Cap the volume: `-m/--max-count` per file, and scope to a path or `-g` glob before widening.
- If this profile carries a rule naming a batch-execute or sandbox tool, **that rule governs** any
  search whose output you cannot bound: follow it instead of paging matches into the conversation.
  It still cannot un-spend a result set you did not need, so bound first, then route.

Capture expensive output once; query the file rather than re-running:

```bash
# Wrong — runs twice, output may differ
pnpm build | tail -50
pnpm build | rg error

# Right
pnpm build > /tmp/build.log 2>&1
tail -50 /tmp/build.log
rg -i error /tmp/build.log
```
