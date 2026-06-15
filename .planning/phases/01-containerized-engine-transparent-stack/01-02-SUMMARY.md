# Plan 01-02 Summary: §4a host-integration mount layer

**Completed:** 2026-06-14
**Requirements:** MNT-01, MNT-02

## What was built

- **`lib/harnessed-mounts.sh`** — `harnessed_host_integration_mounts <project_path> <relpath>` appends the full §4a layer to a `MOUNT_ARGS` bash array (ported from `container.sh:start_new_container`): `--userns=keep-id`, `--cap-add NET_ADMIN`, `TERM`, project mount at `/home/harnessed/<relpath>` + `-w`, the egress-firewall script mount, 1Password agent socket + `SSH_AUTH_SOCK`, GPG SSH socket, `~/.gnupg` ro, YubiKey `--device`, `~/.zai.json` ro, per-tool `~/.config/<tool>` from `extra-tools.txt`, git config (XDG/legacy) ro, `/etc/machine-id` ro, `~/.ssh` ro. Each mount is conditional on the host source existing.
- **`lib/egress-firewall.sh`** — relocated from repo root via `git mv` (content/history preserved); consumed by `apply_firewall` (in `harnessed-common.sh`).

## Key decisions honored

- **Host-native (D-08):** sources are real host paths (`$HOME`, project path); no host-absolute helper or DooD translation needed — the launcher runs on the host.
- **Array-based args** instead of `container.sh`'s string concatenation — safer quoting for paths with spaces.
- **No `~/.claude*` here** — config-mode-specific, handled by the transparent launcher (01-03).

## Verification

- `bash -n lib/harnessed-mounts.sh` ✓, `bash -n lib/egress-firewall.sh` ✓.
- Live mount behavior is exercised by the transparent launcher (01-03) under the operator's run checkpoint.

## Notes / cutover

- The old `container.sh` still references the root `egress-firewall.sh` (now moved). `container.sh` is superseded this phase and is removed in 01-03 when the new `container` alias lands (clean cutover, no shim).

## Files

- `lib/harnessed-mounts.sh`, `lib/egress-firewall.sh` (moved from root)

## Commits

- `4f556c3` feat(01-02): §4a host-integration mount layer + relocate egress firewall to lib/
