# pulumi

The Pulumi CLI, pinned via mise (`tools:` — no Dockerfile), plus the egress allowlist entry for
Pulumi Cloud.

Authentication is **forwarded from the host**: the recipe declares `persist: scope: global` on the
real `~/.pulumi`, so the pod reuses the login you already did with `pulumi login` on the host —
`credentials.json` and the plugin cache alike. That dir carries a long-lived Pulumi token, so the
mount is default-deny: add your expanded `~/.pulumi` path to
`~/.config/harnessed/persist-allowlist` or the launch fails, naming the exact line to add. `init:`
exports `PULUMI_HOME="$HOST_HOME/.pulumi"` because a global persist mount is path-preserving and the
pod's `$HOME` is `/home/harnessed`.

`PULUMI_ACCESS_TOKEN` as a varlock/1Password secret still works and takes precedence — that is the
path for CI, or for keeping the agent off your host token. Nothing is ever baked into the image.
See `docs/guides/pulumi.md`.

Ships a CLI only. No MCP server.

Upstream: <https://github.com/pulumi/pulumi>
