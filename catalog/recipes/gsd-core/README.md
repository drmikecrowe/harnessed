# gsd-core

GSD Core — a spec-driven-development suite of skills, agents, and workflows. Installed by running
its own upstream installer (`@opengsd/gsd-core`), pinned to an exact version.

Ships as skills/agents baked by `install.sh`. No MCP server.

## Container vs `harnessed host-run`

`install.sh` runs in **both** modes and does the same thing in each — this is a pure content recipe,
so nothing is skipped host-side. The installer's `--global` flag targets `os.homedir()/.claude`. On a
host-native launch, `install.sh` points a throwaway `$HOME` at the stack's own config dir so "global"
means *this stack*, never your real `~/.claude`.

Requires `pnpm` on PATH host-side (it is the installer's runner). If `pnpm` is missing the install
fails loudly rather than silently shipping a stack with no GSD skills.

## Footprint / removal

Everything the installer writes lands inside the stack's config dir, which harnessed rebuilds from
scratch on every launch — nothing of GSD's to clean up. The one side effect outside it is pnpm's own
package store (shared with every other pnpm project on the machine, `~/.local/share/pnpm/store` by
default):

```bash
pnpm store prune     # drop unreferenced packages, incl. this one, from the shared store
```

Upstream: <https://github.com/open-gsd/gsd-core>
