# agent-carnet

A shared, auto-expiring markdown notebook for agents. Notes live in a `.carnet/` directory in the
project and expire after 30 days of disuse, so the agent can hand off context between sessions
without the notebook growing forever.

Ships as a **rule** (plus a Dockerfile that bakes the CLI) — no MCP server.

Upstream: <https://github.com/yamadashy/agent-carnet>
