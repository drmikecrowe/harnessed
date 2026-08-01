# gstack

Garry Tan's gstack skill suite — browser automation, design, PDF handling, and more. Installed by
running upstream's own `./setup`, from the recipe's `install.sh`.

Ships as skills. No MCP server.

`install.sh` runs in both modes, but one step cannot: `bunx playwright install-deps chromium` is an
apt install needing root, so it stays in the recipe Dockerfile and is declared as `install.system:`.
A `--host` launch prints that reason and skips it — you get gstack's skills, but its headless
Chromium will not launch without those OS libraries. Use a container for the browser skills.

`install.sh` also requires `bun` on `PATH` (upstream's `./setup` shells out to it). The container
base image ships bun; on a host launch the install fails loudly if it is missing.

## Removing what this recipe leaves behind

The skill tree itself lives under the harnessed-owned agent config dir, which is rebuilt from
scratch on every launch — nothing to clean up there.

On a **host** launch, upstream's `./setup` populates the caches its own tools own, in your real home
rather than a disposable container. These are shared, tool-owned caches — other projects may be
using them, so removing them is your call, not harnessed's:

```bash
rm -rf ~/.bun/install/cache     # bun's package cache, from ./setup's `bun install`
rm -rf ~/.cache/ms-playwright   # Playwright's browser downloads (macOS: ~/Library/Caches/ms-playwright)
```

This recipe also runs `gstack-config set redact_prepush_hook true`, which makes gstack's `/ship`
install a managed `pre-push` git hook into **every repo you ship from** — a per-project write
nothing reclaims. gstack ships its own remover; run it inside each such repo:

```bash
~/.claude/skills/gstack/bin/gstack-redact uninstall-prepush-hook
```

Upstream: <https://github.com/garrytan/gstack>
