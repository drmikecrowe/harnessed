# ccstatusline

Bakes [`ccstatusline`](https://www.npmjs.com/package/ccstatusline) — the status-line renderer Claude
Code runs for its `statusLine` — into the agent image, and wires Claude Code to use it by default.

## What it does

Both steps live in `install.sh`, which runs on a **container build and a host launch alike**.

- **Installs the pinned `ccstatusline` CLI.** In a container, via mise's `npm:` backend, so a shim
  resolves at `/home/harnessed/.local/share/mise/shims/ccstatusline`. On a host launch, via `pnpm`
  into the recipe's install cache (`$XDG_CACHE_HOME/harnessed/install/ccstatusline/<version>`) —
  `mise use -g` is not used host-side because it writes *your* global mise config.
- **Writes a `statusLine` block** into the config dir's `settings.json` (branched on `${HARNESS}` —
  `statusLine` is a Claude Code concept, so only the `claude` harness gets it):

  ```json
  "statusLine": {
    "type": "command",
    "command": "/home/harnessed/.local/share/mise/shims/ccstatusline",
    "padding": 0,
    "refreshInterval": 10
  }
  ```

  That `command` is **computed per mode**, not hard-coded: the container gets the mise shim path
  above, a host launch gets the cached binary's absolute path. (The old Dockerfile baked the
  container path unconditionally, which is why a host launch got a `statusLine` pointing at a
  directory that does not exist on the host.)

  harnessed's `emit.merge_settings` preserves this baked key while re-applying its own required
  settings (the hatago MCP grant), so the status line survives the post-build settings merge.

Requires `pnpm` on PATH for the host path. A missing `pnpm` fails the install loudly.

## Host config forward

If the host has `~/.config/ccstatusline/settings.json`, the launcher bind-mounts it **read-only** at
the same path inside the container, so the agent's status line matches your host layout/segments.
When the host file is absent the mount is skipped and **ccstatusline's built-in defaults** apply — a
missing host config never breaks launch.

## Footprint / removal

A host launch installs the package into the recipe's install cache, which is the one thing it leaves
behind on purpose — the stack's config dir is rebuilt from scratch on every launch, but `statusLine`
is an absolute path the agent execs for the whole session, so the binary has to outlive it.

```bash
rm -r "${XDG_CACHE_HOME:-$HOME/.cache}/harnessed/install/ccstatusline"   # drop the cached CLI
pnpm store prune                                                        # and its shared-store copy
```

Nothing else is written outside the stack's config dir; your own
`~/.config/ccstatusline/settings.json` is only ever read.

## Version

Pinned once, by the `tools:` entry in `recipe.yaml`. `install.sh` carries no copy of the version —
it resolves the binary through `command -v`, so there is nothing to keep in lockstep and nothing
to drift. Bump the `tools:` pin and you are done.
