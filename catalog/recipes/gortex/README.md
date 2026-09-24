# gortex

Graph code intelligence for the agent: [gortex](https://github.com/zzet/gortex) indexes the
mounted repo (257 languages, tree-sitter + in-process resolvers) into a persistent SQLite
symbol/call graph and serves it over MCP. The agent reads the symbols it needs
(`read`, `search`, `trace`, `explore`, `analyze`) instead of whole files; blast-radius and
editing-context queries answer "what breaks if I change this?" without a scouting read.

Wired as a **stdio MCP server** whose graph lives in a **daemon** the recipe starts before the
harness (`init.run`). Upstream's own installer bakes 21 skills, 19 slash commands and 2
graph-only subagents into the profile, and its hook set is declared in `recipe.yaml` so the
assembler emits it into the generated `settings.json`.

## What fires when

| Piece | Delivered by | When |
| --- | --- | --- |
| `gortex` binary | `tools:` (mise `github:` release install, pinned) | install, both modes |
| skills / commands / subagents | `install.sh` → `gortex install --agents=claude-code …` | install, both modes |
| MCP server (`gortex mcp`) | hatago child (container) / native `.mcp.json` (host), behind a one-line daemon-ensure wrapper | harness start |
| daemon + repo registration | `init.run` (daemon ensure + `gortex track "$PROJECT_DIR"`) | every attach |
| hooks (`gortex hook`, 8 events) | `recipe.yaml` `hooks:` → assembler `settings.json` | every tool call / prompt |

## Daemon lifecycle

Two status-gated ensures keep the daemon up, order-independent, and both reuse-first — a daemon
that is already serving (on a host launch, usually your own machine-wide one) is left completely
alone; all clients speak to the same unix socket with isolated per-session state:

1. **The MCP entry itself** (`bash -c 'gortex daemon status || gortex daemon start --detach; poll
   status up to 5s; exec gortex mcp'`). v0.64.5 has **no** MCP-side auto-start — a bare
   `gortex mcp` exits when the daemon is down (upstream's onboarding doc claims otherwise; stale
   at this pin). The wrapper is what makes headless pods (`harnessed test`, CI — which never run
   an attach shell) and mid-session daemon crashes recover on their own; the bounded poll covers
   the detach-returns-before-socket-bind race, and a failed start's stderr flows into hatago's
   child log — the only diagnostic surface a headless failure has.

2. **`init.run`**, in the attach shell on every launch: the same ensure, then
   `gortex track "$PROJECT_DIR"` — the step the MCP entry cannot do — so tool calls don't get
   `repo_not_tracked`. Indexing runs in the daemon's background; plain `track` does not block.

Every `init.run` path exits 0: a daemon that will not start degrades to "gortex not connected"
in the capability report, never blocks the attach.

In a container the daemon dies with the pod and the next launch starts a new one
against the **persisted** store (`~/.gortex`, `scope: workspace`) — restart reopens the graph
and re-indexes only files whose mtime changed. On a host launch a daemon the recipe starts is
an unmanaged orphan that **outlives** the session and is reused by later launches; stop it with
`gortex daemon stop` when you want it gone.

## What is deliberately NOT run

- **`gortex init`** (per-repo). It writes `.mcp.json`, hooks and community-routing blocks into
  the repo — harnessed already owns the MCP wiring (hatago / native), the hooks come from the
  recipe, and repo footprint is the user's call. Run it yourself if you want the
  community-routing surfaces in a given checkout.
- **`--claude-md` / user-level hooks in install.sh.** The identity `CLAUDE.md` and
  `settings.json` are assembler-owned; the same workflow text reaches the agent via the MCP
  initialize response and the baked `gortex-*` skills.

## Known mode difference

Through the hatago hub (container) the MCP tools surface as `mcp__hatago__*`, so upstream's
`PostToolUse` localization matcher (written for native `mcp__gortex__*` names) does not fire
there — that one enrichment is host-only. The `PreToolUse` redirect and all name-independent
events work in both modes. Widening the matcher to the hub would fire gortex's hook for every
other recipe's MCP tools, which this recipe does not do.

Upstream's installer pins 3s/5s hook timeouts; the hooks schema carries only
`command`/`matcher`, so Claude Code's default timeout applies. `gortex hook` exits in
milliseconds and degrades silently when the daemon is unreachable.

## Footprint / removal

- **Container:** everything lives in the image layer + the persisted `~/.gortex` dir. Remove
  the recipe from the stack and `harnessed-tools persist-prune --recipe gortex --project
  <path> --yes` to drop the graph.
- **Host launch:** the profile wiring lands in the stack's own config dir (rebuilt each
  launch). Outside harnessed-owned space, a started daemon writes your real `~/.gortex`
  (store, socket, ledger) — the same directory your own gortex uses; delete it outright, or
  `gortex daemon stop` and keep the store.

Upstream: <https://github.com/zzet/gortex> · docs: [onboarding](https://github.com/zzet/gortex/blob/main/docs/onboarding.md),
[daemon](https://github.com/zzet/gortex/blob/main/docs/cli.md)
