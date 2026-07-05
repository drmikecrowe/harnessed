# File Discovery: Use fd

Use `fd` instead of `find`.

```bash
# Wrong
find . -name "*.ts" -type f

# Right
fd -e ts
```
