# openwiki

The agent-driven repository wiki ([langchain-ai/openwiki](https://github.com/langchain-ai/openwiki)),
wired as the **host-driven integration**. The session's own agent researches the repository and
writes each page with its native tools. openwiki owns the durable page queue, Claims validation,
source-drift handling, and finalization.

This is what `openwiki integrations install claude` sets up by hand. That command is not usable
here: it writes a skill into `~/.claude` and an `mcpServers` entry into `~/.claude.json`. In a pod
the profile mount shadows the first, and harnessed generates MCP wiring into the hatago config, so
the second would be dead config. The recipe re-creates both from the same pinned package.

## What you get

| Deliverable | How |
| --- | --- |
| `openwiki` on PATH | `install.sh` — a project-scoped `pnpm install`, symlinked into `$HARNESSED_BIN_DIR` |
| `openwiki` skill | `install.sh` copies the package's own `integrations/openwiki` directory |
| `openwiki` MCP server | `recipe.yaml` — stdio, `openwiki-mcp-host` (wrapper passing `$HARNESS`), spawned by hatago |
| Resumable state | `persist: .openwiki`, scope `project` |

Five operations reach the agent: `openwiki_begin`, `openwiki_submit_plan`, `openwiki_next_page`,
`openwiki_submit_page`, `openwiki_finish`. Ask it to *initialize this repository's OpenWiki*, or to
*update it for changes since the last successful run*.

Author the repository's brief at `openwiki/INSTRUCTIONS.md`. openwiki reads it for scope and
priorities and never rewrites it.

## No credential, and no egress

Host-driven runs use the agent's own authenticated model session, so this recipe needs no provider
key. That is upstream's documented behavior and it holds in the shipped code:
`dist/integrations/mcp/server.js` builds the server from a tool provider and never reaches
`needsCredentialSetup` or the onboarding gate that standalone `openwiki --init` walks.

Nothing outbound happens at run time either. The install fetch runs in its own container before any
pod exists, so it is not subject to the egress firewall, and telemetry is disabled through `env:`.
A stack that wants the standalone generator instead needs provider env and an inference host in
`egress:` — that is a different recipe, not a flag on this one.

## Why not `tools: [npm:openwiki@…]`

openwiki pulls `better-sqlite3` transitively through `@langchain/langgraph-checkpoint-sqlite`, and
imports its `SqliteSaver` statically at `dist/agent/index.js:9`. The native addon is therefore
required to **load** the CLI, for every subcommand including `mcp`. Building it runs a dependency
lifecycle script, and `catalog/base/pnpm/config.yaml` sets `strictDepBuilds: true`.

Measured in `localhost/harnessed-claude:latest`, pnpm 11.21.0:

```text
no allowlist  -> pnpm install exits 1, [ERR_PNPM_IGNORED_BUILDS] better-sqlite3@12.11.1
allowBuilds   -> exit 0, build/Release/better_sqlite3.node present, openwiki loads
```

pnpm v11 rejects `allowBuilds` from the global config, and the allowlist does not apply to global
installs. `tools:` is a list of pinned spec strings with no way to carry a build approval, so the
install is a project-scoped `pnpm install` with a one-entry reviewed allowlist — the mechanism
`catalog/base/pnpm/config.yaml` prescribes for exactly this case.

The failure mode if that allowlist is ever lost is loud: pnpm exits 1 and names the package.

## Pins

The version lives in `install.sh` as `OPENWIKI_VERSION`, and nowhere else. `harnessed update` reads
literals out of an install script, so it appears in the pin report even though it is not a `tools:`
entry.

No `pnpm-lock.yaml` ships with the recipe: the top-level package is pinned and transitives resolve
under the house policy (`minimumReleaseAge`, `blockExoticSubdeps`, `verifyStoreIntegrity`), which is
how every other npm-backed recipe here is pinned.

## Removal

`install.sh` writes to two harnessed-owned places and nowhere else:
`$(dirname "$HARNESSED_BIN_DIR")/share/openwiki` (the install tree and the `openwiki` symlink beside
it) and `$HARNESSED_CONFIG_DIR/skills/openwiki`. Dropping the recipe and relaunching `--fresh`
clears both. Persisted state is separate: `harnessed-tools persist-prune --recipe openwiki`.
