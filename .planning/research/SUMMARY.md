# Project Research Summary

**Project:** harnessed
**Domain:** Composable, isolated AI-coding-harness / dev-container manager (rootless podman pods + MCP hub + build-time supply-chain gate)
**Researched:** 2026-06-14
**Confidence:** HIGH (external facts web-verified; architecture §2–§9 confirmed; repo/schema/CLI §10–§13 proposed)

## Executive Summary

`harnessed` is a controlled evolution of this repo's `container` tool: one executable that launches
**harness stacks** as podman pods (harness container + hatago MCP hub + optional shared service
sidecars), composed at **runtime** because Docker `FROM` is linear inheritance with no union
operator. The old `container` host-mirror behavior folds in unchanged as the built-in `transparent`
stack; the new value is `isolated` stacks that expose **exactly** the skills/commands/MCP/services a
hand-authored recipe set declares — nothing from the host config — reproducibly. Experts build this
shape with rootless podman (the only host dependency, used to build and run images natively on the
host), a build-time **assembler** (a `harnessed-tools` container that EMITS a Dockerfile + build
context + profile + hatago config + a generated launcher — never touching the daemon), an MCP hub
(hatago) aggregating servers behind one HTTP endpoint, and a pnpm-first build-time supply-chain gate.

The recommended approach is **vertical slices**: prove the core value on one thin tracer-bullet stack
(one harness + one MCP server + one skill, green end-to-end via an integration capability test)
before adding breadth. Reproducibility comes from a split output — the file-extension layer is
committed to a git-versioned `profiles/` dir and mounted, while MCP-server dependencies are baked
into pinned images, so nothing is assembled at container start.

The dominant risks are mechanical and front-loaded: (1) `~/.claude.json` is a constantly-rewritten
whole-file blob that must never be rw-bind-mounted (copy-on-start or `CLAUDE_CONFIG_DIR` for
transparent, generated stub for isolated — a silent-corruption correctness risk); and (2) the
isolated onboarding stub must skip the login prompt headlessly (`hasCompletedOnboarding` corroborated;
the rest needs an empirical no-prompt test).

## Key Findings

### Recommended Stack

The toolchain for building harnessed itself (host bootstrap + containerized tools image + base/hub/
service images + scan gate). Podman is the only host dependency; everything else lives inside images.

**Core technologies:**
- **podman (rootless), ≥5.6 / current 5.8.2**: container + native **pod** engine — pods are the §3 stack unit (shared netns → `localhost:port`); Docker-CLI-compatible so existing detection ports as-is
- **Python 3.12/3.13 + mise + uv**: all `harnessed-tools` assembler logic (parse/validate, vendor, sync-links, stub-gen, scan, emit Dockerfile + build context + launcher); pinned inside the image so the host needs no Python
- **pnpm 11.x**: the **only** JS package manager — v11 turns supply-chain guards ON by default (`minimumReleaseAge` 1440 min, lifecycle default-deny via `allowBuilds`, content-addressed store); `pnpm dlx` replaces `npx`
- **hatago MCP hub (`@himorishige/hatago-mcp-hub`)**: aggregates a stack's MCP servers behind one Streamable-HTTP endpoint (default `:3535`); runs light stdio servers as children, proxies network-native ones
- **rich (14.x)**: renders the capability report (markdown→terminal); textual only if a TUI lands
- **osv-scanner V2 + pip-audit** (credential-free baseline); **snyk + Socket.dev** (token-gated, warn-and-skip); **varlock + 1Password `op`** (opt-in secrets, inert without a schema)

### Expected Features

**Must have (table stakes):** host auth passthrough, project mount, image build/lifecycle, MCP wiring,
state persistence, install/PATH shim, §4a host-integration mounts (SSH/GPG/YubiKey/git), egress firewall.

**Should have (differentiators):** two config modes (transparent/isolated), runtime pod composition,
hatago single-endpoint MCP aggregation, hand-authored recipes → committed profile + baked images,
shared service-scoped concurrent sidecars, build-time supply-chain gate, pnpm-everywhere, `--fresh`,
per-stack capability test + markdown report, generated launcher shims, omp-via-bridge.

**Defer (v1.x / v2+):** shared services beyond the first slice, additional recipes (one at a time),
token-gated scanners, scaffolder + yolo profiles, varlock secrets, nightly re-scan timer, textual TUI,
prebuilt published tools image.

**Anti-features (explicit out-of-scope):** dynamic/runtime assembly, host-config merge (the failed
approach), `FROM`-union image combination, npm/npx, multi-harness stacks, a GUI, assembler unit tests.

### Architecture Approach

A clean host/container split — a dependency-free **bash launcher** on the host + a build-time
**`harnessed-tools` assembler image** that EMITS files only (a Dockerfile + build context + profile +
hatago config + a generated launcher) and never touches the daemon. The HOST runs `podman build` on
the emitted Dockerfile(s); the generated `~/.local/bin/<stack>` host-bash launcher then runs the pod
natively via host podman, so the interactive attach is host-native by construction for a clean TTY.

**Major components:**
1. **`harnessed` host launcher** — detect runtime, build base/claude images via host `podman build`, (for isolated stacks) run the assembler, install/exec the generated `~/.local/bin/<stack>` launcher
2. **`harnessed-tools` assembler image** — parse/validate, vendor, sync-links, stub-gen, scan, emit Dockerfile + build context + profile + hatago config + launcher (file emitter, no daemon access)
3. **harness container** — runs `claude`/`omp` with project + profile mounted, auth seeded
4. **hatago hub** — one Streamable-HTTP MCP endpoint; child stdio servers + proxied network-native ones
5. **service sidecars** — hindsight/openbrain; own image/volume/lifecycle, shared concurrently across stacks
6. **profile (committed→mounted)** + **baked images** — the split output that delivers "not dynamic" reproducibility

Repo layout (§10): `harnessed` + `container` alias, `tools/` (assembler), `base/` (lineage Dockerfiles),
`services/`, `recipes/` (inputs), `stacks/` (composition), `profiles/` (generated+committed), `lib/` (runtime bash).

### Critical Pitfalls

1. **`~/.claude.json` race/corruption** — never rw-bind-mount the whole-file blob; copy-on-start or `CLAUDE_CONFIG_DIR` (transparent), generated stub (isolated) → **Phase 1**
2. **Onboarding stub fields** — `hasCompletedOnboarding` corroborated; verify the full set with a headless no-prompt acceptance test, snapshot the working stub → **Phase 2**
3. **MCP transport mismatch** — use Streamable HTTP (SSE deprecated); confirm which servers need hatago's stdio→HTTP wrap → **Phase 2**
4. **Secrets in image layers / committed profiles** — env-only injection always; warn-and-skip on missing scanner token, never prompt (keep build non-interactive) → **Phase 3**
5. **1Password in-container auth** — desktop app-auth socket is finicky in containers; `OP_SERVICE_ACCOUNT_TOKEN` is the cleaner headless path → **Phase 5**

## Implications for Roadmap

Granularity is **coarse** (3-5 phases) and project mode is **MVP/vertical** — each phase delivers an
observable end-to-end capability, building the design's tracer-bullet slices (§18). Suggested structure:

### Phase 1: Host bootstrap/launcher + transparent stack
**Rationale:** A light refactor of `container.sh` into a host bash launcher (`harnessed transparent` +
`container` alias) plus host `podman build` of the renamed base/claude images is the spine everything
rides on; `transparent` has no recipes, so it needs no assembler and no `harnessed-tools` image — it
just runs the prebuilt `harnessed-claude` image with the §4a mounts, re-delivering the existing
`container` with zero regression while exercising the highest-risk file mechanic (`.claude.json`).
**Delivers:** `harnessed transparent [path]` (+ `container` alias) launches a host-mirror instance via
host podman with the §4a host-integration mounts, project mount, egress firewall, and the `.claude.json`
copy-on-start safety fix, on base/claude images built by host `podman build`.
**Addresses:** table-stakes mounts/auth/lifecycle; Pitfall 1 (`.claude.json`).

### Phase 2: Isolated tracer-bullet stack (assemble → run → assert)
**Rationale:** The MVP vertical slice that proves the core value — one harness + one MCP server + one
skill, isolated and reproducible, asserted green by the capability test.
**Delivers:** recipe + stack schema, build-time assembler (vendor + sync-plugin-links fan with
fail-fast collisions + hook wiring + hatago config merge), isolated auth seeding (ro credential mount
+ generated `.claude.json` stub with headless no-prompt test), runtime pod composition (harness +
hatago on `harnessed-net`), committed profile + baked images, per-stack capability test + markdown report.
**Uses:** podman pods, hatago, Streamable HTTP. **Avoids:** Pitfalls 2 & 3.

### Phase 3: Supply-chain gate + pnpm-everywhere
**Rationale:** The build is not trustworthy until vetted; this hardens `harnessed build` into the gate
the design requires before any profile is committed or image published.
**Delivers:** pnpm-everywhere managed config (minimumReleaseAge, lifecycle default-deny), credential-free
scan baseline (osv-scanner + pip-audit) failing on high-severity, recipe validation flagging raw npm/npx.
**Avoids:** Pitfall 4.

### Phase 4: Shared services + recipe breadth + full CLI/lifecycle
**Rationale:** With the single-pod loop proven and gated, add the cross-instance concurrency model and
operable breadth.
**Delivers:** service-scoped concurrent sidecars (hindsight/openbrain) + `svc up/down/list`, additional
recipes one at a time (each red→green via its own capability test), `--fresh`, full CLI
(`list`/`stop`/`rm`/`new`/`install`/`uninstall` shims), host-side state persistence, omp-via-bridge.

### Phase 5: Secrets, hardening, and docs completeness
**Rationale:** Perimeter/policy and the gated documentation surface land last, on top of a working loop.
**Delivers:** varlock + 1Password opt-in (`.env.schema`), token-gated scanners + `harnessed auth`,
nightly re-scan timer, and the full doc set (recipe-authoring, stack guide, secrets, service authoring,
troubleshooting/ops). **Avoids:** Pitfall 5.

### Phase Ordering Rationale

- The highest-risk file mechanic (`.claude.json`) is forced into Phase 1 so nothing is built on a racing mount.
- The isolated tracer bullet (Phase 2) is the smallest end-to-end proof of core value; breadth waits.
- The supply-chain gate (Phase 3) precedes recipe breadth (Phase 4) so every added recipe is vetted on arrival.
- Shared-service concurrency (Phase 4) is deferred until the single-pod path is solid.
- Secrets + docs (Phase 5) are policy/perimeter, meaningless before a working assemble→run→assert loop.

### Research Flags

Phases likely needing deeper research/empirical validation during planning:
- **Phase 1:** `CLAUDE_CONFIG_DIR` scope — does it relocate `.claude.json` (top-level file) or only `.claude/`? Verify empirically (issues #14313/#3833).
- **Phase 2:** exact `.claude.json` stub field set for a headless no-prompt boot; per-server MCP transport (which need hatago stdio→HTTP wrapping vs speak Streamable HTTP natively).
- **Phase 4:** harness session-state path (host `~/.claude/projects/` vs harnessed-owned dir) and legible slug at `/home/harnessed/<relpath>`.
- **Phase 5:** in-container 1Password resolution (app-auth socket vs `OP_SERVICE_ACCOUNT_TOKEN`).

Phases with standard, well-documented patterns:
- **Phase 3:** pnpm supply-chain config and osv-scanner/pip-audit usage are well-documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions web-verified (podman 5.8.2, pnpm 11, uv 0.11.8, osv-scanner V2, MCP spec) |
| Features | HIGH | Categories grounded in design spec + competitor analysis; MVP is the design's explicit slice |
| Architecture | MEDIUM | §2–§9 confirmed; external facts HIGH; repo/schema/CLI (§10–§13) proposed |
| Pitfalls | HIGH | `.claude.json` corroborated by docs; onboarding stub partially [INFERENCE] pending empirical test |

**Overall confidence:** HIGH

### Gaps to Address

- **`.claude.json` stub fields beyond `hasCompletedOnboarding`** — [INFERENCE]; resolve with a headless no-prompt acceptance test in Phase 2, snapshot the working stub.
- **`CLAUDE_CONFIG_DIR` relocation scope** — verify empirically in Phase 1 before choosing it over copy-on-start.
- **In-container 1Password auth mode** — confirm app-auth socket vs service-account token in Phase 5.
- **Per-server MCP transport** — determine per recipe in Phase 2/4 which servers need hatago wrapping.

## Sources

### Primary (HIGH confidence)
- `docs/harnessed-design.md` (§1–§18) — authoritative design spec
- pnpm supply-chain: <https://pnpm.io/supply-chain-security>, <https://pnpm.io/settings>
- MCP transports (stdio + Streamable HTTP; SSE deprecated): <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>
- hatago MCP hub: <https://github.com/himorishige/hatago-mcp-hub>
- osv-scanner: <https://github.com/google/osv-scanner>; pip-audit: <https://pypi.org/project/pip-audit/>
- Podman pods / rootless networking: <https://docs.podman.io/en/stable/markdown/podman.1.html>

### Secondary (MEDIUM confidence)
- pnpm 11 default release-age: <https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults>
- Detailed per-dimension sources in STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

### Tertiary (LOW confidence / needs validation)
- `.claude.json` onboarding stub field set beyond `hasCompletedOnboarding` (community headless guides)
- `CLAUDE_CONFIG_DIR` relocation scope (Claude Code issues #14313, #3833)

---
*Research completed: 2026-06-14*
*Ready for roadmap: yes*
