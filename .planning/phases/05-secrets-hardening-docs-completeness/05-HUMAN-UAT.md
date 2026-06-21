---
status: complete
phase: 05-secrets-hardening-docs-completeness
source: [05-VERIFICATION.md]
started: 2026-06-18T12:30:00Z
updated: 2026-06-21T00:00:00Z
---

# Phase 05 — Human UAT (operator-only verification items)

The phase is **code-complete and all 7 requirements are fully VERIFIED live**
(SEC-01..04, DOC-01..03). All four human-verification legs now PASS: HV-1/HV-2 (live `op://`
resolution + build scan receiving it) after the host-side resolution fix (`81a7f3f`); HV-4
(`loginctl enable-linger` → `Linger=yes`, 2026-06-19); and HV-3 (snyk browser auth) after the
`--network=host` callback fix (`27fe91b`, 2026-06-21). No operator legs remain.

## Current Test

[All HV-1..HV-4 PASS. Phase 05 fully verified — no operator legs remain.]

## Tests

### 1. HV-1 — SEC-01 live `op://` resolution (schema present → pod env)
expected: with `~/.config/harnessed/.env.schema` pointed at real 1Password vault
items, `./harnessed tracer-time --fresh` resolves `op://` refs and the resolved
`SNYK_TOKEN` is present in the pod env; `grep -r SNYK_TOKEN profiles/` returns
nothing; the temp env-file is gone after launch.
result: PASS — verified live (host-side resolution, fix `81a7f3f`); `SNYK_TOKEN` (264 chars) + `SOCKET_SECURITY_API_KEY` present in the pod env; temp env-file unlinked. First run prompts the 1Password app to Authorize the terminal (one-time).
needs: 1Password desktop app running (agent socket at `~/.1password/agent.sock`) + real vault items.
```bash
mkdir -p ~/.config/harnessed && cp .env.schema.example ~/.config/harnessed/.env.schema
$EDITOR ~/.config/harnessed/.env.schema        # point op(op://Private/Snyk/credential) at real items
./harnessed tracer-time --fresh
podman exec "$(podman ps --format '{{.Names}}' | grep tracer-time | head -1)" env | grep SNYK_TOKEN
```

### 2. HV-2 — SEC-01 build scan receives 1Password-resolved tokens
expected: with the schema from HV-1 present and the launcher env cleared of
`SNYK_TOKEN`, `./harnessed build tracer-time` invokes snyk (output must NOT
contain `snyk skipped (no SNYK_TOKEN)`) — proving `build_stack`'s
`resolve_secret_env` call feeds the scan step.
result: PASS — verified live; `harnessed build` resolves on the host and forwards the token to the source scan (no `snyk skipped (no SNYK_TOKEN)` warning); build exits 0.
needs: schema from HV-1 + live 1Password.
```bash
unset SNYK_TOKEN SOCKET_SECURITY_API_KEY
./harnessed build tracer-time
```

### 3. HV-3 — SEC-03 live scanner-token auth (browser flow → host config)
expected: from a real TTY, `./harnessed auth snyk` completes the browser flow and
`~/.config/configstore/snyk.json` holds the token; `podman images --filter
dangling=true` shows no leftover auth layer (the `--rm` guarantee).
result: PASS — verified live 2026-06-21 after the `--network=host` callback fix (`27fe91b`).
`./harnessed auth snyk` completed the OAuth browser flow; `~/.config/configstore/snyk.json` now
holds the OAuth token (`INTERNAL_OAUTH_TOKEN_STORAGE`, 1005 bytes). The auth container runs `--rm`
(a `run`, not a build) so it leaves no image layer. Background: snyk's callback listens on the
container loopback `127.0.0.1:8080`; the first attempt (`-p 127.0.0.1:8080:8080`) failed because
rootless pasta forwards published ports to the container's outward interface, not its loopback
(connection reset). `--network=host` makes snyk's `127.0.0.1:8080` the host loopback so the browser
redirect lands directly (no LAN exposure — snyk still binds loopback only).
needs: real TTY + browser + snyk account. [DONE]
```bash
./harnessed auth snyk
cat ~/.config/configstore/snyk.json
podman images --filter dangling=true
```

### 4. HV-4 — SEC-04 linger prerequisite (survive-logout for the nightly timer)
expected: the timer is already scheduled and its service→rescan path already ran
live today; the only thing keeping it from firing overnight is `Linger=no`. A
one-time host policy flip (not a code change) sets `Linger=yes`.
result: PASS — `loginctl enable-linger "$USER"` ran 2026-06-19 (polkit-authorized, no sudo); `loginctl show-user --property=Linger` → `Linger=yes`. The scheduled nightly timer will now fire while logged out.
needs: operator host policy decision. [DONE]
```bash
loginctl enable-linger "$USER"
loginctl show-user "$USER" --property=Linger   # expected: Linger=yes
```

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

_(none — these are operator-only live legs by design, not code gaps. See
`05-VERIFICATION.md` for the full requirement traceability + threat-model
adherence.)_
