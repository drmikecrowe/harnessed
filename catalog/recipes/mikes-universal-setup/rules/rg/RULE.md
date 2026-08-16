# Text Search: Search Tool First, Then rg

Search with your harness's built-in search tool first. It is structured, respects ignore files, and
returns line-anchored matches that a shell pipeline cannot. Shell out only when it genuinely cannot
answer the question — then use `rg`, never `grep`, which stays denied at the permission layer (see
[[denied-commands]]).

`rg` is the shell fallback, not the default search path. A harness that offers no search tool makes
`rg` the default by elimination, not by preference.

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
