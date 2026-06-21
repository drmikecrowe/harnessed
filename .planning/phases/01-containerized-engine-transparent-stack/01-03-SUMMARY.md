---
phase: 01-containerized-engine-transparent-stack
plan: 03
subsystem: infra
tags: [transparent-stack, container-alias, claude-json, host-mirror, mnt-03, host-native-attach]

# Dependency graph
requires:
  - phase: 01-containerized-engine-transparent-stack (plan 01)
    provides: the harnessed bootstrap + lib/harnessed-common.sh (build_images/ensure_images/lifecycle, apply_firewall)
  - phase: 01-containerized-engine-transparent-stack (plan 02)
    provides: lib/harnessed-mounts.sh (the §4a host-integration mount layer) + lib/egress-firewall.sh
provides:
  - "lib/harnessed-transparent.sh — harnessed_transparent <project_path> [use_claude] [use_zai]: composes the §4a layer (01-02) + host config mounts + copy-on-start .claude.json, runs harnessed-claude via host podman, applies the egress firewall, performs the host-native interactive attach; --claude (Claude YOLO) and --zai (Claude + Z.AI/GLM env) ports"
  - "lib/harnessed-claude-config.sh — harnessed_claude_json_copy_mount (copy-on-start) + harnessed_probe_claude_config_dir_scope"
  - "stacks/transparent/stack.yaml — built-in transparent stack manifest (config: transparent)"
  - "container — thin alias → exec harnessed transparent (D-07); clean cutover removed container.sh (no shim)"
affects: [02-isolated-tracer-bullet-stack, multi-harness]

# Tech tracking
tech-stack:
  added: []
  patterns:
  - "Copy-on-start .claude.json: host ~/.claude.json is NEVER rw-bind-mounted; a per-instance copy under $XDG_STATE_HOME/harnessed/<instance>/ is seeded once and mounted rw (MNT-03 / §4b)"
  - "Host-native interactive attach: exec -it on the host (clean TTY, no tunneling) (ENG-03)"
  - "container thin alias → exec harnessed transparent (D-07): single supported entry point, no shim"

key-files:
  created:
  - lib/harnessed-transparent.sh
  - lib/harnessed-claude-config.sh
  - stacks/transparent/stack.yaml
  - container
  modified:
  - harnessed
  - install.sh

key-decisions:
  - "MNT-03 / §4b (headline fix): host ~/.claude.json is NEVER rw-bind-mounted; a per-instance copy under $XDG_STATE_HOME/harnessed/<instance>/ is seeded once and mounted rw. ~/.claude (dir) stays live."
  - "ENG-03: the attach is host-native (exec on the host) — clean TTY, no tunneling."
  - "MODE-01/02: harnessed transparent and container deliver the host-mirror sandbox; --claude/--zai/--list/--stop/--remove/--clean/--no-firewall preserved."
  - "AUTH-01: transparent auth comes from the live host ~/.claude mount (no re-login)."
  - "Clean cutover: container.sh removed (no shim); container is the supported alias."

patterns-established:
  - "Transparent stack = §4a mount layer (01-02) + host config mounts + copy-on-start .claude.json, run via host podman with egress firewall applied"
  - "container thin alias → exec harnessed transparent (D-07): single supported entry point, clean cutover with no shim"

requirements-completed: [ENG-03, MODE-01, MODE-02, AUTH-01, MNT-03]

# Metrics
completed: 2026-06-14
---

# Plan 01-03 Summary: transparent stack + container alias + .claude.json safety

**Completed:** 2026-06-14
**Requirements:** ENG-03, MODE-01, MODE-02, AUTH-01, MNT-03

## What was built

- **`lib/harnessed-transparent.sh`** — `harnessed_transparent <project_path> [use_claude] [use_zai]`: composes the §4a layer (01-02) + the live host config mounts (`~/.claude` rw, `$HARNESSED_DIR/.codex|.opencode|.gemini`) + the copy-on-start `.claude.json`, runs `harnessed-claude` (`sleep infinity`) via host podman, applies the egress firewall, and performs the **host-native** interactive attach (`exec -it … bash -l -c "$mise_init && $exec_cmd"`). Attach/start/create paths mirror `container.sh`. Ports `--claude` (Claude YOLO) and `--zai` (Claude + Z.AI/GLM env) for zero-regression.
- **`lib/harnessed-claude-config.sh`** — `harnessed_claude_json_copy_mount` (copy-on-start) + `harnessed_probe_claude_config_dir_scope` (CLAUDE_CONFIG_DIR fast-follow note).
- **`stacks/transparent/stack.yaml`** — built-in transparent stack manifest (`config: transparent`, harness omitted).
- **`container`** — thin alias → `exec harnessed transparent "$@"` (D-07).
- **`harnessed`** — wired `--claude`/`--zai` into the transparent dispatch.
- **Cutover:** removed `container.sh` (superseded); `install.sh` now installs both `harnessed` and `container`.

## Key decisions honored

- **MNT-03 / §4b (the headline fix):** host `~/.claude.json` is NEVER rw-bind-mounted; a per-instance copy under `$XDG_STATE_HOME/harnessed/<instance>/` is seeded once and mounted rw. `~/.claude` (dir) stays live.
- **ENG-03:** the attach is host-native (`exec` on the host) — clean TTY, no tunneling.
- **MODE-01/02:** `harnessed transparent` and `container` deliver the host-mirror sandbox; `--claude`/`--zai`/`--list`/`--stop`/`--remove`/`--clean`/`--no-firewall` preserved.
- **AUTH-01:** transparent auth comes from the live host `~/.claude` mount (no re-login).
- Clean cutover: `container.sh` removed (no shim); `container` is the supported alias.

## Verification

- `bash -n` ✓ for `harnessed`, `container`, `install.sh`, `lib/harnessed-transparent.sh`, `lib/harnessed-claude-config.sh`.
- `./harnessed --help`, `./container --help` (alias forwards correctly), `./harnessed --list` ✓.
- **MNT-03 unit check ✓** (sourced libs): host `~/.claude.json` not bind-mounted; per-instance copy created + mounted rw.
- **Image acceptance ✓** (plan 01-01): `harnessed-claude` runs with `HOME=/home/harnessed`, `claude` 2.1.177 on PATH.
- **Pending operator (human-verify checkpoint):** a live interactive `transparent` run with real auth — `./harnessed transparent` (or `./container`) in a project → confirm the harness opens authenticated, project at `/home/harnessed/<relpath>`, and host `~/.claude.json` unchanged after exit. (AGENTS.md bars me from running the interactive harness; the §4a `grep`-based extra-tools parsing also can't be exercised in this sandbox — verified by syntax + direct port from `container.sh`.)

## Files

- `lib/harnessed-transparent.sh`, `lib/harnessed-claude-config.sh`, `stacks/transparent/stack.yaml`, `container`, `harnessed` (edit), `install.sh` (cutover), `container.sh` (removed)

## Commits

- `47ba1b5` transparent host launcher + stack manifest + bootstrap wiring
- `68bf865` .claude.json copy-on-start safety
- `af00507` container thin alias + installer cutover (remove container.sh)
