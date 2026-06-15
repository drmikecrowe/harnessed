# Phase 2: Isolated Tracer-Bullet Stack - Research

**Researched:** 2026-06-14
**Domain:** Isolated, recipe-composed harness pod (assembler-built profile + hatago MCP hub) — the smallest end-to-end slice
**Confidence:** HIGH for external facts (web-verified at milestone level: podman pods, hatago, MCP transports); MEDIUM for the `.claude.json` stub field set and the exact `hatago.config.json` schema (both verify-during-execution).

> Phase-level research. Read the milestone research first — it is the source for external facts:
> `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`, `.planning/research/SUMMARY.md`.
> This file narrows to Phase 2 and carries the locked decisions from `02-CONTEXT.md` (D-01..D-16).

<user_constraints>
## User Constraints (from CONTEXT.md — locked, do not re-litigate)

### Locked Decisions (D-01..D-16)
- **D-01/02/03:** Tracer bullet = `claude` harness + ONE network-free, credential-free `uvx` Python stdio MCP server (recommended `mcp-server-time`) + ONE no-dep **standalone** skill (`skills: [{ path }]`, not a vendored plugin).
- **D-04/05:** The stdio server runs as a **hatago child** (stdio→HTTP); harness `.mcp.json` points only at hatago's single Streamable-HTTP endpoint (`http://localhost:3535/mcp`). Pod `harnessed-<stack>-<projhash>` (harness + hatago) on `harnessed-net`; shared netns → `localhost`.
- **D-06:** One base `hatago` image (`base/Dockerfile.hatago`) bakes the light servers; per-stack `hatago.config.json` (generated, mounted) selects exposure.
- **D-07/08/09:** Mount `~/.claude/.credentials.json` **ro** + generate a minimal `.claude.json` stub (never mount the host file). Start from `hasCompletedOnboarding` + identity fields; verify with a headless no-prompt acceptance test; snapshot the working stub as a committed fixture. The stub generator is the isolated analog of `lib/harnessed-claude-config.sh`.
- **D-10/11:** Capability assertion = machine-readable introspection first (`hatago://servers` + `claude mcp list` for MCP; headless JSON skill diff for skills), LLM prompt as backstop; `rich` markdown report; `--fresh` teardown. No assembler unit tests.
- **D-12/13:** `harnessed-tools` Python image emits files only (Dockerfile + build context + committed `profiles/<stack>/` + `hatago.config.json` + generated launcher); host runs `podman build`. Collision policy = fail-fast (`sync-plugin-links` conflict reporting).
- **D-14:** Implement `recipe.yaml` + `stack.yaml` per design §11/§12; require only tracer-bullet fields, parse rest forward. `config: isolated` default; `harness: claude`.
- **D-15:** New `isolated` arm in the `harnessed` dispatcher + `lib/harnessed-isolated.sh` mirroring the transparent launcher (reuse §4a mounts/firewall/lifecycle).
- **D-16:** Keep §4a operational mounts in isolated as-is; clean-room gating flag deferred.

### Claude's Discretion
- Build-dir location + exact emitted-file layout; assembler Python module factoring + YAML parse/validate (ruamel/PyYAML); hatago port (default 3535); pod/instance naming beyond §13; assemble→build ordering.

### Deferred (OUT OF SCOPE — do not plan)
- Plugin-vendoring **with deps** + supply-chain scan gate + pnpm managed config (Phase 3); shared service sidecars + `svc` + full CLI breadth + state model + omp-via-bridge (Phase 4); varlock/1Password secrets + docs surface (Phase 5).
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Parse/validate recipe+stack, vendor/fan files, merge hatago config, gen stub, emit Dockerfile/profile/launcher | `harnessed-tools` image (Python, build-time) | host (reads emitted files) | Assembler emits files only; no daemon access (§15, D-12) |
| `podman build` the emitted Dockerfiles (hatago + claude already exist from P1) | Host podman | — | Only host dep is podman; no DooD |
| Run the pod (harness + hatago) + §4a mounts + profile mount + firewall + attach | Host bash launcher (`lib/harnessed-isolated.sh`) | host podman (`pod create`/`run`/`exec -it`) | Host-native paths + TTY; reuse P1 launcher shape (D-15) |
| Isolated auth: ro `.credentials.json` + generated `.claude.json` stub | Host bash launcher + assembler stub gen | — | Auth seeded, no host config (D-07..09) |
| MCP aggregation: stdio child → one Streamable-HTTP endpoint | hatago container (in pod) | — | Keeps uvx/npx out of the harness container (D-04) |
| Capability test + `rich` report | `harnessed-tools` image (or a test entrypoint) | host (runs `--fresh` headless instance) | Manifest as oracle; introspection-first (D-10/11) |

Multi-container for Phase 2 (vs P1's single container): the isolated stack is a **pod** with two members
(harness + hatago). Shared services (a third tier) are Phase 4.
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 2 turns the Phase-1 single-container launcher into a **pod-composed isolated stack** plus the
**build-time assembler** that produces what it mounts. Four mechanics, in `assemble → run → assert` order:

1. **Schema + assembler (02-01).** Define `recipes/<name>/recipe.yaml` (MCP layer + file-extension layer,
   per-server `transport`) and `stacks/<name>/stack.yaml` (harness + recipes + config/permissions/state)
   per design §11/§12. The `harnessed-tools` Python image reads these and **emits** a `Dockerfile.hatago`
   build context + a committed `profiles/<stack>/.claude/{skills,...}` tree + `hatago.config.json` + a
   generated launcher into a mounted build dir — never touching the daemon. Fanning skills/commands into
   harness-native paths is `sync-plugin-links`' job and **fails fast** on a name collision. The host then
   runs `podman build` for the hatago image (the base/claude images already exist from P1).

2. **Isolated auth + pod (02-02).** A new `isolated` arm in the `harnessed` dispatcher dispatches to
   `lib/harnessed-isolated.sh`, which mirrors `lib/harnessed-transparent.sh`: reuse the §4a mount layer
   (`harnessed_host_integration_mounts`), `apply_firewall`, and lifecycle helpers, but swap §4b for the
   isolated config source — mount `~/.claude/.credentials.json` **ro**, generate a minimal `.claude.json`
   **stub** (the highest-risk item; headless no-prompt acceptance test, snapshot fixture), and mount the
   committed `profiles/<stack>/.claude` tree. Compose a pod (`podman pod create --network harnessed-net`)
   with the harness container + hatago; the harness `.mcp.json` points at `http://localhost:3535/mcp`.

3. **Capability test + report (02-03).** A per-stack test builds the stack, launches it `--fresh` headless
   (`claude -p … --output-format json`), and asserts the manifest's declared MCP server + skill are present
   via machine-readable introspection (`hatago://servers` and/or `claude mcp list`; headless JSON skill
   list diffed against the manifest oracle), with an LLM-prompt backstop. The same check renders a `rich`
   markdown per-capability report. Tear down (`--fresh` guarantees no state bleed).

**Primary recommendation:** Build it as the design's tracer bullet — the *smallest* slice that exercises
every mechanic. Pick a network-free `uvx` Python stdio server (no egress, deterministic) + a no-dep
standalone skill so neither dependency installation nor the supply-chain scan (Phase 3) is needed yet.
The two genuine unknowns to resolve empirically during execution: the exact `.claude.json` stub field set,
and the exact `hatago.config.json` schema (read hatago's docs/`--help` at implementation time).
</research_summary>

<standard_stack>
## Standard Stack

### Core (new in Phase 2)
| Library/Tool | Version | Purpose | Why Standard |
|--------------|---------|---------|--------------|
| hatago MCP hub (`@himorishige/hatago-mcp-hub`) | latest npm (via `pnpm dlx`) | MCP hub: aggregate stack servers behind one HTTP endpoint; spawn stdio servers as children (stdio→HTTP) | Lightweight, multi-transport, config-file driven; `serve --http --port 3535` → `http://localhost:3535/mcp` |
| Python | 3.12/3.13 (in `harnessed-tools` image) | All assembler logic: parse/validate YAML, vendor, fan (sync-links), merge hatago config, gen stub, emit | `sync-plugin-links` prior art is Python; pinned in-image so host needs no Python (§15) |
| uv / `uvx` | 0.11.x (in hatago image) | Run the light Python stdio MCP server as a hatago child | `uvx mcp-server-time` — no pip/pipx; baked pinned |
| ruamel.yaml / PyYAML | ruamel 0.18.x / PyYAML 6.x | Parse `recipe.yaml`+`stack.yaml`; emit `hatago.config.json` | ruamel if comment round-trip matters; else PyYAML |
| jq | 1.7.x (in image) | `.claude.json` stub generation, hatago config merge | Already in image |
| rich | 14.x (in `harnessed-tools` image) | Render the capability report (markdown → terminal) | De-facto Python report lib; CI consumes the same structured result |

### Reused (from Phase 1 / existing)
| Tool | Purpose | When |
|------|---------|------|
| podman (rootless, 5.8.x) | host `pod create`/`run`/`exec -it`; host `podman build` of the hatago image | run + build, on the host |
| `harnessed-base` / `harnessed-claude` images (P1) | base lineage + the claude harness container | mounted profile + auth |
| `lib/harnessed-mounts.sh` (§4a) | host-integration mounts, reused verbatim in isolated | every isolated run |
| `lib/harnessed-common.sh` | runtime detect, build/ensure images, firewall, instance lifecycle | reused; extend for pod lifecycle |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `mcp-server-time` (uvx, network-free) | `mcp-server-fetch` (network), an npm stdio server | fetch needs egress (firewall blocks → non-deterministic test); npm pulls the JS supply-chain surface forward into a pre-gate phase |
| hatago child (stdio→HTTP) | run stdio server inside the harness container | drags uvx/npx into the harness container — the design explicitly avoids this (§3) |
| generated `.claude.json` stub | `CLAUDE_CODE_OAUTH_TOKEN` env-only auth | keep the token path as a documented fallback if credential-file mounting regresses |
| standalone skill (no deps) | vendored plugin (with deps) | vendoring exercises dep install + scan, which belong to Phase 3; not needed to prove the slice |
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System (Phase 2, isolated)
```
$ harnessed build <stack>   (host bash → harnessed-tools image emits files → host podman build hatago)
   recipes/<r>/recipe.yaml + stacks/<s>/stack.yaml
        │  (harnessed-tools, Python, EMIT ONLY)
        ├─ parse/validate → fan skills (sync-links, fail-fast) → profiles/<s>/.claude/...
        ├─ merge → hatago.config.json   ├─ gen .claude.json stub   └─ emit Dockerfile.hatago + launcher
   host: podman build harnessed-hatago

$ harnessed <stack> --fresh [path]   (host bash: lib/harnessed-isolated.sh)
   ├─ §4a mounts (reuse) + project + egress firewall + ro ~/.claude/.credentials.json + stub + profile mount
   ├─ podman pod create harnessed-<stack>-<projhash> --network harnessed-net
   ├─ podman run -d --pod ... --name hatago  harnessed-hatago        (serve --http --port 3535)
   ├─ podman run -d --pod ... --name <harness> -v cwd -v profile  harnessed-claude
   └─ podman exec -it <harness>  claude   ← .mcp.json → http://localhost:3535/mcp ; host-native TTY
```

### Pattern 1: Pod composition at runtime (§3, design ARCHITECTURE Pattern 1)
**What:** `podman pod create --name harnessed-<stack>-<projhash> --network harnessed-net`, then `podman run -d --pod <pod>` for hatago and the harness. Shared netns → harness reaches hatago at `localhost:3535`.
**Why:** `FROM` can't union two running systems (§6); a pod can. Pod must be re-created when bind mounts change.

### Pattern 2: Split assembly output — committed→mounted profile + baked→images (§7)
**What:** Assembler emits the Claude-canonical file tree → git-committed `profiles/<stack>/` (mounted rw at `/home/harnessed/.claude`), and MCP-server deps → baked into the hatago image.
**Why:** Editable/versioned extensions + pinned/clean dependency closure. "Nothing assembled at container start."

### Pattern 3: Tool-in-a-container emits, host builds (§15)
**What:** `harnessed-tools` reads recipes/stacks and writes Dockerfile + context + profile + hatago.config.json + launcher into a mounted build dir; it never calls the daemon. Host runs `podman build`.
**Why:** Only host dep is podman; no socket, no host-path footgun, clean TTY.

### Pattern 4: Isolated auth = ro credential + generated stub (§4b, Pitfall 2)
**What:** Mount `~/.claude/.credentials.json` ro; generate a minimal `.claude.json` stub with onboarding/identity fields and NO token. Never mount the host `.claude.json`.
**Why:** Auth without dragging host state; avoids the whole-file-blob race (Pitfall 1) and the onboarding re-prompt (Pitfall 2).

### Pattern 5: Capability test, manifest as oracle (§18)
**What:** Build → `--fresh` headless run → assert declared servers connected (`hatago://servers` / `claude mcp list`) + skills present (headless JSON diff) → render `rich` markdown report → teardown.
**Why:** Tests survive refactors; the report doubles as a user artifact. No assembler unit tests.

### Anti-Patterns to Avoid
- Wiring a stdio server as an HTTP URL, or double-wrapping a network-native service (Pitfall 4). Declare `transport` per server; stdio → hatago child, network-native → proxied by URL.
- rw-bind-mounting `~/.claude.json` in isolated (carries P1's MNT-03 rule forward) — generate a stub instead.
- Copying the onboarding stub fields from a blog without the empirical no-prompt test (Pitfall 2) — snapshot-test the working stub.
- Last-wins on recipe name collisions — fail-fast, report both names (Pitfall 5 / RCP-04).
- Any secret in an image layer or the committed profile (Pitfall 7) — env-only; credential ro; stub carries no token.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| §4a host-integration mounts | new mount logic | `lib/harnessed-mounts.sh::harnessed_host_integration_mounts` (P1) | already ported/proven; isolated only swaps §4b |
| instance lifecycle / firewall / runtime detect / image build | new helpers | `lib/harnessed-common.sh` (P1) | reuse; extend for `podman pod` lifecycle |
| launcher shape | new launcher from scratch | mirror `lib/harnessed-transparent.sh` | same daemon-container + `exec -it` attach pattern |
| MCP aggregation / stdio→HTTP | a custom proxy | hatago (`@himorishige/hatago-mcp-hub`) | multi-transport hub; one endpoint; child stdio servers |
| skill/command fan + collision detect | new fan logic | port `sync-plugin-links` (already Python) | explicit fail-fast conflict reporting (RCP-04) |
| plugin acquire | new resolver | port `vendor-plugin` (host prior art) | resolve marketplace/url/git-subdir+sha (deps come Phase 3) |
| `.claude.json` stub seed | mounting host file | a tiny `jq`-built stub generator | never rw-mount the whole-file blob |
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls (Phase-2-relevant; full detail in `.planning/research/PITFALLS.md`)

### Pitfall A: Onboarding/login stub fields wrong → every isolated launch re-prompts (Pitfall 2) — HIGHEST RISK
**What goes wrong:** the minimal `.claude.json` stub omits/misnames the fields Claude gates on → the `--fresh` headless instance drops into theme picker / onboarding / re-login and the capability test hangs.
**How to avoid:** set `hasCompletedOnboarding: true` (primary gate, corroborated); add `oauthAccount`, `userID`, and likely `firstStartTime`, `numStartups` [INFERENCE — verify]. Mount `~/.claude/.credentials.json` ro. **Verify empirically once**: `--fresh` headless run → zero interactive prompts; snapshot-test the working stub so a Claude upgrade that adds a gate fails loudly. Keep `CLAUDE_CODE_OAUTH_TOKEN` as a fallback.
**Warning signs:** headless run hangs or returns an onboarding/login prompt instead of JSON.

### Pitfall B: MCP transport mismatch (Pitfall 4)
**What goes wrong:** wiring a stdio server as an HTTP URL (never connects) or baking a network-native service as a stdio child (double-wrap).
**How to avoid:** explicit `transport` per server in the recipe schema (default `stdio` for `command` entries). Light stdio → hatago child (baked, stdio→HTTP); the tracer-bullet `mcp-server-time` is stdio. Assert connectivity via `hatago://servers` / `claude mcp list`, not by trusting config.

### Pitfall C: `hatago.config.json` schema assumed, not verified — MEDIUM
**What goes wrong:** the exact config keys for declaring a child stdio server + the serve flags are not pinned in our research.
**How to avoid:** at implementation time, read hatago's docs / `pnpm dlx @himorishige/hatago-mcp-hub --help` and an example config; validate the emitted config boots and connects the server before wiring the harness. Treat the config schema as verify-during-execution.

### Pitfall D: secrets in image/profile (Pitfall 7)
**How to avoid:** env-only; credential ro; stub carries no token; `.mcp.json` carries URLs/`*_env` refs, not secret values. (The build-time leak-scan guard is hardened in Phase 3, but keep the rule from the start.)

### Pitfall E: pod identity vs bind mounts
**What goes wrong:** bind mounts are fixed at pod/container creation; changing the project path needs a fresh pod.
**How to avoid:** key the pod name on `<stack>-<projhash>`; `--fresh` recreates cleanly. Reuse P1's `generate_instance_name` convention.
</common_pitfalls>

<open_questions>
## Open Questions (resolve during execution — none block planning)

1. **`.claude.json` stub field set** — candidate `{hasCompletedOnboarding, oauthAccount, userID, firstStartTime, numStartups}` [INFERENCE, MEDIUM]. Resolve with the headless no-prompt acceptance test; snapshot the working stub (02-02). Inspect the real host `~/.claude.json` for the authoritative `oauthAccount`/`userID` shape.
2. **`hatago.config.json` schema + serve flags** — exact keys for a child stdio server and `serve --http --port 3535`. Read hatago docs/`--help` at implementation (02-01/02-02). [MEDIUM]
3. **`mcp-server-time` package** — confirm `uvx mcp-server-time` is the correct invocation, speaks MCP over stdio, and needs no network (works under the egress firewall). Swap to another network-free stdio server if not. [MEDIUM]
4. **Headless skill introspection** — confirm `claude -p … --output-format json` can emit the visible skills/commands as machine-readable JSON for the manifest diff, or fall back to filesystem assertion (profile mounted at `/home/harnessed/.claude/skills`). [MEDIUM]
5. **Harness profile mount target** — confirm `profiles/<stack>/.claude` → `/home/harnessed/.claude:rw` is the right target for claude to read skills/`.mcp.json`/`settings.json`/stub (vs needing `CLAUDE_CONFIG_DIR`). [LOW — claude reads `$HOME/.claude`]
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `SUMMARY.md` (web-verified at milestone level)
- `docs/harnessed-design.md` §3, §4b, §5, §6, §7, §11, §12, §13, §15, §18
- `02-CONTEXT.md` (locked decisions D-01..D-16)
- Phase 1 code: `harnessed`, `lib/harnessed-*.sh`, `base/Dockerfile.harnessed-{base,claude}`, `stacks/transparent/stack.yaml`
- hatago: <https://github.com/himorishige/hatago-mcp-hub>, <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub> (`serve --http --port 3535` → `/mcp`, stdio→HTTP)
- MCP transports (Streamable HTTP; SSE deprecated): <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>
- podman pods / rootless: <https://docs.podman.io/en/stable/markdown/podman.1.html>

### Tertiary (LOW/MEDIUM — validate in execution)
- `.claude.json` onboarding stub field set beyond `hasCompletedOnboarding` (community headless guides; #14313/#3833)
- exact `hatago.config.json` schema (read at implementation)
- `mcp-server-time` availability/invocation

---

*Phase: 02-isolated-tracer-bullet-stack*
*Research completed: 2026-06-14*
*Ready for planning: yes*
