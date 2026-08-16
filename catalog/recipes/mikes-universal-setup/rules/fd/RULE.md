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
