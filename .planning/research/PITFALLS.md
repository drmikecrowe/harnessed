# Pitfalls Research

**Domain:** Rootless-container AI-harness orchestrator (host-native podman pods, MCP hub, pnpm supply-chain gate, Claude-canonical config assembly)
**Researched:** 2026-06-14
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: `~/.claude.json` rw-bind-mount races and corrupts host state

**What goes wrong:**
Binding the host `~/.claude.json` read-write into the instance lets two processes (host Claude + container Claude) rewrite the same whole-file blob concurrently → lost writes, truncated/corrupt JSON, and container-only state (project entries, MCP servers, caches) leaking back into the host's personal config. The existence of `~/.claude/backups/*.backup.*` is direct evidence Claude rewrites this file aggressively.

**Why it happens:**
`~/.claude.json` is a single ~450 KB whole-file document (not a directory of per-key files), rewritten on nearly every interaction. A bind mount gives both writers the same inode; last-writer-wins clobbers the other. Developers assume the differing in-container project path keeps them isolated, but path-keying only spares the `projects` subtree — the top-level fields and the full-file rewrite still collide.

**How to avoid:**
- **Never** rw-bind-mount `~/.claude.json`. In `transparent` mode, seed a **writable per-instance copy at start** (copy-on-start) so the container reads host state once and writes only its own copy.
- Prefer **`CLAUDE_CONFIG_DIR` relocation**: point the instance at a per-instance config dir; Claude then reads/writes `.claude.json` *inside that dir*, fully decoupling container state from the host file. Verified plausible — `CLAUDE_CONFIG_DIR` is the documented relocation knob (`~/.claude` → custom dir; the in-container-wrong-location bug #14313 is fixed by setting it), but historically its scope was muddy (#3833 reported it still creating local `.claude/`). **[INFERENCE — confidence MEDIUM]** Verify empirically that the chosen Claude version writes `.claude.json` (the top-level file, not just the `.claude/` dir) into `CLAUDE_CONFIG_DIR` before relying on it.
- In `isolated` mode the question is moot — you **generate** a stub, never mount the host file (Pitfall 2).

**Warning signs:**
- Host Claude suddenly shows projects/MCP servers it never opened, or its theme/onboarding resets.
- `.claude.json` JSON parse errors; new `*.backup.*` files appearing during container runs.
- Two instances (or instance + host) "fighting" over settings between sessions.

**Phase to address:**
Phase 2 — `transparent` mode port (the safety fix called out in §4b). Settle copy-on-start vs `CLAUDE_CONFIG_DIR` here with an explicit empirical check, since both modes depend on the answer.

---

### Pitfall 2: Onboarding/login stub fields wrong → every isolated launch re-prompts

**What goes wrong:**
The generated minimal `.claude.json` stub omits (or misnames) the fields Claude checks at startup, so the isolated instance drops into the theme picker / onboarding / re-login flow on every launch — fatal for the headless capability test (`claude -p … --output-format json`), which hangs or errors waiting on an interactive prompt.

**Why it happens:**
Onboarding state lives in `.claude.json`, not in the credential file. With auth mounted (`.credentials.json`) but onboarding state absent, Claude assumes a first run. The exact gating field set is version-dependent and undocumented.

**How to avoid:**
- Set **`hasCompletedOnboarding: true`** — corroborated as the primary gate across multiple sources (community headless guides, devcontainer field-notes "a minimal version with two fields is enough to skip onboarding", and the bypass writeups noting that removing/setting it false forces onboarding).
- Add the OAuth identity fields the design lists — `oauthAccount`, `userID` — plus `firstStartTime` and `numStartups` (observed mutating in onboarding-reset bug reports). **[INFERENCE — confidence MEDIUM]** Treat the full set beyond `hasCompletedOnboarding` as unverified until tested.
- **Verify empirically, once, as an acceptance gate:** boot a `--fresh` isolated instance headless and assert zero interactive prompts; pin the working field set and snapshot-test the generated stub so a Claude upgrade that adds a new gate fails loudly.
- Keep `CLAUDE_CODE_OAUTH_TOKEN` as a documented fallback auth path if credential-file mounting regresses.

**Warning signs:**
- Headless run never returns / capability test times out.
- Instance prints "Welcome to Claude Code" / theme selection on launch.
- Works interactively (you click through) but fails in CI.

**Phase to address:**
Phase 3 — `isolated` auth seeding. The stub generator and its empirical no-prompt test are the deliverable; do not mark isolated mode "done" without the headless assertion.

---

### Pitfall 3: Host rootless podman not configured for builds and long-lived pods

**What goes wrong:**
`harnessed` builds and runs everything through the host's rootless podman, but the host was never set up for it: missing/insufficient `subuid`/`subgid` ranges make `podman build`/`podman run` fail with "newuidmap" / "cannot set up namespace" errors; or long-lived shared-service pods (hindsight/openbrain on `harnessed-net`) die after logout/reboot because user lingering was never enabled. Separately, teams reach for *rootful* podman "to make it work," silently granting host-root container control.

**Why it happens:**
Rootless podman needs per-user `subuid`/`subgid` allocations to create user namespaces; without them the very first build fails. User-session services are also torn down when the login session ends unless `loginctl enable-linger <user>` is set — so a service that "worked today" is gone after a reboot. The path of least resistance when either bites is to switch to rootful podman, which runs containers as host root.

**How to avoid:**
- Bootstrap **detects and self-heals**: verify podman is installed and rootless is usable (subuid/subgid present, a trivial `podman info`/build smoke test passes), and recommend `loginctl enable-linger <user>` so long-lived service pods survive logout/reboot.
- Stay **rootless on purpose** and *document the scope honestly*: rootless podman runs everything as *your user* (not host root) — acceptable for a personal dev tool, but state it. Never fall back to rootful podman to dodge a permissions error.
- Fail with an actionable message (the exact `usermod`/`loginctl` line, or "install podman"), never a raw namespace stack trace.

**Warning signs:**
- First build fails with "newuidmap" / "cannot set up namespace" on a fresh machine.
- A shared service works the day it's started, then is gone after a reboot (no lingering).
- Instructions tell users to `sudo` podman — a smell that you've slipped to rootful.

**Phase to address:**
Phase 1 — host bootstrap. The host podman prerequisite check (and the lingering recommendation for services) lands with the first build orchestration.

---

### Pitfall 4: MCP transport mismatch — assuming everything speaks Streamable HTTP

**What goes wrong:**
The pod design points the harness's `.mcp.json` at a single hatago HTTP endpoint, but individual MCP servers vary: some are network-native (Streamable HTTP/SSE), many `npx`/`uvx` servers are **stdio-only**. Wiring a stdio server directly as an HTTP URL (or forgetting to let hatago wrap it) yields a server that never connects; conversely, baking an already-HTTP service as a hatago stdio child double-wraps it.

**Why it happens:**
MCP has multiple transports (stdio, Streamable HTTP, SSE, WebSocket) and the ecosystem is mid-migration. hatago's value is exactly *transport independence* — it can run a stdio child and expose it over HTTP — but the recipe author must declare each server's real transport correctly. The design itself flags this as an open item (§14: "which servers already speak Streamable HTTP vs need hatago's stdio→HTTP wrapping").

**How to avoid:**
- In the recipe schema, make `transport` explicit per server (`stdio` | `http`/`streamable-http` | `sse`); default to `stdio` for `command`-based entries and require a `url`/`service` for network-native ones.
- Light `npx`/`uvx` stdio servers run as **hatago children** (baked into the hatago image, wrapped stdio→HTTP); heavy/stateful services (hindsight = postgres+MCP, likely network-native) are proxied over `harnessed-net` by URL, **not** re-wrapped.
- Hatago serves one endpoint (`hatago serve --http --port <p>` → `http://localhost:<p>/mcp`); the harness `.mcp.json` points only there. Validate at build time that every declared server resolves to exactly one transport path.
- Assert connectivity via hatago's `hatago://servers` resource and/or `claude mcp list` in the capability test, not by trusting config.

**Warning signs:**
- Capability report shows an MCP server "✗ missing / not connected" though the build was green.
- hatago logs "failed to start child" (stdio binary missing) or "connection refused" (treated a stdio server as a URL).
- A server works standalone via `npx` but never appears in the aggregated catalog.

**Phase to address:**
Phase 4 — pod + hatago hub. Per-server transport resolution is the core correctness property of this phase; the capability test is its verification.

---

### Pitfall 5: Plugin/skill/command name collisions across recipes resolved silently

**What goes wrong:**
Two recipes in one stack each ship a `gsd` command or a `docs` skill; assembly fans both into the same harness-native path. Last-wins overwrites one silently, or files interleave, and the instance exposes a capability the author didn't intend — the *exact* failure mode (shared namespace can't hold every experiment) that killed the prior host-merge approach.

**Why it happens:**
The merge happens at build time across independently authored recipes with no global name registry. Without an explicit policy, the filesystem (or a naive copy) decides the winner. The design defers the policy to §14 (fail-fast vs last-wins vs namespacing).

**How to avoid:**
- Adopt **fail-fast** as the default, reusing `sync-plugin-links`' explicit conflict reporting: a colliding skill/command/agent name aborts `harnessed build` with a message naming *both* recipes and the conflicting path — never a silent overwrite.
- Surface conflicts in the capability report (`✗ missing (sync conflict)`) so the user sees *why* something didn't land.
- Reserve namespacing/last-wins as a deliberate, per-stack opt-in (if ever), documented in the stack guide — not the implicit default.

**Warning signs:**
- A stack "works" but a command behaves like a different recipe's version.
- Build output copies N files but the profile contains fewer.
- Capability report lists a skill the manifest didn't declare (or omits one it did).

**Phase to address:**
Phase 5 — build-time assembler (vendor + sync-links + collision policy). Fail-fast and its conflict message are acceptance criteria for the assembler.

---

### Pitfall 6: pnpm rollout via mise mis-tuned — native builds blocked or guard weakened

**What goes wrong:**
Two coupled failures: (a) global tool installs still go through **npm** because mise's npm backend wasn't pointed at pnpm, defeating the pnpm-everywhere supply-chain policy; (b) `minimumReleaseAge` / `onlyBuiltDependencies` mis-tuned — too tight blocks legitimate native builds (postinstall denied, fresh-but-needed release quarantined → red build), too loose reinstates the attack window the policy exists to close.

**Why it happens:**
mise installs node CLIs via its `npm:` backend by default; routing to pnpm requires the `npm.package_manager` setting (`"auto"` uses bun/pnpm if present, or set `"pnpm"` explicitly) — confirmed configurable, plus a third-party `pnpm:` backend exists. Meanwhile pnpm v10 made lifecycle scripts **default-deny** (you must allowlist via `onlyBuiltDependencies`) and v10.16+/v11 ship `minimumReleaseAge` (in **minutes**) as a quarantine window — both are sharp tools that break installs when set blind.

**How to avoid:**
- Set `npm.package_manager = "pnpm"` (or pin pnpm + use the `pnpm:` backend) in `harnessed-base`/mise config so **every** node tool — global, per-recipe, hatago's bundled servers — flows through pnpm. Recipe validation flags any raw `npm`/`npx`.
- Tune the guard explicitly and document it: a `minimumReleaseAge` on the order of **1440–2880 minutes (1–2 days)** is the community sweet spot; ship it as a managed default, not per-user guesswork.
- Maintain a curated **`onlyBuiltDependencies` allowlist** for packages that genuinely need native postinstall (esbuild, sharp, better-sqlite3, etc.); a denied build should produce a clear "add to onlyBuiltDependencies" message, not an opaque failure.
- Update the ported `vendor-plugin`, which currently shells `npm install`, before it lands.

**Warning signs:**
- `pnpm ls`/lockfile shows packages installed via npm, or `~` polluted with npm globals.
- Build fails with "scripts disabled" / missing compiled binary (allowlist too tight).
- A brand-new dependency version errors as "quarantined by minimumReleaseAge" (window vs release timing).
- Conversely: a freshly published package installs instantly (window too loose / not applied).

**Phase to address:**
Phase 5 — assembler + supply-chain policy (pnpm config in `harnessed-base`, recipe validation). Decide the window + allowlist here, per §14.

---

### Pitfall 7: Secrets leaking into image layers or committed profiles

**What goes wrong:**
Claude OAuth creds, scanner tokens (`SNYK_TOKEN`, `SOCKET_SECURITY_API_KEY`), or 1Password-resolved values get `COPY`'d/`ARG`'d into an image, written into the generated `profiles/<name>/` (which is git-committed), or baked into `.claude.json`/`.mcp.json`. Once in a layer or commit they persist in history and ship to anyone pulling the image or cloning the repo.

**Why it happens:**
The assembler both **bakes images** and **commits a profile**, and it has the secrets in hand at build time (to run credentialed scanners, to seed auth). The path of least resistance — write the resolved value where it's needed — lands it in a durable artifact. Docker `ARG`/`ENV` and any file copied into a layer are recoverable from history.

**How to avoid:**
- **Env-only, always.** Auth and scanner/1Password secrets are *referenced from the host and injected as env at launch* — never an image layer, never a repo file (the design's hard rule, §7/§16).
- Credentials mount **read-only at runtime** (`.credentials.json` ro into the instance), never copied into the profile or image.
- Generated `.claude.json` stub carries identity fields but **no token**; `.mcp.json` carries URLs/`*_env` references, not secret values.
- Add a build-time guard: scan the assembled profile + image layers for token-shaped strings and known secret keys; fail the build if found. Keep `.env`/`.credentials.json` in `.gitignore` and the profile generator's deny-list.

**Warning signs:**
- `git log -p profiles/` or `podman history`/`inspect` reveals token-like strings.
- A profile diff contains an `oauthAccount` token, `SNYK_TOKEN`, or `op://`-resolved plaintext.
- The image runs scanners without any env injected (means the token is baked in).

**Phase to address:**
Phase 3 (auth seeding) for credential handling; Phase 5 (assembler/scan gate) for the leak-detection guard. Both must pass before any profile is committed or image published.

---

### Pitfall 8: 1Password in-container resolution assumes the app-auth socket works

**What goes wrong:**
varlock resolves `op(op://Vault/Item/field)` refs by shelling `op`, and the design assumes the **mounted 1Password agent socket** (app-auth, `allowAppAuth`) makes that work inside the tools container. It generally **does not**: `op` inside a container can't use the desktop-app integration, so resolution fails with "No accounts configured for use with 1Password CLI" and every opt-in secret comes back empty — silently degrading scanners/services that needed them.

**Why it happens:**
The 1Password CLI's desktop-app integration is a host-GUI handshake; "the `op` CLI doesn't have support for the native 1Password Desktop app integration via the socket inside containers" (nodejs-security devcontainer guide). The socket can be mounted, but the integration won't authenticate from a sibling container.

**How to avoid:**
- Use a **service-account token** (`OP_SERVICE_ACCOUNT_TOKEN`) for in-container `op` — the headless/container-native story the design itself flags as cleaner (§16 "to verify"). Inject it as env (env-only rule, Pitfall 7), never bake it.
- Keep varlock + `op` **inert unless a schema exists** (opt-in); when present, resolve via the service-account token path. If you *must* support app-auth, resolve on the **host** (in the bootstrap, before entering the tools container) and pass only the resolved env in — but the service-account token is the recommended container path.
- **[INFERENCE — confidence HIGH]** that app-auth-socket-in-container is unreliable; **verify which path your own 1Password plan supports** (service accounts are a paid/Business feature) and document the requirement.

**Warning signs:**
- `op` errors "No accounts configured" / "turn on desktop app integration" from inside the tool.
- Opt-in secrets resolve to empty; credentialed scanners silently skip though a ref was configured.
- Resolution works on the host shell but not when launched through `harnessed`.

**Phase to address:**
Phase 6 — secrets (varlock + 1Password). Pin the service-account-token path and document the 1Password plan prerequisite here.

---

### Pitfall 9: First-run build latency mistaken for a hang

**What goes wrong:**
The first `harnessed` invocation builds the `harnessed-tools` image (python + rich/textual + yq/jq + git + pnpm + scanners + varlock + op) and base/hatago/service images — minutes of work with no harness output. Users `Ctrl-C` thinking it's stuck, leaving a half-built image cache that then errors on retry.

**Why it happens:**
The "only host dep is podman" design pushes *all* tooling into images, so the first build is unavoidably heavy; subsequent runs are cache hits. Without progress feedback, a multi-minute silent build reads as a freeze.

**How to avoid:**
- Stream build progress (rich) with an explicit "first run builds the toolchain, ~N min, later runs are instant" banner.
- **Pin** the tools image and optionally publish a prebuilt one so most users pull instead of build; make `--build` the explicit rebuild path.
- Make builds resumable/idempotent: a canceled build must not poison the cache; detect partial images and rebuild cleanly.

**Warning signs:**
- Issues reporting "harnessed hangs on first run."
- Users running with `Ctrl-C` then hitting "image exists but is broken."
- Cold-start time measured in minutes with no terminal output.

**Phase to address:**
Phase 1 — bootstrap (build orchestration + progress UX). The latency-mitigation banner ships with the first build.

---

### Pitfall 10: Session slug path illegible or polluting the host `~/.claude`

**What goes wrong:**
If the project is mounted at an unstable or opaque in-container path, Claude's per-project slug (derived from the path, e.g. `-home-harnessed-<relpath>`) becomes illegible and *changes between runs*, so host-persisted sessions don't reconnect — continuity breaks. Worse, if `session_state: host` writes into the host's own `~/.claude/projects/`, instance sessions pollute the user's personal Claude history.

**Why it happens:**
Claude keys session state by the project path slug. A path like `/container/$USER` (the old `container.sh` convention) or a hash-y mount target yields a slug that's both ugly and unstable across instances/projects; and the natural place to persist is the host's real `~/.claude`, which co-mingles instance and host history.

**How to avoid:**
- Mount the project at a **stable, legible** in-container path: `/home/harnessed/<relpath>` → slug `-home-harnessed-<relpath>`, deterministic per project (§4b, §14). Verify it doesn't break harness installs that assume a particular `$HOME`.
- Persist `session_state: host` into a **harnessed-owned** dir (e.g. `~/.harnessed/projects/`), *not* the host's `~/.claude/projects/`, so instance sessions stay inspectable but separate (design recommendation, §14). `session_state: volume` opts into throwaway.
- Make the path part of pod identity so the same stack re-attaches the same session for the same project.

**Warning signs:**
- "New" sessions every launch though `persist: true`; history doesn't carry over.
- Host Claude's project list shows container-only projects.
- Slug contains a hash or temp path rather than a readable relpath.

**Phase to address:**
Phase 3 (isolated state/session layout) with the host-scope decision; verify path legibility in the Phase 8 capability/continuity test.

---

### Pitfall 11: Non-interactive build prompts instead of warn-and-skip

**What goes wrong:**
`harnessed build` blocks on an interactive prompt — typically asking for a missing scanner token (snyk/Socket.dev), or worse, accepting a typed token that then risks landing in a repo/layer. Any prompt breaks CI and the nightly re-scan timer, which run headless.

**Why it happens:**
The instinct when a credential is missing is to ask for it. But build must be reproducible and non-interactive, and `osv-scanner` + `pip-audit` are credential-free and form the baseline gate regardless.

**How to avoid:**
- **Missing credentialed scanner → warn and skip that scanner**, never prompt (§7). Credential-free `osv-scanner` + `pip-audit` always run; high-severity findings still fail the build.
- Token setup is a separate, deliberate, **interactive-once** command (`harnessed auth snyk|socket`) that runs the CLI's own `auth` and persists to host config — outside the build path.
- Detect non-TTY/CI context and assert no prompt is ever reachable; the nightly systemd-timer re-scan must run unattended.

**Warning signs:**
- CI/nightly job hangs awaiting input.
- Build asks "enter your Snyk token."
- A token appears in build logs or a committed file.

**Phase to address:**
Phase 5 — supply-chain gate. Warn-and-skip + the separate `auth` command are acceptance criteria; test the build under a no-TTY harness.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| rw-bind-mount `~/.claude.json` instead of copy-on-start/`CLAUDE_CONFIG_DIR` | One less file to manage; "it just works" | Host config corruption + container/host state bleed (Pitfall 1) | **Never** |
| Last-wins on recipe name collisions | Build always "succeeds" | Silent wrong-capability instances; the host-merge failure returns | **Never** (only as documented per-stack opt-in) |
| Skip the empirical onboarding-stub test, copy fields from a blog | Faster isolated-mode bring-up | Breaks on the next Claude release; CI hangs (Pitfall 2) | MVP only, with a snapshot test backstop |
| Use rootful podman to dodge permission errors | Immediate "it works" | Grants host-root container control; violates rootless design | **Never** |
| Bake scanner token into the tools image to "make scans pass" | Scans run everywhere with no env wiring | Secret in image history forever (Pitfall 7) | **Never** |
| Loose/unset `minimumReleaseAge` to stop quarantine-blocked builds | Green builds today | Reopens the supply-chain window the policy exists to close (Pitfall 6) | Only with a documented, deliberate window value |
| Persist sessions into host `~/.claude/projects/` | Zero extra plumbing; full host continuity | Instance sessions pollute personal history; can't tell apart (Pitfall 10) | Only if the user explicitly wants host continuity |
| Assembler unit tests instead of integration capability test | Pinpoint failures | Couples to implementation, breaks on refactor (design §18 anti-pattern) | **Never** (design decision) |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Host podman (build + run) | Assuming a mounted daemon socket / Docker-out-of-Docker is needed | The `harnessed-tools` container only *emits* files (Dockerfile + context + launcher); the **host** runs `podman build` and the generated `~/.local/bin/<stack>` launcher natively — no socket, no `DOCKER_HOST`; ensure rootless podman is configured and `loginctl enable-linger` for long-lived service pods |
| hatago MCP hub | Wiring stdio servers as HTTP URLs / double-wrapping network-native services | Declare `transport` per server; bake light stdio servers as hatago children (stdio→HTTP), proxy heavy services by URL; one endpoint `http://localhost:<p>/mcp` |
| Claude Code auth | Mounting `~/.claude.json` for "auth" | Auth is `~/.claude/.credentials.json` (mount ro); `.claude.json` is state — stub it (isolated) or copy/relocate it (transparent) |
| 1Password `op` in container | Relying on the desktop app-auth socket inside the container | Use `OP_SERVICE_ACCOUNT_TOKEN` (env), or resolve on the host and pass resolved env in; keep varlock inert without a schema |
| mise node tooling | Leaving the npm backend on npm, defeating pnpm policy | `npm.package_manager = "pnpm"` (or `pnpm:` backend) so all global/recipe/hatago installs use pnpm |
| Credentialed scanners (snyk/Socket.dev) | Prompting for a token mid-build | Warn-and-skip when absent; credential-free `osv-scanner`+`pip-audit` are the baseline; tokens set via `harnessed auth` |
| Shared services (hindsight/openbrain) | Per-instance volumes/names, so memory can't be shared | Service-scoped volumes/names (`hindsight-data`, not `harnessed-data-<stack>`); one long-lived container on `harnessed-net`, concurrent attach |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Rebuilding tools/base/hatago images on every run | Minutes of latency per launch | Pin + cache images; publish prebuilt; `--build` is explicit | Every cold cache / first run on a new machine |
| `minimumReleaseAge` quarantine vs build timing | Builds intermittently fail on "too-new" deps | Pin dep versions; tune window (1–2 days); pre-warm allowlisted builds | When a recipe pulls a freshly published version |
| Re-vendoring/re-scanning unchanged recipes each build | Build time grows linearly with recipe count | Content-address/cache vendored trees + scan results; only re-scan changed inputs | At ~10+ recipes or frequent rebuilds |
| One hatago child per stdio server, all eagerly started | Pod start latency + memory climb with many MCP servers | Lazy/on-demand child start; keep heavy servers as shared sidecars, not children | Stacks with many `npx`/`uvx` servers |
| Shared service treated as per-instance | Duplicate postgres/openbrain containers, volume sprawl, port clashes | Service-scoped singleton on `harnessed-net`; start-if-absent, outlive instances | When >1 instance attaches the same service |
| Persisting full session state to host for throwaway runs | Disk growth, slow `--fresh` that isn't actually fresh | `session_state: volume` for clean-room; host persistence only when wanted | Repeated `--fresh` comparison runs |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Secret in image layer / committed profile | Permanent leak via image history or git clone | Env-only injection; ro credential mounts; layer/profile secret-scan guard (Pitfall 8) |
| Disabling/loosening pnpm supply-chain controls | Compromised newly-published dep installed immediately; malicious postinstall runs | Keep `minimumReleaseAge` window + `onlyBuiltDependencies` deny-by-default; flag raw npm/npx |
| Falling back to rootful podman | Container gains host-root control | Stay rootless on the host; document scope honestly |
| Skipping the build-time scan gate | High-severity CVE ships in an image | `osv-scanner`+`pip-audit` always run and fail on high severity; nightly re-scan of installed images |
| `yolo`/skip-permissions config leaking to transparent/host | Unsandboxed harness on the real host | `permissions: yolo` only writes into the **isolated** profile; never applied in transparent/host context |
| Mounting host `~/.ssh`/gnupg rw or broad host dirs into isolated | Container can alter host keys/identity | Keep host-integration mounts ro (`~/.ssh`, git config, gnupg per §4a); least-privilege device passthrough |
| Trusting `.mcp.json` connectivity without verification | Silent missing/extra MCP servers (capability drift) | Assert via `hatago://servers` / `claude mcp list` in capability test |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent first-run build | Looks hung; user kills it, corrupts cache | Progress banner + ETA; prebuilt image; resumable build (Pitfall 9) |
| Raw podman/build stack-trace errors | User can't tell what to fix | Actionable messages (e.g. "install podman" / the exact rootless-setup line), never a raw stack trace |
| Illegible/unstable session slug | "New session every time"; lost continuity | Stable `/home/harnessed/<relpath>` mount → legible deterministic slug |
| Build aborts with bare "conflict" | User doesn't know which recipes clashed | Name both recipes + the colliding path; show `✗ (sync conflict)` in capability report |
| Interactive token prompt in build | Breaks CI/nightly; encourages pasting secrets | Warn-and-skip; separate `harnessed auth snyk|socket` once |
| `container` muscle-memory broken | Existing users' workflow disrupted | Keep `container` as thin alias → `harnessed transparent` (zero cost) |
| Capability "pass/fail" only | User can't see *how complete* a build is | Render the markdown capability report (per-capability table), not just green/red |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Isolated launch:** Often missing the empirical no-prompt proof — verify a `--fresh` headless run reaches the harness with **zero** onboarding/login prompts (not just "it launched").
- [ ] **MCP wiring:** Often missing real connectivity — assert `hatago://servers` / `claude mcp list` shows every manifest-declared server **connected**, not just present in `.mcp.json`.
- [ ] **pnpm policy:** Often missing actual enforcement — confirm `pnpm ls`/lockfile (no npm globals), `minimumReleaseAge` set in minutes, and `onlyBuiltDependencies` allowlist applied.
- [ ] **Supply-chain gate:** Often missing the failure path — confirm a seeded high-severity dep actually **fails** the build, and a missing scanner token **warns-and-skips** (no prompt) under no-TTY.
- [ ] **Secrets:** Often missing leak verification — grep the committed profile + `podman history`/`inspect` for token-shaped strings; confirm none.
- [ ] **`.claude.json` safety:** Often missing the race fix — confirm transparent mode never rw-mounts the host file (copy-on-start or `CLAUDE_CONFIG_DIR`), and host config is untouched after a run.
- [ ] **Session persistence:** Often missing scope correctness — confirm sessions persist to a harnessed-owned dir, reconnect across runs, and don't appear in host `~/.claude`.
- [ ] **Collision policy:** Often missing the negative test — verify two recipes sharing a skill/command name **fail the build** with both names reported.
- [ ] **1Password:** Often missing the container reality — confirm resolution works via service-account token in-container (not just on the host shell).
- [ ] **Docs:** Often missing — each feature's doc section (recipe guide, stack guide, secrets, troubleshooting) lands *with* the feature; a feature isn't done without it (§17).

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| `~/.claude.json` corrupted by rw mount | MEDIUM | Restore from `~/.claude/backups/*.backup.*`; switch to copy-on-start/`CLAUDE_CONFIG_DIR`; audit for state bleed |
| Onboarding re-prompts in isolated | LOW | Add `hasCompletedOnboarding`+identity fields; re-test headless; snapshot the working stub |
| Recipe name collision shipped silently | MEDIUM | Switch to fail-fast; rebuild; rename one recipe's capability or namespace it; re-run capability test |
| Secret leaked into image/profile | HIGH | Rotate the secret immediately; purge image layers + rewrite git history (BFG/filter-repo); add the scan guard |
| Supply-chain: malicious dep installed | HIGH | Pin/rollback the dep; raise `minimumReleaseAge`; re-scan all installed images (nightly job); rebuild affected stacks |
| Rootless podman not configured / service pods lost after reboot | LOW | Add `subuid`/`subgid` ranges; `loginctl enable-linger` so long-lived service pods survive logout |
| Sessions polluting host `~/.claude` | MEDIUM | Move persistence to harnessed-owned dir; clean stray host project entries; remount at stable path |
| 1Password resolution failing in container | LOW | Provision a service-account token, inject as `OP_SERVICE_ACCOUNT_TOKEN`; or resolve on host and pass env |
| Corrupted first-run image cache | LOW | `harnessed build --build` (forced rebuild) / remove the partial image and rerun |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Rootless podman host setup (3) | Phase 1 — bootstrap | Podman present + rootless usable (subuid/subgid); long-lived service pods survive reboot with lingering |
| First-run build latency (9) | Phase 1 — bootstrap | Progress banner shown; second run is a cache hit; canceled build recovers cleanly |
| `~/.claude.json` race (1) | Phase 2 — transparent mode port | Host `.claude.json` byte-identical after a run; no new `*.backup.*` from container |
| Onboarding stub fields (2) | Phase 3 — isolated auth seeding | `--fresh` headless run: zero prompts; stub snapshot test green |
| Session slug / host pollution (10) | Phase 3 — isolated state layout | Stable legible slug; sessions reconnect; nothing in host `~/.claude` |
| MCP transport mismatch (4) | Phase 4 — pod + hatago | `hatago://servers` / `claude mcp list` shows all declared servers connected |
| Recipe name collisions (5) | Phase 5 — assembler | Negative test: dup name fails build, both recipes named; report shows `✗ (sync conflict)` |
| pnpm via mise + tuning (6) | Phase 5 — supply-chain policy | pnpm-only install graph; documented window + allowlist; native build succeeds |
| Non-interactive build / warn-skip (11) | Phase 5 — scan gate | No-TTY build: missing token warns+skips; high-severity dep fails build |
| Secrets in layers/profiles (7) | Phase 3 + Phase 5 | Profile + image-layer secret scan finds nothing; creds env-only at runtime |
| 1Password in-container (8) | Phase 6 — secrets (varlock/op) | Service-account-token resolution succeeds in container; inert without schema |
| Capability drift (all) | Phase 8 — capability test/report | Per-stack markdown report matches manifest oracle; `--fresh` no state bleed |

## Sources

- pnpm — *Mitigating supply chain attacks* (`minimumReleaseAge`, `onlyBuiltDependencies`, store integrity): <https://pnpm.io/supply-chain-security>; *pnpm in 2025* (v10 "security by default", lifecycle scripts no longer implicitly trusted): <https://pnpm.io/blog/2025/12/29/pnpm-in-2025>; *pnpm 11.0 supply-chain defaults*: <https://blog.ogwilliam.com/post/pnpm-11-supply-chain-security.html>; min-age window guidance (1440–2880 min): <https://gajus.com/blog/3-pnpm-settings-to-protect-yourself-from-supply-chain-attacks>, <https://github.com/pnpm/pnpm/issues/9921>
- hatago MCP Hub — transport independence (stdio/Streamable HTTP/SSE/WebSocket), unified catalog: <https://dev.to/himorishige/getting-started-with-multi-mcp-using-hatago-mcp-hub-one-config-to-connect-them-all-2bjp>; repo + `serve --http --port 3535` `/mcp` endpoint: <https://github.com/himorishige/hatago-mcp-hub>, <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub>; stdio→HTTP wrapping rationale: <https://github.com/pyroprompts/mcp-stdio-to-streamable-http-adapter>
- Claude Code config — `CLAUDE_CONFIG_DIR` relocation + containerized `.claude.json` location bug/workaround: <https://github.com/anthropics/claude-code/issues/14313>, <https://github.com/anthropics/claude-code/issues/3833>, <https://code.claude.com/docs/en/claude-directory>, <https://ccusage.com/guide/custom-paths>; onboarding skip (`hasCompletedOnboarding`, minimal-stub, `firstStartTime`/`numStartups`): <https://www.vellum.ai/skills/headless-claude-code>, <https://github.com/tfvchow/field-notes-public/issues/10>, <https://github.com/anthropics/claude-code/issues/29029>, <https://jedi.be/blog/2025/automating-claude-code-configuration/>
- Rootless podman — rootless mode and `loginctl enable-linger` (user-session lingering for long-lived pods): <https://docs.podman.io/en/latest/markdown/podman-system-service.1.html>, <https://man.archlinux.org/man/podman-system-service.1.en>, <https://oneuptime.com/blog/post/2026-03-18-enable-podman-socket-rootless-users/view>, <https://access.redhat.com/solutions/7011472>
- 1Password in containers — app-auth socket unsupported inside containers, use service-account token (`OP_SERVICE_ACCOUNT_TOKEN`): <https://www.nodejs-security.com/blog/mitigate-supply-chain-security-with-devcontainers-and-1password-for-nodejs-local-development>, <https://1password.com/blog/1password-service-accounts>, <https://www.mackorone.com/2023/12/06/1password-service-accounts.html>
- mise npm/pnpm backend — `npm.package_manager` setting, `pnpm:` backend: <https://mise.jdx.dev/dev-tools/backends/npm.html>, <https://github.com/jdx/mise/discussions/4879>, <https://github.com/michaelprowacki/mise-pnpm>
- Credential-free scanners — osv-scanner ("no account required, no usage limits"), pip-audit (public OSV/PyPI): <https://github.com/google/osv-scanner>, <https://appsecsanta.com/osv-scanner>, <https://pypi.org/project/pip-audit/>
- Project sources of truth: `docs/harnessed-design.md` (§4, §7, §14, §15, §16, §18), `.planning/PROJECT.md`

---
*Pitfalls research for: rootless-container AI-harness orchestrator (harnessed)*
*Researched: 2026-06-14*
