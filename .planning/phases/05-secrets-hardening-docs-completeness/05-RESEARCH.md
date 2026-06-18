# Phase 5: Secrets, Hardening + Docs Completeness — Research

**Researched:** 2026-06-18
**Domain:** Opt-in secrets resolution (varlock + 1Password), token-gated supply-chain scanners (snyk/Socket.dev), one-shot scanner-token auth, a nightly image re-scan timer, and the gated documentation surface.
**Confidence:** HIGH for external facts (varlock/snyk/socket/op/systemd-timer all verified against official docs + live CLIs + npm registry on 2026-06-18); HIGH for repo integration points (every claim grounded in actual code/file reads — scan.py, build_stack, the launcher, the shipped `.env.schema.example`, the §4a mount layer); MEDIUM for the exact varlock resolution wiring (a design choice the planner locks — see Open Questions / A1) and for the `@varlock/1password-plugin` 0.3.2→1.2.0 API stability (a major-version bump the plan must verify — A4).

<user_constraints>
## User Constraints

**No CONTEXT.md exists for this phase — the discuss-phase was skipped (mode: yolo).** The binding constraints below are lifted verbatim from `CLAUDE.md` (which the role treats with the same authority as locked CONTEXT.md decisions), from `.planning/REQUIREMENTS.md` Out-of-Scope, and from `docs/harnessed-design.md` §7/§16/§17. The planner MUST honor these as if locked.

### Locked decisions (from CLAUDE.md → §7/§15/§16 of `docs/harnessed-design.md`)

- **Security/secrets:** auth and scanner/1Password secrets are **env-only, never an image layer or repo file**; varlock + 1Password are **optional opt-in** (§16). `[CITED: CLAUDE.md Constraints]`
- **Supply chain (credential scanners):** token-gated scanners (`snyk`/`Socket.dev`) run when a token is present and **warn-and-skip otherwise**; `harnessed build` stays **non-interactive/reproducible** (CI + nightly timer) — never prompt. Credential-free `osv-scanner` + `pip-audit` remain the baseline gate (§7). `[CITED: CLAUDE.md Constraints + design §7]`
- **Scanner tokens:** `harnessed auth snyk|socket` sets a token once, **persisted to host config (never an image layer)** (§7). `[CITED: design §7 "Scanner credentials"]`
- **Tech stack:** all logic in the containerized `harnessed-tools` Python image; **host deps stay at podman/docker only** (§15). varlock + `op` may be baked into `harnessed-tools` so opt-in users need nothing extra on the host — but they stay **inert unless a `.env.schema` exists** (§16). `[CITED: design §15/§16]`
- **Execution model:** `harnessed-tools` **emits files only** — it NEVER invokes podman/docker or mounts a daemon socket (§15, D-12). Scanner invocation during `harnessed build` already runs inside the tools image over the mounted build dir; image scanning is host-driven (`podman save` → tools `scan-image`). Phase 5 reuses this split — no new daemon wiring. `[CITED: Phase 3 RESEARCH Pattern 2 + verified in `lib/harnessed-common.sh:110-141`]`
- **1Password resolution preference:** for interactive use, prefer the **mounted desktop-app agent socket** (app-auth, `allowAppAuth`); reserve `OP_SERVICE_ACCOUNT_TOKEN` for **headless/CI where no agent exists**, and scope it narrowly — a visible service-account token leaks into any process sharing the env (CLAUDE.md "What NOT to Use"). `[CITED: CLAUDE.md pitfalls]`
- **Docs:** each documentation section lands **with the feature it documents** — a feature isn't done until its docs exist (§17). `[CITED: design §17 + CLAUDE.md Constraints]`
- **MCP transport:** Streamable HTTP only; SSE is deprecated (MCP spec 2025-06-18). N/A to this phase's code, but the service-authoring doc (DOC-03) must state it. `[CITED: CLAUDE.md "What NOT to Use"]`

### Claude's Discretion (research recommends — planner may adjust)

- **Where varlock resolution executes:** host-vs-tools-image. Recommendation: a throwaway `harnessed-tools` invocation that resolves the schema and emits an env-file/env-array the host launcher passes to the pod (preserves "podman-only host"). See Architecture Pattern 1 + Open Question 1.
- **Nightly timer install mechanism:** a static shipped unit vs a `harnessed timer enable|disable` subcommand. Recommendation: ship static units + a thin `harnessed rescan` subcommand the unit calls (see Architecture Pattern 4).
- **snyk install mechanism under pnpm 11 `strictDepBuilds`:** `allowBuilds: snyk` vs the standalone snyk installer vs `npm install -g`. Recommendation: add `snyk: true` to `allowBuilds` in the tools image (it's the official wrapper's documented bootstrap). See Pitfall 3.
- **Doc format/location:** `docs/` subdirectory vs repo root. Recommendation: `docs/guides/` for the three new how-tos; refresh the existing `docs/harnessed-design.md` cross-references; `README.md` at repo root. See Architecture Pattern 5.

### Out-of-Scope for this phase (REQUIREMENTS — do NOT plan)

- **`npm`/`npx` for JS installs** — explicitly forbidden; pnpm only (REQUIREMENTS Out-of-Scope). snyk/socket install via `pnpm add -g` / `pnpm dlx`, never `npm install -g`. `[CITED: REQUIREMENTS.md Out-of-Scope]`
- **Per-stack secret overrides referenced from `stack.yaml`** — that is **SEC-05, a v2 requirement** (deferred). Phase 5 ships ONLY the host-level `~/.config/harnessed/.env.schema` + per-service `~/.config/<service>/.env.schema` (§16). `[CITED: REQUIREMENTS.md v2 → SEC-05]`
- **A prebuilt/published `harnessed-tools` image** — IMG-01 (v2). Phase 5 keeps baking locally. `[CITED: REQUIREMENTS.md v2]`
- **Re-baking the credential-free scan gate** — Phase 3 shipped BLD-02 (osv-scanner + pip-audit). Phase 5 ADDS token-gated scanners alongside it; it does not re-implement the baseline.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **SEC-01** | varlock + 1Password secrets are opt-in via `.env.schema` (inert when absent) and injected as env only — never baked or committed. | Standard Stack §varlock/§op; Architecture Pattern 1 (detect-and-wrap, inert when absent); Code Examples §1–§2; the repo ALREADY ships `.env.schema.example` (verified). Pitfall 1 (the plugin pin is stale). |
| **SEC-02** | Token-gated scanners (snyk/Socket.dev) run when a token is present and warn-and-skip otherwise, keeping `harnessed build` non-interactive. | Standard Stack §snyk/§socket; Architecture Pattern 2 (extend `scan.py` with token-gated invokers); Code Examples §3–§4; Pitfall 2 (snyk exit code 1 = vulns, not error) + Pitfall 3 (snyk postinstall vs pnpm `strictDepBuilds`). |
| **SEC-03** | `harnessed auth snyk\|socket` sets a scanner token once, persisted to host config (never an image layer). | Architecture Pattern 3 (new `auth` subcommand parallel to `svc`/`install`); Code Examples §5; the host ALREADY has `~/.config/configstore/snyk.json` (verified) — the persistence path is `snyk config set api=` / `socket login`. |
| **SEC-04** | A nightly re-scan timer re-runs osv-scanner against installed images to catch post-build CVEs. | Standard Stack §systemd-user-timer; Architecture Pattern 4 (user `.timer`+`.service` + `harnessed rescan`); Code Examples §6; Environment Availability (`loginctl enable-linger` is OFF on the host — a documented prerequisite). |
| **DOC-01** | README documents what harnessed is, the two modes, install, first-run build, and a quickstart. | Architecture Pattern 5; the repo already has `docs/harnessed-design.md` (590 lines, source of truth) + `AGENTS.md` (the OLD `container` setup). README supersedes/extends AGENTS.md. |
| **DOC-02** | Recipe-authoring and stack guides document writing recipes/stacks with a worked example. | Architecture Pattern 5; existing `recipes/time/`, `recipes/ping/`, `stacks/tracer-time/`, `stacks/ping-time/`, `stacks/transparent/` are ready-made worked examples (verified by read). |
| **DOC-03** | Secrets-setup, service-authoring, and troubleshooting/ops docs exist. | Architecture Pattern 5; secrets doc lands WITH SEC-01 (cadence rule); service-authoring uses the existing `services/ping/` (Dockerfile + server.py + service.yaml, verified) as the worked example; troubleshooting covers podman socket, first-run build, auth/onboarding, `--fresh`, host-persisted sessions. |
</phase_requirements>

## Summary

Phase 5 closes the perimeter and the documentation surface. Four of the seven requirements (SEC-01..SEC-04) are **opt-in hardening that must stay inert by default** — the no-secrets, no-token path cannot regress. Three (DOC-01..DOC-03) are the gated docs. The good news: **the repo has already done significant Phase 5 groundwork.** A ready-to-copy `.env.schema.example` ships at the repo root (verified — it uses the varlock `@env-spec` DSL with `@plugin(@varlock/1password-plugin)` + `@initOp(allowAppAuth=true)` and `op(op://…)` refs for `SNYK_TOKEN`/`SOCKET_SECURITY_API_KEY`); the 1Password agent socket is **already mounted** at `$CONTAINER_HOME/.1password/agent.sock` in the shared §4a mount layer (`lib/harnessed-mounts.sh:23-27`), so `op` resolution needs no new mount; the Phase 3 scan gate (`tools/harnessed/scan.py`) is structured exactly to extend with new scanner invokers; and the bash launcher already has a clean subcommand-dispatch pattern (`svc`, `install`, `new`) that `auth` and `rescan` slot into.

1. **SEC-01 — varlock + 1Password, opt-in.** The shipped `.env.schema.example` is the opt-in switch: copy it to `~/.config/harnessed/.env.schema` and the launcher detects it and wraps the launch so resolved secrets reach the pod **as env only**. Absent the file, varlock is **never invoked** (the launcher has zero varlock references today — verified). The work is: bake varlock + `op` into `harnessed-tools` (currently absent — `docs/codebase/INTEGRATIONS.md:178-181` confirms "varlock/op are also not yet baked"), wire the detect-and-resolve path, and keep it dead-code when no schema exists. Resolution reuses the **already-mounted agent socket** (app-auth, `allowAppAuth`) for interactive use; `OP_SERVICE_ACCOUNT_TOKEN` is the headless fallback (nightly timer / CI). **One real finding:** the example file pins `@varlock/1password-plugin@0.3.2` but the current npm release is **1.2.0** (a 0.x→1.x major bump) — the plan must bump the pin and verify the `op()` / `@initOp` API is stable across it (Pitfall 1, A4).

2. **SEC-02 — token-gated scanners, warn-and-skip.** Add `snyk` and `socket` invokers to `scan.py`, gated on `os.environ.get("SNYK_TOKEN")` / `SOCKET_SECURITY_API_KEY`. The critical difference from the Phase 3 gate: **snyk `test --severity-threshold=high` HAS a native severity filter** (exit 0=clean, **1=vulns-at-threshold-found**, 2=failure, 3=no-supported-projects) — so the snyk gate reads the exit code directly, unlike osv-scanner where the gate is Python-over-JSON. Socket's `socket scan create` is **server-side** (uploads the manifest to Socket.dev) — it adds a network dependency and a quota cost, so its warn-and-skip path is the more important one. **Pitfall 3:** the snyk npm package has a postinstall (`node wrapper_dist/bootstrap.js exec`) that downloads the platform binary; under pnpm 11 `strictDepBuilds: true` (shipped Phase 3) this is **blocked** unless `snyk: true` is added to `allowBuilds`. The plan must resolve this tension (allowlist entry vs standalone installer).

3. **SEC-03 — `harnessed auth snyk|socket`.** A new bash subcommand parallel to `svc`/`install`. It runs the vendor CLI's own auth inside a `--rm` tools container with the host config dir bind-mounted rw, so the token persists to host config (`~/.config/configstore/snyk.json` for snyk — `snyk config set api=<token>`; Socket's config for `socket login`) and **never lands in an image layer**. The host ALREADY has `~/.config/configstore/snyk.json` (1010 bytes, verified) — the path is real and pre-existing.

4. **SEC-04 — nightly re-scan timer.** A systemd **user** timer (`~/.config/systemd/user/harnessed-rescan.{timer,service}`, `OnCalendar=daily` + `Persistent=true`) calling a new `harnessed rescan` subcommand that re-runs `osv-scanner scan image` in **online** mode (fresh DB — the whole point is post-build CVEs) against every installed harnessed-labelled image. **Two prerequisites the docs/setup must state:** `loginctl enable-linger $USER` (currently OFF on the host — without it the timer does not fire when the user is logged out) and network egress to osv.dev at scan time (the build-time gate uses the offline DB; the nightly cannot).

5. **DOC-01/02/03 — the gated docs.** `docs/harnessed-design.md` (the 590-line architecture source of truth) already exists; the new docs are how-tos that **reference** it. Per the cadence rule, the secrets doc lands with SEC-01, service-authoring can land anytime (Phase 4 already ships the surface), troubleshooting lands at phase end.

**Primary recommendation:** Do SEC-01..SEC-04 as plan 05-01 in dependency order (secrets plumbing → scanner invokers → auth command → nightly timer), because SEC-02/03/04 all build on either the varlock env-resolution path (SEC-01) or the existing scan.py structure. Do DOC-01/02/03 as plan 05-02, gated on 05-01's features being real (the secrets doc cannot precede SEC-01). Resolve the three open questions (varlock wiring site, snyk-under-pnpm install, timer install mechanism) at plan time; the research recommends a default for each but they are genuine design forks.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| **SEC-01** `.env.schema` detection + opt-in switch | host bash launcher (`harnessed` + `lib/`) | — | The launcher is the only place that sees the host filesystem (`~/.config/harnessed/`); it's the natural "is varlock opted in?" gate. Inert when absent = a bash `[[ -f ]]` test. |
| **SEC-01** varlock + `op` resolution | `harnessed-tools` image (throwaway resolve invocation) | host launcher (captures resolved env, passes to the pod) | varlock is a Node CLI; the host must stay podman-only. Resolution runs in a tools container (schema + op socket mounted), emits resolved env, host re-injects. Mirrors the existing emit-only tools pattern. |
| **SEC-01** 1Password auth transport | `lib/harnessed-mounts.sh` (agent socket, already mounted) | `OP_SERVICE_ACCOUNT_TOKEN` env (headless fallback) | The §4a agent socket mount (`:23-27`) is the default app-auth path; the service-account token is the documented headless fallback. No new mount needed. |
| **SEC-01** env injection into the pod | host launcher (`-e`/`--env-file` to `podman run` members) | — | Resolved secrets are passed as `-e KEY=VAL` (or a temp `--env-file`) to the pod members — never written to the profile or an image. |
| **SEC-02** snyk/socket invocation | `harnessed-tools` image (`tools/harnessed/scan.py`) | host `build_stack` (passes `-e SNYK_TOKEN`/`SOCKET_SECURITY_API_KEY` to the scan step) | Same home as osv-scanner/pip-audit (Phase 3). Token arrives via env; scanner CLIs baked inert into the image. |
| **SEC-02** warn-and-skip decision | `scan.py` Python (`os.environ.get(...)` gate) | — | Pure env-presence check; no prompt, no network-on-absence. Keeps `harnessed build` non-interactive. |
| **SEC-03** `harnessed auth snyk\|socket` | host launcher (`harnessed` dispatch + a new `lib/` helper or inline) | tools image (`--rm`, runs `snyk auth`/`socket login`) | Mirrors `svc`/`install` dispatch. Token persists to the bind-mounted host config dir; `--rm` guarantees no layer. |
| **SEC-04** nightly timer (unit files) | `~/.config/systemd/user/harnessed-rescan.{timer,service}` (host) | `loginctl enable-linger` (host prerequisite) | A user timer is the rootless podman-native cron replacement; linger is mandatory for fire-while-logged-out. |
| **SEC-04** image re-scan logic | `harnessed-tools` image (`run_image_scan`, online mode) | new `harnessed rescan` subcommand (host: iterates images, calls tools) | Reuses Phase 3's `run_image_scan` but ONLINE (fresh DB). The host iterates `podman images` (label-filtered) and drives the scan, exactly like `harnessed test`/`build_stack` image-scan. |
| **DOC-01** README | repo root `README.md` | — | Conventional entry point; supersedes the `AGENTS.md` `container`-era setup. |
| **DOC-02** recipe/stack guides | `docs/guides/` (new) | `docs/harnessed-design.md` (cross-ref) | How-tos reference the design doc for *why*; they show *how* with a worked example. |
| **DOC-03** secrets/service/troubleshooting | `docs/guides/` (new) | — | Secrets lands with SEC-01 (cadence); service-authoring + troubleshooting land at phase end. |

## Standard Stack

> All package versions verified live on 2026-06-18 via `npm view <pkg> version` + `npm view <pkg> repository/scripts` + `slopcheck install --ecosystem npm`. The host has the real CLIs installed (`op` 2.34.1, `varlock` 1.7.0, `snyk` 1.1305.1, `socket` 1.1.102) — versions below are the **latest npm releases**; the plan pins into the tools image, not the host.

### Core (new in Phase 5)

| Tool | Version (verified 2026-06-18) | Purpose | Why standard |
|------|-------------------------------|---------|--------------|
| **varlock** (`dmno-dev/varlock`) | **1.7.1** (npm; host has 1.7.0). Node ≥ 20. | Reads `.env.schema` (`@env-spec` DSL), resolves `op(op://…)` refs (via the 1Password plugin), validates, injects into a child process via `varlock run -- <cmd>`. | The designed opt-in secrets layer (§16). `varlock run` is the documented injection primitive. AI-safe schema, type validation, leak detection. `[VERIFIED: npm registry + varlock.dev/guides/schema + varlock.dev/reference/cli-commands]` |
| **`@varlock/1password-plugin`** | **1.2.0** (npm; same `dmno-dev/varlock` monorepo, `packages/plugins/1password`). The shipped `.env.schema.example` pins **0.3.2** — STALE. | Provides the `op()` resolver function + `@initOp(allowAppAuth=true)` decorator that the example schema uses. | The `op(op://Vault/Item/field)` shorthand in the shipped example depends on this plugin. slopcheck `[OK]`. `[VERIFIED: npm registry — but 0.3.2→1.2.0 is a major bump; API stability to verify — A4]` |
| **`@env-spec/parser`** | **0.4.1** (npm; same monorepo, `packages/env-spec-parser`). | The DSL parser varlock is built on. Pulled transitively by varlock; listed for provenance. | The `.env.schema` syntax (`@decorator` comments, `KEY=value`, resolver functions) is the @env-spec DSL. `[VERIFIED: npm registry]` |
| **1Password CLI (`op`)** | **2.34.1** (host; apt/GitHub-release distributed, not a registry pkg). | Resolves `op://Vault/Item/field` refs for varlock; `op read` is the underlying call. | The designed secrets backend (§16). Auth via the **mounted agent socket** (app-auth, `allowAppAuth`) — already in `lib/harnessed-mounts.sh:23-27` — OR `OP_SERVICE_ACCOUNT_TOKEN` for headless. `[VERIFIED: `op --version` on host + developer.1password.com/docs/service-accounts/use-with-1password-cli/]` |
| **snyk CLI** (`snyk`) | **1.1305.1** (npm; host has the same). | `snyk test --severity-threshold=high --json` on npm/pnpm trees. | The designed token-gated scanner (§7). **Native severity threshold** (unlike osv-scanner). Token via `SNYK_TOKEN` env or `~/.config/configstore/snyk.json`. slopcheck `[OK]`, but **postinstall flag** — see Pitfall 3. `[VERIFIED: npm registry + docs.snyk.io/snyk-cli/commands/test]` |
| **Socket.dev CLI** (`socket`) | **1.1.122** (npm; host has 1.1.102). | `socket scan create ./proj --json` (server-side scan) / `socket ci` (CI alias, exits non-zero if unhealthy). | The designed optional token-gated scanner (§7). Auth via `SOCKET_SECURITY_API_KEY` **or** `SOCKET_SECURITY_API_TOKEN` (BOTH accepted — verified live on the host CLI) or `socket login` (config). slopcheck `[OK]`, no postinstall. `[VERIFIED: npm registry + docs.socket.dev/docs/socket-cli + live `socket --help` env-var probe]` |

### Supporting (already in repo — reuse)

| Tool | Where | Reuse in Phase 5 |
|------|-------|------------------|
| osv-scanner v2.3.8 + pip-audit 2.10.1 | `tools/Dockerfile:38-55`, `tools/harnessed/scan.py` | The credential-free baseline gate (Phase 3, BLD-02). Phase 5 ADDS snyk/socket alongside; the nightly re-scan (SEC-04) reuses `run_image_scan` in online mode. **No change to the baseline.** |
| pnpm 11 managed config (`lib/pnpm/config.yaml`) | shipped Phase 3 | snyk/socket install via `pnpm add -g` honors `minimumReleaseAge`/`strictDepBuilds`/`allowBuilds`. **snyk's postinstall needs an `allowBuilds` entry** (Pitfall 3). |
| jq | `tools/Dockerfile:17` | Shape snyk/socket JSON output for the gate / report. |
| rich | `tools/pyproject.toml`, `tools/harnessed/report.py` | Render the scanner summary (warnings for skipped/present scanners) the way the capability/supply-chain report renders. |
| ruamel.yaml | `tools/pyproject.toml` | Parse `stack.yaml`/`service.yaml` for the rescan image set + the service-authoring worked example. |
| systemd (host) | `systemctl` 260 on host | The user-timer runtime for SEC-04. `systemctl --user enable --now harnessed-rescan.timer`. |
| `lib/harnessed-mounts.sh:harnessed_host_integration_mounts` | `:11-82` | The 1Password agent socket mount (`:23-27`) is the `op` app-auth transport — **already wired, no new mount**. |

### Alternatives considered

| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| **varlock** | `op run -- <cmd>` / `op inject` alone, sops, doppler, plain env | `op run` injects `op://` refs directly with no schema/validation layer; varlock adds **validation + typing + AI-safe schema + leak detection** (§16). Keep varlock opt-in so the no-secrets path stays zero-config. The design locked varlock; do not reconsider. `[CITED: CLAUDE.md "Alternatives Considered"]` |
| **`op()` plugin shorthand** | `exec(`op read "op://…"`)` (manual, no plugin) | The plugin shorthand is what the shipped `.env.schema.example` uses; the manual `exec(op read …)` form is documented in `varlock.dev/guides/schema` as the no-plugin alternative. Either works; the example file is the convention. |
| **snyk via `pnpm add -g`** | snyk standalone installer (`npm install -g snyk` is the vendor-documented path; or the Snyk Desktop/Docker image) | The standalone installer bypasses pnpm policy; `pnpm add -g` honors `minimumReleaseAge` etc. but trips `strictDepBuilds` (Pitfall 3). Recommendation: `pnpm add -g` + `allowBuilds: snyk`. |
| **Socket `scan create`** | `socket npm`/`socket npx` wrappers (install-time gating) | The wrappers gate *installs*; `scan create` is the build-time scan that matches the snyk/osv posture. Use `scan create` (or `socket ci`) for the build gate. |
| **systemd user timer** | cron, `podman-auto-update.timer` (system), a long-running `harnessed` daemon | cron is legacy; a system timer needs root; a daemon violates "podman-only host, no resident process." The **user** timer is the rootless podman-native choice (`Persistent=true` catches missed runs after boot). `[CITED: Red Hat podman-auto-update.timer + ArchWiki Systemd/Timers]` |
| **Online osv-scanner for nightly** | re-seed the offline DB nightly then scan offline | Online is simpler and is the point (catches newly-disclosed CVEs). Offline-reseed is deterministic but adds a DB-fetch step. Recommendation: online for the nightly; offline stays for the build-time gate. |

**Installation (inside the `harnessed-tools` image — never the host):**
```dockerfile
# tools/Dockerfile — Phase 5 additions (all INERT unless a schema/tokens exist at run).
# varlock + the 1Password plugin (Node CLIs via pnpm, honoring the Phase-3 supply-chain policy).
# NOTE: requires Node — add `mise use -g node@24` (or rely on a node layer) before this.
RUN pnpm add -g varlock@1.7.1 @varlock/1password-plugin@1.2.0
# 1Password CLI (op) — official apt repo (mirrors base/Dockerfile.harnessed-base:27-33).
RUN ... (apt install 1password-cli per the 1Password docs)
# Token-gated scanners (pnpm; snyk postinstall needs allowBuilds — Pitfall 3).
RUN pnpm add -g snyk@1.1305.1 socket@1.1.122
```

> The plan decides whether Node lands in the tools image via mise (the base-image precedent) or a multi-stage copy. The tools image is currently `python:3.13-slim` with no Node (`tools/Dockerfile:13`) — **adding Node is a real prerequisite** for varlock/snyk/socket (all Node CLIs). See Open Question 2.

**Version verification done this session:** `npm view varlock version` → 1.7.1; `npm view @varlock/1password-plugin version` → 1.2.0; `npm view @env-spec/parser version` → 0.4.1; `npm view snyk version` → 1.1305.1; `npm view socket version` → 1.1.122; `op --version` → 2.34.1 (host). All cross-checked with `npm view <pkg> repository` (all map to github.com/dmno-dev/varlock, github.com/snyk/snyk, github.com/SocketDev/socket-cli) and `slopcheck install --ecosystem npm` → all `[OK]`.

## Package Legitimacy Audit

> slopcheck 0.6.1 installed and run this session with `--ecosystem npm` (the default auto-detect probed PyPI and false-[SLOP]'d all five — a cross-ecosystem confusion; re-run with the explicit npm flag, per the protocol's Step 3).

| Package | Registry | Age / maturity | Source repo | slopcheck | Disposition |
|---------|----------|----------------|-------------|-----------|-------------|
| `varlock` | npm | 1.7.1; dmno-dev/varlock monorepo (active, Discord-linked) | github.com/dmno-dev/varlock | **[OK]** | Approved (SEC-01) |
| `@varlock/1password-plugin` | npm | 1.2.0; same monorepo, `packages/plugins/1password` | github.com/dmno-dev/varlock | **[OK]** | Approved (SEC-01) — **but the shipped `.env.schema.example` pins 0.3.2 (STALE); bump to 1.2.0 and verify the 0.x→1.x API** (A4) |
| `@env-spec/parser` | npm | 0.4.1; same monorepo, `packages/env-spec-parser` | github.com/dmno-dev/varlock | **[OK]** | Approved (transitive; listed for provenance) |
| `snyk` | npm | 1.1305.1; official Snyk CLI, 5+ yrs, very high downloads | github.com/snyk/snyk | **[OK]** | Approved (SEC-02/03) — **postinstall `node wrapper_dist/bootstrap.js exec` downloads the platform binary; under pnpm 11 `strictDepBuilds` it is BLOCKED unless `allowBuilds: snyk`** (Pitfall 3). Inline tag: `snyk` [WARNING: postinstall downloads binary — allowlist via `allowBuilds: snyk` or use the standalone installer.] |
| `socket` | npm | 1.1.122; official Socket.dev CLI | github.com/SocketDev/socket-cli | **[OK]** | Approved (SEC-02/03) — no postinstall. |
| `op` (1Password CLI) | apt / GitHub releases (NOT a registry pkg) | 2.34.1; AgileBits official | developer.1password.com | n/a (apt/release-binary; verify the apt repo key + checksum at install, mirroring `base/Dockerfile.harnessed-base:27-33`) | Approved (SEC-01) |

**Packages removed due to slopcheck [SLOP]:** none.
**Packages flagged [SUS]:** none flagged by slopcheck. `snyk` carries a manual `[WARNING]` for its postinstall binary-download behavior (a known snyk-CLI characteristic, not a slopcheck verdict) — the plan MUST resolve the pnpm `strictDepBuilds` tension.

## Architecture Patterns

### System data flow (where each SEC requirement lands in the existing pipeline)

```
A) harnessed <stack> [path]   (host launcher: lib/harnessed-isolated.sh::harnessed_isolated)
   │
   ├─[SEC-01] detect opt-in:  [[ -f ~/.config/harnessed/.env.schema ]]   (absent → varlock NEVER invoked)
   │      YES → throwaway tools container (schema + op agent socket mounted):
   │              varlock load --format env     →  emits "KEY=value..." on stdout (dotenv — podman --env-file compatible)
   │              varlock run -- true           →  (alt: validate-then-resolve)
   │              host captures resolved env → writes a TEMP --env-file (mode 0600, host-only)
   │      NO  → plain host env passthrough (today's behavior, unchanged)
   │
   ├─ pod create + members (existing) — members receive resolved env via --env-file / -e
   │      (creds reach the pod as ENV ONLY — never the profile, never an image layer)
   │
B) harnessed build <stack>    (host: lib/harnessed-common.sh::build_stack)
   │
   ├─[Phase 3] assemble + source/image scan (osv-scanner + pip-audit) — UNCHANGED baseline
   │
   ├─[SEC-02] token-gated scan step (tools image: scan.py, env-gated):
   │      if SNYK_TOKEN present:        snyk test --severity-threshold=high --json  (exit 1 = HIGH finding)
   │      else:                         warn "snyk skipped (no SNYK_TOKEN)"  — NO prompt
   │      if SOCKET_SECURITY_API_KEY:   socket scan create ./<profile> --json        (server-side; network)
   │      else:                         warn "socket skipped (no SOCKET_SECURITY_API_KEY)"
   │      → never aborts on absence; aborts ONLY on a present-scanner HIGH finding
   │
C) harnessed auth snyk|socket   (host launcher: new dispatch → tools container)
   │      podman run --rm -v ~/.config/configstore:<img>/.config/configstore:rw harnessed-tools \
   │          snyk config set api=<…>   (OR interactive `snyk auth` / `socket login`)
   │      → token persists to HOST config; --rm ⇒ no image layer
   │
D) harnessed rescan  (called by the nightly systemd user timer, SEC-04)
   │      for img in $(podman images --filter reference='harnessed-*' --format '{{.Repository}}:{{.Tag}}'):
   │          podman save "$img" -o /tmp/$$.tar
   │          podman run --rm -v /tmp/$$.tar:/img.tar:ro harnessed-tools scan-image-online /img.tar
   │          # ONLINE osv-scanner (fresh DB) — catches CVEs disclosed AFTER build
   │      (optionally re-runs snyk/socket if tokens present)
```

### Recommended file touch-list

| File | Change | Why |
|------|--------|-----|
| `tools/Dockerfile` | Add Node (mise) + `pnpm add -g varlock @varlock/1password-plugin snyk socket` + `op` (apt). Pin versions. Add `snyk: true` to the tools-image `allowBuilds` (Pitfall 3). | SEC-01/02 — the CLIs live inert in the image; the host stays podman-only. |
| `lib/pnpm/config.yaml` (or a tools-image-scoped copy) | Add `snyk: true` under `allowBuilds`. | SEC-02 — snyk's bootstrap postinstall must run to fetch the platform binary; without this, `strictDepBuilds` blocks the install. |
| `tools/harnessed/secrets.py` (new) OR inline in `scan.py` / a bash helper | varlock resolve-and-emit (`varlock load --format env` capture) + the opt-in detection contract. | SEC-01 — the detect-and-resolve primitive. |
| `tools/harnessed/scan.py` | Add `_scan_snyk(target, highs, warnings)` + `_scan_socket(target, warnings)`, env-gated; call from `run_source_scan`. Add `run_image_scan_online(archive_tar)` for the nightly (online DB). | SEC-02 (build gate) + SEC-04 (nightly). Mirrors `_scan_source_osv`/`_audit_pip` structure. |
| `tools/harnessed/cli.py` | New `scan-image-online` subcommand (nightly) + optional `auth`/`rescan` subcommands if the Python CLI owns them. | SEC-04 entrypoint (the timer calls `harnessed rescan` → this). |
| `harnessed` (launcher) | New `auth`, `rescan`, (optional `timer`) subcommand dispatch blocks, parallel to `svc`/`install`/`new` (`:102-176`). | SEC-03/04 — the user-facing surface. |
| `lib/harnessed-secrets.sh` (new) OR extend `lib/harnessed-common.sh` | `resolve_secret_env()` — detect `~/.config/harnessed/.env.schema`, run the throwaway tools resolve, emit the env-file. Called by `harnessed_isolated` before pod create. | SEC-01 wiring. Inert when no schema. |
| `lib/harnessed-common.sh::build_stack` | Pass `-e SNYK_TOKEN -e SOCKET_SECURITY_API_KEY` (if present in the launcher env) to the existing `scan` invocation (`:116-118`). | SEC-02 — the token reaches the tools image's scan step. |
| `lib/harnessed-isolated.sh::harnessed_isolated` | Call `resolve_secret_env` before the members are created; pass the resolved `--env-file` to the harness + hatago members. | SEC-01 — resolved secrets reach the pod as env. |
| `systemd/harnessed-rescan.service` + `systemd/harnessed-rescan.timer` (new, shipped in repo) | Static user-unit templates the operator copies to `~/.config/systemd/user/`. Timer: `OnCalendar=daily` + `Persistent=true`. Service: `Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan` (or the repo path). | SEC-04 — the nightly mechanism. |
| `harnessed` (usage text) | Document `auth`, `rescan`, `timer` in the `usage()` block (`:36-68`). | SEC-03/04 discoverability + DOC-01. |
| `.env.schema.example` | **Bump `@varlock/1password-plugin@0.3.2` → `@1.2.0`** and verify the API still parses. | SEC-01 — the shipped opt-in template must reference a current, non-yanked version. |
| `README.md` (new/refresh) | What/why, two modes, install, first-run build, quickstart. | DOC-01. |
| `docs/guides/recipe-authoring.md`, `docs/guides/stacks.md` (new) | Worked example end-to-end (`recipes/time` + `stacks/tracer-time`). | DOC-02. |
| `docs/guides/secrets.md`, `docs/guides/service-authoring.md`, `docs/guides/troubleshooting.md` (new) | Secrets (with SEC-01), service-authoring (with `services/ping`), troubleshooting. | DOC-03. |

### Pattern 1 — Opt-in varlock: detect in the launcher, resolve in a throwaway tools container, inject as env only (SEC-01)

**What:** varlock is a Node CLI, and the host must stay podman-only. So resolution happens **inside a `--rm` `harnessed-tools` invocation**: the host launcher detects `~/.config/harnessed/.env.schema` (and per-service `~/.config/<service>/.env.schema`), mounts the schema + the already-mounted `op` agent socket, runs `varlock load --format env` (or `varlock run -- env`), captures the resolved `KEY=value` lines, writes them to a **mode-0600 temp env-file on the host**, and passes that file to the pod members via `--env-file`. The temp file is unlinked after launch.

**When:** EVERY isolated launch (and `svc up` for a service with its own schema) — but the detect is a single `[[ -f ]]`, so the no-schema path is one cheap branch and varlock is **never invoked**.

**Inertness guarantee:** the detection is purely filesystem — no schema, no varlock process, no `op` call, no env mutation. Today's no-secrets behavior is preserved bit-for-bit.

**Resolution transport:** the `op` agent socket (`~/.1password/agent.sock`) is **already mounted** at `$CONTAINER_HOME/.1password/agent.sock` (`lib/harnessed-mounts.sh:23-27`) with `SSH_AUTH_SOCK` pointing at it. `@initOp(allowAppAuth=true)` in the schema tells the varlock 1Password plugin to use it. For headless (nightly timer / CI), `OP_SERVICE_ACCOUNT_TOKEN` is the documented fallback.

**Anti-pattern:** resolving on the host (requires host Node — breaks "podman-only"); OR baking resolved values into the profile/image (violates §16); OR leaving the temp env-file around (mode-0600 + unlink-on-exit; never write it under the repo or the profile dir).

### Pattern 2 — Token-gated scanners: env-presence gate, native severity where it exists (SEC-02)

**What:** Extend `run_source_scan` in `scan.py` with two env-gated invokers, mirroring `_scan_source_osv`/`_audit_pip`:

- **snyk** — `snyk test --severity-threshold=high --json --file <manifest>` (or `--all-projects`). **snyk HAS a native severity threshold** (verified: `--severity-threshold=<low|medium|high|critical>` on `docs.snyk.io/snyk-cli/commands/test`). Exit codes: **0** clean, **1** vulns-at-threshold-found (this is the HIGH gate — fail the build), **2** failure (warn + investigate), **3** no supported projects (warn). So unlike osv-scanner, the snyk gate reads the exit code directly: `1` ⇒ `ScanError`. The build manifest is the emitted profile's `package.json`/lockfile or a synthesized manifest for globals (the "nightly-updates trick" in design §7 — synthesize from `pnpm ls -g --json`).
- **socket** — `socket scan create <dir> --json` (server-side; uploads the manifest to Socket.dev) OR `socket ci` (CI alias). **Socket does NOT surface a CVSS severity threshold** the way snyk does — its model is policy/alert-based. Recommendation: treat socket findings as **warnings** (render in the report) unless the plan elects a fail-on policy; the warn-and-skip-on-no-token contract is the non-negotiable part.

**Env gate (the non-interactive guarantee):**
```python
def _scan_snyk(target: Path, highs: list[str], warnings: list[str]) -> None:
    token = os.environ.get("SNYK_TOKEN")
    if not token:
        warnings.append("snyk skipped (no SNYK_TOKEN) — credential-free baseline remains the gate")
        return
    # snyk auth via the env token; --severity-threshold=high ⇒ exit 1 ONLY for HIGH+
    proc = _run(["snyk", "test", "--severity-threshold=high", "--json", "--org", ...])
    if proc.returncode == 1:
        highs.extend(_snyk_high_ids(proc.stdout))   # HIGH+ findings ⇒ abort
    elif proc.returncode in (2, 3):
        warnings.append(f"snyk: non-clean exit {proc.returncode} (investigate)")
    # returncode 0 ⇒ clean
```
**Token source chain (host launcher → tools image):** the launcher passes `-e SNYK_TOKEN="$SNYK_TOKEN"` to the `scan` step in `build_stack` (`lib/harnessed-common.sh:116-118`) ONLY if `SNYK_TOKEN` is already in the launcher's env (raw env, or varlock-resolved via SEC-01, or read from `~/.config/configstore/snyk.json`). **Never prompt.**

**Anti-pattern:** prompting for a token (breaks CI + the nightly timer); trusting snyk exit 1 as "any finding" (it's threshold-specific — that's actually what we want, but the plan should confirm the threshold semantics); treating socket absence as a hard fail (it's optional + server-side + quota-cost).

### Pattern 3 — `harnessed auth snyk|socket`: persist to host config, never a layer (SEC-03)

**What:** A new launcher subcommand (`harnessed auth snyk` / `harnessed auth socket`) that runs the vendor CLI's own auth inside a `--rm` tools container with the host config dir bind-mounted **rw**. The token persists to the host filesystem (`~/.config/configstore/snyk.json` for snyk; Socket's config dir for `socket login`); `--rm` guarantees nothing is committed to an image.

**snyk** — non-interactive: `snyk config set api=<token>` (writes `~/.config/configstore/snyk.json`). The launcher can accept the token from stdin / an arg, OR run interactive `snyk auth` (browser flow) when the operator is at a TTY. `[CITED: docs.snyk.io/snyk-cli/commands/config — "a JSON file located at $XDG_CONFIG_HOME or ~/.config followed by configstore/snyk.json"]`
**socket** — `socket login` is interactive (prompts for the API token, stores locally). For non-interactive, write `SOCKET_SECURITY_API_KEY` to the shell/profile, or pre-create the socket config.

**Dispatch shape (mirrors `svc`/`install` in the launcher):**
```bash
# harnessed launcher
auth)
    shift
    AUTH_TOOL="${1:-}"; shift
    case "$AUTH_TOOL" in
        snyk|socket) ;;
        *) print_error "auth requires snyk|socket"; usage; exit 1 ;;
    esac
    . "$HARNESSED_DIR/lib/harnessed-secrets.sh"
    auth_scanner "$AUTH_TOOL"   # runs the tools container with ~/.config rw-mounted
    exit 0
    ;;
```

**Anti-pattern:** `podman commit` after auth (creates a layer with the token — the exact exfiltration risk); writing the token into the repo or the profile; leaving `OP_SERVICE_ACCOUNT_TOKEN` in a long-lived shell env (CLAUDE.md pitfall).

### Pattern 4 — Nightly re-scan: systemd user timer + `harnessed rescan`, online osv-scanner (SEC-04)

**What:** Ship two static unit files in `systemd/` for the operator to copy (or a `harnessed timer enable` subcommand to install them):

```ini
# ~/.config/systemd/user/harnessed-rescan.timer
[Unit]
Description=Nightly harnessed image re-scan (post-build CVE catch)

[Timer]
OnCalendar=daily
Persistent=true           # fire a missed run after boot (laptop was off overnight)

[Install]
WantedBy=timers.target
```
```ini
# ~/.config/systemd/user/harnessed-rescan.service
[Unit]
Description=Re-scan installed harnessed images for newly-disclosed CVEs

[Service]
Type=oneshot
ExecStart=%h/.local/bin/harnessed rescan
# Optional: surface findings via notify-send / mail / a health file
```

**`harnessed rescan`** iterates the installed harnessed image set and re-runs `osv-scanner scan image` in **online mode** (a fresh DB — the whole point is CVEs disclosed AFTER build). The build-time gate uses the offline DB (`tools/Dockerfile:37-55`); the nightly MUST use online, so it sees new advisories. Reuse `run_image_scan` from `scan.py` with an online variant (drop `--offline --offline-vulnerabilities`), driven host-side via `podman save` (exactly the Phase-3 image-scan pattern, `lib/harnessed-common.sh:131-137`).

**Two host prerequisites the docs/setup MUST state:**
1. `loginctl enable-linger $USER` — **currently OFF on the host** (verified). Without linger, a user timer does NOT fire when the user is logged out (the nightly-at-3am case). `[CITED: Red Hat podman-auto-update docs + unix.stackexchange.com enable-linger]`
2. Network egress to osv.dev at scan time — the online DB requires it. The build-time offline gate does not; the nightly does. (The instance egress firewall is unrelated — it governs runtime instances, not the host nightly job.)

**Anti-pattern:** a system-level timer (needs root); a resident `harnessed` daemon (violates "no resident host process"); offline mode for the nightly (defeats the purpose); re-scanning ALL podman images (scope to the harnessed-labelled set — `--filter reference='harnessed-*'` + service images).

### Pattern 5 — Documentation: how-tos that reference the design doc, cadence-gated (DOC-01/02/03)

**What:** `docs/harnessed-design.md` (590 lines, §1–§18) is the *why* source of truth and ALREADY EXISTS. The Phase 5 docs are *how-tos* that cross-reference it. Three audiences, three deliverables, mapped to requirements:

| Doc | Requirement | Lands with | Source material (verified present) |
|-----|-------------|------------|-------------------------------------|
| `README.md` (repo root) | DOC-01 | this phase | `docs/harnessed-design.md` (intro/modes/install), `AGENTS.md` (the OLD `container` setup — supersede), the `harnessed` `usage()` block (`:36-68`) |
| `docs/guides/recipe-authoring.md` + `docs/guides/stacks.md` | DOC-02 | this phase | `recipes/time/recipe.yaml`, `recipes/ping/recipe.yaml`, `stacks/tracer-time/stack.yaml`, `stacks/transparent/stack.yaml` (worked examples) |
| `docs/guides/secrets.md` | DOC-03 (⅓) | **with SEC-01** (cadence) | `.env.schema.example`, the §4a agent-socket mount, `varlock.dev/guides/schema` |
| `docs/guides/service-authoring.md` | DOC-03 (⅓) | anytime (Phase 4 surface) | `services/ping/` (Dockerfile + server.py + service.yaml), `lib/harnessed-services.sh` |
| `docs/guides/troubleshooting.md` | DOC-03 (⅓) | phase end | podman socket, first-run build, `~/.claude.json` onboarding, `--fresh`, host-persisted sessions (`lib/harnessed-isolated.sh:105-112`) |

**Cadence rule (CLAUDE.md §17):** the secrets doc lands **with** SEC-01 (a reader of the secrets feature has the doc the moment the feature ships). The plan MUST sequence the secrets doc inside 05-01, not defer it to 05-02.

**Anti-pattern:** duplicating the design doc's *why* in the how-tos (cross-reference instead); documenting behavior that isn't shipped yet (each doc must match shipped behavior — verified by running the example); letting the README and AGENTS.md drift (reconcile: README is the entry point, AGENTS.md either redirects or is folded in).

### Anti-patterns to avoid (consolidated)

- **Baking/committing any resolved secret or scanner token** — into an image layer (`COPY`/`ARG`/`ENV`), the committed `profiles/<stack>/`, or `.claude.json`/`.mcp.json`. Recoverable from history; ship to anyone pulling/cloning. Inject as **env only**; `harnessed auth` persists to host config, never a layer. `[CITED: CLAUDE.md "What NOT to Use" + PITFALLS.md #7]`
- **Prompting during `harnessed build`** — breaks CI + the nightly timer. Warn-and-skip the absent scanner; the credential-free baseline always runs.
- **Leaving `OP_SERVICE_ACCOUNT_TOKEN` in a long-lived shell env** — leaks into any process sharing the env. Prefer the mounted agent socket for interactive; scope the service-account token to the headless invocation only.
- **Resolving secrets on the host** — requires host Node (varlock) / host `op`; breaks "podman-only host." Resolve in a throwaway tools container.
- **SLOP/cross-ecosystem confusion in the legitimacy gate** — slopcheck's default probed PyPI and false-flagged `varlock`/`snyk`/`socket`/`@env-spec/parser` as `[SLOP]`. Always pass `--ecosystem npm` for Node packages (this session's audit did).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Secrets resolution + validation | A custom `.env` parser / `op://` ref resolver | **varlock** + `@varlock/1password-plugin` | Schema-driven, typed, leak-detected, AI-safe; the `op()` shorthand is the plugin's job. (SEC-01) |
| 1Password ref resolution | A custom `op read` wrapper / token manager | **`op`** (1Password CLI) + the mounted agent socket (app-auth) | The official CLI; the agent socket is already mounted. (SEC-01) |
| npm/pnpm vulnerability matching | A custom advisory fetcher / CVSS recompute | **snyk `test --severity-threshold=high`** (native threshold) + **osv-scanner** (the baseline) | snyk HAS a native severity flag; osv-scanner covers the credential-free baseline. (SEC-02) |
| Supply-chain behavioral analysis | A custom telemetry/telemetry scorer | **Socket.dev `socket scan create`** | Socket's whole product; don't rebuild it. (SEC-02) |
| Scanner-token persistence | A custom token store / secrets file | **`snyk config set api=`** (`~/.config/configstore/snyk.json`) / **`socket login`** | The vendor CLIs' own persistence; `harnessed auth` just drives them. (SEC-03) |
| Nightly scheduling | A custom daemon / cron reimplementation / sleep loop | **systemd user timer** (`OnCalendar=daily` + `Persistent=true`) | The rootless podman-native cron; lingers correctly with `enable-linger`. (SEC-04) |
| Post-build CVE re-scan | A custom "what's new since build" differ | **osv-scanner `scan image` (online)** against the installed images | osv-scanner already does the matching; online mode sees new advisories. (SEC-04) |
| Documentation rendering/hosting | A custom static-site generator | Markdown in `docs/` + `README.md` (the repo's existing convention) | The repo already ships `docs/harnessed-design.md`; match it. (DOC-01..03) |

**Key insight:** Phase 5 is almost entirely **integration + wiring** of mature tools (varlock, op, snyk, socket, systemd timers). The only genuinely custom code is (a) the launcher's opt-in detect-and-resolve branch (SEC-01), (b) the env-gated snyk/socket invokers + the snyk-exit-code gate (SEC-02), (c) the `auth`/`rescan` subcommand dispatch (SEC-03/04), and (d) the docs themselves — all small, all testable through the running build/launch.

## Common Pitfalls

### Pitfall 1 — Stale `@varlock/1password-plugin` pin (0.3.2 vs 1.2.0)
**What goes wrong:** The shipped `.env.schema.example` pins `@plugin(@varlock/1password-plugin@0.3.2)`. The current npm release is **1.2.0** (verified) — a 0.x→1.x **major** bump. Either the old pin resolves to a yanked/unmaintained version, or the `op()`/`@initOp(allowAppAuth=true)` API changed across the major boundary and the example schema no longer parses.
**Why:** The example file was authored against an older plugin line and not bumped.
**How to avoid:** Bump the pin to `@1.2.0` (or latest) AND run `varlock load` against the example schema in the built tools image to confirm it still resolves. Treat the 0.x→1.x jump as a breaking-change risk until verified.
**Warning signs:** `varlock load` errors on the shipped example; `op()` unresolved; `@initOp` decorator ignored.

### Pitfall 2 — Treating snyk exit code 1 as "any finding" (or as a hard error)
**What goes wrong:** Mis-mapping snyk's exit codes breaks the gate. **0** = clean, **1** = vulns-at-the-specified-threshold found (with `--severity-threshold=high`, exit 1 means HIGH+ found — THIS is the fail), **2** = failure (re-run; warn + investigate), **3** = no supported projects detected (warn). Confusing 1 for "scanner error" (→ warn-and-skip a real HIGH) or 2 for "HIGH finding" (→ false abort) both break the contract.
**Why:** snyk's exit-code semantics differ from osv-scanner (exit 1 = any finding, no threshold) and from Unix convention (non-zero = error).
**How to avoid:** With `--severity-threshold=high`: exit **1** ⇒ `ScanError` (HIGH finding, abort the build); exit **2/3** ⇒ warning; exit **0** ⇒ clean. Document this inline in `scan.py`.
**Warning signs:** a known-HIGH dep passes the snyk gate; the build aborts on a "no supported projects" (exit 3) scan.

### Pitfall 3 — snyk's postinstall blocked by pnpm 11 `strictDepBuilds`
**What goes wrong:** The snyk npm package's `postinstall` (`node wrapper_dist/bootstrap.js exec`, verified via `npm view snyk scripts.postinstall`) downloads the platform-specific snyk binary at install time. Phase 3 shipped pnpm 11 with `strictDepBuilds: true` (lifecycle default-deny) + a curated `allowBuilds` map. Without `snyk: true` in `allowBuilds`, `pnpm add -g snyk` **fails** (or installs a non-functional wrapper with no binary).
**Why:** pnpm 11 default-denies all build/postinstall scripts; the snyk wrapper is one of them.
**How to avoid:** Add `snyk: true` to the tools-image `allowBuilds` (a scoped, deliberate exception — the snyk wrapper's behavior is well-known and vendor-documented). Verify with `snyk --version` in the built image. The alternative (the standalone snyk installer) bypasses pnpm policy — not preferred.
**Warning signs:** `snyk: command not found` or `snyk` exits with a wrapper error in the built tools image; `pnpm add -g snyk` warns about ignored build scripts.

### Pitfall 4 — Socket's scan is SERVER-side (network + quota), not a local scan
**What goes wrong:** Treating `socket scan create` like osv-scanner (local, free, offline-capable). Socket uploads the manifest to Socket.dev, costs API quota (`full-scans:create`, 1 unit/scan per the CLI help), and needs network egress. In an air-gapped/firewalled build, it fails; on a busy CI it can rate-limit.
**Why:** Socket's value is its hosted analysis dataset; the CLI is a thin client.
**How to avoid:** The warn-and-skip contract is load-bearing for Socket specifically — absence of `SOCKET_SECURITY_API_KEY` OR a network failure MUST skip gracefully (warning), never abort the build. Consider treating Socket findings as **warnings** (not a hard gate) given the different model; let the plan decide.
**Warning signs:** `harnessed build` hangs on the Socket step (network); CI aborts on a transient Socket API error.

### Pitfall 5 — Nightly timer silently never fires (no linger)
**What goes wrong:** The operator installs the user timer, `systemctl --user enable --now harnessed-rescan.timer` reports success, but the nightly never runs because the user is logged out at 3am and `loginctl enable-linger` was never set. The timer appears healthy and does nothing.
**Why:** user timers only run while a user session is active, UNLESS linger is enabled.
**How to avoid:** The setup/troubleshooting docs MUST state `loginctl enable-linger $USER` as a hard prerequisite (it is currently OFF on the host — verified). `Persistent=true` handles the "laptop was off" case (fires on next boot), but only if linger lets the user manager run at all.
**Warning signs:** `systemctl --user list-timers` shows the timer scheduled but `journalctl --user -u harnessed-rescan.service` has no runs; CVEs disclosed post-build go unnoticed.

### Pitfall 6 — Nightly re-scan using the OFFLINE DB (defeats the purpose)
**What goes wrong:** Copy-pasting the build-time scan invocation (`osv-scanner scan image --offline --offline-vulnerabilities`) into the nightly. The offline DB is the one baked at image-build time, so it only knows about CVEs that existed when the image was built — the nightly sees nothing new.
**Why:** The build-time gate is deliberately offline for determinism; the nightly's whole purpose is to see post-build disclosures.
**How to avoid:** The nightly path runs `osv-scanner scan image` in **online mode** (no `--offline` flags) so it pulls the current osv.dev/deps.dev advisory set. Network egress to osv.dev is a nightly prerequisite (document it).
**Warning signs:** Nightly reports "0 findings" forever even after a widely-disclosed CVE in a baked dep.

### Pitfall 7 — Resolved secret leaks into the committed profile or image layer
**What goes wrong:** Writing the varlock-resolved env into the per-instance `.claude` tree (the copy-on-start dir under `$XDG_STATE_HOME/harnessed/...`), OR into the committed `profiles/<stack>/`, OR passing it as a podman `ARG`/`ENV` that an image-build captures.
**Why:** The assembler/launcher holds the resolved values at launch time; the path of least resistance writes them somewhere durable.
**How to avoid:** Resolved secrets are **runtime env only** — pass via `--env-file` (mode 0600, host-only, unlinked after launch) or `-e` to the pod members. Never write them to any file under the repo, the profile, or `$XDG_STATE_HOME`. `harnessed auth` persists tokens to `~/.config/configstore/` (host config), never an image. `[CITED: PITFALLS.md #7]`
**Warning signs:** a `grep` for the token value finds it in `profiles/` or a committed file; `podman history <image>` shows an `ARG`/`ENV` carrying the token.

### Pitfall 8 — Slopsquatch / cross-ecosystem false negatives in the legitimacy gate
**What goes wrong:** Running `slopcheck install varlock snyk socket` without `--ecosystem npm` makes slopcheck probe **PyPI**, which false-`[SLOP]`-flags all four (they're npm packages). The planner either ignores the (wrong) verdict or wastes time chasing a phantom hallucination.
**Why:** slopcheck's ecosystem auto-detect looks at project files; in a Python-rooted repo it picks PyPI.
**How to avoid:** Always pass `--ecosystem npm` (or the correct ecosystem) when auditing Node packages. This session's audit did; the verdicts are `[OK]`.
**Warning signs:** slopcheck `[SLOP]` for a package you can see on npmjs.com.

## Code Examples

### §1 — Opt-in detection + inertness guarantee (SEC-01, bash)
```bash
# lib/harnessed-secrets.sh (new) — sourced by harnessed_isolated before pod create.
HARNESSED_SCHEMA="${HARNESSED_SCHEMA:-$HOME/.config/harnessed/.env.schema}"

# Emit a mode-0600 --env-file of resolved secrets; echo its path. Empty output ⇒ no schema.
# INERT when ~/.config/harnessed/.env.schema is absent (varlock NEVER invoked).
resolve_secret_env() {
    [ -f "$HARNESSED_SCHEMA" ] || return 0
    local envfile; envfile="$(mktemp -t harnessed-env.XXXX --suffix=.env)"
    chmod 600 "$envfile"
    # Throwaway tools container: schema + op agent socket mounted, resolves via varlock.
    "$CONTAINER_RUNTIME" run --rm --userns=keep-id \
        -v "$HARNESSED_SCHEMA":"$HARNESSED_SCHEMA":ro \
        -v "$HOME/.1password/agent.sock":"$CONTAINER_HOME/.1password/agent.sock" \
        -v "$envfile":"$envfile" \
        -w "$(dirname "$HARNESSED_SCHEMA")" \
        "$HARNESSED_TOOLS_IMAGE" \
        bash -lc "varlock load --format env >> '$envfile'"
    echo "$envfile"   # caller unlinks after launch
}
```
*Source: pattern derived from `lib/harnessed-common.sh::build_stack` (throwaway-tools-container precedent, `:106-108`) + `varlock.dev/reference/cli-commands` (`varlock load --format env`).*

### §2 — Launcher wiring: pass resolved env to the pod members (SEC-01)
```bash
# lib/harnessed-isolated.sh::harnessed_isolated — before the harness/hatago `podman run`.
local secret_env; secret_env="$(resolve_secret_env)"
local env_args=()
[ -n "$secret_env" ] && env_args=( --env-file "$secret_env" )
# ... later, on each member:
"$CONTAINER_RUNTIME" run -d --pod "$pod" "${env_args[@]}" ... "$harness_image" sleep infinity
# After the interactive attach returns:
[ -n "$secret_env" ] && rm -f "$secret_env"
```

### §3 — snyk invoker, env-gated, native severity (SEC-02)
```python
# tools/harnessed/scan.py — mirrors _scan_source_osv / _audit_pip.
import os

def _scan_snyk(target: Path, highs: list[str], warnings: list[str]) -> None:
    """snyk test --severity-threshold=high. Skipped (warning) if no SNYK_TOKEN.
    snyk's exit 1 with --severity-threshold=high ⇒ HIGH+ found (the gate). 2/3 ⇒ warn."""
    if not os.environ.get("SNYK_TOKEN"):
        warnings.append("snyk skipped (no SNYK_TOKEN) — credential-free baseline remains the gate")
        return
    # snyk reads SNYK_TOKEN from env; --severity-threshold=high ⇒ exit 1 ONLY for HIGH+.
    proc = _run(["snyk", "test", "--severity-threshold=high", "--json", "--file", str(target / "package.json")])
    if proc.returncode == 1:
        data = _parse_json(proc.stdout) or {}
        highs.extend(_snyk_high_ids(data))    # abort the build
    elif proc.returncode in (2, 3):
        warnings.append(f"snyk: exit {proc.returncode} for {target.name} (investigate)")
    # returncode 0 ⇒ clean (no high+ findings)
```
*Source: `docs.snyk.io/snyk-cli/commands/test` (exit codes + `--severity-threshold`).*

### §4 — Socket invoker, env-gated, server-side (SEC-02)
```python
def _scan_socket(target: Path, warnings: list[str]) -> None:
    """socket scan create (server-side). Skipped (warning) if no token OR network failure.
    Socket's model is policy/alert-based (no CVSS threshold) → findings are warnings here."""
    if not (os.environ.get("SOCKET_SECURITY_API_KEY") or os.environ.get("SOCKET_SECURITY_API_TOKEN")):
        warnings.append("socket skipped (no SOCKET_SECURITY_API_KEY) — optional scanner")
        return
    proc = _run(["socket", "scan", "create", "--json", str(target)])
    if proc.returncode != 0:
        warnings.append(f"socket: non-zero exit {proc.returncode} (network/quota?) — skipped")
        return
    # Findings rendered as warnings (the plan may elect a fail-on policy).
    warnings.extend(_socket_alerts(_parse_json(proc.stdout) or {}))
```
*Source: `docs.socket.dev/docs/socket-cli` + live `socket scan create --help` (env-var probe confirmed BOTH `SOCKET_SECURITY_API_KEY` and `SOCKET_SECURITY_API_TOKEN` accepted).*

### §5 — `harnessed auth snyk` dispatch + tools-container auth (SEC-03)
```bash
# lib/harnessed-secrets.sh
auth_scanner() {
    local tool="$1"
    case "$tool" in
        snyk)
            # Interactive at a TTY: snyk auth (browser). Non-interactive: snyk config set api=.
            "$CONTAINER_RUNTIME" run --rm -it --userns=keep-id \
                -v "$HOME/.config":"$CONTAINER_HOME/.config":rw \
                "$HARNESSED_TOOLS_IMAGE" snyk auth
            ;;
        socket)
            "$CONTAINER_RUNTIME" run --rm -it --userns=keep-id \
                -v "$HOME/.config":"$CONTAINER_HOME/.config":rw \
                "$HARNESSED_TOOLS_IMAGE" socket login
            ;;
    esac
    # --rm ⇒ nothing committed to an image; token lives in ~/.config/configstore (snyk) / socket config.
}
```
*Source: `docs.snyk.io/snyk-cli/commands/config` (configstore path) + `docs.socket.dev/docs/socket-cli` (`socket login`); dispatch shape mirrors `harnessed` launcher `svc`/`install` blocks (`:102-176`).*

### §6 — systemd user timer + `harnessed rescan` (SEC-04)
```bash
# harnessed launcher — new dispatch block (parallel to svc/install).
rescan)
    shift
    . "$HARNESSED_DIR/lib/harnessed-cli.sh"   # or a dedicated rescan helper
    # Iterate the installed harnessed image set; re-scan ONLINE (fresh DB for post-build CVEs).
    harnessed_rescan_images
    exit 0
    ;;

# lib/harnessed-cli.sh (or common.sh) — reuse Phase-3 run_image_scan in ONLINE mode.
harnessed_rescan_images() {
    local img tar rc=0
    for img in $("$CONTAINER_RUNTIME" images --filter reference='harnessed-*' \
                 --format '{{.Repository}}:{{.Tag}}'); do
        tar="$(mktemp --suffix=.tar)"
        "$CONTAINER_RUNTIME" save "$img" -o "$tar"
        "$CONTAINER_RUNTIME" run --rm -v "$tar":"$tar":ro "$HARNESSED_TOOLS_IMAGE" \
            scan-image-online "$tar" || rc=$?
        rm -f "$tar"
        # rc≠0 ⇒ a newly-disclosed HIGH finding on an installed image → surface/alert.
    done
    return "$rc"
}
```
*Source: Red Hat `podman-auto-update.timer` (`OnCalendar=daily` + `Persistent=true`) + ArchWiki Systemd/Timers; image-scan pattern from `lib/harnessed-common.sh:131-137`.*

## State of the Art

| Old (design doc / milestone STACK.md, 2026-06-14) | Current (verified 2026-06-18) | Impact |
|---|---|---|
| `.env.schema.example` pins `@varlock/1password-plugin@0.3.2` | Current npm release is **1.2.0** (0.x→1.x major). | Bump the pin; verify `op()`/`@initOp` API stability across the major bump (Pitfall 1, A4). |
| Design doc §7 names the Socket env var `SOCKET_SECURITY_API_KEY` | The Socket CLI accepts **BOTH** `SOCKET_SECURITY_API_KEY` and `SOCKET_SECURITY_API_TOKEN` (verified live — both produce `token: … (env)`). | No correction needed — the design-doc name works. The docs should mention both for discoverability. |
| Design doc §16 `[INFERENCE — verify]` 1Password in-container resolution (agent socket vs service account) | **Verified:** the agent socket (app-auth, `allowAppAuth`) is the default and is ALREADY mounted (`lib/harnessed-mounts.sh:23-27`); `OP_SERVICE_ACCOUNT_TOKEN` is the headless fallback (precedence: `OP_CONNECT_*` > `OP_SERVICE_ACCOUNT_TOKEN` > agent). | The §16 inference is RESOLVED. Resolution reuses the existing mount; no new mount needed. |
| osv-scanner `scan` has no severity threshold (Phase 3) | snyk `test` HAS `--severity-threshold` natively; Socket has no CVSS threshold (policy-based). | The snyk gate is simpler than osv-scanner's (exit code, not JSON-over-Python); Socket is warnings-only. (SEC-02) |
| "nightly-updates trick" (design §7) — synthesize `package.json` from `pnpm ls`/`npm ls -g` for manifest-less globals | Still valid; snyk needs a manifest, osv-scanner's image scan covers the baked case. | For snyk on the baked hatago image, prefer image/manifest synthesis over a raw source scan. |

**Deprecated/outdated to correct at execution:**
- The `.env.schema.example` plugin pin (0.3.2 → bump to 1.x).
- Any doc implying `op(op://…)` works without the `@varlock/1password-plugin` (it doesn't — the plugin provides `op()`; the no-plugin alternative is `exec(`op read "op://…"`)`).

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | The cleanest home for varlock resolution is a **throwaway `harnessed-tools` invocation** that emits resolved env the host launcher re-injects (preserving "podman-only host"). | Arch Pattern 1 / Open Q 1 | If the planner prefers host-side resolution (requires host Node) or baking resolved values (forbidden), the wiring differs. The constraint set rules out both, but the exact throwaway-container shape is a design choice. |
| A2 | snyk exit code 1 with `--severity-threshold=high` means HIGH+ found (the fail gate); 2/3 are non-clean non-findings. | Pattern 2 / Pitfall 2 / Code §3 | If snyk's threshold semantics differ (e.g. 1 = any finding regardless of threshold), the gate logic changes. Verified against `docs.snyk.io/snyk-cli/commands/test` but not yet against a live HIGH finding during execution. |
| A3 | Socket findings are best treated as **warnings** (not a hard gate), given the policy/alert model + server-side cost. | Pattern 2 / Pitfall 4 | If the project wants Socket as a hard gate, the invoker raises instead of warns. The warn-and-skip-on-no-token contract is the non-negotiable part; the fail-on-finding policy is a planner choice. |
| A4 | `@varlock/1password-plugin` 1.2.0 preserves the `op()` + `@initOp(allowAppAuth=true)` API the shipped `.env.schema.example` depends on. | Standard Stack / Pitfall 1 | If the 0.x→1.x major bump broke the API, the example schema must be rewritten (and possibly the resolver function changes). Verify by running `varlock load` on the example in the built image. |
| A5 | The `harnessed-tools` image should gain a Node layer (via mise, the base-image precedent) to host varlock/snyk/socket. | Open Q 2 | If the planner keeps the tools image Node-free, varlock/snyk/socket must run in a DIFFERENT image (a Node sidecar) or on the host (forbidden). The Node-layer choice is the simplest path but adds image build time. |
| A6 | The nightly re-scan's scope is the harnessed-labelled image set (`harnessed-*` + service images), not ALL podman images. | Pattern 4 | If the operator wants a broader scope (e.g. all images in a pod), the iteration filter changes. Scope to harnessed images to keep the nightly cheap + relevant. |
| A7 | `socket scan create` requires network egress to Socket.dev at build/scan time (server-side). | Pitfall 4 / Environment | If the build env is air-gapped, Socket always warns-and-skips (acceptable per the contract); document the egress requirement. |

## Open Questions (RESOLVED)

1. **Where does varlock resolution execute — and how does the resolved env reach the pod?**
   - Known: varlock is a Node CLI; the host must stay podman-only; resolved secrets are env-only.
   - Recommendation (A1): a throwaway `harnessed-tools` invocation runs `varlock load --format env`, the host captures stdout into a mode-0600 `--env-file`, passes it to the pod members, unlinks after launch. Detect is a bash `[[ -f ~/.config/harnessed/.env.schema ]]` — inert when absent.
   - The planner locks the exact shape (subprocess capture vs a Python helper in the tools image vs a dedicated `harnessed secrets resolve` subcommand).
   - ✅ **RESOLVED (plan 05-02):** bash `resolve_secret_env` in `lib/harnessed-secrets.sh` — throwaway tools container runs `varlock load --format env` (dotenv, NOT shell — podman `--env-file` compatible), host captures into a mode-0600 `--env-file`, passes to pod members. The container exports `-e HOME=$CONTAINER_HOME` so the `tools` user (UID 1000) resolves the agent socket at the mounted path. Also wired into `build_stack` so the build scan step receives resolved tokens.

2. **Does `harnessed-tools` gain a Node layer, or do varlock/snyk/socket live in a separate image?**
   - Known: `tools/Dockerfile` is `python:3.13-slim` with no Node today (`:13`).
   - Recommendation (A5): add `mise use -g node@24` (the `base/Dockerfile.harnessed-base` precedent) + `pnpm add -g varlock @varlock/1password-plugin snyk socket` to the tools image. One image, one place for all build-time tools.
   - Alternative: a `harnessed-scanners` sidecar image. More moving parts; not preferred.
   - ✅ **RESOLVED (plan 05-01):** add `mise use -g node@24 pnpm@11` to `tools/Dockerfile` (the base-image precedent). One image for all build-time tools.

3. **snyk under pnpm 11: `allowBuilds: snyk` vs standalone installer?**
   - Known: snyk's postinstall downloads the binary; `strictDepBuilds` blocks it (Pitfall 3).
   - Recommendation: `allowBuilds: snyk: true` in the tools-image pnpm config (scoped, deliberate, vendor-documented behavior).
   - Alternative: the Snyk standalone installer bypasses pnpm policy — rejected.
   - ✅ **RESOLVED (plan 05-01):** `allowBuilds: { snyk: true }` in a new project-scoped `tools/pnpm-workspace.yaml` (pnpm v11 reads it here, not from the global config). Empirical verification required at the checkpoint.

4. **Is the snyk gate `--fail-on=upgradable` (only fixable) or any HIGH?**
   - Known: `--severity-threshold=high` + optional `--fail-on=all|upgradable|patchable`.
   - Recommendation: `--severity-threshold=high` alone (any HIGH fails), matching the osv-scanner/pip-audit posture. `--fail-on=upgradable` is less strict; the plan decides.
   - ✅ **RESOLVED (plan 05-01):** `--severity-threshold=high` alone (any HIGH fails), matching the osv-scanner/pip-audit posture. No `--fail-on` flag.

5. **Timer install mechanism: static units copied by hand, or `harnessed timer enable|disable`?**
   - Known: either works; the units live in `~/.config/systemd/user/`.
   - Recommendation: ship static units in `systemd/` + document the copy + `loginctl enable-linger`. Optionally add `harnessed timer enable` as a convenience.
   - ✅ **RESOLVED (plan 05-03):** ship static `systemd/harnessed-rescan.{timer,service}` units + a `harnessed rescan` subcommand (no `timer enable` subcommand — the operator copies the units manually, per the lighter default).

## Environment Availability

| Dependency | Required by | Available (host) | In-image plan | Fallback |
|------------|-------------|------------------|---------------|----------|
| podman/docker | build + image scan + rescan | ✓ podman 5.8.3 (no docker — expected) | — | — |
| `op` (1Password CLI) | SEC-01 (resolve `op://` refs) | ✓ 2.34.1 (host) | bake into tools image (apt, mirrors base) | `OP_SERVICE_ACCOUNT_TOKEN` (headless) |
| 1Password agent socket | SEC-01 app-auth (interactive) | ✓ `~/.1password/agent.sock` (verified) | already mounted (`lib/harnessed-mounts.sh:23-27`) | service-account token |
| varlock + plugin | SEC-01 | ✓ 1.7.0 (host) — not required on host | `pnpm add -g varlock@1.7.1 @varlock/1password-plugin@1.2.0` in tools image | — |
| snyk CLI | SEC-02/03 | ✓ 1.1305.1 (host) | `pnpm add -g snyk@1.1305.1` + `allowBuilds: snyk` (Pitfall 3) | warn-and-skip if no token |
| socket CLI | SEC-02/03 | ✓ 1.1.102 (host) | `pnpm add -g socket@1.1.122` in tools image | warn-and-skip if no token |
| Node ≥ 20 | varlock/snyk/socket runtime | ✓ v24.16.0 (host) — not required on host | add Node layer to tools image (mise) | — |
| systemd user units | SEC-04 (nightly timer) | ✓ systemctl 260 (host) | — (units live in `~/.config/systemd/user/`) | cron (legacy; not preferred) |
| `loginctl enable-linger` | SEC-04 (timer fires while logged out) | ✗ **OFF** on the host (verified) | — (host prerequisite) | none — MUST be enabled for the nightly to fire; document in setup/troubleshooting |
| osv.dev / deps.dev network | SEC-04 online nightly re-scan | ✓ (host has network) | online mode in the nightly | offline DB (defeats the purpose — Pitfall 6) |
| Socket.dev network | SEC-02 socket scan | ✓ (host has network) | server-side scan | warn-and-skip on network failure (Pitfall 4) |

**Missing with no fallback:**
- `loginctl enable-linger $USER` — without it the nightly timer does not fire while logged out. This is a **documented host setup step**, not a blocker (the feature ships; the operator runs the one-time command).

**Missing with fallback:**
- None of the CLIs are required on the host (all bake into the tools image); the host stays podman-only.

## Security Domain

> `security_enforcement: true` (`.planning/config.json`), ASVS L1, block-on: high. This phase IS the security perimeter — secrets handling, scanner-token persistence, and the post-build CVE catch. The security lens is central.

### Applicable ASVS categories

| ASVS Category | Applies | Standard control |
|---------------|---------|------------------|
| V2 Authentication | yes (scanner tokens) | Tokens are bearer secrets; persist to host config (`~/.config/configstore/snyk.json`, mode 0600 by `configstore`), inject as env only. `harnessed auth` drives the vendor CLI's own auth. Never bake. |
| V3 Session Management | no | No session surface (tokens are long-lived API keys, not sessions). |
| V4 Access Control | yes | The opt-in `.env.schema` is the access-control switch: no schema ⇒ no secrets resolution. Resolved env is scoped to the pod members only. |
| V5 Input Validation / V1 Sanitization | yes | varlock validates the `.env.schema` (typed, `@required`, leak detection) before resolution — input validation on the secrets source. Scanner-token presence is an env-presence check (no prompt). |
| V6 Cryptography / integrity | yes | `op` (1Password CLI) handles secret transport over the agent socket / service-account token; varlock's `@sensitive` redaction. Scanner CLIs are pinned + checksum-verified at image build (Phase 3 precedent). |
| V7 Logging / V9 Communications | yes | Resolved secrets NEVER logged — varlock's `--redact-stdout` / `@redactLogs`; the launcher's temp env-file is mode 0600 + unlinked. |
| V10 Malicious Code / Supply Chain | yes (core, layered on Phase 3) | Token-gated snyk + Socket ADD depth on top of the credential-free osv-scanner + pip-audit baseline; the nightly re-scan (SEC-04) catches post-build CVEs. |
| V14 Configuration | yes | Inert-by-default opt-in; managed pnpm config governs scanner installs; `loginctl enable-linger` documented. |

### Known threat patterns for this stack

| Pattern | STRIDE | Mitigation (this phase) |
|---------|--------|--------------------------|
| Resolved secret baked into image/profile | Information Disclosure / Tampering | Env-only injection (`--env-file`, mode 0600, unlinked); `harnessed auth` persists to host config, never a layer; the assembler never sees resolved values. (Pitfall 7) |
| Scanner token in a long-lived shell env | Information Disclosure | `SNYK_TOKEN`/`SOCKET_SECURITY_API_KEY` passed per-invocation; `OP_SERVICE_ACCOUNT_TOKEN` scoped narrowly to headless; prefer the agent socket. |
| Non-interactive build broken by a scanner prompt | Denial of Service (build) | Warn-and-skip on absent token; the credential-free baseline always runs. (SEC-02 contract) |
| Post-build CVE goes unnoticed | Tampering (time-of-check/time-of-use) | Nightly ONLINE osv-scanner re-scan of installed images (SEC-04); `Persistent=true` catches missed runs. |
| Slopsquatched scanner CLI / varlock plugin | Tampering / Elevation | pnpm `minimumReleaseAge` + `strictDepBuilds` (Phase 3) govern the install; `allowBuilds: snyk` is a deliberate exception; slopcheck `[OK]` for all packages; pin + checksum versions. |
| Malicious `op://` ref / schema injection | Tampering / Elevation | The `.env.schema` is operator-owned (`~/.config/harnessed/`), not recipe-authored; varlock validates it; recipe/stack manifests do NOT carry secret refs (SEC-05 per-stack overrides are v2). |
| Scanner CLI hang stalls `harnessed build` | Denial of Service | `_TIMEOUT` (existing, `scan.py:34`) bounds every scanner invocation; Socket network failure ⇒ warn-and-skip (Pitfall 4). |
| Timer silently never fires (no linger) | (operational gap → Tampering window) | Document `loginctl enable-linger`; `Persistent=true`; troubleshooting doc lists the diagnostic (`systemctl --user list-timers` + journal). |

## Project Constraints (from CLAUDE.md)

The planner MUST verify compliance with these (authority ≡ locked decisions):
1. **Secrets are env-only, never baked/committed** — varlock-resolved values and scanner tokens reach the pod/tools as ENV ONLY (`-e`/`--env-file`); never `COPY`/`ARG`/`ENV` into an image, never written to `profiles/`, `.claude.json`, or `.mcp.json`. `[CITED: CLAUDE.md Constraints + "What NOT to Use"]`
2. **varlock + 1Password are opt-in** — inert unless `~/.config/harnessed/.env.schema` exists; the no-secrets path is today's behavior, unchanged. `[CITED: CLAUDE.md Constraints + design §16]`
3. **pnpm everywhere, no npm/npx** — snyk/socket/varlock install via `pnpm add -g`; `npx`→`pnpm dlx`. Recipe validation (Phase 3) still enforces. `[CITED: CLAUDE.md Constraints]`
4. **Host deps = podman/docker only** — varlock/`op`/snyk/socket/Node live in the `harnessed-tools` image; nothing new on the host (the host already has them, but the design does not REQUIRE that). `[CITED: CLAUDE.md Constraints + design §15]`
5. **`harnessed-tools` emits files only** — scanner invocation during `harnessed build` already runs inside the tools image over the mounted build dir (Phase 3); Phase 5 reuses that, no new daemon wiring. Image scanning (SEC-04 nightly) is host-driven (`podman save` → tools), mirroring `harnessed test`. `[CITED: design §15, D-12]`
6. **Non-interactive / reproducible build** — no prompts; warn-and-skip absent scanners; pin every version; the nightly uses online mode by design. `[CITED: CLAUDE.md Constraints + design §7]`
7. **1Password resolution preference** — mounted agent socket (app-auth) for interactive; `OP_SERVICE_ACCOUNT_TOKEN` for headless only, narrowly scoped. `[CITED: CLAUDE.md "What NOT to Use"]`
8. **Docs land with the feature** — the secrets doc lands WITH SEC-01; each doc matches shipped behavior. `[CITED: design §17 + CLAUDE.md Constraints]`
9. **Bash launchers under `set -euo pipefail`; fallible probes use `|| true`** — the new `auth`/`rescan`/secrets-resolution paths must capture non-zero exits safely (the Phase-3 `a963a69` precedent). `[CITED: Phase 3 RESEARCH constraint 9]`
10. **Integration-only testing** — prove SEC-01..04 through the running build/launch/rescan (the `tools/uat/` harness, AAA pattern, is the established vehicle); no assembler unit tests. `[CITED: design §18 + Phase 4 UAT precedent]`

## Validation Architecture

> `workflow.nyquist_validation: false` in `.planning/config.json` → **section SKIPPED** per the agent's Step 4 skip rule. Testing guidance for the planner is captured in Code Examples + the established `tools/uat/` harness (Phase 4 precedent: pure-bash AAA, `assert_exit_zero`/`assert_match`/`assert_contains`).

**Validation approach (integration-only, per CLAUDE.md §18):**
- SEC-01: a fixture schema (`tools/test-fixtures/.env.schema`) with a test `op://` ref (or a stub resolver) → assert resolved env reaches a `--fresh` instance's env (via `podman exec env`) and is NOT in the committed profile or image history. Assert NO schema ⇒ varlock never invoked (grep the launch trace).
- SEC-02: `harnessed build` with `SNYK_TOKEN` unset ⇒ build green + "snyk skipped" warning; with a dummy token ⇒ snyk invoked (or warn-on-auth-failure); the existing vuln-stack fixture still aborts on the osv-scanner HIGH (baseline unchanged).
- SEC-03: `harnessed auth snyk` writes `~/.config/configstore/snyk.json` (assert exists + mode); assert NO image layer carries it (`podman history`).
- SEC-04: install the timer units + `harnessed rescan` ⇒ iterates the harnessed image set; a fixture image with a known post-build advisory surfaces (online) OR the offline-DB equivalence is documented.
- DOC-01..03: each doc's worked example runs as-documented (copy-paste runnable).

## Sources

### Primary (HIGH confidence — read live 2026-06-18)
- **varlock.dev/guides/schema** — `.env.schema` syntax, `@env-spec` DSL, item/root decorators, resolver functions, `exec(`op read "op://…"`)` form, ref expansion.
- **varlock.dev/reference/cli-commands** — `varlock run -- <cmd>` (injection), `varlock load --format shell|json|env` (resolve-and-print), `varlock init`/`varlock init --agent`, `--path`/`-p`.
- **varlock.dev/env-spec/overview** — the @env-spec DSL (decorator-style comments, the underlying spec).
- **docs.snyk.io/snyk-cli/commands/test** — exit codes (0 clean / 1 vulns-at-threshold / 2 failure / 3 no-projects), `--severity-threshold=<low|medium|high|critical>`, `--fail-on=`, `--json`, `--file=`.
- **docs.snyk.io/snyk-cli/commands/config** — config file at `$XDG_CONFIG_HOME` or `~/.config` + `configstore/snyk.json`; `snyk config set api=<token>`; `SNYK_TOKEN` env override.
- **docs.socket.dev/docs/socket-cli** — `socket scan create` (server-side), `socket login`/`socket ci`, `--json`/`--markdown`, `SOCKET_SECURITY_API_TOKEN` env var.
- **Live host CLI probes (this session):** `socket --help` confirmed BOTH `SOCKET_SECURITY_API_KEY` and `SOCKET_SECURITY_API_TOKEN` accepted (each set → `token: … (env)`); `op --version` → 2.34.1; `~/.1password/agent.sock` exists; `~/.config/configstore/snyk.json` exists (1010 bytes); `loginctl` linger = OFF; `systemctl --user podman.socket` = inactive.
- **developer.1password.com/docs/service-accounts/use-with-1password-cli/** — `OP_SERVICE_ACCOUNT_TOKEN` bearer-token auth, precedence (`OP_CONNECT_*` > `OP_SERVICE_ACCOUNT_TOKEN` > agent).
- **Red Hat "Porting containers to systemd using Podman"** (docs.redhat.com) — the canonical `podman-auto-update.timer` (`OnCalendar=daily`, `Persistent=true`, `WantedBy=timers.target`) user-timer pattern.
- **ArchWiki Systemd/Timers** — `OnCalendar=` realtime timer semantics.
- **npm registry (`npm view`):** `varlock` 1.7.1, `@varlock/1password-plugin` 1.2.0, `@env-spec/parser` 0.4.1, `snyk` 1.1305.1 (+ `scripts.postinstall: node wrapper_dist/bootstrap.js exec`), `socket` 1.1.122 (+ repository github.com/SocketDev/socket-cli). All `slopcheck install --ecosystem npm` → `[OK]`.

### Secondary (MEDIUM — corroboration / community)
- **1Password Community discussions** (167032, 26375) — in-container `op`: agent-socket app-auth vs `OP_SERVICE_ACCOUNT_TOKEN`; the "token in long-lived env" caution (matches CLAUDE.md pitfall).
- **schalkneethling.com "Stop Storing Secrets on Disk"** — the varlock + 1Password `op(op://Vault/Item/field)` pattern (the plugin shorthand).
- **unix.stackexchange.com** (enable-linger best-practices) — `loginctl enable-linger $USER` for user-timer persistence.

### In-repo ground truth (HIGH — read this session)
- `.env.schema.example` (repo root) — the shipped opt-in template; pins `@varlock/1password-plugin@0.3.2` (STALE — Pitfall 1).
- `docs/harnessed-design.md` §7 (scanner credentials), §16 (secrets), §17 (docs), §15 (emit-only).
- `docs/codebase/INTEGRATIONS.md:135-186` — the current (pre-Phase-5) scanner + 1Password state ("varlock/op not yet baked"; "launcher has zero varlock references today").
- `lib/harnessed-mounts.sh:23-27` — the 1Password agent socket mount (the `op` app-auth transport).
- `lib/harnessed-common.sh:94-144` — `build_stack` (the SEC-02 injection point + the throwaway-tools-container precedent).
- `lib/harnessed-isolated.sh:31-199` — the isolated launcher (the SEC-01 wiring point, before pod member creation).
- `tools/harnessed/scan.py` (full) — the Phase-3 scan gate (the SEC-02 extension point; `_scan_source_osv`/`_audit_pip`/`run_image_scan` structure).
- `tools/harnessed/cli.py:28-105` — the `_build_parser` subcommand precedent.
- `harnessed:36-271` — the launcher dispatch (`svc`/`install`/`new`) the `auth`/`rescan` subcommands mirror.
- `tools/uat/uat-common.sh` — the established UAT harness (AAA, pure-bash assertions).
- `tools/test-fixtures/{vuln,low,npm,svc}-stack` — the fixture precedent for SEC-02 tests.

## Metadata

**Confidence breakdown:**
- Standard stack (varlock / op / snyk / socket / systemd-timer): **HIGH** — all verified against official docs + live CLIs + npm registry + slopcheck on 2026-06-18. Versions confirmed.
- Architecture (where each requirement hooks in): **HIGH on constraints** (emit-only, podman-only, env-only — all read from actual code); **MEDIUM on the two open design forks** (varlock resolution wiring A1; snyk-under-pnpm install Pitfall 3) the planner locks.
- Pitfalls: **HIGH** — grounded in snyk/socket/osv-scanner docs, pnpm 11 behavior (Phase 3), the systemd-timer linger requirement (probed live), and the stale-plugin-pin finding (verified against npm).

**Research date:** 2026-06-18
**Valid until:** ~2026-07-18 for the npm packages (fast-moving — re-check `npm view` at execution); stable for the systemd-timer, op agent-socket, and repo-integration findings.
