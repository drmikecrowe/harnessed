# rtk

rtk (Rust Token Killer) — compresses dev-command output by 60–90% before it reaches the model. Wrap
a build/test/lint command in `rtk` and the model sees a digest instead of thousands of lines of
scrollback.

Ships as a CLI baked by the Dockerfile; no MCP server.

Upstream: <https://github.com/rtk-ai/rtk>
