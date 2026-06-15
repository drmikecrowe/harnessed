# Phase 1: Containerized Engine + Transparent Stack - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the harnessed host entrypoint and re-deliver the existing `container` SKU through it with
zero behavioral regression. Concretely:

- A dependency-free `harnessed` **bash bootstrap** on PATH: detect podman/docker, ensure the
  base/claude images exist (auto-build on first run), and dispatch to a stack launcher.
- The base/claude **image lineage** (`base/Dockerfile.harnessed-base` → `harnessed-claude`), built
  via **host `podman build`**, with the in-container home at `/home/harnessed`.
- The `transparent` stack = today's `container`: a **host-bash launcher** that runs the prebuilt
  `harnessed-claude` image with the host config mounted live (`~/.claude` + `.codex`/`.config/opencode`/`.gemini`),
  the §4a host-integration mount layer, project mount, and egress firewall — plus the `~/.claude.json`
  safety fix.
- `container` retained as a thin alias → `harnessed transparent`.

**Execution model (corrected — no DooD):** the host runs `podman build` and `podman run` natively.
There is **no** `harnessed-tools` image, **no** daemon-in-container, and **no** rootless API socket
in this phase. The `harnessed-tools` assembler image (which only emits files) arrives in **Phase 2**,
where isolated stacks actually need assembly.

**Out of phase (later):** the assembler / recipes / isolated mode / hatago / profile assembly
(Phase 2), supply-chain gate / pnpm policy (Phase 3), shared services / full CLI breadth (Phase 4),
secrets / docs completeness (Phase 5).
</domain>

<decisions>
## Implementation Decisions

### `~/.claude.json` safety (the §4b fix)
- **D-01:** Replace the existing unsafe rw bind-mount of `~/.claude.json` (`container.sh:124-126`) with a **copy-on-start writable per-instance copy** — the container reads host state once at start and writes only its own copy. Chosen over `CLAUDE_CONFIG_DIR` relocation because that knob's scope is unverified (may relocate only `.claude/`, not the top-level `.claude.json` — issues #14313/#3833).
- **D-02:** Keep `CLAUDE_CONFIG_DIR` relocation as a fast-follow: if an empirical check confirms it relocates the top-level `.claude.json` cleanly, switch to it. Capture the check result in this phase's planning.
- **D-03:** `~/.claude` itself may still be mounted for live skills/commands/settings (per-path dirs, append-mostly → low race risk), but **never** rw-bind-mount the whole-file `~/.claude.json`.

### Build & first-run UX
- **D-04:** The bootstrap **auto-builds** the base/claude images on first run (with a visible progress message); `harnessed --build` forces a rebuild. First-run latency is accepted; a prebuilt/published image is deferred (v2, IMG-01).

### Execution model — host runs podman natively (no DooD)
- **D-05:** Prefer **podman** on the host; fall back to docker. Mirrors the existing `container.sh` runtime detection. The host runs `podman build` and `podman run`/`exec -it` directly — **no API socket is mounted, no `CONTAINER_HOST`/`DOCKER_HOST`, no Docker-out-of-Docker.**
- **D-08:** The `transparent` launcher is **plain host bash** (a refactor of `container.sh`), so it computes the §4a conditional mounts on the host where `$HOME`/`$PWD`/project paths are host-native by construction. No host-absolute-path mount helper is needed — that footgun only existed under the rejected DooD model.

### In-container home / project path
- **D-06:** Adopt **`/home/harnessed/<relpath>`** as the in-container project path (replacing `container.sh`'s `/container/$USER`) for a legible, stable Claude session slug and consistency with isolated mode. Verify it doesn't break the harness install paths during planning (§14 open item).

### `container` continuity
- **D-07:** `container` becomes a **thin alias → `harnessed transparent`** (zero behavior change for existing muscle memory). Port `container.sh`'s logic into the new structure; the `container` entrypoint delegates rather than duplicating.

### Claude's Discretion
- The launcher's bash module factoring (one script vs `lib/*.sh`), the bootstrap's runtime-detection code shape, and base-image lineage details beyond reusing the existing mise-based `Dockerfile` toolchain — planner/executor decide.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source of truth
- `docs/harnessed-design.md` §2 — one engine, two config modes (transparent vs isolated)
- `docs/harnessed-design.md` §4 — mounts: §4a shared host-integration layer; §4b transparent config source + the `.claude.json` caveat
- `docs/harnessed-design.md` §6 — image tier (`FROM` = base lineage only)
- `docs/harnessed-design.md` §14 — open items (CLAUDE_CONFIG_DIR scope; container home path; `container` alias)
- `docs/harnessed-design.md` §15 — implementation (CORRECTED): host runs podman natively; the container-as-assembler **emits files only** (Phase 2); no DooD/socket; host-bash launcher

### Research
- `.planning/research/STACK.md` — podman 5.x on the host (build + run); mise/pnpm/python in-image; no API socket
- `.planning/research/ARCHITECTURE.md` — System Overview; "assembler emits Dockerfile → host builds" + "generated host-bash launcher runs the pod" patterns
- `.planning/research/PITFALLS.md` — `~/.claude.json` race/corruption; host rootless podman config for builds/long-lived pods

### Planning docs
- `.planning/PROJECT.md` — core value, constraints, key decisions
- `.planning/REQUIREMENTS.md` — Phase 1 reqs: ENG-01..03, MODE-01..02, AUTH-01, MNT-01..03
- `.planning/ROADMAP.md` — Phase 1 goal + success criteria

### Existing code to port
- `container.sh` §`start_new_container` (lines 37-146) — the §4a mount layer + the **unsafe** `~/.claude.json` rw mount (124-126) to replace
- `container.sh` §`apply_firewall` (284-303) + `egress-firewall.sh` — egress firewall, ported verbatim
- `container.sh` §`build_image`/`image_exists` (223-248), §`generate_container_name` (202-220), runtime detection (26-34)
- `Dockerfile` — mise-based base image toolchain to split into `harnessed-base` + `harnessed-claude` (home → `/home/harnessed`)
- `install.sh` — clone + PATH-symlink install pattern (reuse for the `harnessed` bootstrap; the `harnessed install <stack>` shim is Phase 4)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `container.sh:start_new_container` (37-146): the complete §4a host-integration mount set — 1Password SSH agent socket + `SSH_AUTH_SOCK`, GPG SSH socket, `~/.gnupg` ro, YubiKey `--device` passthrough, `~/.zai.json` ro, per-tool `~/.config/<tool>` mounts, git config ro, `/etc/machine-id` ro, `~/.ssh` ro, project mount, `--cap-add NET_ADMIN`, `--userns=keep-id`. Port into the host-bash mount layer almost verbatim.
- `egress-firewall.sh` + `apply_firewall` (284-303): default-DROP egress allowlist, re-applied per session via `/run/egress-firewall-active`. Mount verbatim at `/usr/local/sbin/egress-firewall`.
- `install.sh`: clone-to-`~/.local/share` + symlink-to-PATH. Template for the `harnessed` bootstrap install.
- `build_image`/`image_exists` (223-248): adapt for base/claude auto-build-on-first-run + `--build`.

### Established Patterns
- mise-based image build (`Dockerfile`): `mise use -g node@22 pnpm@latest python@latest …` — split into `harnessed-base`; the claude layer adds `claude` (`Dockerfile:77`).
- `--userns=keep-id` + daemon container `sleep infinity` + `exec -it` attach shape (host-native).
- `CONTAINER_HOME=/container/$USER` (`container.sh:23`) → CHANGES to `/home/harnessed/<relpath>` (D-06).

### Integration Points
- **This phase stays close to today's design:** like `container.sh`, the launcher runs podman **on the host**. The only structural change vs `container.sh` is the rename/split (harnessed + image lineage + `/home/harnessed`) and the `.claude.json` safety fix. (The bigger structural change — the file-emitting assembler — is Phase 2.)
- `container` entrypoint → delegates to `harnessed transparent` (D-07).
- **Unsafe mount to fix:** `container.sh:124-126` rw-mounts `~/.claude.json` — replaced by copy-on-start (D-01).
</code_context>

<specifics>
## Specific Ideas

- `docs/harnessed-design.md` §15 is the corrected source of truth ("why"); the host-runs-podman / file-emitting-assembler model is owner-confirmed (2026-06-14) over the earlier DooD draft.
- The §4a layer is operational (credentials/signing/agents) and belongs in **every** stack including isolated — build it as a reusable host-bash mount module from the start.
- "transparent is the degenerate case" — implement it as a stack (`stacks/transparent/`) the launcher consumes, so Phase 2's isolated mode reuses the same launcher path.
</specifics>

<deferred>
## Deferred Ideas

These surfaced as boundaries, not scope creep — each belongs to a later phase:

- The `harnessed-tools` **assembler** image (emits Dockerfile + profile + launcher) + recipes + isolated mode + `.claude.json` **stub** + hatago → Phase 2.
- pnpm managed supply-chain config + scan gate → Phase 3.
- Shared service sidecars, full CLI breadth (`new`/`install` shims/`svc`) → Phase 4.
- varlock/1Password secrets, docs completeness → Phase 5.

None — discussion stayed within phase scope (auto mode resolved all gray areas with recommended defaults).
</deferred>

---

*Phase: 1-Containerized Engine + Transparent Stack*
*Context gathered: 2026-06-14 (revised: DooD removed per owner — host runs podman natively)*
