# Phase 2: Isolated Tracer-Bullet Stack - Patterns

**Mapped:** 2026-06-14
**Scope:** Existing code Phase 2 reuses/mirrors, and the closest analog for each new file. Read the cited line ranges before implementing.

## Files to create / modify (role → analog)

| New/modified file | Role | Closest analog (read first) | Reuse note |
|-------------------|------|-----------------------------|------------|
| `harnessed` (modify) | Dispatcher: add `isolated` arm + `build <stack>` subcommand | `harnessed:50-101` (arg parse + `case "$STACK"`) | The `*)` error arm at `harnessed:96-99` becomes the isolated dispatch; add a `build` branch beside `--build` (`harnessed:57,75`) |
| `lib/harnessed-isolated.sh` (new) | Isolated launcher: §4a mounts + isolated §4b + pod compose + attach | `lib/harnessed-transparent.sh:9-102` (`harnessed_transparent`) | **Mirror its shape**: source mounts + claude-config libs, resolve relpath/instance, attach-or-create, `apply_firewall`, `exec -it`. Swap §4b (lines 86-93) for ro credential + stub + profile mount; add `podman pod create` + a hatago `run` |
| `lib/harnessed-isolated.sh` stub-gen (new fn) | Generate `.claude.json` stub (no token) | `lib/harnessed-claude-config.sh:10-27` (`harnessed_claude_json_copy_mount`) | Transparent COPIES the host file; isolated GENERATES a minimal stub (jq) and mounts `~/.claude/.credentials.json` ro |
| `recipes/<name>/recipe.yaml` (new) | Recipe: MCP layer (per-server `transport`) + file-extension layer | `stacks/transparent/stack.yaml` (manifest precedent) + design §11 | YAML manifest; require only tracer-bullet fields, parse rest forward |
| `stacks/<name>/stack.yaml` (new) | Stack: harness + recipes (+ config/permissions/state) | `stacks/transparent/stack.yaml:5-8` + design §12 | `config: isolated`, `harness: claude`, `recipes: [<r>]` |
| `tools/Dockerfile` + `tools/pyproject.toml` + `tools/harnessed/` (new) | `harnessed-tools` assembler image (Python, emit-only) | `base/Dockerfile.harnessed-base` (image build pattern) | No in-repo logic analog; prior art is host `vendor-plugin` + `sync-plugin-links` (port; deps come Phase 3). Emits Dockerfile + context + profile + hatago.config.json + launcher |
| `base/Dockerfile.hatago` (new) | hatago hub + baked light stdio servers | `base/Dockerfile.harnessed-claude` (FROM-lineage + tool install) | `pnpm dlx @himorishige/hatago-mcp-hub` + `uvx mcp-server-time` baked; `serve --http --port 3535` |
| `profiles/<stack>/.claude/...` + `hatago.config.json` (generated, committed) | Mounted profile | none (generated artifact) | Output of the assembler; mounted at `/home/harnessed/.claude:rw` |
| capability test + report (new; in `tools/` or a test entrypoint) | Per-stack assert + `rich` report | none (new) | Build → `--fresh` headless → introspect → report → teardown |

## Reusable Assets (reuse verbatim / extend — do NOT re-author)

| Asset | Location | Reuse in Phase 2 |
|-------|----------|------------------|
| §4a host-integration mounts | `lib/harnessed-mounts.sh:11` (`harnessed_host_integration_mounts`) | Call unchanged from `lib/harnessed-isolated.sh` (D-16) — isolated swaps only §4b |
| Runtime detection | `lib/harnessed-common.sh:23` (`detect_runtime`) | Reuse (podman→docker) |
| Image build / ensure | `lib/harnessed-common.sh:35,38,66` (`image_exists`/`build_images`/`ensure_images`) | Extend `build_images` to also build `harnessed-hatago` from `base/Dockerfile.hatago` |
| Identity / home | `lib/harnessed-common.sh:16-19` (`HARNESSED_*_IMAGE`, `CONTAINER_HOME=/home/harnessed`) | Add `HARNESSED_HATAGO_IMAGE`; reuse `CONTAINER_HOME` for profile/project mount targets |
| Instance lifecycle | `lib/harnessed-common.sh:74-78,103-134` (`container_exists/running`, `generate_instance_name`, stop/remove/clean, `stop_if_last_session`) | Reuse for the harness container; extend stop/remove to tear down the **pod** (`podman pod rm`) |
| Project relpath | `lib/harnessed-common.sh:92` (`project_relpath`) | Reuse: project mounts at `/home/harnessed/<relpath>` |
| Egress firewall | `lib/harnessed-common.sh` (`apply_firewall`) + `lib/egress-firewall.sh` | Apply to the harness container in the pod (network-free MCP server keeps the test deterministic under the firewall) |
| Logging helpers | `lib/harnessed-common.sh:10-13` (`print_info/success/warning/error`) | Reuse |
| Launcher attach shape | `lib/harnessed-transparent.sh:60-101` (attach-or-create, `exec -it`, `stop_if_last_session`) | Mirror for isolated |

## Conventions to preserve
- `set -euo pipefail`; fallible probes use `|| true` or `local var=$(…)` (P1 blocker `a963a69`) — applies to new YubiKey/jq/hatago/introspection probes.
- `--userns=keep-id` + daemon container `sleep infinity` + `exec -it` attach (host-native TTY) — extend to `--pod` members.
- Stable identity `harnessed-<stack>-<projhash>` (`generate_instance_name`); the pod takes the same base name.
- In-container home `/home/harnessed/<relpath>` for project; profile at `/home/harnessed/.claude`.
- `FROM` is lineage only (§6): `base/Dockerfile.hatago` is standalone (or `FROM harnessed-base`), not a union.

## Integration points / seams
- **`harnessed` dispatcher** (`harnessed:90-101`): the `case "$STACK"` currently has `transparent)` and a `*)` error arm. Phase 2 adds `build) ...` handling (run the `harnessed-tools` image → host `podman build`) and replaces the `*)` arm with isolated dispatch → `lib/harnessed-isolated.sh`.
- **`stacks/`** already exists (`stacks/transparent/stack.yaml`); add `stacks/<tracer>/stack.yaml` + `recipes/<tracer>/recipe.yaml` beside it.
- **`base/`** already holds `Dockerfile.harnessed-{base,claude}`; add `Dockerfile.hatago`.
- **Pod compose** is new runtime behavior: `podman pod create --network harnessed-net` + two `podman run -d --pod`. The harness `.mcp.json` (from the profile) points at `http://localhost:3535/mcp`.

## What NOT to touch in Phase 2
- `lib/harnessed-transparent.sh` behavior (transparent stays the degenerate case; isolated is additive).
- pnpm install in images stays as-is (managed supply-chain config is Phase 3).
- No shared service sidecars, `svc`, full CLI breadth, omp, state model (Phase 4); no secrets/docs (Phase 5).
- `vendor-plugin` dependency installation + supply-chain scan path (Phase 3) — the tracer bullet uses a no-dep skill + baked light server, so the vendor step is implemented but not dependency-exercised.

---

*Phase: 02-isolated-tracer-bullet-stack*
*Patterns mapped: 2026-06-14*
