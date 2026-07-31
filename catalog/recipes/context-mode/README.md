# context-mode

Per-session token discipline. Large tool output is run in a sandbox so only the *derived answer*
enters the conversation rather than the raw dump ("think in code"); raw `Bash`/`Read`/`Grep`/
`WebFetch` calls are routed through `ctx_*` tools instead; and session state is snapshotted to a
local SQLite DB so the model can resume after a compaction.

Wired as a **stdio MCP server plus four hooks** — and both halves are needed, because the MCP server
alone does nothing. `PreToolUse` (injects the routing nudge) and `SessionStart` (re-injects session
context) are the two upstream marks REQUIRED; `PostToolUse` and `PreCompact` are optional upstream
but are what actually give continuity across a compaction, so both are wired here.

The session store (`~/.context-mode`) is declared as workspace-scoped `persist:`, so it survives a
`--fresh` launch and one project's session log never surfaces in another's.

## omp: the native extension (container only)

Under `omp` the bridged Claude hooks are inert, so the recipe suppresses them
(`hooks.skip_harnesses: [omp]`) and installs upstream's own omp extension instead — that is all
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
