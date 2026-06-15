# Phase 1: Containerized Engine + Transparent Stack - Research

**Researched:** 2026-06-14 (revised: DooD removed — host runs podman natively)
**Domain:** Host-native rootless-podman launcher (host-mirror dev container)
**Confidence:** HIGH (external facts web-verified at project level; repo/CLI shape proposed)

> Phase-level research. Read the project-level research first:
> `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`,
> `.planning/research/SUMMARY.md`. This file narrows to Phase 1 and carries the locked decisions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `~/.claude.json` safety = **copy-on-start** writable per-instance copy (NOT rw bind-mount).
- **D-02:** Keep `CLAUDE_CONFIG_DIR` relocation as a fast-follow contingent on an empirical scope check.
- **D-03:** `~/.claude` may be mounted for live skills/commands/settings, but never the whole-file `.claude.json`.
- **D-04:** Bootstrap auto-builds the base/claude images on first run; `harnessed --build` forces rebuild.
- **D-05:** Prefer podman on the host; fall back to docker. **Host runs `podman build`/`podman run` directly — no API socket, no `CONTAINER_HOST`/`DOCKER_HOST`, no DooD.**
- **D-06:** In-container project path = `/home/harnessed/<relpath>` (legible Claude slug). Verify install paths.
- **D-07:** `container` becomes a thin alias → `harnessed transparent`; port logic, no behavior change.
- **D-08:** The `transparent` launcher is plain host bash (a `container.sh` refactor); `$HOME`/`$PWD`/project paths are host-native — no host-absolute mount helper needed.

### Claude's Discretion
- Launcher bash module factoring; bootstrap runtime-detection shape; base-image lineage details beyond reusing the mise toolchain.

### Deferred Ideas (OUT OF SCOPE — do not plan)
- The `harnessed-tools` assembler image / recipes / isolated mode / `.claude.json` stub / hatago (Phase 2)
- pnpm supply-chain config + scan gate (Phase 3); shared services + full CLI breadth (Phase 4); secrets + docs completeness (Phase 5)
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect runtime, ensure/build images, dispatch | Host bootstrap (bash) | Host podman (`podman build`) | Dependency-free entry; images built natively on the host (§15) |
| Compute §4a mounts, run the harness, attach | Host launcher (bash) | Host podman (`run`/`exec -it`) | `transparent` = host-mirror; host paths native; clean TTY (§15) |
| `.claude.json` copy-on-start | Host launcher (bash) | — | Avoid racing the host whole-file blob (Pitfall) |

Single-container application for Phase 1: `transparent` runs one harness container (no pod siblings,
no assembler, no `harnessed-tools` image — those are Phase 2).
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 1 is a faithful refactor of `container.sh` into `harnessed transparent` plus the image
rename/split — **not** a new control plane. The host runs podman directly: `harnessed build` does
host `podman build` of the base/claude images; `harnessed transparent` (and `container`) is a host
bash launcher that runs the prebuilt `harnessed-claude` image with the §4a mounts and the project,
attaching host-natively. Because the launcher runs on the host, `$HOME`/`$PWD`/project paths are
host-native — there is no Docker-out-of-Docker, no API socket, and no host-absolute-path footgun.

The one behavioral change vs `container.sh` is the `~/.claude.json` safety fix: the existing unsafe
rw bind-mount (`container.sh:124-126`) becomes a copy-on-start per-instance copy so the host file is
never raced/corrupted. The §4a host-integration layer and the egress firewall port nearly verbatim.

The toolchain is settled by project research: rootless podman 5.8.x on the host (build + run), and a
base image built on the repo's existing mise toolchain (node/pnpm/python), with the in-container home
moved to `/home/harnessed` for a legible session slug.

**Primary recommendation:** Treat Phase 1 as "rename + split + safety fix" of `container.sh`; reuse
its mount/firewall/build logic; defer all assembler/DooD-free orchestration machinery — there is none
to build here.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library/Tool | Version | Purpose | Why Standard |
|--------------|---------|---------|--------------|
| podman (rootless) | 5.8.x | host build + run engine; only host dep | Native pods later; Docker-CLI compatible; runs on the host (no socket needed) |
| mise | 2026.x | in-image toolchain manager | already this repo's mechanism (`Dockerfile`) |
| bash (host) | — | bootstrap + launcher | dependency-free; `container.sh` is already bash |

### Supporting
| Tool | Version | Purpose | When |
|------|---------|---------|------|
| node/pnpm/python (in-image, via mise) | per `Dockerfile` | the harness runtime inside `harnessed-claude` | baked into the image, not on the host |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| copy-on-start `.claude.json` | `CLAUDE_CONFIG_DIR` relocation | cleaner if it relocates the top-level file; scope unverified (D-02) |
| host-bash launcher | Python `harnessed-tools` driving podman (DooD) | REJECTED — adds a socket, host-path footgun, TTY tunneling for no benefit (§15) |

**Host prerequisite:** just `podman` (or docker). No `systemctl --user enable podman.socket` — the
host runs podman directly. (A user-lingering note applies later for long-lived **service** pods, not
for transparent.)
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System (Phase 1, transparent)
```
$ harnessed transparent [path]   (or: container [path])
   │  (host bash)
   ├─ detect podman/docker; ensure base/claude images (host `podman build` on first run)
   ├─ compute §4a mounts on the HOST ($HOME/$PWD native) + project + .claude copy-on-start
   ├─ podman run harnessed-claude (sleep infinity)
   └─ podman exec -it <instance> <harness>   ← host-native TTY
```

### Pattern 1: host-bash launcher (refactor of container.sh)
**What:** A bash launcher computes conditional §4a mounts and runs the harness via host podman.
**When:** transparent now; the same launcher shape is what the Phase-2 assembler will *generate* for isolated stacks.
**Why:** Host-native paths + TTY; nothing to tunnel; matches today's working `container.sh`.

### Pattern 2: copy-on-start `.claude.json`
**What:** At start, copy host `~/.claude.json` → a per-instance writable file; never rw-bind-mount the host file.
**Why:** It's a constantly-rewritten whole-file blob; a shared rw mount races/corrupts.

### Pattern 3: image lineage by FROM (not union)
**What:** `harnessed-base` (mise toolchain) → `harnessed-claude` (FROM base + claude). Home = `/home/harnessed`.
**Why:** `FROM` is linear inheritance (§6); fine for a single harness image.

### Anti-Patterns to Avoid
- Reaching for a containerized tool that drives the host daemon (DooD) — rejected; host runs podman.
- rw-bind-mounting `~/.claude.json` — host corruption.
- Hardcoding `/container/$USER` — use `/home/harnessed/<relpath>` (D-06).
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| §4a mount set | new mount logic | port `container.sh:start_new_container` (37-146) | proven; agent sockets, YubiKey, signing |
| egress allowlist | new firewall | `egress-firewall.sh` (verbatim) + `apply_firewall` | already audited; default-DROP |
| PATH install | new installer | `install.sh` clone+symlink | proven |
| runtime detection | new detection | `container.sh:26-34` (prefer podman) | already handles podman/docker |
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: `~/.claude.json` rw bind-mount races/corrupts host state
**What goes wrong:** host + container Claude rewrite the same whole-file blob → lost writes/corruption.
**How to avoid:** copy-on-start (D-01); never rw-mount the host file (D-03).
**Warning signs:** host Claude shows unknown projects; `.claude.json` parse errors; new `*.backup.*` during runs.

### Pitfall 2: in-container home change breaks the harness install
**What goes wrong:** moving `$HOME` to `/home/harnessed` could strand the claude binary or mise shims.
**How to avoid:** set image `$HOME=/home/harnessed`, build mise/claude under it, and `which claude` at build verify.
**Warning signs:** `claude: not found` or mise shims missing at runtime.

### Pitfall 3: host rootless podman not ready for builds
**What goes wrong:** first `podman build` fails (storage/subuid not configured).
**How to avoid:** detect podman, surface a clear error; docker fallback. (No socket needed for transparent.)
**Warning signs:** `podman build` errors on a fresh machine.
</common_pitfalls>

<open_questions>
## Open Questions

1. **`CLAUDE_CONFIG_DIR` scope** — relocates top-level `.claude.json` or only `.claude/`? Ship copy-on-start (D-01); add an empirical check; switch only if clean (#14313/#3833).
2. **`/home/harnessed/<relpath>` vs harness installs** — confirm claude/mise resolve from the new home (Pitfall 2).
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md` (web-verified, v2-reframed)
- `docs/harnessed-design.md` §2, §4, §6, §14, §15 (corrected)
- Existing code: `container.sh`, `Dockerfile`, `install.sh`, `egress-firewall.sh`

### Tertiary (LOW confidence — validate in execution)
- `CLAUDE_CONFIG_DIR` relocation scope; in-image `$HOME` interaction with harness installs
</sources>

---

*Phase: 01-containerized-engine-transparent-stack*
*Research completed: 2026-06-14 (revised — host-native, no DooD)*
*Ready for planning: yes*
