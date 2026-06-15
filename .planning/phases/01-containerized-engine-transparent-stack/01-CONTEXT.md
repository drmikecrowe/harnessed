# Phase 1: Containerized Engine + Transparent Stack - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the harnessed control plane and re-deliver the existing `container` SKU through it with
zero behavioral regression. Concretely:

- A dependency-free `harnessed` **bash bootstrap** (detect podman/docker, ensure/build the
  `harnessed-tools` image on first run, then perform the host-native interactive attach).
- The `harnessed-tools` **Python image** (the "brain") that drives the **host** rootless podman over
  the mounted socket (Docker-out-of-Docker), building every bind mount from **host-absolute** paths.
- The `transparent` stack = today's `container`: host config mounted live (`~/.claude` +
  `.codex`/`.config/opencode`/`.gemini`), the §4a host-integration mount layer, project mount, and
  egress firewall — plus the `~/.claude.json` safety fix.
- `container` retained as a thin alias → `harnessed transparent`.

**Out of phase (later):** isolated mode / profile assembly / hatago / recipes (Phase 2),
supply-chain gate / pnpm policy (Phase 3), shared services / full CLI breadth (Phase 4),
secrets / docs completeness (Phase 5).
</domain>

<decisions>
## Implementation Decisions

### `~/.claude.json` safety (the §4b fix)
- **D-01:** Replace the existing unsafe rw bind-mount of `~/.claude.json` (`container.sh:124-126`) with a **copy-on-start writable per-instance copy** — the container reads host state once at start and writes only its own copy. Chosen over `CLAUDE_CONFIG_DIR` relocation because that knob's scope is unverified (may relocate only `.claude/`, not the top-level `.claude.json` — Pitfall 2, issues #14313/#3833).
- **D-02:** Keep `CLAUDE_CONFIG_DIR` relocation as a fast-follow: if an empirical check confirms it relocates the top-level `.claude.json` cleanly, switch to it (fully decouples container state from the host file). Capture the check result in this phase's planning.
- **D-03:** `~/.claude` itself may still be mounted for live skills/commands/settings (per-path dirs, append-mostly → low race risk), but **never** rw-bind-mount the whole-file `~/.claude.json`.

### Tools-image build & first-run UX
- **D-04:** The bootstrap **auto-builds** `harnessed-tools` on first run (with a visible progress message); `harnessed --build` forces a rebuild. No separate mandatory build step (design §15). First-run latency is accepted; a prebuilt/published image is deferred (v2, IMG-01).

### Container engine selection
- **D-05:** Prefer **rootless podman** via the user socket (`unix:///run/user/$UID/podman/podman.sock`, `CONTAINER_HOST`/`DOCKER_HOST`); fall back to docker. Mirrors the existing `container.sh` runtime detection (prefer podman). Document the `systemctl --user enable --now podman.socket` + `loginctl enable-linger` prerequisite.

### In-container home / project path
- **D-06:** Adopt **`/home/harnessed/<relpath>`** as the in-container project path (replacing `container.sh`'s `/container/$USER`) for a legible, stable Claude session slug (`-home-harnessed-<relpath>`) and consistency with isolated mode. Verify it doesn't break the harness install paths during planning (§14 open item).

### `container` continuity
- **D-07:** `container` becomes a **thin alias → `harnessed transparent`** (zero behavior change for existing muscle memory). Port `container.sh`'s logic into the new structure; the `container` entrypoint delegates rather than duplicating.

### DooD mount discipline (correctness invariant)
- **D-08:** All bind-mount sources are built from **injected host `HOME`/`PWD`** (e.g. `HOST_HOME`/`HOST_PWD`), never the tools container's own path view. Centralize mount construction in one helper so no callsite hand-rolls a `-v`; assert each source is host-absolute before issuing (Pitfall 1 — the dominant Phase-1 correctness risk).

### Claude's Discretion
- Exact module layout under `tools/harnessed/` (Python package structure), the bootstrap's runtime-detection code shape, and how the mount-builder helper is factored — planner/executor decide, constrained by D-08.
- Base image lineage details (`harnessed-base` → `harnessed-claude`) beyond reusing the existing mise-based `Dockerfile` toolchain.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source of truth
- `docs/harnessed-design.md` §2 — one engine, two config modes (transparent vs isolated)
- `docs/harnessed-design.md` §4 — mounts: §4a shared host-integration layer; §4b transparent config source + the `.claude.json` caveat
- `docs/harnessed-design.md` §6 — image tier (`FROM` = base lineage only)
- `docs/harnessed-design.md` §14 — open items to verify (`.claude.json` stub is Phase 2; CLAUDE_CONFIG_DIR scope; container home path; `container` alias)
- `docs/harnessed-design.md` §15 — implementation: bash bootstrap + `harnessed-tools` Python image, DooD constraints (host-absolute bind paths, rootless socket, host-native attach)

### Research
- `.planning/research/STACK.md` — rootless podman 5.x + `podman.socket` + DooD; mise/uv/pnpm-in-image; engine versions
- `.planning/research/ARCHITECTURE.md` — System Overview; Pattern 3 (DooD host-absolute bind paths); Pattern 5 (two config modes on one mount axis, incl. the `.claude.json` safety detail); Integration Points (host podman, host auth/signing)
- `.planning/research/PITFALLS.md` — Pitfall 1 (DooD bind paths), Pitfall 2 (`~/.claude.json` race/corruption)

### Planning docs
- `.planning/PROJECT.md` — core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — Phase 1 reqs: ENG-01..03, MODE-01..02, AUTH-01, MNT-01..03
- `.planning/ROADMAP.md` — Phase 1 goal + success criteria

### Existing code to port
- `container.sh` §`start_new_container` (lines 37-146) — the §4a mount layer + the **unsafe** `~/.claude.json` rw mount (124-126) to replace
- `container.sh` §`apply_firewall` (284-303) + `egress-firewall.sh` — egress firewall, ported verbatim
- `container.sh` §`build_image`/`image_exists` (223-248), §`generate_container_name` (202-220), runtime detection (28-33)
- `Dockerfile` — mise-based base image toolchain (node/pnpm/python) to evolve into `harnessed-base`
- `install.sh` — PATH-symlink install pattern (reuse for the bootstrap install and later `harnessed install` shims)
- `Permissions.md`, `.env.schema.example` — referenced for later phases; noted for awareness
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `container.sh:start_new_container` (37-146): the complete §4a host-integration mount set — 1Password SSH agent socket + `SSH_AUTH_SOCK`, GPG SSH socket, `~/.gnupg` ro, YubiKey `--device` passthrough, `~/.zai.json` ro, per-tool `~/.config/<tool>` mounts, git config ro, `/etc/machine-id` ro, `~/.ssh` ro, project mount, `--cap-add NET_ADMIN`, `--userns=keep-id`. Port wholesale into the shared mount layer.
- `egress-firewall.sh` + `apply_firewall` (284-303): default-DROP egress allowlist, re-applied per session via `/run/egress-firewall-active` flag. Mount verbatim at `/usr/local/sbin/egress-firewall`.
- `install.sh`: clone-to-`~/.local/share` + symlink-to-PATH (prefers `~/.local/bin`, sudo `/usr/local/bin` fallback). Template for the `harnessed` bootstrap install and the `harnessed install <stack>` shim generator.
- `generate_container_name` (202-220): stable instance identity from project path → adapt to pod identity `harnessed-<stack>-<projhash>`.

### Established Patterns
- mise-based image build (`Dockerfile`): `mise use -g node@22 pnpm@latest python@latest …` — evolve into `harnessed-base`; note pnpm already present (Phase 3 will add the managed supply-chain config).
- `--userns=keep-id` + `sleep infinity` daemon container + `exec -it` attach — the run/attach shape; harnessed keeps the **attach host-native** (clean TTY) while the tools image issues the `run`.
- `CONTAINER_HOME=/container/$USER` (container.sh:23) — being replaced by `/home/harnessed/<relpath>` (D-06).

### Integration Points
- **Inversion of control vs today:** `container.sh` runs podman **directly on the host**. harnessed moves orchestration **into** `harnessed-tools` (a container) driving the host engine over the rootless socket — so every `-v` must use host-absolute paths (D-08). This is the central new integration seam and the highest-risk change.
- `container` entrypoint → delegates to `harnessed transparent` (D-07).
- **Unsafe mount to fix:** `container.sh:124-126` rw-mounts `~/.claude.json` — replaced by copy-on-start (D-01).
</code_context>

<specifics>
## Specific Ideas

- `docs/harnessed-design.md` is the explicit source of truth ("why"); honor its confirmed decisions (§2–§9) without re-litigating.
- The §4a layer is operational (credentials/signing/agents), not the config-experiment surface — it belongs in **every** stack including isolated, so build it as a shared, reusable mount module from the start.
- "transparent is the degenerate case" — implement it as just another stack (`stacks/transparent/`), not a special-cased code path, so Phase 2's isolated mode reuses the same engine.
</specifics>

<deferred>
## Deferred Ideas

These surfaced as boundaries, not scope creep — each belongs to a later phase:

- Isolated `.claude.json` **stub** generation + headless no-prompt test → Phase 2 (this phase only does the transparent-mode copy-on-start fix).
- hatago / recipes / profile assembly → Phase 2.
- pnpm managed supply-chain config + scan gate → Phase 3 (Phase 1 reuses the existing mise/pnpm image as-is).
- Shared service sidecars, full CLI breadth (`new`/`install` shims/`svc`) → Phase 4.
- varlock/1Password secrets, docs completeness → Phase 5.

None — discussion stayed within phase scope (auto mode resolved all gray areas with recommended defaults).
</deferred>

---

*Phase: 1-Containerized Engine + Transparent Stack*
*Context gathered: 2026-06-14*
