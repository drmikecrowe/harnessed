# Text Search: Use rg

Use `rg` instead of `grep`.

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
