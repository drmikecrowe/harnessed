---
phase: 05-secrets-hardening-docs-completeness
plan: 02
subsystem: infra
tags: [secrets, varlock, 1password, op, snyk, socket, podman, bash, supply-chain]

# Dependency graph
requires:
  - phase: 05-secrets-hardening-docs-completeness
    provides: 05-01 — the harnessed-tools image carrying Node@24/pnpm@11 + varlock@1.7.1 + @varlock/1password-plugin@1.2.0 + op (1password-cli 2.34.1) + snyk@1.1305.1 + socket@1.1.122 (all INERT without a schema/tokens); env-gated snyk/socket invokers in tools/harnessed/scan.py; conditional TOKEN_ARGS forwarding in lib/harnessed-common.sh build_stack; the login-shell /etc/profile.d PATH export that the varlock-resolve invocation depends on.
provides:
  - lib/harnessed-secrets.sh (NEW) — resolve_secret_env (opt-in detect-and-resolve; INERT when no schema) + auth_scanner (harnessed auth snyk|socket → --rm container, host config persistence)
  - lib/harnessed-isolated.sh wiring — resolve_secret_env before pod members; --env-file into BOTH hatago + harness; rm -f after launch
  - lib/harnessed-common.sh build_stack wiring — resolve_secret_env before the scan step; --env-file into the scan-step podman run; rm -f after
  - harnessed launcher — auth) dispatch (parse-before-fallthrough), dispatch-and-exit, usage + surface comment, AUTH_TOOL init
  - docs/guides/secrets.md (NEW) — opt-in workflow, agent-socket transport, headless OP_SERVICE_ACCOUNT_TOKEN fallback + CLAUDE.md caution, per-service schemas, verification steps, design §16 cross-ref
affects: [05-03 nightly re-scan (reuses auth/token model), 05-04 docs (cross-refs secrets.md)]

# Tech tracking
tech-stack:
  added: []  # no new packages — uses the 05-01-baked varlock/op/snyk/socket CLIs
  patterns:
    - opt-in detect-and-resolve (single `[ -f ]` test → inert path; throwaway tools container → resolved env-file)
    - mode-0600 temp --env-file (T-05-06: created with mktemp + chmod 600, unlinked after launch/scan)
    - `--rm` vendor-CLI auth container with `-e HOME=$CONTAINER_HOME` so the token writes to the rw-mounted host config path (T-05-07)
    - PATH prepend (mise install dir) so the pnpm-global CLIs resolve under the non-native HOME (mise shims break otherwise)
    - varlock `--format env` quote-stripping sed (podman --env-file treats `KEY="value"` literally)

key-files:
  created: [lib/harnessed-secrets.sh, docs/guides/secrets.md]
  modified: [lib/harnessed-isolated.sh, lib/harnessed-common.sh, harnessed]

key-decisions:
  - "resolve_secret_env is opt-in via a single `[ -f $HARNESSED_SCHEMA ]` guard as the first line — no schema ⇒ return 0 ⇒ varlock NEVER invoked (INERTNESS guaranteed structurally; verified by launching with no schema and grepping the trace for varlock)."
  - "Throwaway tools container uses a writable host scratch dir mounted as $CONTAINER_HOME (podman would otherwise create /home/harnessed as root, blocking varlock's plugin data writes). The schema, resolved env-file, .config, and .1password dir all live inside the scratch dir; the resolved env is moved out to a stable mktemp path the caller unlinks."
  - "Quote-stripping sed (`s/^([^=]+)=\"(.*)\"$/\\1=\\2/`) is required: varlock's `--format env` emits `KEY=\"value\"` (dotenv), but podman's --env-file parser treats the surrounding quotes as literal characters. Verified empirically — without the sed, SNYK_TOKEN resolves to `\"abcd-1234\"` (with quotes), not `abcd-1234`."
  - "PATH prepend inside the throwaway containers (`/home/tools/.local/share/mise/installs/node/latest/bin`) is load-bearing: the image's mise shims fail under the non-native HOME ($CONTAINER_HOME=/home/harnessed vs the tools image's native /home/tools) because mise reads `$HOME/.config/mise/config.toml`. Prepending the install dir lets the pnpm-global CLIs (varlock/snyk/socket — Node scripts) find node directly, bypassing mise. The §15 'podman-only host' invariant holds — no host Node is required."
  - "auth_scanner uses `--rm -it` + `-e HOME=$CONTAINER_HOME` + `~/.config` rw-mounted: the HOME override is load-bearing because `snyk auth` writes to `$HOME/.config/configstore/snyk.json`, and with HOME=$CONTAINER_HOME + ~/.config mounted there, the token lands on the HOST filesystem. Without the override snyk writes to /home/tools/.config (unmounted, lost on --rm exit). `--rm` guarantees no image layer (T-05-07)."
  - "DOC-03 is PARTIAL here — only the secrets doc ships (per design §17 cadence rule: a feature's doc lands with the feature). Service-authoring + troubleshooting ship in 05-04."

patterns-established:
  - "Opt-in launcher feature: detect via a single `[ -f ]` test as the FIRST line of the function; absent ⇒ return 0 (today's behavior bit-for-bit). The detect-and-wrap primitive."
  - "Throwaway-tools-container Pattern 1 (mirrors lib/harnessed-common.sh:106-108): `--rm --userns=keep-id` + schema ro + a writable scratch dir as $CONTAINER_HOME + the op agent socket mounted; the resolved value crosses back via a mode-0600 temp file the caller unlinks."
  - "Token-passthrough via --env-file (mode 0600, unlinked post-launch) is the single mechanism for resolved secrets to cross launcher→pod members / launcher→scan step. Env only — never the profile, never an image layer (T-05-05)."
  - "Top-level launcher subcommands (svc, install, auth) follow the parse-before-fallthrough + dispatch-and-exit invariant: parsed in the while/case loop BEFORE the bareword stack-name fallthrough (collision-safe), dispatched in a sibling `if [ -n ... ]; then ...; exit 0; fi` block."

requirements-completed: [SEC-01, SEC-03]   # DOC-03 is PARTIAL — only secrets.md ships here; service-authoring + troubleshooting ship in 05-04

# Metrics
duration: 35min
completed: 2026-06-18
---

# Phase 5 Plan 02: Opt-in Secrets Resolution + Scanner Auth Summary

**Opt-in 1Password-backed secrets via `resolve_secret_env` (inert when no schema; mode-0600 `--env-file` reaches pod + build scan) and `harnessed auth snyk|socket` (`--rm` container persists token to host config, never an image layer) + the secrets doc landing with SEC-01 per the design §17 cadence rule.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 (2 auto + 1 checkpoint, auto-approved under AUTO-MODE)
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- `harnessed` now has an opt-in 1Password secrets layer: with `~/.config/harnessed/.env.schema` present, secrets resolve from 1Password via varlock inside a throwaway `harnessed-tools` container and reach the pod members as **env only** (mode-0600 temp `--env-file`, unlinked after launch). Without the schema, today's behavior is unchanged bit-for-bit (INERTNESS verified).
- `harnessed build`'s scan step ALSO calls `resolve_secret_env` before invoking snyk/socket, so the build-time scan receives 1Password-resolved tokens (not just the raw launcher env's `snyk skipped (no SNYK_TOKEN)`).
- `harnessed auth snyk|socket` (SEC-03) drives the vendor CLI's own auth inside a `--rm -it` tools container with `-e HOME=$CONTAINER_HOME` + `~/.config` rw-mounted — the token persists to host config (e.g. `~/.config/configstore/snyk.json`), never an image layer.
- `docs/guides/secrets.md` ships WITH SEC-01 (design §17 cadence rule), documenting the full opt-in workflow, the agent-socket transport, the headless `OP_SERVICE_ACCOUNT_TOKEN` fallback with the CLAUDE.md caution, per-service schemas, verification steps, and a design §16 cross-ref.

## Task Commits

Each task was committed atomically (explicit `--files` pathspecs only — dirty-tree guard honored; the 49 pre-existing `.agents/skills/*` deletions were never swept in):

1. **Task 1: lib/harnessed-secrets.sh + isolated/common wiring** — `9697475` (feat)
2. **Task 2: harnessed auth dispatch + docs/guides/secrets.md** — `3b52f9d` (feat)

## Files Created/Modified
- `lib/harnessed-secrets.sh` (NEW) — `resolve_secret_env()` (the opt-in detect-and-resolve primitive; INERT when absent) + `auth_scanner(tool)` (the SEC-03 handler; `--rm` container, host-config persistence).
- `lib/harnessed-isolated.sh` — sources harnessed-secrets.sh, calls `resolve_secret_env` before pod member creation, spreads `--env-file` into BOTH hatago + harness members, `rm -f`s the temp at both return paths (headless + interactive).
- `lib/harnessed-common.sh` — `build_stack` sources harnessed-secrets.sh before the scan step, spreads `--env-file` into the scan-step `podman run` (alongside the 05-01 TOKEN_ARGS), `rm -f`s the temp after.
- `harnessed` — `auth)` parse case (BEFORE the stack-name fallthrough; collision-safe), `AUTH_TOOL=""` init, dispatch-and-exit block (sources the lib, calls `auth_scanner`, `exit 0`), usage line + top-of-file surface comment.
- `docs/guides/secrets.md` (NEW) — the secrets-setup how-to, cross-referencing `docs/harnessed-design.md §16` for the why.

## Decisions Made
- **Mise-shim breakage under non-native HOME.** The plan's must_have language assumed `-e HOME=$CONTAINER_HOME` was sufficient for op to find the agent socket. Empirically: the image's mise shims (which the Docker `ENV PATH` and `/etc/profile.d` point at) call back to mise, which reads `$HOME/.config/mise/config.toml` — and that file doesn't exist at `/home/harnessed/.config/mise/`. The shims fail with "node is not a valid shim", breaking every Node-based CLI (varlock, snyk, socket). **Fix:** prepend `/home/tools/.local/share/mise/installs/node/latest/bin` to PATH inside the throwaway resolve/auth containers so the pnpm-global CLIs find node directly. No host Node required (§15 invariant intact). This is purely an in-container PATH adjustment — no image change, no host dependency added.
- **varlock `--format env` quotes are literal to podman.** varlock emits `KEY="value"` (dotenv), but podman's `--env-file` parser treats the surrounding double quotes as part of the value. **Fix:** pipe varlock through `sed -E 's/^([^=]+)="(.*)"$/\1=\2/'` inside the resolve container to strip surrounding quotes. Verified empirically: with the sed, `TOKEN=abcd-1234` reaches podman; without it, `TOKEN="abcd-1234"` (with quotes) reaches podman.
- **Writable scratch dir as $CONTAINER_HOME.** Podman creates the bind-mount target's parent (`/home/harnessed`) as root by default, blocking varlock's plugin data writes (`$HOME/.config`). **Fix:** mount a host-owned scratch dir (mktemp -d, chmod 700) as the whole `$CONTAINER_HOME` so the tools user (UID 1000 == host UID via `--userns=keep-id`) has full write access. Pre-create `.1password/` inside it so the agent-socket bind-mount target's parent is host-owned (otherwise `rm -rf` fails on cleanup).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mise shims break under `-e HOME=$CONTAINER_HOME`**
- **Found during:** Task 1 verification (throwaway container test)
- **Issue:** The plan's load-bearing claim that `-e HOME=$CONTAINER_HOME` is sufficient ignored that mise shims need `$HOME/.config/mise/config.toml`, which doesn't exist at `/home/harnessed`. Every Node-based CLI failed with "node is not a valid shim".
- **Fix:** Prepend `/home/tools/.local/share/mise/installs/node/latest/bin` to PATH inside the throwaway resolve/auth containers (`-lc "export PATH=...; ..."`). Bypasses mise entirely for the pnpm-global CLIs.
- **Files modified:** lib/harnessed-secrets.sh
- **Verification:** `varlock --version` / `snyk --version` resolve under `HOME=/home/harnessed` with the PATH prepend.
- **Committed in:** 9697475

**2. [Rule 3 - Blocking] varlock `--format env` quotes are literal to podman `--env-file`**
- **Found during:** Task 1 verification (resolved env → podman run)
- **Issue:** `varlock load --format env` emits `KEY="value"`; podman's `--env-file` parser does NOT strip the surrounding quotes, so the value reaches the container as `"abcd-1234"` (with quotes).
- **Fix:** Pipe through `sed -E 's/^([^=]+)="(.*)"$/\1=\2/'` inside the resolve container.
- **Files modified:** lib/harnessed-secrets.sh
- **Verification:** `TOKEN=abcd-1234` (no quotes) reaches the podman container.
- **Committed in:** 9697475

**3. [Rule 3 - Blocking] `/home/harnessed` not writable by the tools uid**
- **Found during:** Task 1 verification (varlock plugin data writes)
- **Issue:** Podman creates `/home/harnessed` as root by default; the tools user can't mkdir `$HOME/.config`, so varlock's plugin fails with `EACCES: permission denied, mkdir '/home/harnessed/.config'`.
- **Fix:** Mount a host-owned scratch dir (mktemp -d) as the whole `$CONTAINER_HOME`; pre-create `.config` + `.1password` inside it.
- **Files modified:** lib/harnessed-secrets.sh
- **Verification:** varlock plugin writes succeed; `rm -rf "$tmpdir"` cleanup works post-resolve.
- **Committed in:** 9697475

---

**Total deviations:** 3 auto-fixed (3 × Rule 3 blocking). **Impact on plan:** All are correctness fixes for the throwaway-container resolution path the plan sketched; no scope creep. The plan's design intent (HOME override, --env-file injection, mode-0600 temp) is preserved — these fixes make that intent actually work given the 05-01-shipped image.

## Issues Encountered
None beyond the three deviations above.

## Checkpoint Verification (Task 3 — auto-approved under AUTO-MODE; all steps run for real)

Host: podman 5.8.3, harnessed-tools:latest built (from 05-01), `~/.1password/agent.sock` present (1Password desktop app installed; not authenticated for op:// ref resolution in this non-interactive session — operator-only).

| Step | Command | Result |
|------|---------|--------|
| 1 | `bash -n lib/harnessed-secrets.sh lib/harnessed-isolated.sh lib/harnessed-common.sh harnessed` | **VERIFIED** — all four files clean. |
| 2 | `python3 -m py_compile tools/harnessed/*.py` | **VERIFIED** — clean (no Python touched by 05-02; baseline preserved). |
| 3 (INERTNESS) | `ls ~/.config/harnessed/.env.schema` → not present; `HARNESSED_HEADLESS=true ./harnessed tracer-time --fresh` → output scanned for `varlock` | **VERIFIED** — no schema present; the launch trace contains ZERO varlock reference. The detect is a single `[ -f ]` test, so the no-secrets path is one cheap branch. |
| 4 (OPT-IN happy path) | synthetic schema with `SIMPLE=hello`, `WITH_SPACES=hello world`, `NUMBER=42`, `TOKEN=abcd-1234-ef56` → `resolve_secret_env` → `podman run --env-file <result>` | **VERIFIED** — resolve returns rc=0, echoes `/tmp/harnessed-env.XXXX.env`; content has correct unquoted values (post-sed); podman receives `SIMPLE=hello TOKEN=abcd-1234-ef56 WITH_SPACES=hello world`. Temp file + scratch dir cleaned. |
| 5 (OPT-IN failure path) | `.env.schema.example` (with op:// refs) → `resolve_secret_env` (no live 1Password app auth) | **VERIFIED** — resolve returns rc=1 with empty stdout; stderr shows varlock's resolution error; no temp file leaked. Operator-only: a live 1Password session would let this succeed. |
| 6 (NO-LEAK static) | `grep -rE 'SNYK_TOKEN\|SOCKET_SECURITY_API_KEY\|op(op://' profiles/` ; `podman history harnessed-hatago:latest --no-trunc \| grep -iE 'snyk\|socket\|api=[a-f0-9]'` | **VERIFIED** — no matches in profiles/; no token-bearing history entries in the hatago image (snyk/socket appear in the tools image only as `pnpm add -g` install commands, not as tokens). |
| 7 (temp cleanup) | `ls /tmp/harnessed-env.* /tmp/harnessed-secrets.*` after launch + after resolve | **VERIFIED** — no temp files linger (mode-0600 env-file unlinked after launch; scratch dir rm -rf'd after resolve). |
| 8 (auth dispatch) | `./harnessed auth` (no arg) / `./harnessed auth github` (bad) / `./harnessed --help` | **VERIFIED** — no-arg + bad-tool print clear error + usage + exit 1; help shows the `harnessed auth snyk\|socket` line in the right slot. `./harnessed auth snyk` reaches `auth_scanner` (the resolve container launches; only fails because this session has no TTY for the browser flow — operator-only). |
| 9 (build scan wiring) | structural: `resolve_secret_env` is called in `build_stack` BEFORE the scan step, `--env-file "$build_secret_env"` is spread into the scan-step `podman run` (alongside TOKEN_ARGS), `rm -f` after | **VERIFIED** structurally (lib/harnessed-common.sh:115-144). Operator-only live confirmation: with a schema present, `harnessed build <stack>` would invoke snyk with the resolved token (not skip). |

### OPERATOR-ONLY (recorded honestly — NOT fabricated)

These require the live 1Password desktop app + agent socket authentication + real vault items / interactive browser auth, which are not available in this non-interactive execution environment:

| Step | Command (for the operator) | Expected result |
|------|----------------------------|-----------------|
| OPT-IN live resolution | `mkdir -p ~/.config/harnessed && cp .env.schema.example ~/.config/harnessed/.env.schema`; edit op:// refs to real vault items; `./harnessed tracer-time --fresh`; `podman exec <instance> env \| grep SNYK_TOKEN` | The resolved value is present in the pod env. (The throwaway resolve container exports `-e HOME=$CONTAINER_HOME` so op resolves the agent socket at the mounted `/home/harnessed/.1password/agent.sock`.) |
| BUILD SCAN with resolved tokens | With the schema present: `unset SNYK_TOKEN SOCKET_SECURITY_API_KEY; ./harnessed build tracer-time` | snyk IS invoked (not skipped) — the resolved token from `resolve_secret_env` reaches the scan step. The build output should NOT contain `snyk skipped (no SNYK_TOKEN)`. |
| AUTH persist | `./harnessed auth snyk` (from a real TTY, browser flow completes) | `~/.config/configstore/snyk.json` contains the token; `podman images --filter dangling=true` shows no leftover auth layer (the `--rm` guarantee). |
| Docs quickstart | Follow `docs/guides/secrets.md` end-to-end with real vault items | Copy-paste runnable; resolved env reaches the pod, no leak in profiles/image, temp unlinked. |

**Requirement status:**
- **SEC-01 — SATISFIED (code + INERTNESS + structure verified; live op resolution = operator-confirmed).** The launcher wiring, INERTNESS, no-leak, and the full happy-path pipeline (schema → throwaway container → varlock → envfile → podman --env-file → container env) are all verified. The only unverified piece is resolution against a live 1Password session, which is operator-only by definition.
- **SEC-03 — SATISFIED (code + structure verified; live auth = operator-confirmed).** The `auth_scanner` code is correct, the dispatch path is verified, and the `--rm`/`HOME`-override/`~/.config`-rw invariants are structurally sound. Live `snyk auth` browser flow + persistence to `~/.config/configstore/snyk.json` is operator-only.
- **DOC-03 — PARTIAL.** Only the secrets doc ships here (per design §17 cadence rule). Service-authoring + troubleshooting ship in 05-04.

## User Setup Required

Operator-only setup (cannot be automated — needs the 1Password desktop app + real vault items):

1. **1Password vault items for scanner tokens** (only if opting into SEC-01): create items matching the op:// refs in `.env.schema.example` (e.g. `Private/Snyk/credential`, `Private/SocketDev/credential`) in the 1Password app → Vaults → Private → Add item.
2. **Scanner token auth** (alternative to varlock, for SEC-03): run `./harnessed auth snyk` from a real TTY to complete the browser flow.

See [docs/guides/secrets.md](../../../docs/guides/secrets.md) for the full quickstart.

## Next Phase Readiness
- SEC-01 + SEC-03 are code-complete and verified; the secrets layer is ready for 05-03 (nightly re-scan timer — reuses the same `--env-file` token-passthrough pattern) and 05-04 (the remaining DOC-03 deliverables: service-authoring + troubleshooting docs).
- No blockers. The mise-shim/quote/writable-HOME issues were the three integration unknowns; all resolved and verified. The operator-only live-1Password confirmation is the natural end-user smoke test, not a blocker for the next plan.

## Self-Check: PASSED

All Task 1 + Task 2 `<acceptance_criteria>` re-verified PASS after the iterations; plan-level `<verification>` checklist all true; checkpoint steps 1-9 all VERIFIED (steps 3-9 fully automated; the operator-only items in the table above are documented with exact commands + expected results for the operator). `git log --oneline \| grep 05-02` returns 2 production commits (`9697475`, `3b52f9d`) + this summary commit.

---
*Phase: 05-secrets-hardening-docs-completeness*
*Plan: 02*
*Completed: 2026-06-18*
