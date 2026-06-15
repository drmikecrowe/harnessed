# Phase 2: Isolated Tracer-Bullet Stack - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** `--auto` (gray areas auto-resolved with recommended defaults; see DISCUSSION-LOG.md)

<domain>
## Phase Boundary

Prove the core value on the **smallest end-to-end isolated slice** — one harness (`claude`) + one
MCP server + one skill — assembled, run isolated, and asserted **green** by the capability test.
Concretely this phase lands, for that one slice:

- **Recipe + stack schema** (`recipes/<name>/recipe.yaml`, `stacks/<name>/stack.yaml`) — RCP-01, RCP-02.
- **Build-time assembler** (`harnessed-tools` image) that *emits files only* — vendor + sync-links
  fan with **fail-fast collisions**, hook wiring, hatago config merge → committed `profiles/<stack>/`
  + a `Dockerfile` (+ build context) + `hatago.config.json` + a generated launcher; the **host**
  runs `podman build` — RCP-03, RCP-04.
- **Isolated auth seeding** — `~/.claude/.credentials.json` mounted **read-only** + a **generated**
  `.claude.json` stub that boots headlessly with **no onboarding/login prompt** — MODE-03, AUTH-02.
- **Runtime pod composition** — a podman **pod** (harness container + hatago) on `harnessed-net`;
  the harness `.mcp.json` points at hatago's **single Streamable-HTTP endpoint** — MCP-01, MCP-02, MCP-03.
- **Per-stack capability test + `rich` markdown report** — asserts the live `--fresh` headless
  instance exposes exactly the declared MCP server + skill — TST-01, TST-02.

**In scope:** the one tracer-bullet stack and the machinery above, end to end (assemble → run → assert green).
**Out of scope (later phases):** supply-chain scan gate + pnpm managed config + plugin-vendoring-with-deps
(Phase 3); shared service sidecars + `svc` + full CLI breadth + state model + omp-via-bridge (Phase 4);
varlock/1Password secrets + token-gated scanners + docs surface (Phase 5). New capabilities beyond the
single slice are scope creep — they belong to their own phase.
</domain>

<decisions>
## Implementation Decisions

### Tracer-bullet stack composition (the slice)
- **D-01:** The tracer bullet = **`claude` harness + ONE light stdio MCP server + ONE standalone
  skill**, `config: isolated`. (`omp` is Phase 4 / HRN-01 — one harness per stack.)
- **D-02:** Pick a **network-free, credential-free `uvx` Python stdio MCP server** for the slice
  (recommended: `mcp-server-time`; researcher confirms exact package + that it speaks MCP over stdio
  and needs no network). Rationale: the egress firewall (§4a) is on by default, so a network-free
  server keeps the capability test **deterministic**, and a stdio server exercises hatago's
  **stdio→HTTP child** path (MCP-03), which is the riskier transport (Pitfall 3).
- **D-03:** Pick a **small, self-contained skill with NO external dependencies** for the
  file-extension layer (a standalone `skills: [{ path: ... }]` entry, not a vendored plugin).
  Rationale: this exercises the `sync-plugin-links` **fan into harness-native paths** + fail-fast
  collision machinery (RCP-04) **without** dragging in dependency installation or a supply-chain
  scan — those land with Phase 3. Plugin-vendoring-*with-deps* is therefore deferred (see Deferred).

### MCP wiring (hatago)
- **D-04:** The single stdio server runs as a **hatago child** (hatago wraps stdio→HTTP, MCP-03).
  The harness `.mcp.json` points **only** at hatago's **single Streamable-HTTP endpoint** (MCP-02,
  hatago default `:3535`). **SSE is deprecated — Streamable HTTP only.**
- **D-05:** The running stack is a podman **pod** `harnessed-<stack>-<projhash>` containing the
  harness container + hatago on `harnessed-net` (MCP-01). Pod members share a netns, so the harness
  reaches hatago at `localhost:<port>`.

### Hatago image strategy
- **D-06:** **One base `hatago` image** (`base/Dockerfile.hatago`) bakes the hub + the light stdio
  servers the slice needs (the `uvx` server above). **Per-stack selection is the generated, mounted
  `hatago.config.json`** (which baked servers to expose), not a per-stack hatago image. Bake a
  dedicated per-stack hatago image only once a recipe needs a server not in the base image (deferred).
  Matches §6/§7 ("light servers baked into the hatago image").

### Isolated auth seeding (`.claude.json` stub) — HIGHEST-RISK ITEM
- **D-07:** Mount `~/.claude/.credentials.json` **read-only** (AUTH-02). **Generate** a minimal
  `.claude.json` **stub** — **never** mount or rw-bind the host `~/.claude.json` (carries Phase 1's
  MNT-03 rule into isolated).
- **D-08:** Start from the candidate stub field set (`oauthAccount`, `userID`, `hasCompletedOnboarding`,
  + likely `firstStartTime`, `numStartups`) — [INFERENCE]. **Resolve empirically:** the executor runs
  a **headless no-prompt acceptance test**, then **snapshots the working stub as a committed fixture**
  so it is reproducible. This is the Phase 2 research flag (Pitfall 2 / STATE blocker), not a guess to
  ship blind.
- **D-09:** Reuse Phase 1's `lib/harnessed-claude-config.sh` as the *analog*: transparent does
  copy-on-start; isolated needs a **stub generator** (new function/module), not a copy.

### Capability test + report
- **D-10:** Assertion is **machine-readable introspection first, LLM prompt as backstop** (TST-01).
  - **MCP:** assert via hatago's `hatago://servers` resource (JSON) and/or `claude mcp list` that the
    manifest's server is **connected**.
  - **Skills/commands:** ask the harness **headless** (`claude -p … --output-format json`) to emit
    the skills it sees as JSON and **diff against the stack manifest** (the manifest is the oracle).
  - Natural-language "confirm you can use skill X / MCP Y" is the human-readable backstop on top.
- **D-11:** The same check renders a **`rich` markdown capability report** (per-capability status
  table) — one mechanism, two audiences (TST-02). Run `--fresh` so there's no state bleed; tear down
  after. **No assembler unit tests** (project anti-feature) — behavior verified transitively.

### Assembler execution model (no DooD)
- **D-12:** The assembler is the **`harnessed-tools` Python image** that **emits files only** into a
  mounted build dir: a `Dockerfile` (+ build context) per image, the committed `profiles/<stack>/`
  tree, `hatago.config.json`, and a generated launcher. It **never touches the daemon**. The **host**
  runs `podman build` on the emitted Dockerfile(s); a host-bash launcher runs the pod via host podman
  (§15). `transparent` stays assembler-free (degenerate case).
- **D-13:** **Collision policy = fail-fast** (RCP-04) — reuse `sync-plugin-links`' explicit conflict
  reporting so a failed build says *what* it couldn't wire. (Moot for the single-recipe slice, but the
  mechanism is implemented and its error path is covered.)

### Schema scope
- **D-14:** Implement `recipe.yaml` + `stack.yaml` per the proposed §11/§12 shape, but **require only
  the fields the tracer bullet exercises**; parse/validate the rest forward (don't gate the slice on
  unused fields). `config: isolated` is the default; `harness: claude`.

### Isolated mode dispatch / engine integration
- **D-15:** Add an **`isolated` arm** to the `harnessed` dispatcher's `case "$STACK"` (today the `*)`
  error arm) + a new **`lib/harnessed-isolated.sh`** launcher that **mirrors `harnessed-transparent.sh`'s
  shape** — reusing `harnessed_host_integration_mounts` (§4a), `apply_firewall`, and the
  instance/lifecycle helpers from `lib/harnessed-common.sh` — but sourcing config from the assembled
  **profile** + pod composition instead of live host config. For P2, `harnessed <stack>` dispatches
  this directly; the generated per-stack launcher shim (`harnessed install`) is Phase 4.

### §4a host-integration layer in isolated mode
- **D-16:** Keep the §4a layer (1Password SSH agent, GPG/YubiKey signing, `~/.ssh` ro, git config ro,
  `/etc/machine-id` ro, egress firewall, project mount) in isolated **as-is** — it's operational, not
  config-experiment surface (§4a: "belong in every instance"). A "truly empty environment" gating flag
  for the editor/tool `~/.config/<tool>` mounts is **deferred** (low stakes, not needed to prove the slice).

### Claude's Discretion
- Build-dir location + exact emitted-file layout; the assembler's Python module factoring and
  YAML parse/validate approach (yq/jq vs pydantic); hatago port selection; pod/instance naming
  details beyond §13 conventions; how `harnessed build` orders assemble → `podman build`. Planner/executor decide.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source of truth (`docs/harnessed-design.md`)
- §2 — one engine, two config modes (isolated = auth seeded + assembled profile, zero host config)
- §3 — core model: stack = harness container + hatago + (shared services); transparent is degenerate
- §4 — mounts: §4a shared host-integration layer (kept in isolated); §4b isolated config source (ro
  `.credentials.json` + generated `.claude.json` stub; profile-only skills/commands/agents/hooks/rules/`.mcp.json`/`settings.json`)
- §5 — recipes are hand-authored, not dynamic; MCP layer + file-extension layer
- §6 — image tier: `FROM` = base lineage only; legitimate `hatago` image bakes light stdio servers
- §7 — assembly split: committed→mounted profile + baked→images; vendor / sync-links / hook wiring
- §8 — Claude Code format canonical; **one harness per stack** (omp is Phase 4)
- §11 — recipe schema (`recipes/<name>/recipe.yaml`) — PROPOSED, implement this phase
- §12 — stack manifest (`stacks/<name>/stack.yaml`) — PROPOSED, implement this phase
- §13 — CLI surface + naming/identity (pod `harnessed-<stack>-<projhash>`)
- §14 — open items resolved/flagged here: `.claude.json` stub fields (D-08), per-server MCP transport
  (D-04), intra-stack collision policy (D-13), harness config mount points, hatago placement
- §15 — implementation: `harnessed-tools` emits files only; host runs podman build/run; **no DooD**
- §18 — testing: integration-only, manifest as oracle, machine-readable introspection + markdown report

### Research (milestone-level, `.planning/research/`)
- `.planning/research/ARCHITECTURE.md` — System Overview; assembler-emits-files + generated-launcher patterns; pod composition
- `.planning/research/STACK.md` — podman 5.x pods; hatago `@himorishige/hatago-mcp-hub` (`:3535`, Streamable HTTP); uvx/pnpm; rich
- `.planning/research/PITFALLS.md` — Pitfall 2 (`.claude.json` onboarding stub fields, empirical test), Pitfall 3 (MCP transport / stdio→HTTP wrap)
- `.planning/research/FEATURES.md` — must/should/defer split; the tracer-bullet slice is the explicit MVP
- `.planning/research/SUMMARY.md` — Phase 2 rationale + research flags (stub field set; per-server transport)

### Planning docs
- `.planning/PROJECT.md` — core value, constraints, Key Decisions table
- `.planning/REQUIREMENTS.md` — Phase 2 reqs: MODE-03, AUTH-02, RCP-01..04, MCP-01..03, TST-01..02
- `.planning/ROADMAP.md` — Phase 2 goal + the 4 success criteria + plan split (02-01/02-02/02-03)

### Existing code to EXTEND (Phase 1 output)
- `harnessed` (bootstrap dispatcher, lines 88-101) — add the `isolated` `case` arm (currently `*)` errors)
- `lib/harnessed-common.sh` — runtime detection, `build_images`/`ensure_images`, lifecycle,
  `apply_firewall`, `generate_instance_name`, `project_relpath`, `container_running/exists` — reuse
- `lib/harnessed-mounts.sh` — `harnessed_host_integration_mounts` (§4a) — reuse verbatim in isolated
- `lib/harnessed-claude-config.sh` — transparent copy-on-start; the isolated **stub generator** is its analog (D-09)
- `lib/harnessed-transparent.sh` — the launcher SHAPE to mirror for `lib/harnessed-isolated.sh` (D-15)
- `base/Dockerfile.harnessed-{base,claude}` — base lineage; `HOME=/home/harnessed`; add `base/Dockerfile.hatago`
- `stacks/transparent/stack.yaml` — the stack-manifest schema precedent to generalize (§12)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lib/harnessed-mounts.sh::harnessed_host_integration_mounts` — the complete §4a mount set
  (1Password SSH agent, GPG/YubiKey, `~/.ssh` ro, git ro, machine-id ro, project mount). Isolated
  reuses this unchanged; it only swaps the §4b config-source mounts.
- `lib/harnessed-common.sh` — `build_images`/`ensure_images` (auto-build first run), `apply_firewall`,
  `generate_instance_name`, `project_relpath`, container lifecycle. The pod path needs `podman pod`
  creation + a second (hatago) container, but instance naming/firewall/lifecycle helpers carry over.
- `lib/harnessed-claude-config.sh` — copy-on-start pattern; the isolated stub generator is the analog.
- `stacks/transparent/stack.yaml` — minimal manifest precedent (`name`, `config`); §12 adds
  `harness`, `recipes`, `services`, `permissions`, `state` for isolated.

### Established Patterns
- Dispatcher: `harnessed` parses args → `ensure_images` → `case "$STACK"`. New stacks slot in as a
  `case` arm sourcing a `lib/harnessed-<mode>.sh` launcher. Isolated launcher = same daemon-container
  +`exec -it` attach shape, but pod-composed and profile-mounted.
- `set -euo pipefail` everywhere; fallible probes MUST use `|| true` or `local var=$(…)` (Phase 1
  blocker `a963a69`) — applies to any new YubiKey/jq/introspection probes.
- In-container home is `/home/harnessed/<relpath>`; the project mounts there for a legible Claude slug.
- Image lineage built via **host** `podman build`; nothing assembled at container start.

### Integration Points
- **New `harnessed` case arm** `isolated)` → `lib/harnessed-isolated.sh`.
- **New `lib/harnessed-isolated.sh`** — §4a mounts (reuse) + isolated §4b (ro credential mount +
  generated stub + profile mount + `.mcp.json`→hatago) + `podman pod` (harness + hatago on harnessed-net).
- **New `tools/`** — the `harnessed-tools` assembler image (`Dockerfile`, `pyproject.toml`, Python pkg):
  parse/validate, vendor, sync-links fan (fail-fast), hatago config merge, stub gen, emit Dockerfile/profile/launcher.
- **New `base/Dockerfile.hatago`** — hub + baked light stdio servers.
- **New `recipes/<name>/recipe.yaml`**, **`stacks/<name>/stack.yaml`** (the tracer-bullet stack),
  **`profiles/<stack>/`** (generated + committed).
- **`harnessed build <stack>`** — a new bootstrap subcommand: ensure `harnessed-tools` image → run it
  to emit files → host `podman build` the emitted Dockerfiles.
</code_context>

<specifics>
## Specific Ideas

- The tracer bullet must be the **smallest** thing that exercises **every** Phase-2 mechanic:
  assemble (recipe→profile) → fan a skill into the harness path → wrap a stdio MCP via hatago →
  isolated auth (ro credential + generated stub, headless no-prompt) → assert green via introspection.
- Prefer a **uvx Python stdio MCP server** over a JS one for the slice: it sidesteps the JS
  supply-chain surface that Phase 3 hardens, and keeps the build credential-free and network-free.
- "transparent is the degenerate case" (Phase 1 specific) extends here: build `lib/harnessed-isolated.sh`
  by mirroring the transparent launcher so both modes share the §4a + lifecycle path.
- The `.claude.json` stub MUST be **snapshotted as a committed fixture after the empirical no-prompt
  test** — do not ship the inferred field set unverified.
</specifics>

<deferred>
## Deferred Ideas

These surfaced as phase boundaries, not scope creep — each belongs to a later phase:

- **Plugin-vendoring *with* dependency installation** + the supply-chain scan gate (osv-scanner /
  pip-audit) + pnpm managed config — Phase 3 (BLD-01..03). The tracer bullet uses a no-dep standalone
  skill + a baked light server, so no vendor-deps and no scan are needed yet; the assembler's vendor
  step exists but isn't dependency-exercised this phase.
- **omp harness** via `claude-hooks-bridge` + pi-adapter — Phase 4 (HRN-01). One harness per stack;
  the slice is `claude` only.
- **Shared service sidecars** (hindsight/openbrain) + `svc up/down/list` + concurrent attach over
  harnessed-net — Phase 4 (SVC-01..03). The slice's MCP server is a light hatago child, not a shared service.
- **Full state model** — `session_state: host` vs harnessed-owned dir + legible slug + persistent-by-default
  breadth — Phase 4 (STA-01/02). P2 only needs `--fresh` throwaway for the capability test.
- **CLI breadth** — `harnessed install/uninstall` launcher shims, `new` scaffolder, `list/stop/rm`
  generalization to isolated — Phase 4 (CLI-01..03).
- **varlock/1Password secrets, token-gated scanners, docs surface** — Phase 5 (SEC-_, DOC-_).
- **`CLAUDE_CONFIG_DIR` relocation** (Phase 1 fast-follow, D-02 there) — not a Phase 2 concern.
- **Clean-room gating flag** for §4a editor/tool config mounts in isolated — only if a truly-empty
  environment is ever needed; not required to prove the slice (D-16).

None lost to scope creep — auto mode resolved all gray areas with recommended defaults within the phase boundary.
</deferred>

---

*Phase: 2-Isolated Tracer-Bullet Stack*
*Context gathered: 2026-06-14 (--auto: gray areas auto-resolved with recommended defaults)*
