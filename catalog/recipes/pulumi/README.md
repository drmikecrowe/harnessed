# pulumi

The Pulumi CLI, pinned via mise (`tools:` — no Dockerfile), plus the egress allowlist entry for
Pulumi Cloud. Authentication is by `PULUMI_ACCESS_TOKEN`, supplied at launch as a secret — never
baked into the image.

Ships a CLI only; no MCP server.

Upstream: <https://github.com/pulumi/pulumi>
