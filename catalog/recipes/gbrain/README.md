# gbrain

A knowledge brain — synthesis, graph traversal, and gap analysis over a long-lived shared store.

Wired as a **service-backed MCP server**: the recipe carries a `service: gbrain` ref, so the
launcher starts the shared `gbrain` sidecar and hatago proxies it over Streamable-HTTP. Auth is a
long-lived bearer token minted by `gbrain auth create`.

Upstream: <https://github.com/garrytan/gbrain>
