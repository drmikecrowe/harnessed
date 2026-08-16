# File Discovery: Glob Tool First, Then fd

Find paths with your harness's built-in glob or file-discovery tool first. Shell out only when it
cannot express the query — then use `fd`, never `find`, which stays denied at the permission layer
(see [[denied-commands]]).

When you do shell out:

```bash
# Wrong
find . -name "*.ts" -type f

# Right
fd -e ts
```

`rtk` has no `fd` subcommand, so there is nothing to wrap a listing in. When a listing is large
enough to matter, run it through `ctx_batch_execute` instead and query the result. Better still,
narrow it at the source: `-e <ext>`, a starting path, `--max-depth`.
