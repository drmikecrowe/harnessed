# agent-carnet

A shared, auto-expiring markdown notebook for agents. Notes live in a `.carnet/` directory in the
project and expire after 30 days of disuse, so the agent can hand off context between sessions
without the notebook growing forever.

Ships as a **rule**, plus the upstream-bundled skill installed by the recipe's `install.sh` (both in
the container image and on a `--host` launch) — no MCP server.

The `agent-carnet` **CLI** is installed only in the container image (`pnpm add -g` in the recipe
Dockerfile). A `--host` launch deliberately does not install it: that would write into your global
pnpm store, outside every harnessed-owned directory. On a host launch you get the skill without the
binary.

## Removing what this recipe leaves behind

`install.sh` writes only into the harnessed-owned agent config dir, which is rebuilt from scratch on
every launch — nothing to clean up there.

`agent-carnet init`, which you run yourself per project, creates a `.carnet/` notebook in that
project. Nothing reclaims it. To remove it:

```bash
rm -rf .carnet
```

Upstream: <https://github.com/yamadashy/agent-carnet>
