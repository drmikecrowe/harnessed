# Stop-and-Ask

- Never scan the filesystem broadly (`find /`, `rg` over root) for something the user can name. Ask.
- Never take an outward-facing action (push, PR, comment, publish, send) without explicit
  confirmation. A missing "yes" means "no".
- Never echo, log, or restate a secret. Never ask the user to paste a secret into chat, or to edit
  `.env` by hand. Use the secure env mechanism.
