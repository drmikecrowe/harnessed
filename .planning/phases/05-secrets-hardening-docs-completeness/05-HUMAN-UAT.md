---
status: partial
phase: 05-secrets-hardening-docs-completeness
source: [05-VERIFICATION.md]
started: 2026-06-18T12:30:00Z
updated: 2026-06-19T00:00:00Z
---

# Phase 05 — Human UAT (operator-only verification items)

The phase is **code-complete and 6/7 requirements are fully VERIFIED live**
(SEC-01, SEC-02, SEC-04, DOC-01, DOC-02, DOC-03). HV-1 and HV-2 below — live
`op://` resolution and the build scan receiving it — are now **PASS** after the
host-side resolution fix (commit `81a7f3f`): resolution runs `varlock` on the host
(the 1Password desktop app authorizes the calling terminal; an in-container `op`
cannot be), and the resolved env reaches isolated pods, transparent instances,
sidecar services, and the build scan. After 2026-06-19, **HV-4 is also PASS** (`loginctl
enable-linger` flipped `Linger=yes`). One operator-only leg remains (HV-3): snyk's interactive
**browser** auth — not a code gap, it needs a human at a real TTY with a snyk account.

## Current Test

[HV-1, HV-2, HV-4 PASS. Awaiting operator: HV-3 (snyk browser auth) — the only remaining leg.]

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
result: [pending]
needs: real TTY + browser + snyk account.
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
passed: 3
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

_(none — these are operator-only live legs by design, not code gaps. See
`05-VERIFICATION.md` for the full requirement traceability + threat-model
adherence.)_
