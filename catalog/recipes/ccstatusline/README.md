# ccstatusline

Bakes [`ccstatusline`](https://www.npmjs.com/package/ccstatusline) — the status-line renderer Claude
Code runs for its `statusLine` — into the agent image, and wires Claude Code to use it by default.

## What it does

- **Installs the pinned `ccstatusline` CLI** via mise's `npm:` backend, so a shim resolves at
  `/home/harnessed/.local/share/mise/shims/ccstatusline`.
- **Bakes a `statusLine` block** into the container's `~/.claude/settings.json` at build time
  (branched on `${HARNESS}` — `statusLine` is a Claude Code concept, so only the `claude` harness
  gets it):

  ```json
  "statusLine": {
    "type": "command",
    "command": "/home/harnessed/.local/share/mise/shims/ccstatusline",
    "padding": 0,
    "refreshInterval": 10
  }
  ```

  harnessed's `emit.merge_settings` preserves this baked key while re-applying its own required
  settings (the hatago MCP grant), so the status line survives the post-build settings merge.

## Host config forward

If the host has `~/.config/ccstatusline/settings.json`, the launcher bind-mounts it **read-only** at
the same path inside the container, so the agent's status line matches your host layout/segments.
When the host file is absent the mount is skipped and **ccstatusline's built-in defaults** apply — a
missing host config never breaks launch.

## Version

Pinned via the `CCSTATUSLINE_VERSION` build arg in the recipe `Dockerfile`. Bump it deliberately.
