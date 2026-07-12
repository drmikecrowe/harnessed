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

Upstream: <https://github.com/mksglu/context-mode>
