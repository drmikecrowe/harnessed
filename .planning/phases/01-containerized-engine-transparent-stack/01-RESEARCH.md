# Phase 1: Containerized Engine + Transparent Stack - Research

**Researched:** 2026-06-14
**Domain:** Rootless podman control plane (Docker-out-of-Docker) + host-mirror container launcher
**Confidence:** HIGH (external facts web-verified at project level; repo/CLI shape proposed)

> Phase-level research. The project-level research is the primary source — read it first:
> `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`,
> `.planning/research/SUMMARY.md`. This file narrows to Phase 1 and carries the locked decisions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `~/.claude.json` safety = **copy-on-start** writable per-instance copy (NOT rw bind-mount).
- **D-02:** Keep `CLAUDE_CONFIG_DIR` relocation as a fast-follow contingent on an empirical scope check.
- **D-03:** `~/.claude` may be mounted for live skills/commands/settings, but never the whole-file `.claude.json`.
- **D-04:** Bootstrap auto-builds `harnessed-tools` on first run; `harnessed --build` forces rebuild.
- **D-05:** Prefer rootless podman via the user socket; fall back to docker. Mirror existing detection.
- **D-06:** In-container project path = `/home/harnessed/<relpath>` (legible Claude slug). Verify install paths.
- **D-07:** `container` becomes a thin alias → `harnessed transparent`; port logic, no behavior change.
- **D-08:** All bind-mount sources built from injected host `HOME`/`PWD`; centralize in one helper; assert host-absolute.

### Claude's Discretion
- Python package layout under `tools/harnessed/`; bootstrap runtime-detection code shape; mount-builder factoring (constrained by D-08); `harnessed-base` lineage beyond reusing the mise toolchain.

### Deferred Ideas (OUT OF SCOPE — do not plan)
- Isolated mode / `.claude.json` stub / hatago / recipes / profile assembly (Phase 2)
- pnpm supply-chain config + scan gate (Phase 3); shared services + full CLI breadth (Phase 4); secrets + docs completeness (Phase 5)
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect runtime, ensure tools image, attach | Host bootstrap (bash) | — | Dependency-free entry; host-native TTY for attach (§15) |
| Parse args, build mounts, drive podman | `harnessed-tools` (Python, in-container) | Host podman engine | The "brain"; DooD over rootless socket (§15) |
| Run the harness with host config live | Harness container (pod member) | — | `transparent` = host-mirror; degenerate stack (no pod siblings) |
| Egress control, signing, auth passthrough | Shared mount layer (§4a) | Host agents/sockets | Operational credentials, not the config-experiment surface |

Single-pod-or-less application for Phase 1: `transparent` runs the harness container only (no hatago/sidecars).
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 1 inverts today's control flow: `container.sh` runs podman directly on the host; harnessed moves
orchestration into a containerized Python tool (`harnessed-tools`) that drives the **host** rootless podman
over a mounted socket (Docker-out-of-Docker). The single hardest correctness constraint is that bind-mount
sources resolve on the **host daemon**, so every `-v` must be built from injected host `HOME`/`PWD`, never the
tool container's own path view (Pitfall 1). The `transparent` stack re-delivers `container.sh`'s host-mirror
behavior with one safety change: the unsafe rw bind-mount of `~/.claude.json` (`container.sh:124-126`) becomes a
copy-on-start per-instance copy (Pitfall 2).

The toolchain is settled by project research: rootless podman 5.8.x (pods, user `podman.socket`,
`CONTAINER_HOST`/`DOCKER_HOST`), a Python tools image built on the repo's existing mise base (node/pnpm/python).
The §4a host-integration mount layer (1Password agent, GPG/YubiKey, `.gnupg`/`.ssh`/git/machine-id ro, egress
firewall) ports nearly verbatim from `container.sh:start_new_container`.

**Primary recommendation:** Build the DooD mount-construction helper FIRST and prove one host-correct mount
before layering anything on it; reuse `container.sh`/`install.sh`/`egress-firewall.sh` rather than re-authoring.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library/Tool | Version | Purpose | Why Standard |
|--------------|---------|---------|--------------|
| podman (rootless) | 5.8.x | pod/container engine; only host dep | Native pods; Docker-CLI compatible; user socket for DooD |
| `podman.socket` (user) | bundled 5.x | host API socket the tool drives | `systemctl --user enable --now podman.socket` → `unix:///run/user/$UID/podman/podman.sock` |
| Python | 3.12/3.13 | `harnessed-tools` logic | parse/validate, build mounts, orchestrate podman; pinned in-image (no host Python) |
| mise | 2026.x | in-image toolchain manager | already this repo's mechanism (`Dockerfile`) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyYAML / ruamel.yaml | 6.x / 0.18.x | parse `stacks/transparent/stack.yaml` | minimal in Phase 1 (transparent has almost no config) |
| rich | 14.x | status/build progress output | always in tools image |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python tools image | bash orchestrator on host | rejected by §15 — would require host runtimes; supersedes the old split |
| copy-on-start `.claude.json` | `CLAUDE_CONFIG_DIR` relocation | cleaner if it relocates the top-level file; scope unverified (D-02) |

**Host prerequisite (documented, not installed by the tool):**
```bash
systemctl --user enable --now podman.socket
loginctl enable-linger "$USER"        # socket survives logout
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System Architecture (Phase 1, transparent)
```
$ harnessed transparent [path]   (or: container [path])
   │  (bash bootstrap, dep-free)
   ├─ detect podman/docker; ensure harnessed-tools image (auto-build first run)
   ├─ podman run harnessed-tools  ── DooD: -v rootless sock, --env HOST_HOME/HOST_PWD
   │     │  (Python brain)
   │     ├─ build host-absolute mounts (§4a layer + project + .claude copy-on-start)
   │     └─ podman run harness container (host config live; sleep infinity)
   └─ podman exec -it <instance> <harness>   ← HOST-NATIVE TTY
```

### Pattern 1: DooD host-absolute mount helper (the invariant)
**What:** One helper builds every `-v` from `HOST_HOME`/`HOST_PWD` (injected env), asserts the source is absolute and host-rooted.
**When:** Every mount, every callsite — no hand-rolled `-v`.
**Why:** Bind sources resolve on the host daemon; the tool's internal view is wrong (Pitfall 1).

### Pattern 2: copy-on-start `.claude.json`
**What:** At start, copy host `~/.claude.json` → a per-instance writable file the container uses; never rw-bind-mount the host file.
**When:** transparent mode (isolated generates a stub in Phase 2).
**Why:** It's a constantly-rewritten whole-file blob; a shared rw mount races/corrupts (Pitfall 2).

### Pattern 3: transparent = degenerate stack
**What:** Implement transparent as `stacks/transparent/stack.yaml` consumed by the same engine, not a special code path.
**Why:** Phase 2's isolated mode reuses the engine; "one engine, two modes" (§2).

### Anti-Patterns to Avoid
- Tool-internal paths in `-v` (Pitfall 1) — silent wrong mounts.
- rw-bind-mounting `~/.claude.json` (Pitfall 2) — host corruption.
- Tunneling the interactive attach through the tools container — broken TTY; keep attach host-native (§15).
- Running `podman` from the host directly (today's `container.sh`) — Phase 1's whole point is the DooD inversion.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| §4a mount set | new mount logic | port `container.sh:start_new_container` (37-146) | proven; covers agent sockets, YubiKey, signing |
| egress allowlist | new firewall | `egress-firewall.sh` (verbatim) + `apply_firewall` | already audited; default-DROP allowlist |
| PATH install | new installer | `install.sh` clone+symlink pattern | proven; `~/.local/bin` then sudo fallback |
| runtime detection | new detection | `container.sh:28-33` (prefer podman) | already handles podman/docker |
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: DooD bind paths resolved against the wrong root
**What goes wrong:** `-v` source from the tool's internal view → instance boots but mounts the wrong/empty dir.
**Why:** bind sources resolve on the host daemon, not the API client.
**How to avoid:** inject `HOST_HOME`/`HOST_PWD`; centralize mount construction; assert host-absolute (D-08).
**Warning signs:** harness starts but project/`.claude`/credentials missing; `podman inspect` shows tool-internal source paths.

### Pitfall 2: `~/.claude.json` rw bind-mount races/corrupts host state
**What goes wrong:** host + container Claude rewrite the same whole-file blob → lost writes/corruption; container state leaks to host.
**How to avoid:** copy-on-start (D-01); never rw-mount the host file (D-03).
**Warning signs:** host Claude shows unknown projects; `.claude.json` parse errors; new `*.backup.*` during runs.

### Pitfall 3: rootless socket not enabled
**What goes wrong:** tool can't reach `unix:///run/user/$UID/podman/podman.sock`.
**How to avoid:** detect + fail with a clear message pointing at `systemctl --user enable --now podman.socket` (+ `loginctl enable-linger`). Do not auto-modify the user's systemd.
**Warning signs:** `Cannot connect to Podman socket` on first run.
</common_pitfalls>

<open_questions>
## Open Questions

1. **`CLAUDE_CONFIG_DIR` scope** — does it relocate the top-level `.claude.json` or only `.claude/`?
   - Known: documented relocation knob; issues #14313 (fixed) / #3833 (muddy scope).
   - Recommendation: ship copy-on-start (D-01); add an empirical check task; switch to relocation only if it cleanly moves `.claude.json`.
2. **`/home/harnessed/<relpath>` vs harness installs** — confirm Claude/codex installs inside the image don't assume `/container/$USER` or a fixed `$HOME`.
   - Recommendation: set image `$HOME=/home/harnessed`; verify the harness binary resolves at runtime.
3. **podman socket in CI / sandbox** — execution/verification needs the socket enabled; not assumable in every environment.
   - Recommendation: capability/smoke test must detect-and-skip with a clear message when the socket is absent.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md` (web-verified)
- `docs/harnessed-design.md` §2, §4, §6, §14, §15
- Existing code: `container.sh`, `Dockerfile`, `install.sh`, `egress-firewall.sh`

### Secondary (MEDIUM confidence)
- Rootless podman socket / DooD bind-path gotcha (project research sources)

### Tertiary (LOW confidence — validate in execution)
- `CLAUDE_CONFIG_DIR` relocation scope; exact in-image `$HOME` interaction with harness installs
</sources>

---

*Phase: 01-containerized-engine-transparent-stack*
*Research completed: 2026-06-14*
*Ready for planning: yes*
