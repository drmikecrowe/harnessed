# Feature Research

**Domain:** Composable, isolated AI-coding-harness / dev-container manager (rootless podman pods + MCP hub)
**Researched:** 2026-06-14
**Confidence:** HIGH

> Scope note: `harnessed` launches isolated, composable *harness stacks* — each a podman pod (harness container + hatago MCP hub + optional shared service sidecars), assembled ahead-of-time from hand-authored recipes, gated by a build-time supply-chain scan. It evolves this repo's `container` host-mirror sandbox, which folds in as the built-in `transparent` stack. Features below are categorized against that core value: *compose a named stack and launch an isolated, authenticated instance that exposes exactly the skills/commands/MCP/services it declares — nothing from the host config — reproducibly, with podman as the only host dependency.*

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete. These are the baseline any "sandboxed dev container for an AI harness" must clear; most already ship in today's `container.sh` and fold into the shared host-integration layer (§4a).

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Host auth passthrough | The harness is useless unauthenticated; re-login per run is unacceptable | LOW | `isolated`: mount `~/.claude/.credentials.json` (OAuth) read-only + generate a minimal `.claude.json` stub (skip onboarding). `transparent`: live mount. NEVER bake/commit creds (§7, §16) |
| Project mount | You launch the tool *at* a project; it must see your code | LOW | Mount cwd (or `[path]` arg) at a stable in-container path (`/home/harnessed/<relpath>`) for a legible Claude session slug. The launcher runs on the host, so paths are host-native (§15) |
| Image build / lifecycle (`build`/`list`/`stop`/`rm`/`clean`) | Containers accrete; users expect to enumerate and reclaim | MEDIUM | Ported from `container.sh`. `harnessed build` also runs the assembler + scan gate, not just `podman build`. Pod-aware: identity is `harnessed-<stack>-<projhash>` |
| MCP wiring into the harness | An MCP-capable harness with no servers is half a product | MEDIUM | `isolated`: profile `.mcp.json` points at hatago's single HTTP endpoint on `harnessed-net`. `transparent`: MCP comes from host config as-is (no hatago) |
| State persistence | Memory/session accumulation is the point of an iterated harness | MEDIUM | Persistent by default; `projects/` + `history.jsonl` persist host-side (harnessed-owned dir, path-mirrored slug). Service volumes service-scoped (`hindsight-data`) |
| Install / PATH shim | Launch by name from anywhere, like every CLI | LOW | `harnessed install <stack>` writes `~/.local/bin/<stack>` launcher; mirrors existing `install.sh` PATH symlink. `uninstall` removes it |
| Host-integration mounts (SSH / GPG / YubiKey / git) | Signed commits, agent-forwarded SSH, identity must work inside the box | MEDIUM | 1Password SSH agent socket, GPG SSH socket + `~/.gnupg` (ro), YubiKey `--device`, `~/.ssh` (ro), git config (ro), `/etc/machine-id`. Shared by ALL stacks (§4a) |
| Egress firewall | Sandbox without network control is theater | MEDIUM | `--cap-add NET_ADMIN` + `egress-firewall.sh`, ported verbatim. Default-deny allowlist already exists in repo |

### Differentiators (Competitive Advantage)

Features that set the product apart. These align directly with PROJECT.md Core Value — isolation + composition + reproducibility — and are where `harnessed` competes with devcontainers, toolbx/distrobox, and MCP aggregators.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Two config modes (transparent host-mirror vs isolated clean-room) | One engine serves both "my laptop, sandboxed" and "exactly what I picked" — minimal surface, smooth migration from old `container` | MEDIUM | Same base image/mounts/auth; differ only on config source (§2). `transparent` = built-in stack mounting host `~/.claude` live; `isolated` = profile-only |
| Runtime pod composition | Combines *sibling* harness+hub+services that `FROM` cannot union (linear inheritance ≠ union operator) | HIGH | podman pod on `harnessed-net`; the structural insight that makes the whole model work (§3, §6) |
| hatago single-endpoint MCP aggregation | One HTTP endpoint per stack; keeps `pnpm dlx`/`uvx` stdio servers OUT of the harness container | MEDIUM | `@himorishige/hatago-mcp-hub` — lightweight hub unifying many MCP servers behind one config; light stdio servers run as hatago children (stdio→HTTP wrap), heavy ones proxied over network |
| Hand-authored recipes → committed profile + baked images | Reproducible, reviewable, pinned — not magic resolved at launch | HIGH | Split output: file-extension tree → committed/mounted `profiles/<name>/`; MCP deps → baked images. "Not dynamic" is a deliberate guarantee (§5, §7) |
| Isolation removes config-collision by construction | The merge that killed the host approach (openbrain/hindsight collide, `settingSources` drift, `~` pollution) just works per-container | MEDIUM | The reframed core insight: do the merge *per container*, not in a shared host namespace (§1) |
| Shared, service-scoped concurrent sidecars (hindsight/openbrain) | One memory volume shared across `claude+hindsight` and `omp+hindsight`; sidecar outlives any single instance | HIGH | Each its own image/volume/lifecycle; `harnessed svc up/down/list`; multiple instances attach concurrently to one postgres+MCP service (§9) |
| Build-time supply-chain gate | New-release quarantine + lifecycle-script default-deny + CVE scan *before* anything is committed/baked | MEDIUM | osv-scanner + pip-audit (credential-free) always; snyk + Socket.dev when token present (warn-and-skip otherwise). Fail on high-severity (§7) |
| pnpm-everywhere policy | Content-addressed store, `minimumReleaseAge` cooldown, lifecycle default-deny — supply-chain hygiene by default | MEDIUM | pnpm v11 defaults `minimumReleaseAge` to 1440 min (1 day). `npx → pnpm dlx`, `npm install → pnpm install`. Recipe validation flags raw npm/npx (§7) |
| `--fresh` clean-room runs | A/B a recipe against a throwaway volume without disturbing accumulated state | LOW | Empty per-instance state volumes; clean comparison run. The complement to persistent-by-default (§9) |
| Per-stack capability test + markdown capability report | One mechanism, two audiences: CI sees green/red, user sees a per-capability health table | MEDIUM | Manifest is the oracle; assert live instance exposes declared MCP/skills/commands. Rendered with `rich` (§18) |
| Generated launcher shims | Name-addressable instances (`claude-openbrain-headroom-caveman [path]` from anywhere) | LOW | `harnessed install` writes a per-stack shim forwarding to the bootstrap (§13) |
| omp-via-bridge support | Run the same Claude-canonical recipes under omp with no re-authoring | MEDIUM | `claude-hooks-bridge` + `lib-pi-adapter.sh` normalize omp/GSD payloads → Claude shape. Claude format is the single source of truth; one harness per stack (§8) |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems. Several of these are explicit Out-of-Scope items in PROJECT.md — documenting *why* prevents scope creep and re-litigation.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Dynamic / runtime recipe assembly | "Just compose on the fly, no build step" feels flexible | Non-reproducible, un-reviewable, un-pinned; resolution failures surface at launch instead of build; defeats the committed-artifact guarantee | Hand-authored recipes assembled ahead of time into committed `profiles/` + baked images (§5) |
| Host-config merge (the failed approach) | "Reuse my existing `~/.claude`/`~/.agents` setup" | A single shared host namespace can't hold every experiment at once — openbrain/hindsight collide, `settingSources` drift, vendored deps pollute `~`. This is the approach that *already failed* | Per-container merge: isolation makes the collision disappear by construction (§1) |
| Combine systems via Docker `FROM`-union | "Inherit from both base images" | `FROM` is linear inheritance + multi-stage `COPY --from`; there is no union operator. Last stage wins, not a merge | Combine sibling systems at *runtime* in a podman pod (§3, §6) |
| npm / npx installs | "It's the default, everyone uses it" | No release-age cooldown, lifecycle scripts run by default, weaker store integrity → larger supply-chain attack surface | pnpm everywhere with managed config; recipe validation flags raw npm/npx and points at the equivalent (§7) |
| More than one harness per stack | "Run claude *and* omp in one box" | Doubles config surface, ambiguous canonical format, conflicting hook dispatch; no real use case | Exactly one harness (`claude` OR `omp`) per stack; share services across stacks instead (§8) |
| A GUI | "A dashboard would be nicer than a CLI" | Massive surface for a personal dev tool; the harness *is* the interactive surface; TUI (`rich`/`textual`) already covers reporting | CLI + `rich`-rendered capability report; `textual` TUI only if a real need emerges (§15, §18) |
| Assembler unit tests | "Test vendor/sync/merge internals directly" | Couples tests to implementation, breaks on refactor — the exact anti-pattern the TDD philosophy warns against | Integration-only: the running instance is the public interface; assembler bugs surface as capability-test failures. Mitigate with clear assembler errors (§18) |

## Feature Dependencies

```
Host auth passthrough
    └──requires──> Host-integration mounts (§4a shared layer)

Runtime pod composition
    └──requires──> hatago single-endpoint MCP aggregation
                       └──requires──> MCP wiring into the harness
    └──requires──> Shared service-scoped sidecars (for stacks that declare services)

Hand-authored recipes → committed profile + baked images
    └──requires──> Build-time supply-chain gate
                       └──requires──> pnpm-everywhere policy
    └──requires──> Two config modes (isolated mode consumes the profile)

Per-stack capability test + markdown report
    └──requires──> Runtime pod composition (must launch the instance to introspect it)
    └──requires──> Hand-authored recipes (manifest is the test oracle)

Generated launcher shims ──enhances──> Two config modes (name-addressable per stack)

--fresh clean-room runs ──enhances──> State persistence (the opt-out of persistence)

omp-via-bridge ──enhances──> Hand-authored recipes (consumes Claude-canonical extensions)

Isolated clean-room mode ──conflicts──> Host-config merge (anti-feature; mutually exclusive intent)
Runtime pod composition ──conflicts──> FROM-union image combination (anti-feature)
```

### Dependency Notes

- **Host auth passthrough requires the §4a host-integration layer:** auth is mounted through the same shared mount machinery (credential file ro + agent sockets); both must land together or auth half-works.
- **Runtime pod composition requires hatago aggregation:** the pod's value is the single MCP endpoint; without hatago, each MCP server would need its own wiring inside the harness container — exactly what pod composition exists to avoid.
- **hatago requires MCP wiring:** the harness's `.mcp.json` must point at hatago's HTTP endpoint; the wiring is the contract between them.
- **Recipes → profile/images requires the supply-chain gate:** nothing is committed or baked until it passes the scan; the gate is part of `harnessed build`, not a separate optional step.
- **Supply-chain gate requires pnpm-everywhere:** the gate's guarantees (release-age quarantine, lifecycle default-deny, store integrity) come from pnpm config; raw npm/npx would bypass them, so recipe validation enforces pnpm.
- **Capability test requires both pod composition and recipes:** it must launch a real `--fresh` headless instance (composition) and diff its live capabilities against `stack.yaml` (recipes as oracle).
- **`--fresh` enhances state persistence:** it is the deliberate opt-out — a throwaway-volume run for clean A/B comparison, only meaningful *because* the default is persistent.
- **Isolated mode conflicts with host-config merge:** they are opposite resolutions of the same problem; isolated mode *is* the alternative to the merge, so they can never coexist in one design.
- **Pod composition conflicts with `FROM`-union:** runtime composition exists precisely because build-time union is impossible; choosing one rejects the other.

## MVP Definition

### Launch With (v1)

Minimum viable product — the design's explicit **vertical-slice MVP**: *one harness + one MCP server + one skill, with a green capability test end-to-end* (assemble → run → assert). Ruthlessly thin: prove the core value (isolated, composed, reproducible, authenticated, introspectable) on a single tracer-bullet stack before breadth.

- [ ] Containerized tooling bootstrap — thin dependency-free `harnessed` bash + base/claude images built and run by **host** podman (the `harnessed-tools` assembler image emits files only); podman is the only host dep. *Essential: nothing runs without it.*
- [ ] One isolated stack: one harness (`claude`) + one MCP server (via hatago) + one skill. *Essential: the tracer bullet that proves composition.*
- [ ] Host auth passthrough (isolated seeding: ro credential mount + `.claude.json` stub). *Essential: an unauthenticated harness can't validate anything.*
- [ ] Shared host-integration mount layer (§4a) + project mount + egress firewall. *Essential: ported, already proven in `container.sh`.*
- [ ] Runtime pod composition (harness container + hatago on `harnessed-net`). *Essential: the architectural claim under test.*
- [ ] Hand-authored recipe + stack manifest → build-time assembler → committed profile + baked image. *Essential: proves "not dynamic" + reproducible artifacts.*
- [ ] Build-time supply-chain gate (osv-scanner + pip-audit, credential-free baseline) + pnpm-everywhere config. *Essential: the gate is part of `build`, not a bolt-on.*
- [ ] Per-stack capability test + markdown report (green end-to-end for the slice). *Essential: this IS the acceptance oracle.*
- [ ] `transparent` stack retained + `container` alias. *Essential: zero-cost continuity, no regression for existing muscle memory.*
- [ ] CLI core: `harnessed <stack> [path]`, `build`, `--fresh`, `list`, `stop`, `rm`. *Essential: minimal operable surface.*
- [ ] Docs landing with each feature (README quickstart + design doc). *Gated deliverable per §17.*

### Add After Validation (v1.x)

Features to add once the core tracer-bullet stack is green and the model is proven.

- [ ] Shared service-scoped sidecars (hindsight/openbrain) + `svc up/down/list`. *Trigger: a second stack needs persistent cross-instance memory.*
- [ ] Additional recipes added one at a time, each with its own red→green capability test. *Trigger: core slice stable; breadth begins.*
- [ ] omp-via-bridge support (`claude-hooks-bridge` + pi-adapter). *Trigger: demand for a non-claude harness on the same recipes.*
- [ ] Token-gated scanners (snyk + Socket.dev) + `harnessed auth snyk|socket`. *Trigger: a user actually has the tokens and wants deeper signal.*
- [ ] Generated launcher shims (`install`/`uninstall <stack>`). *Trigger: more than ~2 stacks in regular rotation.*
- [ ] `new` scaffolder + `permissions: yolo` profile generation. *Trigger: authoring friction observed once recipes multiply.*
- [ ] varlock + 1Password opt-in secrets (`.env.schema`). *Trigger: a user opts in by copying `.env.schema.example`.*

### Future Consideration (v2+)

Features to defer until the tool has clear product-market fit (even as a personal tool, "do I keep reaching for it?").

- [ ] Nightly re-scan timer (systemd) for post-build CVE disclosure. *Defer: build-time gate covers the primary risk; nightly is hardening.*
- [ ] `textual` TUI beyond `rich` reports. *Defer: CLI + markdown report is sufficient until interaction volume justifies it.*
- [ ] Prebuilt/published `harnessed-tools` image to cut first-run build latency. *Defer: cache hits make this a polish item, not a blocker.*
- [ ] Per-stack secret overrides referenced from `stack.yaml`. *Defer: harnessed-level + per-service schemas cover the common cases first.*
- [ ] Multi-project / cross-machine stack portability conventions. *Defer: single-developer, single-host is the validated context.*

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Containerized tooling bootstrap (podman-only dep) | HIGH | HIGH | P1 |
| Host auth passthrough (isolated seeding) | HIGH | LOW | P1 |
| Shared host-integration mounts + project mount + egress firewall | HIGH | MEDIUM | P1 |
| Runtime pod composition (harness + hatago) | HIGH | HIGH | P1 |
| hatago single-endpoint MCP aggregation | HIGH | MEDIUM | P1 |
| Hand-authored recipes → committed profile + baked images | HIGH | HIGH | P1 |
| Build-time supply-chain gate (credential-free baseline) | HIGH | MEDIUM | P1 |
| pnpm-everywhere policy | MEDIUM | MEDIUM | P1 |
| Per-stack capability test + markdown report | HIGH | MEDIUM | P1 |
| Two config modes + `transparent`/`container` alias | HIGH | MEDIUM | P1 |
| State persistence + `--fresh` | HIGH | MEDIUM | P1 |
| Image build/lifecycle (`list`/`stop`/`rm`/`clean`) | MEDIUM | MEDIUM | P1 |
| Shared service-scoped sidecars + `svc` commands | HIGH | HIGH | P2 |
| omp-via-bridge support | MEDIUM | MEDIUM | P2 |
| Token-gated scanners (snyk/Socket.dev) + `auth` | MEDIUM | LOW | P2 |
| Generated launcher shims (`install`/`uninstall`) | MEDIUM | LOW | P2 |
| `new` scaffolder + `permissions: yolo` | MEDIUM | LOW | P2 |
| varlock + 1Password opt-in secrets | LOW | MEDIUM | P2 |
| Nightly re-scan timer | LOW | LOW | P3 |
| `textual` TUI | LOW | MEDIUM | P3 |
| Prebuilt published tools image | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | devcontainers (VS Code) | toolbx / distrobox | plain `container` (this repo's current SKU) | Nix dev shells (flakes/devenv) | MCP aggregators (hatago / metamcp / agentgateway) | Our Approach (harnessed) |
|---------|--------------------------|--------------------|----------------------------------------------|--------------------------------|----------------------------------------------------|--------------------------|
| Isolation model | Per-project container; editor runs *inside* | Deliberately **un-isolated** — tight host integration, shares `$HOME` | Host-mirror sandbox (bind-mounts `~`) | Process-env isolation only; no container boundary | N/A (aggregation layer, not a sandbox) | Two modes: full host-mirror **or** clean-room isolated; isolation is the headline |
| Composition | `Dockerfile`/compose + **Features** (installable units) + lifecycle hooks | None — you `dnf install` into a mutable box | None — one image, host config drags in | Declarative `devShells` compose packages/env | Compose *MCP servers* behind one endpoint | Hand-authored recipes → committed profile + baked images, composed at runtime in a pod |
| Reproducibility | Image-pinned, but Features run at create-time | Low — mutable, imperative | Image-pinned; config not reproducible (host) | **Very high** — flake.lock hermetic | Config-file pinned per hub | Committed profile + pinned images + lockfiles + scan gate; "not dynamic" |
| AI-harness / MCP wiring | Not a concept; manual | Manual | Inherited from host config | Not a concept | **Core purpose** — unify many servers | First-class: hatago hub in-pod, single endpoint, stdio→HTTP wrap for light servers |
| Supply-chain gate | Trusts base image + Features | None | None | Nix purity ≈ integrity, no CVE gate | None (passes servers through) | osv-scanner + pip-audit always; snyk/Socket.dev token-gated; pnpm release-age + lifecycle deny |
| Host credential/identity passthrough | SSH agent forwarding, dotfiles repo | Inherits host wholesale | Full host auth + SSH/GPG/YubiKey mounts | Manual env | N/A | Ported §4a layer in *every* stack; isolated seeds creds ro + stub, never bakes |
| Shared stateful services | compose sidecars (per-project) | N/A | N/A | N/A | Some proxy heavy servers | Service-scoped sidecars shared **concurrently** across stacks/harnesses (one memory volume) |
| Runtime / engine | Docker/Podman, VS Code-coupled | podman (toolbx) / docker/podman (distrobox), host-coupled | docker/podman, bash | Nix daemon, no container | Node hub process | Rootless podman pods; podman the **only** host dep; host builds/runs natively, the `harnessed-tools` image only emits files |

## Sources

- pnpm — *Mitigating supply chain attacks* (`minimumReleaseAge`, lifecycle-script default-deny, store integrity): <https://pnpm.io/supply-chain-security> ; pnpm Settings reference: <https://pnpm.io/settings> ; pnpm 11 default 1440-min release age confirmed via Socket.dev: <https://socket.dev/blog/pnpm-11-adds-new-supply-chain-protection-defaults>
- hatago MCP Hub — repo + npm package (lightweight hub unifying multiple MCP servers, `hatago.config.json`, tag-filtered endpoints, works with Claude Code/Codex/Cursor/VS Code): <https://github.com/himorishige/hatago-mcp-hub> ; <https://www.npmjs.com/package/@himorishige/hatago-mcp-hub>
- MCP transports — spec 2025-11-25 (stdio + Streamable HTTP standard; SSE deprecated Mar 2025; clients SHOULD support stdio): <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>
- osv-scanner (Google, V2; v2.3.5 Mar 2026; credential-free, scans lockfiles + container images): <https://github.com/google/osv-scanner> ; <https://google.github.io/osv-scanner/usage/>
- pip-audit (credential-free Python audit against OSV/PyPI): <https://pypi.org/project/pip-audit/>
- Dev Containers — Features reference + lifecycle hooks + Dockerfile/compose usage: <https://containers.dev/implementors/features/> ; <https://containers.dev/guide/dockerfile> ; <https://code.visualstudio.com/docs/devcontainers/containers>
- toolbx/distrobox vs devcontainers (un-isolated, host-integrated mutable dev boxes): <https://anglesideangle.dev/blog/container-hell/> ; <https://www.x-cmd.com/blog/251129/>
- Nix flakes devShells (hermetic, reproducible, no container isolation): <https://wiki.nixos.org/wiki/Flakes> ; devenv: <https://devenv.sh/guides/using-with-flakes/>
- Rootless podman setup (host build + run): <https://oneuptime.com/blog/post/2026-03-18-enable-podman-socket-rootless-users/view> ; <https://wiki.archlinux.org/title/Podman>
- MCP aggregator landscape (metamcp, agentgateway, vMCP — competitive context): <https://github.com/metatool-ai/metamcp> ; <https://agentgateway.dev/docs/standalone/main/tutorials/multiplex/>
- Internal: `docs/harnessed-design.md` (§1–§18, authoritative design); `.planning/PROJECT.md` (core value, requirements, key decisions); `container.sh` / `install.sh` / `egress-firewall.sh` (validated existing behavior)

---
*Feature research for: composable, isolated AI-coding-harness / dev-container manager*
*Researched: 2026-06-14*
