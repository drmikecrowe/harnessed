# File Discovery: Glob Tool First, Then fd

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
