# headroom

Context compression on demand — `headroom_compress`, `headroom_retrieve`, `headroom_stats`. Squeezes
JSON, code, and other structured payloads before they reach the model, and lets the agent pull the
full text back when it actually needs it.

Wired as a **stdio MCP server** — hatago spawns it as a child.

Upstream: <https://github.com/headroomlabs-ai/headroom>

## Proxy mode (init.run)

On every launch the recipe also starts headroom's **optimization proxy** before the harness —
same 0.27.0 pin, but a separate uvx env (`headroom-ai[proxy]`): the proxy needs fastapi/uvicorn,
and the MCP server's `[mcp]` extra cannot start it:

1. `ANTHROPIC_BASE_URL` already set → skipped entirely. The proxy targets the Anthropic API
   upstream and has no override, so a gateway user must not be hijacked.
2. Port 8787 already bound → reused only after `GET /livez` names a healthy headroom proxy
   (`{"service":"headroom-proxy","status":"healthy"}` at 0.27.0); a foreign listener is left
   alone. Free → `headroom proxy --port 8787` starts in the background (log:
   `/tmp/headroom-proxy.log`).
3. Proxy answers → `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` is exported into the harness
   process. `uvx` missing or port never opens → warning, launch continues without compression.

Works on both backends: container (sourced in the attach shell, same pod netns as the agent) and
host (`_host_run_inits` propagates the export into the exec'd harness env). The proxy is an
unmanaged daemon, and the lifetimes differ: in a container it dies with the pod; on the host the
`nohup` orphan OUTLIVES the harness session and later launches reuse it — stop it yourself
(`pkill -f 'headroom proxy'`) when you want it gone.
