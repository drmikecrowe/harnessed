# Phase 2: Isolated Tracer-Bullet Stack - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 2-Isolated Tracer-Bullet Stack
**Mode:** `--auto` — gray areas auto-resolved with the recommended option (no interactive prompts).
**Areas discussed:** Tracer-bullet composition, MCP/hatago wiring, Hatago image strategy, Isolated auth stub, Capability assertion, Assembler model, Schema scope, Isolated dispatch, §4a in isolated

---

## Tracer-bullet composition

| Option | Description | Selected |
|--------|-------------|----------|
| claude + uvx network-free stdio MCP server + no-dep standalone skill | Smallest slice; deterministic under egress FW; exercises MCP-03 stdio→HTTP wrap + RCP-04 fan, no deps/scan | ✓ |
| claude + vendored plugin (with deps) + its skill | Exercises vendor-plugin dep install too, but pulls in supply-chain surface Phase 3 owns | |
| claude + JS (`pnpm dlx`) stdio MCP server | Pulls JS supply-chain surface forward into a phase before the scan gate exists | |
| claude + network-native MCP server | Egress firewall makes the capability test non-deterministic; skips the riskier stdio→HTTP path | |

**Choice:** claude + one network-free `uvx` Python stdio MCP server (recommended: `mcp-server-time`, researcher confirms) + one no-dep standalone skill.
**Notes:** The slice must exercise *every* Phase-2 mechanic with the *least* surface. Network-free + credential-free keeps the assert deterministic and credential-free; stdio exercises MCP-03 (Pitfall 3). Plugin-vendoring-with-deps deferred to ride with Phase 3's scan gate. → D-01, D-02, D-03.

---

## MCP / hatago wiring

| Option | Description | Selected |
|--------|-------------|----------|
| stdio server as hatago child; `.mcp.json` → hatago single Streamable-HTTP endpoint | hatago wraps stdio→HTTP (MCP-03); harness sees one endpoint (MCP-02); pod on harnessed-net (MCP-01) | ✓ |
| stdio server inside the harness container | Drags uvx/npx into the harness container — the thing the design explicitly avoids | |
| SSE transport | Deprecated in the MCP spec | |

**Choice:** stdio server runs as a hatago child (stdio→HTTP); harness `.mcp.json` points only at hatago's Streamable-HTTP endpoint (`:3535`); pod members share netns → `localhost:<port>`.
**Notes:** Streamable HTTP only (SSE deprecated). → D-04, D-05.

---

## Hatago image strategy

| Option | Description | Selected |
|--------|-------------|----------|
| One base `hatago` image bakes light servers + per-stack generated `hatago.config.json` selects exposure | One extra Dockerfile; config is the variable; reproducible/pinned | ✓ |
| Per-stack baked hatago image | Heavier; only needed when a recipe wants a server not in the base image (deferred) | |

**Choice:** base `hatago` image bakes the light servers; per-stack `hatago.config.json` (generated, mounted) selects which to expose.
**Notes:** Matches §6/§7 "light servers baked into the hatago image." → D-06.

---

## Isolated auth stub (highest-risk item)

| Option | Description | Selected |
|--------|-------------|----------|
| ro `.credentials.json` mount + generated `.claude.json` stub, headless no-prompt test, snapshot working stub | Resolves Pitfall 2 / STATE blocker empirically; reproducible fixture | ✓ |
| Ship the inferred stub field set unverified | Risks a re-login/onboarding prompt on a "headless" boot | |
| Mount host `~/.claude.json` | Violates MNT-03 (whole-file blob; corruption/leak) | |

**Choice:** mount `~/.claude/.credentials.json` read-only + generate a minimal `.claude.json` stub; candidate set `oauthAccount`, `userID`, `hasCompletedOnboarding` (+ likely `firstStartTime`, `numStartups`); verify with a headless no-prompt acceptance test; snapshot the working stub as a committed fixture.
**Notes:** This is the Phase 2 research flag. The stub generator is the isolated analog of Phase 1's `lib/harnessed-claude-config.sh` copy-on-start. → D-07, D-08, D-09.

---

## Capability assertion

| Option | Description | Selected |
|--------|-------------|----------|
| Machine-readable introspection first, LLM prompt as backstop | Deterministic primary (hatago `hatago://servers` + `claude mcp list`; headless JSON skill diff vs manifest); NL prompt on top | ✓ |
| LLM prompt only ("can you use skill X?") | Non-deterministic, flaky as a CI gate | |
| Assembler unit tests | Project anti-feature — couples tests to implementation | |

**Choice:** introspection primary (manifest is the oracle), LLM prompt as behavioral backstop; render a `rich` markdown per-capability report; run `--fresh`, tear down after.
**Notes:** One mechanism, two audiences (CI green/red + user report). → D-10, D-11.

---

## Assembler execution model

| Option | Description | Selected |
|--------|-------------|----------|
| `harnessed-tools` emits files only; host runs `podman build`/run | No DooD, no socket, no host-path footgun, clean TTY (§15) | ✓ |
| Assembler drives the daemon (DooD) | Rejected design — socket mount, host-path footgun, TTY tunneling | |

**Choice:** the `harnessed-tools` Python image emits `Dockerfile` + build context + committed `profiles/<stack>/` + `hatago.config.json` + a generated launcher; the host runs `podman build`. Collision policy = fail-fast (reuse `sync-plugin-links` conflict reporting).
**Notes:** `transparent` stays assembler-free. → D-12, D-13.

---

## Schema scope

| Option | Description | Selected |
|--------|-------------|----------|
| Implement §11/§12 schema; require only tracer-bullet fields, parse rest forward | Doesn't gate the slice on unused fields; schema lands once | ✓ |
| Implement the full schema with all fields required now | Over-builds before later phases need the fields | |

**Choice:** `recipe.yaml` + `stack.yaml` per §11/§12; require only the fields the slice exercises; `config: isolated` default, `harness: claude`.
**Notes:** → D-14.

---

## Isolated dispatch / engine integration

| Option | Description | Selected |
|--------|-------------|----------|
| New `isolated` case arm + `lib/harnessed-isolated.sh` mirroring the transparent launcher | Reuses §4a mounts, firewall, lifecycle; minimal new surface | ✓ |
| A separate top-level isolated entrypoint | Duplicates the dispatcher and lifecycle plumbing | |

**Choice:** add `isolated)` to the `harnessed` dispatcher `case` + `lib/harnessed-isolated.sh` mirroring `harnessed-transparent.sh`, sourcing config from the assembled profile + pod composition. `harnessed <stack>` dispatches directly (the per-stack shim is Phase 4).
**Notes:** → D-15.

---

## §4a host-integration layer in isolated

| Option | Description | Selected |
|--------|-------------|----------|
| Keep §4a as-is in isolated; defer a clean-room gating flag | §4a is operational (auth/signing/git), belongs in every instance (§4a) | ✓ |
| Gate editor/tool config mounts behind a flag now | Low stakes; not needed to prove the slice | |

**Choice:** keep the §4a layer unchanged in isolated; defer a "truly empty environment" gating flag.
**Notes:** → D-16.

---

## Claude's Discretion

- Build-dir location + exact emitted-file layout; assembler Python module factoring + YAML
  parse/validate approach (yq/jq vs pydantic); hatago port selection; pod/instance naming beyond §13;
  the `harnessed build` assemble → `podman build` ordering.

## Deferred Ideas

- Plugin-vendoring-with-deps + supply-chain scan gate + pnpm managed config → Phase 3.
- omp harness via `claude-hooks-bridge` + pi-adapter → Phase 4.
- Shared service sidecars + `svc` + concurrent attach → Phase 4.
- Full state model (`session_state` host vs harnessed-owned, persistent breadth) → Phase 4.
- CLI breadth (`install`/`uninstall` shims, `new`, `list`/`stop`/`rm` for isolated) → Phase 4.
- varlock/1Password secrets, token-gated scanners, docs surface → Phase 5.
- `CLAUDE_CONFIG_DIR` relocation (Phase 1 fast-follow) — not Phase 2.
- Clean-room gating flag for §4a editor/tool config mounts in isolated.
