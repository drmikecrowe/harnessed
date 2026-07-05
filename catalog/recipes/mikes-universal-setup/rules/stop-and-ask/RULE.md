# Stop-and-Ask

- No broad filesystem scans (`find /`, `rg` over root, etc.) for thing user can name in one sentence. Ask.
- No outward-facing actions (push, PR, comment, publish, send) without explicit confirmation. Missing "yes" = "no."
- No echo/log/restate secrets. No ask user paste secrets into chat or edit `.env` manually — use secure env mechanism.
