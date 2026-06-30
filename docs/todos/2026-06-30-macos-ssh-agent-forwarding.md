---
created: 2026-06-30T00:00:00.000Z
title: macOS SSH-agent forwarding — verify the host→VM socket relay
area: launcher
status: pending
files:
  - src/harnessed/launcher.py
---

# macOS SSH-agent forwarding — pending verification

The credential-forwarding feature (`_credential_forward_args` in `launcher.py`) restores host
git-signing + push credentials into the harness container: 1Password / gpg-agent SSH socket,
`~/.gnupg`, YubiKey, git config, and the non-secret `~/.ssh` surface (config / known_hosts / `*.pub`)
plus stack-declared private keys.

Path detection is OS-aware and lands now:

| Piece | Linux | macOS |
|---|---|---|
| 1Password socket | `~/.1password/agent.sock` | `~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock` |
| gpg-agent ssh socket | `gpgconf --list-dirs agent-ssh-socket`, else `/run/user/<uid>/gnupg/S.gpg-agent.ssh` | `gpgconf --list-dirs agent-ssh-socket` |
| YubiKey USB | `lsusb` + `--device /dev/bus/usb/...` | **n/a** — no `/dev/bus/usb` inside the Linux VM |

## The unverified part

On macOS the container runtime is a **Linux VM** (podman machine / Docker Desktop). A host **unix
domain socket does not traverse the host→VM file share** (virtiofs/9p don't carry socket semantics),
so a plain `-v <host_op_sock>:<ctr>/.1password/agent.sock` is expected to **fail** even though the
path is correct.

`_macos_op_socket_mount_source(rt, host_sock)` wires the documented workaround for podman: a
**reverse-forward of the host socket into the VM**

```
podman machine ssh -f -N -T -R /tmp/harnessed-op-agent.sock:<host_op_sock>
```

then bind-mounts the in-VM `/tmp/harnessed-op-agent.sock`. This is **best-effort and non-fatal**:
on failure the launch continues and prints a note pointing here. **None of it has been run on real
macOS hardware** — I implemented it from Linux.

## Verify on the Mac

1. `podman machine` running, 1Password SSH agent enabled (Settings → Developer → "Use the SSH agent").
2. `harnessed launch <stack> --path <project>` on macOS, then inside the container:
   - `echo $SSH_AUTH_SOCK` → should be `/home/harnessed/.1password/agent.sock`
   - `ssh-add -l` → should list your 1Password keys (proves the socket relay works end to end)
   - `ssh -T git@github.com` → should authenticate
   - `git commit -S --allow-empty -m test && git log --show-signature -1` → should sign
3. **Open question to settle:** does `podman run -v <vm-local-path>:…` resolve the source against the
   VM filesystem (works) or the host (fails)? If it resolves host-side, the relay needs a different
   landing path (e.g. a path under the podman-machine's shared mount, or a TCP bridge). Capture the
   answer here and adjust `_macos_op_socket_mount_source`.
4. **Docker Desktop** path is not wired (`rt != "podman"` returns None). If macOS users run Docker
   Desktop, add its relay (it shares `/run/host-services/ssh-auth.sock` for the *host* agent, which
   is a different mechanism than 1Password's socket — needs its own design).

## YubiKey on macOS

USB passthrough is not possible (no `/dev/bus/usb` in the VM). The YubiKey reaches the container via
the **gpg-agent SSH socket** relay instead (same host→VM problem as above). Verify `gpgconf
--list-dirs agent-ssh-socket` resolves and that the forwarded socket signs.
