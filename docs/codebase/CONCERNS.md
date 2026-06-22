# CONCERNS — Technical Debt, Known Issues & Areas of Concern

> Codebase: `harnessed` (repo root: `/home/mcrowe/Programming/Personal/code-container`)
> Mapped: 2026-06-22. Severity is **risk × likelihood**, not just severity of impact.
> Methodology: every item is corroborated against live source (`lib/*.sh`, `tools/harnessed/*.py`, `base/Dockerfile.*`) and cross-checked against `.planning/STATE.md` (Decisions + Blockers/Concerns) and `.planning/PROJECT.md`. Stale historical assertions that the code already contradicts are filed under **Resolved / verified**, not as open debt.

## At a glance

| Sev | Count | Themes |
|-----|-------|--------|
| HIGH | 2 | Unverified docker runtime path; no CI gate on the assembler/launchers |
| MEDIUM | 6 | Stale-tools-image scan gate, hardcoded mise PATH, quote-stripping sed, egress DNS staleness, floating image tags, integration-only test coverage |
| LOW | 7 | Dead `ensure_harnessed_net`/`$net`, stale design-doc banner + `[INFERENCE]` markers, sed-based YAML parse, `--network=host` auth, `iptables -F` clobber, PROJECT.md split |

There are **zero** `TODO`/`FIXME`/`HACK`/`XXX`/`WORKAROUND` markers in the live source tree (`lib/`, `tools/harnessed/`, `harnessed`, `services/`, `recipes/`, `base/`). The project deliberately routes unresolved assumptions into prose `[INFERENCE — verify]` markers (see `.planning/phases/06-tech-debt-cleanup/06-CONTEXT.md:144`) rather than code comments, so the absence of in-code TODOs is by design, not evidence of completeness.

---

## HIGH

### H-1. Docker runtime path is implemented but unverified (WIP)

`lib/harnessed-runtime.sh` advertises a provider-agnostic abstraction and ships real docker branches:

- `rt_hatago_placement` (`lib/harnessed-runtime.sh:51-58`) — docker falls back to `--network "$HARNESSED_NET"` or the default bridge.
- `rt_harness_placement` (`lib/harnessed-runtime.sh:64-71`) — docker uses `--network container:<instance>-hatago` to join hatago's netns.
- `rt_group_teardown` (`lib/harnessed-runtime.sh:80-82`) — docker removes the flat `<instance>` + `<instance>-hatago` pair.

`detect_runtime` (`lib/harnessed-common.sh:52-61`) will happily select `docker` when podman is absent, and every launcher then flows through these untested branches. The most recent commit contradicts the "provider-agnostic" claim:

```
686833b docs: stress ALPHA status + runtime WIP matrix (podman in testing; docker/apple pending)
```

Apple `container` is correctly gated out (design §3, `lib/harnessed-runtime.sh:17-18`), but **docker is not** — it is reachable code with no recorded verification. A docker host will silently exercise the `--network container:` shared-netns model, the daemon-side uid remap (no `--userns=keep-id`), and `inspect`-based existence checks (`rt_network_exists`/`rt_volume_exists`) that have never been run.

**Fix:** Either (a) gate docker behind an explicit `--runtime docker`/env opt-in with a "experimental" warning until a docker harness-matrix UAT exists (mirror the `tools/uat/phase-06.sh` podman matrix), or (b) add a docker leg to `tools/uat/` and record a VERIFIED entry. Until one of those lands, `detect_runtime` should refuse docker rather than present it as supported.

### H-2. No CI gate on the assembler or launchers

The only GitHub Actions workflow is `.github/workflows/deploy-web.yml` (deploys the Astro marketing site). There is **no** workflow that runs the UAT suites, the supply-chain scan, or even `bash -n`/`python -m py_compile` on PRs. The verification record lives entirely in `.planning/phases/*/0*-VERIFICATION.md` and is run by hand via `./tools/uat/run-uat.sh <phase>`.

Consequence: a regression in `tools/harnessed/*.py` (the CVSS gate, the manifest parser, the synclinks collision logic) or in `lib/harnessed-*.sh` can land on `main` with nothing failing. The capability test (`harnessed test <stack>`) is the oracle, but nothing automates it.

**Fix:** Add a `.github/workflows/ci.yml` that, at minimum: (1) `bash -n` every `lib/*.sh` + `harnessed`; (2) `python -m py_compile tools/harnessed/*.py`; (3) run `./tools/uat/run-uat.sh 06 --quick` (the fast, non-container manifest/validation leg that already exists). Wire it to run on push + PR.

---

## MEDIUM

### M-1. `ensure_tools_image` is build-if-missing, not staleness-aware

`lib/harnessed-common.sh:100-106` builds `harnessed-tools` only when the image is absent. After editing any `tools/harnessed/*.py`, the on-disk image keeps running the **old** assembler and the **old** scan gate. `.planning/STATE.md:74` calls this out explicitly:

> Operational note: rebuild harnessed-tools after a tools/harnessed/*.py upgrade (ensure_tools_image is build-if-missing, not staleness-aware).

This is acutely dangerous for the supply-chain gate (`tools/harnessed/scan.py`): a stale image runs a stale CVSS parser / scanner invocation and can report a false-clean on a real HIGH finding. The nightly rescan (`lib/harnessed-rescan.sh:52-53`) reuses the same stale image.

**Fix:** Make `ensure_tools_image` content-aware — hash `tools/Dockerfile` + `tools/harnessed/*.py` + `tools/pyproject.toml` into a label (`io.harnessed.tools-hash`), and rebuild when the running image's label differs. Cheaper alternative: a `harnessed build --tools` force flag documented next to the STATE.md note, plus a banner in `harnessed rescan` warning if the tools image is older than the newest `.py` mtime.

### M-2. Hardcoded mise node PATH under the non-native HOME

`lib/harnessed-secrets.sh:45`:

```bash
_HARNESSED_TOOLS_NODE_PATH="/home/tools/.local/share/mise/installs/node/latest/bin"
```

This is prepended to `PATH` inside the throwaway resolve/auth containers (`:84`, `:186`) so the pnpm-global CLIs (varlock/snyk/socket) find node without going through mise — because mise reads `$HOME/.config/mise/config.toml`, which does not exist at the overridden `$CONTAINER_HOME=/home/harnessed` (`lib/harnessed-secrets.sh:39-44`). The path hardcodes three assumptions: the tools image's native home is `/home/tools`, node is installed under mise's `node/latest` symlink, and that symlink resolves. If the tools image home changes, or mise stops exposing a `latest` symlink, or a different node minor is needed, resolution silently breaks and `varlock`/`snyk`/`socket` become "command not found".

**Fix:** Derive the path at build time and bake it as an image label/env (`ENV HARNESSED_NODE_BIN=…` in `tools/Dockerfile`), then read that env in the launcher instead of hardcoding. This survives home/path changes and makes the coupling visible in one place.

### M-3. Quote-stripping `sed` for podman `--env-file`

`lib/harnessed-secrets.sh:114`:

```bash
sed -E 's/^([^=]+)="(.*)"$/\1=\2/' "$raw" > "$envfile"
```

This exists because podman's `--env-file` treats varlock's `KEY="value"` literally (the quotes become part of the value) — documented in `.planning/STATE.md:67` and the function header (`:109-111`). The regex is safe for varlock's one-`KEY="value"`-per-line output, but it is greedy on `(.*)` and would mis-strip a value that itself contains `"`. More subtly, it silently drops the file's quoting semantics: a value with embedded spaces or shell metacharacters survives only because podman re-parses dotenv, not because the transform is correct. There is no test covering a value containing `"` or `=`.

**Fix:** Replace the `sed` with a Python one-liner inside the existing throwaway tools container (`python -c 'import shlex,sys; …'` emitting `KEY=value` with proper escaping), or have varlock emit podman-native dotenv directly (upstream feature). At minimum, add a fixture in `tools/test-fixtures/` exercising a value containing `"` and `=` through `resolve_secret_env`.

### M-4. Egress firewall resolves domains once; DNS rotation makes rules stale

`lib/egress-firewall.sh:78-100` resolves each whitelisted domain (`WHITELIST`, `:11-34`) to IPs **at apply time** and pins iptables rules to those IPs. The firewall is re-applied per session start (`apply_firewall`, `lib/harnessed-common.sh:382-392`, idempotent via `/run/egress-firewall-active`), so a long-lived instance whose CDN rotates IPs (api.anthropic.com, registry.npmjs.org, files.pythonhosted.org all sit behind rotating CDN edges) silently loses egress to a now-blocked IP — the harness fails with opaque connection timeouts, not a firewall message.

Additionally, `iptables -F OUTPUT` (`:42`) flushes **all** OUTPUT rules. If any coexisting process (VPN, another sandbox) installed rules, they are clobbered on every harnessed start.

**Fix:** (1) Resolve domains via `iptables ... -d <fqdn>` is not supported, so the realistic fix is a shorter re-resolve cadence — drop the `/run/egress-firewall-active` idempotency skip for sessions longer than N hours, or add a documented "if a previously-working host goes silent, re-run the firewall" note. (2) Replace the blanket `-F OUTPUT` with a chain-scoped flush (a dedicated `HARNESSED-EGRESS` chain jumped from OUTPUT) so coexisting rules survive.

### M-5. Floating image tags in `harnessed-base`

`base/Dockerfile.harnessed-base:70-78`:

```dockerfile
mise use -g \
    node@22 \
    pnpm@11 \
    python@latest \
    fd \
    ripgrep \
    npm:opencode-ai \
    npm:@openai/codex \
    npm:@google/gemini-cli && \
```

`node@22`/`pnpm@11` are major-pinned (good). But `python@latest`, `fd`, `ripgrep`, and the three `npm:` harness CLIs (`opencode-ai`, `@openai/codex`, `@google/gemini-cli`) are fully floating. Two builds on different days produce different images. The pnpm supply-chain config (`minimumReleaseAge`, `lib/pnpm/config.yaml`) mitigates the `npm:` tools' install-time risk, but `python@latest` and the mise-native `fd`/`ripgrep` are unbounded, and nothing pins the resolved versions into the image for reproducibility.

**Fix:** Pin to resolved versions (`python@3.13`, `fd@10.x`, etc.) or emit a `mise.toml`/lockfile at build time recording what `latest` resolved to, committed for reproducible rebuilds. The supply-chain scan gate then has a stable manifest to audit.

### M-6. Integration-only test coverage with no unit tests for pure functions

Design §18 (`docs/harnessed-design.md:608-660`) explicitly rejects assembler unit tests: behavior is asserted transitively through the running instance. That is a defensible philosophy, but it leaves the **pure** logic in `tools/harnessed/scan.py` (the CVSS v3.1 base-score math in `_cvss3_base`/`_roundup`/`gate`, `:65-132`) and `tools/harnessed/schema.py` (the raw-npm lint regex `_RAW_NPM_RE`, `:271`) covered only when a full `--fresh` headless pod happens to exercise them. There are no `tools/test_*.py` / `conftest.py` files (confirmed: only `tools/uat/` shell suites + `tools/test-fixtures/` manifests exist). A CVSS-parsing regression that mis-scores a 7.5 as 6.9 (below the `HIGH = 7.0` gate, `scan.py:31`) would let a HIGH CVE through the build gate and surface only as a real-world compromise.

**Fix:** The design rejects coupling to *implementation*, not to *pure functions*. Add a small `tools/tests/test_scan_gate.py` that asserts `gate()` returns known CVE-IDs at/above/below 7.0 from fixture OSV JSON (the dataclass inputs are stable across refactors). This honors §18 (tests survive refactors) while closing the highest-leverage gap.

---

## LOW

### L-1. Dead code: `ensure_harnessed_net()` has no callers

`lib/harnessed-services.sh:27-29` defines `ensure_harnessed_net()` (→ `ensure_named_net harnessed-net`), but the isolated launcher only ever calls `ensure_named_net "$HARNESSED_NET"` directly (`lib/harnessed-isolated.sh:148`). A repo-wide search confirms `ensure_harnessed_net` appears only at its own definition. This is residue from the Phase-04 "make harnessed-net the default" plan that was reverted to the publish+host-gateway model (`.planning/phases/04-.../04-01-SUMMARY.md:107-109`).

**Fix:** Delete `ensure_harnessed_net()` (and its comment, `:27`). `ensure_named_net` is the only live entry point.

### L-2. Assigned-but-unused `$net` variable

`lib/harnessed-isolated.sh:77`:

```bash
local net="${HARNESSED_NET:-harnessed-net}"
```

The live pod-network block (`:146-150`) reads `${HARNESSED_NET:-}` directly, so `$net` is never referenced. The comment at `:73-76` acknowledges this ("KEPT per D-04 — if unsure, leave it and add a clarifying comment"). The clarifying comment exists; the variable is still dead.

**Fix:** Delete `$net`. The comment already explains why it was historically kept; the code no longer needs it.

### L-3. Stale design-doc status banner + resolved-but-open `[INFERENCE]` markers

`docs/harnessed-design.md:3-5` still reads "Schemas, repo layout, and CLI (§10–§13) are **proposed** … §14 items are **to verify during execution**" — but the milestone is complete (`.planning/STATE.md:6`) and §10–§13 are shipped. Two `[INFERENCE — verify]` markers remain open by policy (D-06: gap-closure must not touch them):

- `docs/harnessed-design.md:450` — the minimal `.claude.json` stub field set. `.planning/STATE.md:83` records this as **RESOLVED** ("proven sufficient for a headless no-prompt boot"). The marker still says "verify empirically."
- `docs/harnessed-design.md:490` — `CLAUDE_CONFIG_DIR` relocation. Phase 1 chose copy-on-start instead (`.planning/STATE.md:82`), so the assumption is effectively resolved by decision.

**Fix:** Update the §3-5 banner to "shipped" and, per the CONCERNS marker-table convention (`.planning/phases/06-.../06-CONTEXT.md:144`), flip the two `[INFERENCE]` markers to `[RESOLVED — …]` with a one-line citation to the STATE.md decision. (D-06 forbade this during gap-closure execution; it is fair game as standalone debt.)

### L-4. `sed`-based YAML parsing in the launcher

`lib/harnessed-isolated.sh:41` parses `harness:` via `sed -n 's/^harness:[[:space:]]*//p'`, and `:163-167` parses `services:` with bracket/comma stripping. The comment at `:36` calls this out ("flat scalar grep — the manifest is authored"). It breaks on quoted values (`harness: "claude"`), inline comments, or any indentation drift — but manifests are hand-authored and validated by `tools/harnessed/schema.py` at build time, so a malformed manifest fails earlier.

**Fix:** Acceptable as-is for the launcher's hot path (avoids a Python round-trip). Add a one-line guard that the parsed `harness` is in the supported set (it already defaults to `claude` and the image switch at `:43-48` silently maps unknown → claude-image, which is a latent footgun — an `else` error would be clearer).

### L-5. `--network=host` for snyk interactive auth

`lib/harnessed-secrets.sh:171-173,179` runs the snyk auth container with `--network=host` so the browser OAuth callback to snyk's loopback listener (`127.0.0.1:8080`) lands. The comment (`:158-167`) justifies this thoroughly and scopes it to the one-shot interactive auth container. Residual risk: that container shares the host net namespace for the duration of the browser flow.

**Fix:** Acceptable given the justification. Document the blast radius in `docs/guides/secrets.md` (operator should close the flow promptly). No code change.

### L-6. `.planning/PROJECT.md` Active/Validated split is stale

`.planning/PROJECT.md:138` self-reports: "the Active/Validated split above has NOT been migrated phase-by-phase since Phase 1 — a full milestone review (`/gsd-complete-milestone`) should move shipped items Active → Validated." Items like "Runtime stack composition as a podman pod" (`:40`) are checked-off-but-listed-under-Active, and the `harnessed-net` phrasing in that line (`:40`) is itself stale post-pivot.

**Fix:** Run the milestone review, or at minimum correct `:40` to drop the `(harnessed-net)` phrasing in favor of the shipped pasta + host-gateway model.

### L-7. `iptables -P OUTPUT DROP` default-deny without an escape hatch

`lib/egress-firewall.sh:42-43` sets `iptables -P OUTPUT DROP` after flushing. If the whitelist resolution fails for a domain the harness needs (e.g. a new Anthropic telemetry host not in `WHITELIST`, `:11-14`), traffic silently drops. The `failed[]` array (`:80`,`:106`) only warns about *unresolvable* domains, not about *needed-but-unlisted* ones. There is no `--no-firewall` per-run escape documented beyond the launcher flag (`harnessed --no-firewall`, `harnessed:206`).

**Fix:** Acceptable for a security-first tool, but add a troubleshooting pointer in `docs/guides/troubleshooting.md` for "harness can't reach host X → check WHITELIST + re-apply." The `NO_FIREWALL` env (`lib/harnessed-common.sh:44`) is the documented escape.

---

## Resolved / verified (not open debt)

These appear in `.planning/STATE.md:84` (Blockers/Concerns) as the **SC-1 gap** — "stale bridge-as-default `harnessed-net` assertions in files plan 06-01 did NOT cover." A repo-wide search on 2026-06-22 confirms the live code is now **clean**: the only `harnessed-net` references outside `.planning/` historical docs are (a) the intentional `HARNESSED_NET` opt-in (`lib/harnessed-isolated.sh:29,77,147-149`), (b) the accurate replacement-doc comment in `tools/harnessed/assemble.py:65-67`, and (c) the corrected reachability prose in `docs/harnessed-design.md:266-269` (host.containers.internal primary, bridge opt-in).

The four files STATE.md flagged were all corrected by the SC-1 gap closure (commit `153c0f6` + `1ab4df5`):

| File | STATE.md claim | Current state (verified 2026-06-22) |
|------|----------------|-------------------------------------|
| `services/ping/server.py:6-8` | docstring contradicts `:19-25` impl | Consistent — both describe `host.containers.internal` as primary, `HARNESSED_NET` as opt-in |
| `tools/harnessed/schema.py:140-149` (`ServiceDef`) | stale B1+B4 pattern left unfixed | Corrected — docstring states host-gateway primary, bridge opt-in |
| `CLAUDE.md:153` | "pod on harnessed-net" vs pasta default | Corrected — "rootless (pasta) networking by default … HARNESSED_NET is the opt-in bridge" |
| `docs/codebase/INTEGRATIONS.md` | stale transport phrasing | Regenerated by `map-codebase` (commit `1ab4df5`) |

**Takeaway:** the `pasta vs harnessed-net` concern is closed in code. The only residue is the dead `ensure_harnessed_net()` (L-1) and `$net` (L-2) variables.

## Accepted tradeoffs (by design, not debt)

- **No assembler unit tests** — design §18; the mitigation gap is scoped narrowly in M-6 above (pure functions only).
- **`set -euo pipefail` with `local var=$(…)` / `|| true` probes** — `.planning/PROJECT.md:118` records this as a deliberate, learned convention (bugfix `a963a69`); any edit to `lib/*.sh` must preserve it.
- **varlock/1Password opt-in via a single `[ -f $HARNESSED_SCHEMA ]` test** — INERTNESS guarantee (`lib/harnessed-secrets.sh:52-53`); no schema ⇒ varlock never invoked. Verified in `.planning/phases/05-.../05-02-SUMMARY.md:135`.
- **Secrets never baked/committed** — env-only via mode-0600 temp `--env-file`, unlinked via a RETURN trap (`lib/harnessed-isolated.sh:187-192`). Verified no token-bearing layers (`.planning/.../05-02-SUMMARY.md:138`).
- **Offline build-time scan vs online nightly scan** — the correct separation; `run_image_scan` (offline, deterministic) vs `run_image_scan_online` (nightly, fresh DB) in `tools/harnessed/scan.py:319-370`. The only residual risk is M-1 (stale tools image running old scan logic).

## Open follow-ups (tracked, not debt)

- `.planning/todos/pending/2026-06-21-apple-container-named-network-mcp-endpoint.md` — Apple `container` support (design §3 follow-up; correctly gated out today).
- `.planning/todos/pending/2026-06-21-persist-agy-auth-via-in-pod-keyring.md` — antigravity OAuth persistence (Option 2; host-keyring mount rejected).

---

*Last verified against HEAD on 2026-06-22. Re-run `rg -n 'TODO|FIXME|HACK|XXX|WORKAROUND' lib tools harnessed services recipes base` after edits to confirm the zero-marker invariant still holds.*
