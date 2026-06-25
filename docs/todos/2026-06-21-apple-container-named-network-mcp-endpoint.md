---
created: 2026-06-21T13:10:00.000Z
title: Apple container support — named-net + dynamic MCP endpoint
area: general
status: pending
files:
  - tools/harnessed/launcher.py
  - tools/harnessed/paths.py
  - base/Dockerfile.harnessed-opencode
  - base/Dockerfile.harnessed-gemini
  - base/Dockerfile.harnessed-antigravity
  - base/Dockerfile.harnessed-codex
  - tools/harnessed/emit.py
---

> **Migration note (2026-06-24):** the bash launcher referenced below (`lib/harnessed-runtime.sh`,
> `lib/harnessed-isolated.sh`) was replaced by the Python CLI (`tools/harnessed/launcher.py`,
> `paths.py`). The problem/solution analysis still applies — map the bash file refs to their Python
> equivalents (runtime abstraction + mount/endpoint assembly now live in `launcher.py`/`paths.py`).

## Problem

Provider-agnosticism targets podman, docker, AND Apple `container`. The podman→docker port
(shared network namespace via `--network container:<hatago>`) preserves the load-bearing
assumption that the harness and hatago share `localhost:3535`. Apple `container` BREAKS that
assumption: it runs one lightweight VM per container, each with its own IP and network stack,
with NO shared-namespace / pod / `--network container:` equivalent (researched 2026-06-21).
So `localhost:3535/mcp` — which every harness image bakes into its MCP config and the profile's
`.claude/.mcp.json` — cannot reach hatago on Apple container.

## Solution

Redesign the MCP endpoint to be NON-localhost on Apple container:
- Put hatago + the harness on a user-defined Apple `container network` (macOS 26+) and reach
  hatago by a stable DNS name (e.g. `http://hatago:3535/mcp` or `<instance>-hatago`).
- Make the baked MCP endpoint configurable per provider/instance instead of hardcoded
  `localhost:3535` — affects opencode (~/.config/opencode), gemini (~/.gemini/settings.json),
  antigravity (~/.gemini/config/mcp_config.json), codex (~/.codex/config.toml), AND the
  Claude-canonical profile `.mcp.json` (emit.py `HATAGO_ENDPOINT`) + claude/omp launch.
- Either bake a templated endpoint resolved at launch, or generate the harness MCP config at
  launch (like the auth stub) so the host/endpoint is instance-specific.
- Handle Apple's lack of pods (group = network + two containers), userns (Apple VMs differ),
  the egress firewall (per-VM, not shared netns), and `container network`/DNS setup; note
  macOS 26 (Tahoe) requirement for `container network`. Consider third-party `apple-compose`.
- Extend the phase-06 harness matrix to run under Apple `container` as the proof.

Depends on the podman+docker runtime-abstraction layer (now in `launcher.py`) landing first.
