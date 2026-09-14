# context-mode

Per-session token discipline. Tool calls that return large output run in a sandbox. Only the
*derived answer* enters the conversation, not the raw output ("think in code"). Raw `Bash`/`Read`/`Grep`/
`WebFetch` calls are routed through `ctx_*` tools instead. Session state is snapshotted to a
local SQLite DB so the model can resume after a compaction.

Wired as a **stdio MCP server plus four hooks** — and both halves are needed, because the MCP server
alone does nothing. `PreToolUse` (injects the routing nudge) and `SessionStart` (re-injects session
context) are the two upstream marks REQUIRED; `PostToolUse` and `PreCompact` are optional upstream
but are what actually give continuity across a compaction, so both are wired here.

The session store (`~/.context-mode`) is declared as workspace-scoped `persist:`, so it survives a
`--fresh` launch and one project's session log never surfaces in another's.

## Skills

A marketplace install of context-mode also ships a skill suite. `install.sh` delivers it, in both
modes and on every harness, by copying it out of the package `tools:` already pinned:

| Skill | What it does |
| --- | --- |
| `context-mode` | routing: when to reach for a `ctx_*` tool instead of raw Bash/Read, plus language pattern references |
| `ctx-search` | query the FTS5 knowledge base |
| `ctx-index` | index a path into that knowledge base |
| `ctx-stats` | context savings for the session |
| `ctx-doctor` | diagnostics |
| `ctx-purge` | wipe the knowledge base (destructive) |
| `ctx-insight` | open the hosted Insight dashboard |

**Installed, not vendored.** The skills come out of the pinned package rather than a copy in
`catalog/`, so the skills and the binary cannot drift apart and `harnessed update` keeps one place
to bump. `expect.skills:` declares them, because the assembler cannot infer what an install script
writes.

**`ctx-upgrade` is not installed.** Upstream's eighth skill pulls latest from GitHub, rebuilds, and
updates the npm global — it unpins the binary mid-session. Bump `tools:` in `recipe.yaml` and
rebuild instead.

Two upstream strings assume a plugin install and are rewritten in place on copy: the
`/context-mode:ctx-foo` slash-command namespace becomes `/ctx-foo` (each skill is fanned standalone
here), and the `mcp__context-mode__ctx_foo` tool name becomes bare `ctx_foo` (the server sits behind
the hatago hub, so the plugin-form literal names nothing).

## omp: the native extension (container only)

Under `omp` the bridged Claude hooks are inert, so the recipe suppresses them
(a per-entry `skip_harnesses: [omp]` on each) and installs upstream's own omp extension instead — that is all
`install.sh` does: `omp plugin install context-mode@<version>`. The step is **container-only, and
says so on a host launch**: it writes into `~/.omp/plugins`, which host-side is *your own* omp
installation. harnessed mounts `~/.omp/agent` read-write as deliberately shared host state, but it
does not install plugins into your omp, and there is no per-stack omp plugin root to redirect the
install into.

So `harnessed host-run` with `HARNESS=omp` gets the MCP server and CLI (via `install:`) but neither
the bridged hooks nor the native extension. Run the stack in a container for the full wiring. Every
other harness is unaffected — the hooks are the delivery mechanism there, and they work in both modes.

## Footprint / removal

`install.sh` writes nothing at all on a host launch (see above), so there is nothing to remove. The
session store is a declared `persist:` entry under `$XDG_DATA_HOME/harnessed/persist/`, managed by
harnessed. Container-side the omp plugin is an image layer and goes away with the image.

Upstream: <https://github.com/mksglu/context-mode>
