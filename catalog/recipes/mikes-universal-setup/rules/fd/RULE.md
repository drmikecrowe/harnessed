# File Discovery: Glob Tool First, Then fd

Find paths with your harness's built-in glob or file-discovery tool first. Shell out only when it
cannot express the query — then use `fd`, never the `find` binary (see [[denied-commands]]). The
ban names the shell binary only: built-in file tools are not shell `find`, and nothing here
restricts them.

When you do shell out (`fd -e py` filters by extension; `fd -H` includes hidden files):

```bash
# Wrong
find . -name "*.ts" -type f

# Right
fd -e ts
```

Narrow at the source first: `-e <ext>`, a starting path, `--max-depth`. When a listing is still
large enough to matter, wrap it in `rtk find`, which takes native `find` flags and prints a compact
tree. For a listing you need to question rather than read, run it through `ctx_batch_execute`.

Keep those queries SPECIFIC. A broad query matches every section and re-emits the whole listing, once
per query. That is the dump you were avoiding. Too narrow and a section you asked for never surfaces.
Both failure directions are real. See [[ctx-routing]].
