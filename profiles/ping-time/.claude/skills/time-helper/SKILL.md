---
name: time-helper
description: Ask the time MCP server for the current time in any IANA timezone and convert times between timezones.
---

# Time Helper

Use the `time` MCP server (exposed through the hatago hub at the harness's single MCP endpoint) to
answer time questions. Call `get_current_time` with an IANA timezone (for example
`America/New_York`) to report the current time, and `convert_time` to translate a time from one
timezone to another. This skill ships no dependencies — it only documents how to drive the baked
`mcp-server-time` server.
