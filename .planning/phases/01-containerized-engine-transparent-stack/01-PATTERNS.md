# Phase 1: Containerized Engine + Transparent Stack - Patterns

**Mapped:** 2026-06-14
**Scope:** Existing code in this repo that Phase 1 ports/reuses. Read the cited line ranges before implementing.

## Reusable Assets (port, don't re-author)

| Asset | Location | Reuse in Phase 1 |
|-------|----------|------------------|
| §4a host-integration mount set | `container.sh:37-146` (`start_new_container`) | Port wholesale into the shared mount layer: 1Password agent socket + `SSH_AUTH_SOCK` (45-50), GPG SSH socket (52-60), `~/.gnupg` ro (62-65), YubiKey `--device` (67-75), `~/.zai.json` ro (77-81), per-tool `~/.config/<tool>` (83-107), git config ro (109-114), `/etc/machine-id` ro (116-119), `~/.ssh` ro (141), project mount + `-w` (133-134), `--cap-add NET_ADMIN` + `--userns=keep-id` (130-131) |
| **Unsafe `.claude.json` rw mount** | `container.sh:121-126` | REPLACE with copy-on-start (D-01). `~/.claude` rw mount (123) may stay; the `.claude.json` rw mount (124-126) must go |
| Egress firewall | `egress-firewall.sh` (whole) + `container.sh:284-303` (`apply_firewall`, `/run/egress-firewall-active` flag) | Mount verbatim at `/usr/local/sbin/egress-firewall`; re-apply per session |
| Runtime detection | `container.sh:26-34` | Prefer podman, else docker (D-05); harnessed adds the rootless-socket check |
| Image build / existence | `container.sh:223-248` (`image_exists`, `build_image`) | Adapt for `harnessed-tools` auto-build-on-first-run (D-04) and base image build |
| Stable instance identity | `container.sh:202-220` (`generate_container_name`) | Adapt to `harnessed-<stack>-<projhash>` pod identity |
| PATH install | `install.sh` (clone→`~/.local/share`, symlink→`~/.local/bin` w/ sudo fallback) | Template for the `harnessed` bootstrap install |
| mise base toolchain | `Dockerfile:49-74` (mise + node@22/pnpm/python + extra-tools) | Evolve into `harnessed-base`; the harness container layer adds `claude` (`Dockerfile:77`) |

## Conventions to preserve
- `--userns=keep-id` (rootless UID mapping) + daemon container `sleep infinity` + `exec -it` attach shape.
- Config dirs mounted from `$SCRIPT_DIR/.codex|.opencode|.gemini` (`container.sh:136-138`) for transparent mode.
- Color-coded `print_info/success/warning/error` helpers (`container.sh:148-163`) — mirror for tool output (or use `rich`).
- `CONTAINER_HOME=/container/$USER` (`container.sh:23`) → CHANGES to `/home/harnessed/<relpath>` (D-06).

## Integration points / seams
- **Control-flow inversion (highest risk):** today `container.sh` runs podman on the host; harnessed runs podman from inside `harnessed-tools` over the rootless socket. Every mount source becomes a host-absolute path problem (D-08, Pitfall 1).
- **`container` entrypoint** → delegates to `harnessed transparent` (D-07); keep the existing flags (`--build`, `--list`, `--stop`, `--remove`, `--clean`) working through the alias.
- **egress-firewall.sh** stays a runtime-mounted script (lib/), not baked logic.

## What NOT to touch in Phase 1
- `Dockerfile`'s pnpm install stays as-is (Phase 3 adds the managed supply-chain config).
- No recipe/stack assembler, hatago, or services (Phase 2+). `stacks/transparent/stack.yaml` is the only stack manifest this phase needs.

---

*Phase: 01-containerized-engine-transparent-stack*
*Patterns mapped: 2026-06-14*
