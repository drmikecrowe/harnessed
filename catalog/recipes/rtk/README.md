# rtk

rtk (Rust Token Killer) — compresses dev-command output by 60–90% before it reaches the model. Wrap
a build/test/lint command in `rtk` and the model sees a digest instead of thousands of lines of
scrollback.

Ships as a CLI baked by `install.sh`; no MCP server.

## Container vs `launch --host`

`install.sh` runs in both modes, but the two halves differ:

| | container build | `launch --host` |
| --- | --- | --- |
| the `rtk` binary | installed via mise's `github:` backend, pinned | **not installed** — a loud warning, see below |
| `rtk init -g --auto-patch` (RTK.md + the PreToolUse hook) | into the image's `~/.claude` | into the stack's `$HARNESSED_CONFIG_DIR`, but only if `rtk` is already on your PATH |

The binary is deliberately not installed host-side. `mise use -g` writes *your* global mise config
and data dir, which harnessed does not own; and `install:` has no way to place an executable on the
host agent's PATH (it is handed `$HARNESSED_CONFIG_DIR` and the install cache, not the stack bin
dir). Landing host-native binaries on PATH is `provision:`'s job — see bd harnessed-zi6.1. Until rtk
grows one, install `rtk 0.43.0` yourself and the wiring half still runs, or run the stack in a
container.

## Footprint / removal

A host launch writes **only** inside the stack's own config dir (`rtk init -g`'s `RTK.md` and its
`settings.json` patch), and harnessed rebuilds that dir from scratch on every launch — nothing to
clean up. If you installed `rtk` yourself to get the host path, undoing that is yours (e.g.
`mise rm -g github:rtk-ai/rtk`, or however you installed it).

Upstream: <https://github.com/rtk-ai/rtk>
