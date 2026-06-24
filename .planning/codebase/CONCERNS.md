# Codebase Concerns

**Analysis Date:** 2026-06-24

## Tech Debt

**Profiles committed then gitignored:**
- Issue: `profiles/` was previously tracked in git and many profile files are now deleted (`D` status in git). `.gitignore` now correctly excludes `/profiles/`, but the tracked files have not been removed via `git rm`. Any `git status` shows dozens of deleted files, and `git checkout` of an old commit could restore the ignored directory.
- Files: `profiles/*/` (all profile dirs), `.gitignore`
- Impact: Confusing git status; `git stash` or bisect operations may restore stale profiles that shadow live builds
- Fix approach: Run `git rm -r --cached profiles/` to remove all tracked entries, then commit

**Single hatago image tag shared across all stacks:**
- Issue: `build_stack()` always tags the built hatago image as `harnessed-hatago:latest`. Building stack A overwrites the hatago image that stack B was running against. All stacks share a single mutable image tag.
- Files: `lib/harnessed-common.sh:213` (`build_stack`), `lib/harnessed-common.sh:39` (`HARNESSED_HATAGO_IMAGE`)
- Impact: A rebuild of any stack silently changes the image for all running or future instances; no per-stack hatago image isolation
- Fix approach: Tag as `harnessed-hatago-<stack>:latest` and reference it per-stack in the launcher

**CVSS vector string parsing is hand-rolled:**
- Issue: `scan.py` implements a full CVSS v3.1 base score calculator from scratch (metric tables `_AV`, `_AC`, `_PR_*`, `_UI`, `_CIA`, roundup function). This is the load-bearing build abort gate.
- Files: `tools/harnessed/scan.py:37-115`
- Impact: Any mistake in the formula silently allows HIGH CVEs through or incorrectly aborts builds; the code is complex enough to contain subtle bugs (e.g., scope-changed PR table selection)
- Fix approach: Depend on the `cvss` PyPI package (actively maintained, FIRST.org validated) instead of a manual implementation

**`jq` is an undocumented host dependency violating the "podman-only" invariant:**
- Issue: `harnessed-isolated-config.sh` unconditionally calls `jq` on the host to read `~/.claude.json` and generate the `.claude.json` stub. The design doc (CLAUDE.md §15) explicitly states "podman is the only host dependency," but `jq` is required for isolated mode.
- Files: `lib/harnessed-isolated-config.sh:97-120`
- Impact: Isolated mode (the primary mode) fails with a clear error on hosts without `jq`; contradicts documented constraints
- Fix approach: Either document `jq` as a required host tool, or generate the stub via a throwaway tools container instead of the host

**`[INFERENCE]` items unverified in production:**
- Issue: Several design decisions are explicitly marked `[INFERENCE]` in `docs/harnessed-design.md` §14 and `CLAUDE.md`. These include: the exact fields Claude Code gates onboarding on in `.claude.json`; whether `CLAUDE_CONFIG_DIR` relocates `.claude.json` not just `.claude/`; whether `mise`'s `npm:` backend routes through pnpm for supply-chain policy.
- Files: `lib/harnessed-isolated-config.sh:10-19` (onboarding stub fields), `CLAUDE.md:172,179`, `docs/harnessed-design.md:508-550`
- Impact: A Claude Code update that adds an onboarding gate field will break isolated mode silently (no prompt, just stuck); pnpm supply-chain policy may not apply to mise-installed tools
- Fix approach: Each [INFERENCE] should have a UAT checkpoint that verifies empirically and pins the result as a fixture

## Known Bugs

**Snyk container test silently degrades to warning when tools container lacks daemon socket:**
- Symptoms: `SC-03` (snyk container test) exits 2 ("failure") instead of testing the image; the build succeeds with a warning
- Files: `tools/harnessed/scan.py:348-349` (documented in comment), `lib/harnessed-common.sh:261-268`
- Trigger: When the tools container runs `snyk container test <image>` it has no access to the host's podman socket and cannot pull the image layers for inspection
- Workaround: The osv-scanner baseline (BLD-02b) still runs on the saved tar archive and covers this gap; SC-03 is a secondary gate

## Security Considerations

**Egress firewall uses DNS-resolved static IPs:**
- Risk: The firewall resolves domain IPs at container startup and uses those IPs as iptables rules. Cloud/CDN services (GitHub, npm registry, Anthropic API) use dynamic IP pools that change. A session started after an IP rotation will have stale allowlist rules.
- Files: `lib/egress-firewall.sh:79-100`
- Current mitigation: DNS is always allowed (UDP/TCP port 53), so resolution succeeds; the resolved IPs are the most recent at launch time
- Recommendations: Either allow the CDN IP ranges via CIDR blocks, or add a refresh hook triggered by connection failure; document the IP-staleness risk window

**Antigravity uses OS system keyring — no credential pre-seeding:**
- Risk: `agy` (antigravity harness) authenticates via Google OAuth stored in the OS Secret Service keyring. A clean-room container has no keyring daemon, so every new container instance requires an interactive re-auth (printed URL or browser flow). Sessions cannot be recovered across container recreates.
- Files: `lib/harnessed-isolated-config.sh:60-67`, `base/Dockerfile.harnessed-antigravity`
- Current mitigation: Warning printed on launch; documented limitation in `docs/guides/`
- Recommendations: If agy adds an API key option or a credential-file export, implement pre-seeding. For now, document clearly that `--fresh` on an antigravity stack always prompts for auth.

**Claude installer and mise installer use unpinned curl-pipe-bash:**
- Risk: `Dockerfile.harnessed-claude` and `Dockerfile.harnessed-base` use `curl ... | bash` with no version pinning for the claude CLI and mise respectively. Any supply-chain compromise of those installer scripts affects the image silently.
- Files: `base/Dockerfile.harnessed-claude:7`, `base/Dockerfile.harnessed-base:51`, `base/Dockerfile.harnessed-antigravity:30`, `base/Dockerfile.hatago` (uv installer)
- Current mitigation: Images pass the post-build osv-scanner scan; the build-time scan catches known CVEs after the fact
- Recommendations: Pin the claude installer via `--version <pin>` flag if available; for mise, use a release-tagged URL with SHA verification; note that agy explicitly has no version-pin mechanism (vendor limitation)

**`OP_SERVICE_ACCOUNT_TOKEN` injected into tools container env:**
- Risk: When resolving secrets in headless mode (no host varlock), `OP_SERVICE_ACCOUNT_TOKEN` is passed via `-e` to the tools container. Any process inside that container that logs env variables could expose it.
- Files: `lib/harnessed-secrets.sh:78-85`
- Current mitigation: `--rm` on the tools container; the token is not written to any image layer; container is short-lived
- Recommendations: Acceptable for current use; note that `--env-file` is slightly safer than `-e` for tokens (no shell history exposure)

## Performance Bottlenecks

**`harnessed build` runs serial image saves for scanning:**
- Problem: `build_stack()` runs `podman save <image> -o <tar>` before each osv-scanner run, synchronously. A stack with a large base image (~2GB+) means two sequential save operations (hatago image + derived stack image) before scan results are known.
- Files: `lib/harnessed-common.sh:218-258`
- Cause: The scan design requires a tar archive (osv-scanner image mode); saves are O(image size)
- Improvement path: Cache save tars keyed by image digest; skip the save when the image hasn't changed since the last scan

**Hatago readiness uses a 30-second busy-wait with 1-second sleep intervals:**
- Problem: The launcher polls for hatago's HTTP port with a 1-second sleep per iteration, up to 30 retries. No feedback until a connection succeeds or all 30 retries are exhausted.
- Files: `lib/harnessed-isolated.sh:207-209`
- Cause: No readiness signal from the pod members; HTTP port binding is the only observable signal
- Improvement path: Add a hatago `--readiness-timeout` flag if available, or use exponential backoff; print progress after N seconds

## Fragile Areas

**`stop_if_last_session` — race window in session counting:**
- Files: `lib/harnessed-common.sh:450-466`
- Why fragile: Counts attached sessions by scanning `ps ax` output for matching `podman exec -it` commands. A new session started between the count and the `stop` will keep the container alive incorrectly; a session that exits in that window will leave the container running
- Safe modification: Do not call `stop_if_last_session` from contexts where session count matters; prefer explicit `harnessed stop <stack>` for lifecycle management
- Test coverage: Not covered by UAT (requires timing-sensitive multi-process setup)

**`.claude.json` stub field set is empirically unverified:**
- Files: `lib/harnessed-isolated-config.sh:110-120`
- Why fragile: The fields (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`, `oauthAccount`, `userID`) are documented as `[INFERENCE]` in design §14. A Claude Code update adding a new onboarding gate field will cause isolated mode to silently prompt for re-login without a clear error.
- Safe modification: Add a UAT assertion that launching a fresh isolated instance completes without an onboarding prompt; treat a prompt as a failing test
- Test coverage: Covered by phase-04 and phase-06 UAT but only when the specific fields happen to be sufficient

**`harnessed-manifest-mounts.sh` depends on `yq` being in PATH:**
- Files: `lib/harnessed-manifest-mounts.sh:28,51`
- Why fragile: `yq` is called on the host to parse `lib/manifests/<harness>.yaml`. The error handling returns `1` on yq failure but only prints a warning. If yq is absent or returns a non-zero exit, MOUNT_ARGS is partially populated.
- Safe modification: Add a `command -v yq` check at the top of `harnessed_manifest_mounts` and emit a clear dependency error
- Test coverage: No UAT test exercises the yq-absent failure path

**Services: inline YAML parsing via `sed` with no quoting validation:**
- Files: `lib/harnessed-services.sh:35-38` (`_svc_yaml_val`)
- Why fragile: Reads `service.yaml` scalar values via `sed -n "s/^${key}: *//p"` followed by `tr -d '"'`. A `service.yaml` value containing special characters (colons, brackets) will be silently misread
- Safe modification: Use `yq` (already a dependency in manifest-mounts) for all YAML reading; or require strictly flat `key: simple-value` fields in service.yaml and document that constraint
- Test coverage: `tools/test-fixtures/services/` has only the ping service; no test for malformed service.yaml

## Scaling Limits

**All stacks share one `harnessed-hatago:latest` image:**
- Current capacity: One hatago image configuration per host at a time
- Limit: Cannot run two stacks simultaneously if they have different MCP server sets and both need a fresh build — building one overwrites the other
- Scaling path: Per-stack hatago image tags (`harnessed-hatago-<stack>:latest`); requires updating `HARNESSED_HATAGO_IMAGE` to be dynamic in `build_stack` and both launchers

## Dependencies at Risk

**`@himorishige/hatago-mcp-hub` — single maintainer, early-stage:**
- Risk: The entire MCP aggregation layer depends on this package. It is a small npm package with a single author (`himorishige`). If it is abandoned or breaks on a hatago schema change, all isolated stacks lose MCP connectivity.
- Impact: Every stack's MCP capability chain breaks
- Migration plan: hatago's config format is simple JSON; the fallback is to replace it with another hub (`@samanhappy/mcphub`, `mcp-gateway`) or a thin custom stdio-to-HTTP bridge

**`agy` (antigravity) — no API key mechanism, installer lacks version pinning:**
- Risk: The `agy` CLI has no documented API-key env var for non-interactive auth. The installer (`curl ... | bash`) has no version-pin flag. If Google changes the auth model or the binary URL, the antigravity harness is broken silently.
- Impact: `harnessed-antigravity` image builds successfully but agy prompts for interactive auth on every container recreate
- Migration plan: Monitor for an `ANTIGRAVITY_API_KEY` or credential-file option; if unavailable, document antigravity as a "persistent session only" harness (never `--fresh`)

**`node@22` (LTS), `python@3.12` — major-only pins in mise:**
- Risk: `Dockerfile.harnessed-base` pins `node@22` and `python@3.12` (major only). Patch-level updates via mise are automatic on each image rebuild, meaning a patch that breaks a dependency would propagate silently.
- Impact: Non-reproducible builds between rebuild dates
- Migration plan: Pin to exact versions (`node@22.x.y`, `python@3.12.x`) in `Dockerfile.harnessed-base`; update pins deliberately rather than on every build

## Missing Critical Features

**Apple `container` runtime not supported:**
- Problem: `lib/harnessed-runtime.sh` explicitly documents that Apple's `container` tool (one VM+IP per container) has no shared-netns/pod equivalent and is not handled. The harness depends on localhost-shared netns for hatago connectivity.
- Blocks: Users on macOS who use Apple `container` instead of Podman/Docker cannot run isolated stacks at all
- Fix: Requires a different MCP endpoint model (dynamic port + env var instead of `localhost:3535`) or a per-container DNS mechanism

**No automated rollback on failed scan:**
- Problem: If `harnessed build <stack>` passes the source scan but fails the image scan, the `profiles/<stack>/` directory has already been written. The next `harnessed <stack>` launch will use a stale (potentially inconsistent) profile while the caller thinks the build failed.
- Files: `lib/harnessed-common.sh:124-276` (`build_stack`)
- Blocks: Reproducible, atomic build semantics
- Fix: Write profiles to a temp directory first; rename to final location atomically only after all scans pass

## Test Coverage Gaps

**Python assembler has no unit tests:**
- What's not tested: `schema.py` (YAML parsing, schema validation, collision detection), `assemble.py` (server merging, service resolution), `emit.py` (artifact writing), `scan.py` (CVSS calculation, severity gating), `synclinks.py` (skill/command fan-out, collision detection)
- Files: `tools/harnessed/schema.py`, `tools/harnessed/assemble.py`, `tools/harnessed/emit.py`, `tools/harnessed/scan.py`, `tools/harnessed/synclinks.py`
- Risk: Logic bugs in CVSS calculation or YAML parsing go undetected until a full UAT run against a live container
- Priority: High — the CVSS gate and collision detection are correctness-critical

**No test for secrets resolution failure paths:**
- What's not tested: `resolve_secret_env` failure modes (varlock exits non-zero, empty schema, malformed dotenv output), `discover_scanner_tokens` with malformed `snyk.json`
- Files: `lib/harnessed-secrets.sh`
- Risk: A broken secrets configuration aborts the launch with an unhelpful message and no recovery guidance
- Priority: Medium

**UAT harness matrix only runs if all harness images are pre-built:**
- What's not tested: `phase-06.sh` tests `test_harness_omp`, `test_harness_opencode`, etc. only when those harness images exist. If a CI run hasn't pre-built them, these tests are silently skipped.
- Files: `tools/uat/phase-06.sh`
- Risk: A regression in an alternative harness's MCP wiring (omp, gemini, codex) goes undetected
- Priority: Medium — gate on image existence but emit a clear skip vs silent pass

---

*Concerns audit: 2026-06-24*
