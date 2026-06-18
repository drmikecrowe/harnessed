---
phase: 05-secrets-hardening-docs-completeness
review: 05-REVIEW
status: issues            # clean | issues | skipped — medium + 1 low resolved post-review (3 low remain)
scope: source/config changes shipped in phase-05 commits (31067bb..5201b77); docs excluded
reviewer: Reviewer-05 (security-focused code review, advisory / non-blocking)
date: 2026-06-18
finding_counts: { high: 0, medium: 0, low: 3 }   # was {0,1,4}; #1(med)+#3(low) fixed in e494520
addressed_post_review: { "1": "e494520", "3": "e494520" }
---

# Phase 05 — Source Code Review (advisory)

Scope = the 11 source/config artifacts touched by the four phase-05 plans
(`git diff --name-only 31067bb^..5201b77`, docs excluded):

| area | files |
|------|-------|
| Python (scanner/auth CLI) | `tools/harnessed/scan.py`, `tools/harnessed/cli.py` |
| Shell — new, security-critical | `lib/harnessed-secrets.sh`, `lib/harnessed-rescan.sh` |
| Shell — modified | `lib/harnessed-common.sh`, `lib/harnessed-isolated.sh`, `harnessed` (launcher) |
| Supply chain | `tools/Dockerfile`, `tools/pnpm-workspace.yaml` |
| Systemd | `systemd/harnessed-rescan.service`, `systemd/harnessed-rescan.timer` |

`tools/harnessed/assemble.py`, `capability.py`, `schema.py` were **not** touched by phase 05
(verified against the diff) and are out of scope.

**Headline:** the secrets-handling design is sound — env-only injection, mode-0600 temp files,
`--rm` auth containers, inert-until-schema, correct scanner exit-code semantics. One **medium**
info-disclosure gap (temp secret env-file not cleaned on `set -e` error paths — no trap handler)
plus four **low** robustness/supply-chain notes. Nothing blocks; all are advisory.

---

## Findings

| # | Severity | Location | Issue | Recommendation |
|---|----------|----------|-------|----------------|
| 1 | **medium** | `lib/harnessed-isolated.sh:153-217` | **Resolved-secret temp file leaks on `set -e` error paths.** `secret_env` (the mode-0600 plaintext env-file holding resolved API tokens) is created at L153 and unlinked only at the two *happy* return points (L197 headless, L217 post-attach). Between those, several un-captured commands can trip `set -e` and abort the whole launcher: the hatago member `podman run -d` (L163-167), the harness member `podman run -d` (L177-179), `apply_firewall` (L182). There is **no `trap` handler anywhere** in `lib/` or the launcher (confirmed). On such an abort the file persists in `$TMPDIR` with an *unbounded* lifetime (until systemd-tmpfiles/reboot) — exactly the window T-05-06 was written to close, and the mitigation lands on the happy paths only. Mode-0600 limits readers to the invoking uid, which keeps this medium rather than high. (`build_stack` in `harnessed-common.sh:122-144` is **not** affected — its scan exit is captured with `\|\| src_rc=$?`, so the L144 unlink always runs.) | Add an exit/return trap that unlinks the temp file on every path, e.g. a launcher-level `trap 'rm -f "$_HARNESSED_SECRET_ENV" ...' EXIT` (set the var right after `resolve_secret_env`), or capture each post-resolution `podman run`/`apply_firewall` exit and unlink before re-raising. Cheap, closes T-05-06 fully. |
| 2 | **low** | `lib/harnessed-secrets.sh:99` | **Hand-rolled dotenv unquoter is fragile for escaped chars.** The `varlock load --format env \| sed -E 's/^([^=]+)="(.*)"$/\1=\2/'` strips surrounding double-quotes (needed because podman `--env-file` keeps them literally). Verified empirically: correct for typical alphanumeric tokens (`KEY="abc"`→`abc`) and for `=`-in-value (`EQ="a=b"`→`a=b`), but it does **not** unescape `\"` (`ESC="a\"b"`→`a\"b`, stray backslash) or `\\` (`BS="a\\b"`→`a\\b`). A dotenv emitter following spec escapes those; a secret containing a quote/backslash would be stored verbatim-wrong in the container env. Defense-in-depth: if varlock ever emitted an *unescaped* newline in a value, line-by-line sed + podman `--env-file` could inject a spurious `KEY=…` line (varlock is audited `[OK]` to escape, so this is latent, not active). | Prefer a real dotenv consumer over sed. If sed stays, make it quote/backslash-aware (`s/\\(.)/\1/` on the captured value) and add a unit test with `"`/`\`/newline-containing fixtures. Low practical risk for current API-token-shaped secrets. |
| 3 | **low** | `lib/harnessed-rescan.sh:37-45` | **`podman save` is not error-captured → leaks the tar and aborts the nightly.** `tar=$(mktemp --suffix=.tar)` (L37) then `podman save "$img" -o "$tar"` (L38) with no `\|\| …`. Under `set -e`, a save failure (e.g. an image removed between the `images` listing and the save, or a transient podman error) aborts the **entire** `harnessed_rescan_images` run *and* leaves the (potentially large) `.tar` in `/tmp` — the `rm -f "$tar"` at L45 is post-scan and unreachable. This defeats the loop's stated finding-isolation intent (which is correctly applied to the *scan* step at L43-44). One unsaveable image should not kill the nightly or leak disk. | Wrap the save: `"$CONTAINER_RUNTIME" save "$img" -o "$tar" \|\| { rm -f "$tar"; print_error "save failed for $img — skipping"; rc=1; continue; }`. No secret content in the tar, so this is robustness/disk, not disclosure. |
| 4 | **low** | `lib/harnessed-secrets.sh:91-104` | **Failure-path error block is ineffective (and the `2>&1` is a no-op).** `errout="$(podman run … -lc '…; varlock … \| sed … > file')" 2>&1 \|\| rc=$?`. Command substitution captures only podman's **stdout**, but varlock's output is redirected to the file *inside* the container — so podman stdout is empty and `errout` is always `""`. varlock/podman diagnostics instead flow **live** to the terminal (not captured). Net: the `printf '%s\n' "$errout"` on failure prints nothing useful. (Security upside: no secret-bearing stream is captured/echoed — good.) The `2>&1` after the closing `"` redirects the assignment's fds, which emit nothing, so it does nothing. | Capture podman stderr deliberately for the failure message — e.g. redirect the inner command's stderr to a second temp file and print a *tail* of it (avoid echoing anything that could be a resolved value). Or simply drop `$errout` and document that diagnostics stream live. Minor. |
| 5 | **low** | `tools/Dockerfile:113, 62-68` | **Runtime pins are major, not exact.** `mise use -g node@24 pnpm@11` (L113) pins the major only — a rebuild resolves the latest `24.x`/`11.x` and can drift. `op` (1password-cli, L62-68) is installed via apt with **no** version pin. The secret-handling CLIs are correctly exact (`varlock@1.7.1 @varlock/1password-plugin@1.2.0 snyk@1.1305.1 socket@1.1.122`, L122) and osv-scanner is pinned+checksummed (`ARG OSV_SCANNER_VERSION=2.3.8` + SHA256SUMS verify, L38-55). | Acceptable as-is (matches `base/Dockerfile.harnessed-base` precedent). If bit-for-bit reproducible tools images become a goal, pin node/pnpm to exact patches and pin `op` to a release. |

---

## Positive observations

- **Env-only secret injection is clean end-to-end.** `resolve_secret_env` writes resolved values
  only to a throwaway scratch dir → mode-0600 temp file under `$TMPDIR`; nothing is written to
  `profiles/`, the `run_claude` state dir, `.claude.json`, `.mcp.json`, or any image layer. The
  value crosses launcher→pod only via `--env-file` (spread into both pod members, L163-179). This
  is exactly the T-05-05 mitigation. (Note, accepted by design: the resolved vars are visible in
  `podman inspect <running-container>` while the pod is up — transient, gone on container removal,
  strictly better than baking them into a layer.)
- **`--rm` + `-e HOME=$CONTAINER_HOME` auth path is correct.** `auth_scanner` (L129-178) uses
  `--rm -it` so no image layer captures the token (T-05-07), and the HOME override is load-bearing
  — without it `snyk auth` writes to the unmounted `/home/tools/.config` and the token is lost on
  `--rm` exit. The same `-e HOME=$CONTAINER_HOME` is applied consistently in `resolve_secret_env`
  (L93) so `op` resolves the mounted agent socket.
- **Inert-until-schema is genuinely one test.** `resolve_secret_env` opens with
  `[ -f "$HARNESSED_SCHEMA" ] || return 0` (L48) — a single `[ -f ]`, no varlock invocation, no
  side effect when the schema is absent. Today's bit-for-bit behavior is preserved.
- **Scanner exit-code semantics are exactly right and explicitly de-conflated.** `_scan_snyk`
  (scan.py:226-258) maps snyk exit 1→HIGH abort, 2/3→warn, 0→clean, and the docstring calls out
  that this must **not** be treated like osv-scanner's exit-1=any-finding. osv's HIGH decision is
  made over parsed JSON (`gate(data)`), never over its exit code. The fail-closed branch (exit 1
  with no parseable ids → surface as HIGH, L252-253) is a nice touch.
- **Rescan finding-isolation works for the scan step.** `img_rc=0; … scan-image-online … || img_rc=$?`
  (rescan.sh:42-44) swallows the HIGH exit so the loop continues; overall `rc` tracks any failure;
  the launcher correctly lets the non-zero return propagate as its exit code (`exit 0` is reached
  only on the all-clean path, harnessed:304-312). The `while … < <(…)` form avoids the subshell
  that would lose `rc` mutations — good, and well commented.
- **`set -euo pipefail` discipline is strong.** The `${VAR:-}` idiom is used everywhere a var may
  be unset (build_stack L136-137, secrets.sh L79, launcher L296). Empty-array spreads
  (`"${env_args[@]}"`, `"${TOKEN_ARGS[@]}"`, `"${build_env_args[@]}"`) are safe under `set -u` —
  verified: a declared-empty array expands to zero args with no error.
- **Supply-chain allowlist is minimal and scoped.** `pnpm-workspace.yaml` lists `allowBuilds:
  { snyk: true }` only; `minimumReleaseAgeExclude: [socket@1.1.122]` (Dockerfile L102) is scoped to
  the exact audited pin, not a blanket bypass. osv-scanner is downloaded over HTTPS and
  checksum-verified against the release `SHA256SUMS` before `chmod +x` (L40-47) — the
  unverified-download threat (T-03-05 ancestry) is mitigated.
- **Warn-and-skip, never prompt.** snyk/socket/pip-audit all degrade to warnings on missing
  token / network / quota failure and never abort for the wrong reason (scan.py:238-240, 271-277,
  191-195). `resolve_secret_env` is intentionally fail-closed instead (a *present* schema that
  won't resolve must abort) — the two semantics are correctly split by intent.

---

## Per-file notes

### `tools/harnessed/scan.py` (modified: +`_scan_snyk`, `_scan_socket`, `_snyk_vuln_ids`,
`_socket_alerts`, `run_image_scan_online`; snyk/socket wired into `run_source_scan`)
- Exit-code mapping and JSON-gate separation are correct (see Positives). `_run` (L160-165) bounds
  every invocation with `_TIMEOUT=300` (T-05-03) and raises `ScanError` only on subprocess
  *infrastructure* failure, never on a scanner's non-zero exit. Token values are never logged —
  only `os.environ.get(...)` boolean checks (T-05-02). `_socket_alerts` defensively handles three
  nested JSON shapes. No injection surface: all commands are `list[str]` to `subprocess.run` (no
  shell). Clean.

### `tools/harnessed/cli.py` (modified: +`scan-image-online` parser/handler)
- `scan-image-online` (L105-109, 184-198, 214-215) mirrors `scan-image` and returns 1 on
  `ScanError`, 0 otherwise. The `HIGH < CVSS 7.0` threshold string is duplicated inline (L195)
  rather than imported from `scan.HIGH` — cosmetic only. Clean.

### `lib/harnessed-secrets.sh` (NEW — security-critical)
- Inertness, mode-0600, `--rm`, HOME override, scratch-dir hygiene all correct (see Positives).
  The scratch `tmpdir` is `rm -rf`'d on both success (L121) and failure (L102); the `.1password`
  dir is pre-created host-owned (L65) so the socket bind-mount parent doesn't get root-owned and
  block cleanup — careful. Findings #2 and #4 above are the only nits. `OP_SERVICE_ACCOUNT_TOKEN`
  is forwarded only when already in the launcher env and never prompted/exported (T-05-09). The
  schema is operator-owned (`~/.config/harnessed/.env.schema`), never recipe-authored (T-05-08).

### `lib/harnessed-rescan.sh` (NEW)
- Loop isolation, `reference='harnessed-*'` scoping (not all images), and the `< <(…)` non-subshell
  form are correct. Finding #3 (un-captured `podman save`) is the only gap. Tar is cleaned after
  each *scan*; the leak is only on the save-failure path.

### `lib/harnessed-common.sh` (`build_stack` — TOKEN_ARGS + resolve_secret_env wiring)
- Clean. The resolved env is unlinked at L144 immediately after the error-captured scan run, so
  the secret file is removed even when the scan finds a HIGH. `TOKEN_ARGS` uses the
  `${VAR:-}` idiom. Notably this path does **not** share finding #1 — its cleanup is on all paths.

### `lib/harnessed-isolated.sh` (`--env-file` spread into both pod members + unlink)
- The `--env-file` is correctly spread into **both** the hatago (L164) and harness (L178) members
  so resolved secrets reach the whole pod as env only. **This is the file with finding #1** — the
  two unlinks (L197, L217) cover the happy paths but not the `set -e` aborts between resolution
  and attach.

### `harnessed` launcher (`auth` / `rescan` dispatch)
- Both new subcommands are parsed **before** the bareword stack-name fallthrough
  (collision-safe — a stack named `auth`/`rescan` can't collide, mirroring `svc`/`install`), then
  dispatched in sibling `if …; then …; exit 0; fi` blocks (L296-313). `auth` validates the tool
  against `snyk|socket` before dispatch. The rescan dispatch correctly lets a non-zero
  `harnessed_rescan_images` propagate (the trailing `exit 0` is reached only when clean). Clean.

### `tools/Dockerfile` + `tools/pnpm-workspace.yaml` (supply chain)
- Secret-handling CLI pins are exact; osv-scanner is pinned + SHA256-verified; allowBuilds is
  snyk-only; minimumReleaseAgeExclude is version-scoped. Finding #5 (node@24/pnpm@11 major pins;
  `op` via unpinned apt) is the only note. The `/etc/profile.d` PATH shim (L86-87) correctly
  re-exports the pnpm-global + mise PATH for login shells (the 05-02 varlock path uses `bash -lc`).

### `systemd/harnessed-rescan.{service,timer}`
- `Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan`, `OnCalendar=daily`,
  `Persistent=true`. The timer correctly documents the `loginctl enable-linger` prerequisite
  (without it the user instance is torn down on logout and the timer never fires). No secrets are
  involved (online osv scan is credential-free). Optional hardening (NoNewPrivileges /
  ProtectSystem) would be nice-to-have for a user unit but is not required.

---

## STRIDE / threat-register cross-check (did the mitigations land?)

| Threat | Register | Mitigation as shipped | Status |
|--------|----------|-----------------------|--------|
| snyk postinstall vs `strictDepBuilds` | T-05-01 | `allowBuilds: { snyk: true }` in `tools/pnpm-workspace.yaml` (kept defensively; SUMMARY notes the binary is fetched lazily so it was not load-bearing). | landed |
| Scanner token echoed in logs | T-05-02 | Boolean `os.environ.get(...)` gates; token value never logged/echoed. | landed |
| Scanner CLI hang | T-05-03 | `_TIMEOUT=300` bounds every `_run()` incl. snyk/socket; socket net failure warn-and-skip. | landed |
| Stale plugin pin (0.3.2→1.2.0) | T-05-04 | `@varlock/1password-plugin@1.2.0` in Dockerfile L122 + `.env.schema.example`. | landed |
| Slopsquatch / new npm packages | T-05-05 / T-05-SC | All `[OK]` per audit; exact pins; `minimumReleaseAge=1440` + `strictDepBuilds`; scoped exclude for socket freshness. | landed |
| Resolved secret baked into profile/image | T-05-05 (05-02) | Env-only `--env-file`; never written to `profiles/`, state dir, `.claude.json`, `.mcp.json`, layer. | landed |
| Temp env-file persists past launch | T-05-06 | `chmod 600` + `rm -f` after attach **on happy paths**. **Error paths uncovered — finding #1.** | partial |
| Token persisted to image layer via `auth` | T-05-07 | `--rm -it` + `-e HOME=$CONTAINER_HOME` + rw `~/.config`; token lands on host, no layer. | landed |
| Malicious schema via recipe/stack | T-05-08 | Schema is operator-owned (`~/.config/harnessed/.env.schema`), not recipe-authored. | landed |
| `OP_SERVICE_ACCOUNT_TOKEN` lingering | T-05-09 | Forwarded only if already in launcher env; socket preferred; never exported/prompted. | landed |
| varlock needs host Node | T-05-10 | Resolution runs inside throwaway `harnessed-tools` container (Pattern 1); host stays podman-only. | landed |

**Verdict:** 10 of 11 mitigations fully landed; T-05-06 landed on the intended (happy) paths but
its error-path coverage is incomplete (finding #1). No mitigation is *missing*; the gap is a
cleanup-on-failure refinement.

---

## Advisory note

This review is advisory and non-blocking. The phase-05 source is sound; the one medium finding
(#1) has a small, localized fix (a cleanup trap) and a mode-0600/$TMPDIR blast radius that keeps
it from being high-severity. The four low findings are robustness and supply-chain hygiene
improvements. Recommended as follow-ups, not gates.

---

## Post-review: findings addressed

Two findings were fixed inline after this review (the medium security gap + the rescan-save
low), committed as `fix(05): secret temp env-file cleanup on error paths + resilient rescan save`
(`e494520`):

- **#1 (medium → resolved):** `lib/harnessed-isolated.sh` now installs a scoped `RETURN` trap
  immediately after `resolve_secret_env` succeeds, so the mode-0600 temp env-file is unlinked on
  *any* exit from `harnessed_isolated` — a `set -e` abort on either member `podman run`, the
  readiness wait, `apply_firewall`, or an early return — not only the two happy-path `rm -f`s at
  the tail (which remain as harmless belts). This closes T-05-06 on **all** paths.
- **#3 (low → resolved):** `lib/harnessed-rescan.sh` now wraps `podman save` in `if ! …; then
  rm -f "$tar"; rc=1; continue; fi`, so one unsaveable image (removed between list and save, or a
  transient podman error) skips without aborting the nightly or leaking the tar — mirroring the
  scan step's finding-isolation.

Re-verified: `bash -n` clean on both files; live `./harnessed rescan` still returns exit 0 with
all images clean (online) — the save-step wrap does not perturb the loop.

**Remaining open (3 low, non-blocking, accepted as follow-ups):** #2 (varlock dotenv unquoter is
not backslash/quote-escaping-aware — latent for non-alphanumeric secrets; varlock is audited to
escape, so not active today); #4 (secrets.sh failure-path `errout` capture is a no-op — podman
stderr already flows live to the terminal, and no secret is echoed); #5 (Dockerfile node@24 /
pnpm@11 are major pins, `op` via unpinned apt — matches the base-image precedent; only a concern
if bit-for-bit reproducible tools images become a goal).
