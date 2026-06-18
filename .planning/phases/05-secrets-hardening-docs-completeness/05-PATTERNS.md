# Phase 5: Secrets, Hardening + Docs Completeness - Pattern Map

**Mapped:** 2026-06-18
**Files analyzed:** 17 new/modified files (5 in plan 05-01; 5 in plan 05-02; 6 in plan 05-03; 6 in plan 05-04; the secrets doc is sequenced into 05-02 per the design §17 cadence rule — it ships with SEC-01 in plan 05-02)
**Analogs found:** 12 / 17 (5 are documentation deliverables with no in-repo prose analog — their *content* sources are listed instead)

> **No CONTEXT.md exists** (mode: yolo). The file list below is extracted from `05-RESEARCH.md` alone — its "Recommended file touch-list" (§Architecture Patterns) + the SEC-01..04 / DOC-01..03 requirement rows. Locked constraints are lifted from `CLAUDE.md` (treated as authority-equivalent per the research's `<user_constraints>`).

## File Classification

| New/Modified File | Plan | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `tools/Dockerfile` (modify) | 05-01 | config | build / file-I/O | `tools/Dockerfile:37-55` (osv-scanner layer) + `base/Dockerfile.harnessed-base:27-33, 64-80` (op apt + mise node) | **exact** (same file, extend the scanner/toolchain layer) |
| `tools/pnpm-workspace.yaml` (new, in tools build ctx) | 05-01 | config | config | `lib/pnpm/config.yaml` (⚠ read the caveat — see assignment) | **role-match** (new project-scoped file; `allowBuilds` is rejected from the global config in pnpm v11) |
| `tools/harnessed/scan.py` (modify) | **05-01** + **05-03** | service | subprocess / request-response | `tools/harnessed/scan.py:159-254` (`_run`, `_scan_source_osv`, `_audit_pip`, `run_image_scan`) | **exact** (same file, add 2 invokers + 1 online variant) |
| `tools/harnessed/cli.py` (modify) | **05-03** | controller | request-response | `tools/harnessed/cli.py:28-105, 167-194` (`_build_parser` scan-image subparser + `_run_scan_image`) | **exact** (same file, add `scan-image-online` subcommand) |
| `tools/harnessed/secrets.py` (new, optional) | — (n/a — bash path chosen in 05-02) | utility | subprocess / transform | `tools/harnessed/scan.py:159-164` (`_run` capture pattern) | **role-match** (only if the planner elects a Python resolve helper over bash; RESEARCH Open Q1 default is bash `lib/harnessed-secrets.sh`) |
| `lib/harnessed-secrets.sh` (new) | **05-02** | utility / service | subprocess / file-I/O | `lib/harnessed-services.sh:68-130` (`svc_up` — `--rm`/`-d` container w/ host paths) + `lib/harnessed-common.sh:106-108` (throwaway tools container) | **role-match** (new lib; closest shape = svc_up's container launch + build_stack's throwaway tools invocation) |
| `harnessed` launcher (modify) | **05-02** + **05-03** | controller | request-response | `harnessed:102-176` (`svc`/`install`/`new` dispatch) + `harnessed:36-68` (`usage()`) | **exact** (same file, add `auth`/`rescan` case blocks + usage lines) |
| `lib/harnessed-common.sh::build_stack` (modify) | **05-01** + **05-02** | controller | request-response | `lib/harnessed-common.sh:116-118` (the scan invocation being extended) | **exact** (same function, pass `-e SNYK_TOKEN -e SOCKET_SECURITY_API_KEY`) |
| `lib/harnessed-isolated.sh::harnessed_isolated` (modify) | **05-02** | controller | request-response | `lib/harnessed-isolated.sh:90, 145-164` (MOUNT_ARGS + member launch) | **exact** (same function, call `resolve_secret_env` + pass `--env-file`) |
| `systemd/harnessed-rescan.timer` (new) | **05-03** | config | event-driven | — (no systemd units in repo) | **no analog** → RESEARCH Pattern 4 + Red Hat `podman-auto-update.timer` |
| `systemd/harnessed-rescan.service` (new) | **05-03** | config | event-driven | — (no systemd units in repo) | **no analog** → RESEARCH Pattern 4 |
| `.env.schema.example` (modify) | 05-01 | config | config | `.env.schema.example` (itself — bump the plugin pin) | **exact** (same file, one-line version bump + API verify) |
| `docs/guides/secrets.md` (new) | **05-02** (cadence) | docs | file-I/O | — (no how-to docs) | **no analog** → content sources: `.env.schema.example` + `docs/harnessed-design.md` §16 |
| `README.md` (new/refresh) | **05-04** | docs | file-I/O | `AGENTS.md` (the OLD `container` setup — supersede) + `docs/harnessed-design.md` §1-§2 | **role-match** (AGENTS.md is the closest existing prose; README is the new entry point) |
| `docs/guides/recipe-authoring.md` (new) | **05-04** | docs | file-I/O | — (no how-to docs) | **no analog** → worked-example source: `recipes/time/recipe.yaml`, `recipes/ping/recipe.yaml` |
| `docs/guides/stacks.md` (new) | **05-04** | docs | file-I/O | — (no how-to docs) | **no analog** → worked-example source: `stacks/tracer-time/stack.yaml`, `stacks/transparent/stack.yaml`, `stacks/ping-time/stack.yaml` |
| `docs/guides/service-authoring.md` (new) | **05-04** | docs | file-I/O | — (no how-to docs) | **no analog** → worked-example source: `services/ping/` (Dockerfile + server.py + service.yaml) |
| `docs/guides/troubleshooting.md` (new) | **05-04** | docs | file-I/O | — (no how-to docs) | **no analog** → content: podman socket, first-run build, `--fresh`, host-persisted sessions (`lib/harnessed-isolated.sh:105-112`) |

> **Plan split (actual — 4 plans):** 05-01 = SEC-02 (tools image + token-gated scanners); 05-02 = SEC-01 (opt-in secrets) + SEC-03 (scanner auth) + the cadence-gated `docs/guides/secrets.md`; 05-03 = SEC-04 (nightly timer); 05-04 = DOC-01/02/03 (docs). The secrets doc ships inside 05-02 (with SEC-01 — a reader of the secrets feature has the doc the moment it lands; design §17).

---

## Pattern Assignments

### `tools/Dockerfile` (config, build/file-I/O) — plan 05-01

**Analog:** the file's own scanner layer (`:37-55`) for the new CLIs; `base/Dockerfile.harnessed-base:27-33` for the `op` apt install; `base/Dockerfile.harnessed-base:64-80` for the mise-managed Node layer (the precedent the research's Open Q2 / A5 points at).

**The osv-scanner layer to extend (the verify-checksum-before-chmod precedent — Threat T-03-05):** `tools/Dockerfile:37-55`:
```dockerfile
ENV XDG_CACHE_HOME=/opt/osv-cache
ARG OSV_SCANNER_VERSION=2.3.8
RUN mkdir -p /tmp/osv-dl \
    && curl -fsSL -o /tmp/osv-dl/osv-scanner_linux_amd64 \
        "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64" \
    && curl -fsSL -o /tmp/osv-dl/osv-scanner_SHA256SUMS \
        "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_SHA256SUMS" \
    && cd /tmp/osv-dl \
    && grep ' osv-scanner_linux_amd64$' osv-scanner_SHA256SUMS | sha256sum -c - \
    && mv osv-scanner_linux_amd64 /usr/local/bin/osv-scanner \
    && chmod +x /usr/local/bin/osv-scanner \
    && osv-scanner --version \
    && rm -rf /tmp/osv-seed /tmp/osv-dl \
    && test -d "${XDG_CACHE_HOME}/osv-scanner" \
    && chown -R 1000:1000 "${XDG_CACHE_HOME}"
```
The new varlock/snyk/socket layer mirrors this discipline: pin the version (`ARG`), fetch, verify, smoke-test (`<cli> --version`). snyk + socket come via `pnpm add -g` (see the pnpm assignment below), so they are NOT curl-installed — but the **checksum-verify-before-trust** ethos applies to the apt key for `op`.

**The `op` apt install precedent (apt key + signed-by):** `base/Dockerfile.harnessed-base:27-33`:
```dockerfile
# 1Password CLI + desktop app (for SSH signing with op-ssh-sign)
RUN curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
    tee /etc/apt/sources.list.d/1password.list && \
    apt-get update && apt-get install -y 1password 1password-cli && \
    rm -rf /var/lib/apt/lists/*
```
The tools image needs only `1password-cli` (the `op` binary), not the desktop app — copy the key-ring + signed-repo shape, drop `1password` (desktop) from the install list. This is the documented `op` install path (RESEARCH Standard Stack).

**The mise Node precedent (the Node-layer decision, Open Q2 / A5):** `base/Dockerfile.harnessed-base:64-80`:
```dockerfile
# npm.package_manager=pnpm routes the npm: tools through pnpm so the managed policy governs them
# (RESEARCH Pitfall 5); set BEFORE `mise use -g`. pnpm@11 (not @latest) so the v11 supply-chain
# defaults are in effect (Node 22+ required).
RUN mise settings set experimental true && \
    mise settings set npm.package_manager pnpm && \
    mise use -g \
        node@22 \
        pnpm@11 \
        ...
```
The tools image is `FROM python:3.13-slim` (`tools/Dockerfile:13`) with **no Node today**. Adding `mise use -g node@24 pnpm@11` (the base-image precedent) is the recommended path so `pnpm add -g varlock @varlock/1password-plugin snyk socket` honors the supply-chain policy. **Note:** the tools image currently does NOT install mise — the planner either adds a mise layer (mirror `base/Dockerfile.harnessed-base:50-52`) or installs Node directly. The base image is the established precedent.

**The pnpm-config COPY precedent (the policy must be in place BEFORE pnpm resolves globals):** `base/Dockerfile.harnessed-base:54-62`:
```dockerfile
USER root
COPY lib/pnpm/config.yaml /tmp/pnpm-config.yaml
RUN mkdir -p /home/${USERNAME}/.config/pnpm && \
    mv /tmp/pnpm-config.yaml /home/${USERNAME}/.config/pnpm/config.yaml && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/.config
USER ${USERNAME}
```
Phase 5 MUST replicate this in the tools image (it currently has a comment at `tools/Dockerfile:60-62` explicitly deferring it: *"pnpm supply-chain config is intentionally NOT baked here... Bake the policy when node deps actually land (phase-3 checkpoint 03-01 finding B)."*). That checkpoint is now. **Critical:** the COPY source must be `lib/pnpm/config.yaml` from the **repo root build context** — `tools/Dockerfile`'s build context is `tools/` (`lib/harnessed-common.sh:83` passes `"$HARNESSED_DIR/tools"`), so the planner must either widen the context or COPY from a path that reaches `lib/pnpm/config.yaml`. The current tools context CANNOT see `lib/`.

---

### `tools/pnpm-workspace.yaml` (config) — plan 05-01  ⚠ critical caveat

**Analog:** `lib/pnpm/config.yaml` — but read its own self-documenting comment block (`:18-28`) before copying anything:

```yaml
strictDepBuilds: true            # lifecycle default-deny: non-zero exit on any unreviewed build/postinstall script.
# allowBuilds is intentionally NOT set here. pnpm v11 rejects it from the global config
# ("Move them to a project-level pnpm-workspace.yaml") and silently ignores it — setting
# it here warns on every run and gives a false sense of being configured. The allowlist is
# project-scoped (pnpm-workspace.yaml / config-dependencies) and does NOT apply to global installs.
```

**Pattern for the planner:** RESEARCH Pitfall 3 says "add `snyk: true` to the tools-image `allowBuilds`." That is correct in intent but the **mechanism is a new project-scoped `pnpm-workspace.yaml`** in the tools build context — NOT an edit to the global `lib/pnpm/config.yaml` (pnpm v11 silently ignores `allowBuilds` there and warns on every run). The new file's shape (seed list already sketched in `lib/pnpm/config.yaml:24-28`):

```yaml
# tools/pnpm-workspace.yaml — project-scoped lifecycle allowlist (pnpm v11 reads it HERE,
# not from the global config.yaml). Only packages whose postinstall/build is reviewed.
allowBuilds:
  snyk: true          # snyk's wrapper_dist/bootstrap.js exec fetches the platform binary (RESEARCH Pitfall 3)
```

**Open question for the planner (RESEARCH Pitfall 3 + this caveat interaction):** the global config comment says `allowBuilds` *"does NOT apply to global installs."* snyk/socket/varlock are installed via `pnpm add -g` (global). If pnpm v11 enforces `strictDepBuilds` on global installs but only honors `allowBuilds` from a project `pnpm-workspace.yaml`, the global snyk install may still fail. **The planner MUST verify the install path empirically** (`pnpm add -g snyk` in the built image → `snyk --version`); the fallbacks are (a) the snyk standalone installer, or (b) a temp project dir with the workspace file for the install step. This is the highest-risk integration point of the phase — flag it as a checkpoint task, not an assumed one.

---

### `tools/harnessed/scan.py` (service, subprocess/request-response) — plan 05-01 + 05-03

**Analog:** itself — the existing invoker structure. This is the single closest-pattern file in the phase: snyk/socket invokers are line-for-line siblings of `_scan_source_osv`/`_audit_pip`, and `run_image_scan_online` is `run_image_scan` minus the `--offline` flags.

**The subprocess runner to reuse (never raises on scanner non-zero — the gate is in Python):** `tools/harnessed/scan.py:159-164`:
```python
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a scanner, capturing output. Never raise on a non-zero scanner exit (gated in Python)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except (subprocess.SubprocessError, OSError) as exc:
        raise ScanError(f"scanner invocation failed ({' '.join(cmd)}): {exc}") from exc
```
`_TIMEOUT = 300` (`:34`) bounds every scanner — snyk/socket invokers inherit this for free (RESEARCH threat: "Scanner CLI hang stalls `harnessed build`"). `_parse_json` (`:146-153`) is the shared JSON-shape helper.

**The invoker signature to copy (highs/warnings list-accumulator pattern):** `tools/harnessed/scan.py:167-199`:
```python
def _scan_source_osv(target: Path, highs: list[str], warnings: list[str]) -> None:
    """osv-scanner offline source scan of one dir; HIGH ids -> highs, everything else -> warnings."""
    proc = _run(["osv-scanner", "scan", "source", "--offline", "--offline-vulnerabilities", "-r", "--format", "json", str(target)])
    data = _parse_json(proc.stdout)
    if data is None:
        if proc.returncode == 128:
            warnings.append(f"osv-scanner found no packages in {target} (exit 128 — investigate)")
        elif proc.returncode not in (0, 1):
            warnings.append(f"osv-scanner did not produce results for {target} (exit {proc.returncode}; offline DB present?) — investigate")
        return
    for finding in gate(data):
        highs.append(finding)
    for finding in _all_finding_ids(data):
        if finding not in highs:
            warnings.append(finding)


def _audit_pip(requirement: Path, warnings: list[str]) -> None:
    """pip-audit a requirements.txt; findings are warnings only (its JSON carries no CVSS)."""
    proc = _run(["pip-audit", "-r", str(requirement), "--format", "json", "--vulnerability-service", "osv"])
    data = _parse_json(proc.stdout)
    if data is None:
        warnings.append(f"pip-audit could not produce results for {requirement.name} (exit {proc.returncode}; network?) — skipped")
        return
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vid = vuln.get("id")
            if vid:
                warnings.append(f"pip-audit: {vid}")
```
**`_scan_snyk` and `_scan_socket` copy this exact shape** (env-gate prepended; see RESEARCH Code §3/§4). The **snyk exit-code map is the load-bearing difference** (RESEARCH Pitfall 2): with `--severity-threshold=high`, exit `1` ⇒ `highs.append(...)` (abort); `2/3` ⇒ `warnings.append(...)`; `0` ⇒ clean. Do NOT treat snyk's non-zero like osv-scanner's (osv `1` = any finding; snyk `1` = HIGH+ at the threshold — which is exactly the gate we want).

**The runner structure to extend (the loop that calls every invoker):** `tools/harnessed/scan.py:202-231`:
```python
def run_source_scan(root: Path | str, stack_name: str, build_dir: Path | str) -> ScanResult:
    """SCOPED source/Python scan of one stack (BLD-02a). Raises ScanError on any HIGH+ finding."""
    root = Path(root); build_dir = Path(build_dir)
    stack, recipes = schema.load_stack_with_recipes(root, stack_name)
    scan_targets: list[Path] = [recipe.root for recipe in recipes]
    profile_dir = build_dir / "profiles" / stack.name
    if profile_dir.is_dir():
        scan_targets.append(profile_dir)
    highs: list[str] = []; warnings: list[str] = []
    for target in scan_targets:
        _scan_source_osv(target, highs, warnings)
        for requirement in target.rglob("requirements.txt"):
            _audit_pip(requirement, warnings)
    if highs:
        unique = sorted(set(highs))
        raise ScanError(f"supply-chain source scan found {len(unique)} HIGH+ finding(s) (CVSS >= {HIGH}): {', '.join(unique)}")
    return ScanResult(scope=f"source:{stack.name}", highs=[], warnings=warnings)
```
The SEC-02 wiring adds `_scan_snyk(target, highs, warnings)` + `_scan_socket(target, warnings)` inside the per-target loop. The `ScanResult`/`ScanError` dataclasses (`:48-58`) and `HIGH = 7.0` (`:30`) are reused as-is.

**The image-scan function to clone for the online nightly variant:** `tools/harnessed/scan.py:234-254`:
```python
def run_image_scan(archive_tar: Path | str) -> ScanResult:
    """Scan a saved image archive via osv-scanner (BLD-02b). Raises ScanError on any HIGH+ finding.
    Driven HOST-side by build_stack (`podman save` → this scan), mirroring `harnessed test`."""
    archive_tar = Path(archive_tar)
    proc = _run(["osv-scanner", "scan", "image", "--offline", "--offline-vulnerabilities", "--archive", str(archive_tar), "--format", "json"])
    if proc.returncode == 128:
        warnings = [f"osv-scanner found no packages in image archive (exit 128 — investigate)"]
        return ScanResult(scope="image", highs=[], warnings=warnings)
    data = _parse_json(proc.stdout) or {}
    highs = gate(data)
    if highs: ...  # raise ScanError
    warnings = [vid for vid in _all_finding_ids(data)]
    return ScanResult(scope="image", highs=[], warnings=warnings)
```
**`run_image_scan_online` is this function with the two `--offline*` flags dropped** (RESEARCH Pitfall 6 — the whole point of the nightly is a fresh DB). Clone, rename, drop the flags, done. Keep the `returncode == 128` investigate-branch (a vacuous "0 findings" forever is the Pitfall 6 warning sign).

---

### `tools/harnessed/cli.py` (controller, request-response) — plan 05-03

**Analog:** itself — the argparse subparser + runner pattern.

**The subparser declaration to clone (for `scan-image-online`):** `tools/harnessed/cli.py:100-105`:
```python
sci = sub.add_parser(
    "scan-image",
    help="supply-chain image scan of a saved image archive via osv-scanner (BLD-02)",
)
sci.add_argument("archive", help="path to a podman/docker image archive tar (from `podman save`)")
```
The new `scan-image-online` subparser is identical (one positional `archive` arg). Add it right after `sci`.

**The runner + dispatch to clone:** `tools/harnessed/cli.py:167-194`:
```python
def _run_scan_image(args: argparse.Namespace, out: Console, err: Console) -> int:
    """Run the image-archive supply-chain scan; exit 1 on any HIGH+ finding (BLD-02)."""
    try:
        result = run_image_scan(Path(args.archive))
    except ScanError as exc:
        err.print(f"[bold red]supply-chain image scan failed:[/bold red] {exc}", highlight=False)
        return 1
    out.print(f"[bold green]Supply-chain image scan clean[/bold green] (HIGH < CVSS {7.0:.1f})")
    for warning in sorted(set(result.warnings)):
        out.print(f"  [yellow]warning:[/yellow] {warning}")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = Console(); err = Console(stderr=True)
    if args.command == "assemble": return _run_assemble(args, out, err)
    if args.command == "test":     return _run_test(args, out, err)
    if args.command == "scan":     return _run_scan(args, out, err)
    if args.command == "scan-image": return _run_scan_image(args, out, err)
    parser.error(f"unknown command: {args.command}")
    return 2
```
The import line to extend is `tools/harnessed/cli.py:23`: `from .scan import ScanError, run_image_scan, run_source_scan` — add `run_image_scan_online`. `_run_scan_image_online` is `_run_scan_image` calling `run_image_scan_online`. The `main()` dispatch gains one `if` line.

> **Note (RESEARCH §6 + Open Q5):** if the planner elects a `harnessed timer enable|disable` subcommand, that lives in the **bash launcher** (next assignment), not here. The Python CLI only owns the tools-image entrypoints (`scan-image-online` is the one the nightly calls).

---

### `tools/harnessed/secrets.py` (utility, subprocess/transform) — plan — (OPTIONAL; not delivered — bash path chosen in 05-02)

**Analog:** `tools/harnessed/scan.py:159-164` (`_run` capture) — IF the planner elects a Python varlock-resolve helper.

**Condition for this file to exist:** RESEARCH Open Q1's recommended default is the **bash** `lib/harnessed-secrets.sh` path (Code §1), where `varlock load --format env` runs in a throwaway tools container and the host captures stdout. A Python `secrets.py` is only needed if the planner instead adds a `harnessed secrets resolve` tools-image subcommand (so the host does `harnessed-tools secrets resolve --schema <path>` and parses JSON on stdout). Either is valid; pick ONE to avoid two resolution paths. If Python: clone the `_run` + `_parse_json` helpers from `scan.py:146-164`, run `varlock load --format json`, validate, print. If bash: this file does not exist.

---

### `lib/harnessed-secrets.sh` (utility/service, subprocess/file-I/O) — plan 05-02 (NEW)

**Analog:** `lib/harnessed-services.sh:68-130` (`svc_up` — the container-launch-with-host-paths shape) for `auth_scanner`; `lib/harnessed-common.sh:106-108` (throwaway tools container) for `resolve_secret_env`.

**The throwaway-tools-container pattern to copy (SEC-01 varlock resolve):** `lib/harnessed-common.sh:106-108`:
```bash
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" assemble "$stack" --root "$ROOT" --build-dir "$ROOT"
```
`resolve_secret_env` (RESEARCH Code §1) is this shape with: the schema mounted ro, the op agent socket mounted (already at `$CONTAINER_HOME/.1password/agent.sock` per `lib/harnessed-mounts.sh:23-27`), a temp env-file mounted rw, `varlock load --format env` redirected into it. The function returns the env-file path; the caller unlinks after launch. **Inertness = the first line is `[ -f "$HARNESSED_SCHEMA" ] || return 0`** — no schema ⇒ no varlock invocation, no `op` call, today's behavior unchanged.

> **Correction (post-implementation, commit 81a7f3f):** this agent-socket-mount pattern is **WRONG for op app-auth** — the 1Password desktop app authorizes the calling terminal (not an in-container `op`), and `~/.1password/agent.sock` is the SSH agent (git signing), not the op app-auth transport. Resolution now runs **on the HOST** via `varlock load --format env`; keep this container shape only for the headless `OP_SERVICE_ACCOUNT_TOKEN` fallback.

**The host-config-mounted container pattern to copy (SEC-03 auth_scanner):** `lib/harnessed-services.sh:103-109`:
```bash
"$CONTAINER_RUNTIME" run -d \
    -p "$port:$port" \
    --name "$service" \
    --label harnessed-service="$service" \
    --userns=keep-id \
    -v "$volume:$data_path" \
    "$image" >/dev/null
```
`auth_scanner` (RESEARCH Code §5) is this shape with: `--rm -it` instead of `-d` (one-shot, TTY for interactive `snyk auth`/`socket login`), `-v "$HOME/.config":"$CONTAINER_HOME/.config":rw` (token persists to host), and the tools image running the vendor CLI's own auth command. **`--rm` is the security-critical flag** — it guarantees no image layer captures the token (RESEARCH Pitfall 7). Mirror `svc_up`'s `container_running` idempotency check is NOT wanted here (auth is always interactive/one-shot).

**The set -euo pipefail-safe capture (Constraint 9 — RESEARCH Project Constraint 9):** `lib/harnessed-common.sh:115-118`:
```bash
local src_rc=0
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT" || src_rc=$?
if [ "$src_rc" -ne 0 ]; then ...; fi
```
Every fallible probe in the new code (`resolve_secret_env`, `auth_scanner`, `harnessed_rescan_images`) MUST use the `local rc=0; cmd || rc=$?` shape — the launcher runs under `set -euo pipefail` (`harnessed:25`), so a bare scanner/container pipeline aborts the whole launch on a non-zero exit.

**Where this lib is sourced from:** mirror how the launcher sources `harnessed-services.sh` on the `svc)` path (`harnessed:233-234`):
```bash
. "$HARNESSED_DIR/lib/harnessed-services.sh"
```
The new `auth)`/`rescan)` case blocks source `lib/harnessed-secrets.sh` (or a `lib/harnessed-rescan.sh`) the same way, just-in-time (keeps the launcher's cold-start cost down — only load what the subcommand needs).

---

### `harnessed` launcher (controller, request-response) — plan 05-02 + 05-03

**Analog:** itself — the `svc`/`install`/`new` dispatch + the `usage()` block.

**The subcommand parse block to clone (RESEARCH Pattern 3 dispatch shape):** `harnessed:102-126` (the `svc)` case):
```bash
svc)
    # `harnessed svc up|down|list <service>` → shared service lifecycle (plan 04-01 / SVC-01).
    shift
    SVC_ACTION="${1:-}"
    [ -n "$SVC_ACTION" ] || { print_error "svc requires an action (up|down|list)"; usage; exit 1; }
    shift
    case "$SVC_ACTION" in
        up)   ...; SVC_TARGET="$1"; shift ;;
        down) ...; [ "${1:-}" = "--purge" ] && { SVC_PURGE=true; shift; } ;;
        list) SVC_TARGET="" ;;
        *) print_error "unknown svc action: $SVC_ACTION (use up|down|list)"; usage; exit 1 ;;
    esac
    ;;
```
The new `auth)` case validates `${1:-}` ∈ {`snyk`,`socket`} (RESEARCH Code §5 dispatch shape), stores `AUTH_TOOL`, shifts. The new `rescan)` case takes no sub-args (RESEARCH Code §6). Both are parsed BEFORE the stack-name fallthrough (`:192-212`) so a stack named `auth` cannot collide — the same ordering invariant the `svc`/`list`/`new` blocks enforce (see comments at `:104`, `:129`, `:146`).

**The dispatch-and-exit block to clone (top-level commands exit, never reach the launch path):** `harnessed:228-271`:
```bash
if [ -n "$SVC_ACTION" ]; then
    . "$HARNESSED_DIR/lib/harnessed-services.sh"
    case "$SVC_ACTION" in
        up)   svc_up "$SVC_TARGET" ;;
        down) ... ;;
        list) svc_list ;;
    esac
    exit 0
fi
...
if [ -n "$SUB_INSTALL_ACTION" ]; then
    . "$HARNESSED_DIR/lib/harnessed-cli.sh"
    case "$SUB_INSTALL_ACTION" in
        install)   install_stack "$SUB_INSTALL_STACK" ;;
        uninstall) uninstall_stack "$SUB_INSTALL_STACK" ;;
    esac
    exit 0
fi
```
Add two sibling blocks: `if [ -n "$AUTH_TOOL" ]; then . .../lib/harnessed-secrets.sh; auth_scanner "$AUTH_TOOL"; exit 0; fi` and `if [ "$SUB_RESCAN" = true ]; then . .../lib/harnessed-rescan.sh; harnessed_rescan_images; exit 0; fi`. The `exit 0` is mandatory — these are top-level commands, not a launch path (mirror the existing invariant).

**The usage block to extend:** `harnessed:36-68` — add two lines in the same style:
```
  harnessed auth snyk|socket   Set a scanner token (persisted to host config; never an image layer)
  harnessed rescan             Re-scan installed harnessed images online (post-build CVE catch; timer-driven)
```
Also add to the surface comment at the top of the file (`harnessed:8-23`).

---

### `lib/harnessed-common.sh::build_stack` (controller, request-response) — plan 05-01 + 05-02

**Analog:** itself — the scan invocation being extended.

**The exact injection point (the SEC-02 wiring):** `lib/harnessed-common.sh:116-118`:
```bash
local src_rc=0
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v "$ROOT":"$ROOT" -w "$ROOT" \
    "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT" || src_rc=$?
```
Add `-e SNYK_TOKEN` + `-e SOCKET_SECURITY_API_KEY` to this `run` — but ONLY if present in the launcher env (raw env, varlock-resolved via SEC-01, or read from `~/.config/configstore/snyk.json`). The conditional-injection idiom (don't pass an empty `-e`): build an array, extend it conditionally, expand `"${TOKEN_ARGS[@]}"`. **Never prompt** (RESEARCH SEC-02 contract). The tools image's `scan.py` does the env-presence gate (warn-and-skip), so build_stack just forwards whatever is set.

**The image-scan block (the SEC-04 nightly reuses this host-side shape):** `lib/harnessed-common.sh:131-137`:
```bash
local img_tar img_rc=0
img_tar="$(mktemp --suffix=.tar)"
"$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"
"$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro \
    "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar" || img_rc=$?
rm -f "$img_tar"
```
`harnessed_rescan_images` (RESEARCH Code §6) is this exact block inside a `for img in $(podman images --filter reference='harnessed-*' ...)` loop, calling `scan-image-online` instead of `scan-image`, temp-tar cleaned up per iteration. **Clone, don't call** — rescan lives in a new `lib/harnessed-rescan.sh` (or `harnessed-secrets.sh`), sourced only on the `rescan)` path.

---

### `lib/harnessed-isolated.sh::harnessed_isolated` (controller, request-response) — plan 05-02

**Analog:** itself — the MOUNT_ARGS + member-launch structure.

**The wiring point (call resolve_secret_env before pod create; pass --env-file to members):** `lib/harnessed-isolated.sh:90-93, 145-161`:
```bash
local MOUNT_ARGS=()
harnessed_host_integration_mounts "$project_path" "$relpath"
harnessed_isolated_auth_mounts "$instance"
...
# hatago member
"$CONTAINER_RUNTIME" run -d --pod "$pod" --name "${instance}-hatago" \
    -v "$profile_dir/hatago.config.json:$CONTAINER_HOME/hatago.config.json:ro" \
    "$HARNESSED_HATAGO_IMAGE" hatago serve --http --port "$HATAGO_PORT" --config ... >/dev/null

# harness member
local member_args=() _arg
for _arg in "${MOUNT_ARGS[@]}"; do
    [ "$_arg" = "--userns=keep-id" ] && continue
    member_args+=( "$_arg" )
done
"$CONTAINER_RUNTIME" run -d --pod "$pod" --name "$instance" "${member_args[@]}" \
    "$harness_image" sleep infinity >/dev/null
```
SEC-01 inserts (RESEARCH Code §2): call `local secret_env; secret_env="$(resolve_secret_env)"` after the `MOUNT_ARGS` block, build `local env_args=(); [ -n "$secret_env" ] && env_args=( --env-file "$secret_env" )`, and spread `"${env_args[@]}"` into BOTH the hatago and harness member `run` commands. After the interactive attach returns (`:197`), `[ -n "$secret_env" ] && rm -f "$secret_env"` (mode-0600 temp file unlinked — RESEARCH Pitfall 7). The resolved creds reach the pod as **env only** — never written to the profile, the run_claude state dir, or an image layer.

**The agent socket is already mounted (no new mount needed):** `lib/harnessed-mounts.sh:22-27`:
```bash
# 1Password SSH agent socket.
local op_agent="$HOME/.1password/agent.sock"
if [ -S "$op_agent" ]; then
    MOUNT_ARGS+=( -v "$op_agent:$CONTAINER_HOME/.1password/agent.sock" )
    MOUNT_ARGS+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.1password/agent.sock" )
fi
```
This is the `op` app-auth transport varlock's `@initOp(allowAppAuth=true)` uses — **already wired by every stack**. SEC-01 resolution reuses it; no new mount line. (`OP_SERVICE_ACCOUNT_TOKEN` is the headless-only fallback — pass it through the same env_args if set, scoped narrowly per CLAUDE.md "What NOT to Use".)

---

### `systemd/harnessed-rescan.timer` + `systemd/harnessed-rescan.service` (config, event-driven) — plan 05-03 (NEW)

**Analog:** NONE in repo (no `systemd/` dir exists — confirmed via `find`). Use RESEARCH Pattern 4 + the cited external references.

**Source material (RESEARCH Pattern 4, lines 283-304):**
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
```
**Two mandatory setup notes the docs MUST carry (RESEARCH Pitfall 5):** (1) `loginctl enable-linger $USER` — currently OFF on the host; without it the timer never fires while logged out; (2) network egress to osv.dev at scan time (the online DB requires it; the build-time offline gate does not). The repo convention for "shipped config the operator copies into place" is the `lib/pnpm/config.yaml` + `extra-tools.default.txt` precedent (shipped template, copied/idempotently-seeded) — the planner may either ship static units in a new `systemd/` dir or add a `harnessed timer enable` subcommand (Open Q5). Static units + docs is the lighter default.

---

### `.env.schema.example` (config) — plan 05-01

**Analog:** itself — the one-line plugin-pin bump.

**Current state (`:11`):** `# @plugin(@varlock/1password-plugin@0.3.2)` — STALE (current npm release is 1.2.0; RESEARCH Pitfall 1 / A4). Bump to `@1.2.0` AND run `varlock load` against the example in the built tools image to confirm the `op()` + `@initOp(allowAppAuth=true)` API survived the 0.x→1.x major bump. The rest of the file (`:15-25`, the `SNYK_TOKEN`/`SOCKET_SECURITY_API_KEY` `op(op://…)` refs) is the documented contract — leave the structure, just verify it parses under 1.2.0.

---

### `docs/guides/secrets.md` (docs) — plan 05-02 (cadence-gated)

**Analog:** NONE (no how-to docs exist). **Content sources:** `.env.schema.example` (the template the reader copies), `docs/harnessed-design.md` §16 (the *why* — cross-reference, don't duplicate), `lib/harnessed-mounts.sh:22-27` (the agent-socket transport).

**Why this is in 05-02:** design §17 cadence rule — *"each section lands with the feature it documents."* A reader of SEC-01 has the doc the moment the feature ships (SEC-01 is delivered in plan 05-02). Worked example: copy `.env.schema.example` → `~/.config/harnessed/.env.schema`, edit the `op://` refs, launch — resolved env reaches the pod, never a layer. Document the headless `OP_SERVICE_ACCOUNT_TOKEN` fallback + the CLAUDE.md "don't leave it in a long-lived shell" caution.

---

### `README.md` (docs) — plan 05-04

**Analog:** `AGENTS.md` (the OLD `container` setup prose — `:1-95`; README supersedes/reconciles with it) + `docs/harnessed-design.md` §1-§2 (what/why, two modes — the source of truth).

**The prose structure to supersede:** `AGENTS.md:9-44` (Setup Instructions, Post-setup, common commands). README replaces the `container --build`/`--list`/`--stop` quickstart with the `harnessed` surface (`harnessed build <stack>`, `harnessed <stack>`, `harnessed list`, etc. from the `usage()` block at `harnessed:36-68`). **Reconcile AGENTS.md** (RESEARCH Pattern 5 anti-pattern: "letting the README and AGENTS.md drift") — either fold AGENTS.md's AI-assistant setup into README + leave a stub, or rewrite AGENTS.md to point at README. The planner decides; both must not contradict.

**The two-modes framing to lift:** `docs/harnessed-design.md:27-41` (§2 One engine, two config modes — the transparent/isolated table). README's quickstart shows one of each (transparent = "my laptop sandboxed"; isolated = the tracer-time worked example).

---

### `docs/guides/recipe-authoring.md`, `docs/guides/stacks.md`, `docs/guides/service-authoring.md`, `docs/guides/troubleshooting.md` (docs) — plan 05-04

**Analog:** NONE (no how-to docs exist — `docs/` holds only `harnessed-design.md` + the `docs/codebase/` analysis set). **Content sources** (worked examples, all verified present in the repo):

| Doc | Worked-example source (copy-paste runnable) | Cross-ref (the *why*) |
|-----|---------------------------------------------|------------------------|
| `recipe-authoring.md` | `recipes/time/recipe.yaml` (stdio MCP + standalone skill — the tracer bullet), `recipes/ping/recipe.yaml` (service-ref MCP, no command) | design §5, §11 |
| `stacks.md` | `stacks/tracer-time/stack.yaml` (isolated + claude + one recipe), `stacks/transparent/stack.yaml` (transparent mode), `stacks/ping-time/stack.yaml` | design §2, §12 |
| `service-authoring.md` | `services/ping/` — the full triple: `service.yaml` (`services/ping/service.yaml:1-11`), `Dockerfile` (`services/ping/Dockerfile:1-22`), `server.py` (`services/ping/server.py:1-49`, a FastMCP streamable-http server with a `/health` route) | design §3, §9; `lib/harnessed-services.sh` (svc lifecycle) |
| `troubleshooting.md` | podman socket setup, first-run build, `~/.claude.json` onboarding, `--fresh`, host-persisted sessions (`lib/harnessed-isolated.sh:105-112`), `loginctl enable-linger` (RESEARCH Pitfall 5) | design §15, §17 |

**Pattern (RESEARCH Pattern 5, anti-point):** how-tos show *how* with a worked example; they cross-reference `docs/harnessed-design.md` for *why* — they do NOT duplicate the design doc's rationale. Each doc's worked example MUST run as-documented (the RESEARCH validation contract: "copy-paste runnable"). The `ping` service triple is the model for `service-authoring.md` — a complete, minimal, scannable sidecar (own image + volume + healthcheck + network-native MCP).

---

## Shared Patterns

### Throwaway-tools-container invocation
**Source:** `lib/harnessed-common.sh:106-108` (assemble), `:116-118` (scan), `:131-137` (image scan)
**Apply to:** `lib/harnessed-secrets.sh::resolve_secret_env` (SEC-01), `lib/harnessed-secrets.sh::auth_scanner` (SEC-03), `lib/harnessed-rescan.sh::harnessed_rescan_images` (SEC-04)
```bash
"$CONTAINER_RUNTIME" run --rm --userns=keep-id \
    -v <host-path>:<container-path> -w <workdir> \
    "$HARNESSED_TOOLS_IMAGE" <tools-subcommand> <args>
```
Every SEC-01/03/04 host→tools interaction is this shape. The host stays podman-only; the tools image does the work; `--rm` guarantees no layer. `HARNESSED_TOOLS_IMAGE` is defined at `lib/harnessed-common.sh:25`.

### Env-gated scanner invoker (subprocess capture + list-accumulator)
**Source:** `tools/harnessed/scan.py:159-199` (`_run`, `_scan_source_osv`, `_audit_pip`)
**Apply to:** `tools/harnessed/scan.py::_scan_snyk` (SEC-02), `tools/harnessed/scan.py::_scan_socket` (SEC-02)
```python
def _scan_X(target: Path, highs: list[str], warnings: list[str]) -> None:
    if not os.environ.get("<TOKEN>"):
        warnings.append("X skipped (no <TOKEN>) — credential-free baseline remains the gate"); return
    proc = _run(["X", "test", "--json", ...])
    # map proc.returncode → highs/warnings per the scanner's exit semantics
```
The warn-and-skip-on-no-token contract (RESEARCH SEC-02) is the non-negotiable part. The snyk exit-code map (1=HIGH+, 2/3=warn) differs from osv-scanner — document inline (Pitfall 2).

### Launcher subcommand dispatch (parse-before-fallthrough + source-lib-and-exit)
**Source:** `harnessed:102-176` (parse), `harnessed:228-271` (dispatch+exit)
**Apply to:** `harnessed` `auth)` case (SEC-03), `harnessed` `rescan)` case (SEC-04)
```bash
# 1. Parse (in the while/case loop, BEFORE the stack-name fallthrough at :192-212)
auth)  shift; AUTH_TOOL="${1:-}"; case "$AUTH_TOOL" in snyk|socket) ;; *) ...; exit 1 ;; esac; shift ;;
rescan) SUB_RESCAN=true; shift ;;
# 2. Dispatch (after the loop, as a top-level if-block that exits)
if [ -n "$AUTH_TOOL" ]; then . .../lib/harnessed-secrets.sh; auth_scanner "$AUTH_TOOL"; exit 0; fi
```
Two invariants from the existing code: (a) parse before the bareword fallthrough so a stack named `auth`/`rescan` cannot collide (comments at `:104`, `:129`); (b) the dispatch block ends in `exit 0` — these are top-level commands, never a launch path.

### Safe non-zero-exit capture under `set -euo pipefail`
**Source:** `lib/harnessed-common.sh:115-118, 132-137`
**Apply to:** every fallible probe in `lib/harnessed-secrets.sh`, `lib/harnessed-rescan.sh`, and the `build_stack` scan-step extension
```bash
local rc=0
"$CONTAINER_RUNTIME" run --rm ... <cmd> || rc=$?
if [ "$rc" -ne 0 ]; then print_error "..."; return 1; fi
```
The launcher runs `set -euo pipefail` (`harnessed:25`); a bare scanner/container pipeline aborts the whole launch on non-zero. This is RESEARCH Project Constraint 9 + the cited `a963a69` Phase-3 precedent.

### Argparse subparser + `_run_*` runner + `main()` dispatch
**Source:** `tools/harnessed/cli.py:28-105` (`_build_parser`), `:167-194` (runners + main)
**Apply to:** `tools/harnessed/cli.py` `scan-image-online` subcommand (SEC-04)
```python
# _build_parser: add a sibling subparser
sci_online = sub.add_parser("scan-image-online", help="...")
sci_online.add_argument("archive", ...)
# a _run_scan_image_online runner + one more `if args.command == ...` line in main()
```
One subparser + one runner + one dispatch line. Extend the import at `:23` (`run_image_scan_online`).

### UAT AAA harness (pure-bash, integration-only)
**Source:** `tools/uat/uat-common.sh` (`arrange/act/assert` markers, `assert_exit_zero`/`assert_match`/`assert_contains`/`assert_exists`, `run_test`, `uat_run`/`uat_run_env`), `tools/uat/phase-04.sh` (suite shape)
**Apply to:** new `tools/uat/phase-05.sh` (SEC-01..04 integration tests)
```bash
source "$HERE/uat-common.sh"
test_secrets_inert() {
    arrange; uat_run "$HARNESSED" build tracer-time   # no .env.schema present
    act;     # (no-op — the build is the act)
    assert;  assert_not_match 'varlock' "$UAT_OUT" "varlock never invoked without a schema"
}
run_test secrets_inert "SEC-01: no schema ⇒ varlock never invoked"
```
Test through the running build/launch/rescan (RESEARCH §Validation Architecture + design §18 — integration-only, no assembler unit tests). Fixture precedent: `tools/test-fixtures/{vuln,low,npm,svc}-stack` — add a `tools/test-fixtures/.env.schema` (SEC-01) and reuse the vuln stack for the SEC-02 snyk/socket gate.

---

## No Analog Found

Files with no close in-repo match — the planner uses RESEARCH.md patterns + the cited external sources instead:

| File | Role | Data Flow | Reason | Fallback source |
|------|------|-----------|--------|-----------------|
| `systemd/harnessed-rescan.timer` | config | event-driven | No systemd units exist in the repo (no `systemd/` dir). | RESEARCH Pattern 4 (`:283-294`) + Red Hat `podman-auto-update.timer` (`OnCalendar=daily` + `Persistent=true` + `WantedBy=timers.target`) |
| `systemd/harnessed-rescan.service` | config | event-driven | Same — no systemd precedent. | RESEARCH Pattern 4 (`:295-304`) — `Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan` |
| `docs/guides/secrets.md` | docs | file-I/O | No how-to docs exist (`docs/` holds only the design doc + codebase analysis). Content sources are concrete. | `.env.schema.example` + design §16 + RESEARCH Pattern 1 |
| `docs/guides/recipe-authoring.md`, `stacks.md`, `service-authoring.md`, `troubleshooting.md` | docs | file-I/O | Same — no how-to precedent. | Worked examples (`recipes/`, `stacks/`, `services/ping/`) + design §2/§5/§9/§11/§12 + RESEARCH Pattern 5 |
| `README.md` | docs | file-I/O | No repo-root README exists today. `AGENTS.md` is the closest prose but is AI-assistant-setup-focused, not user-facing. | `AGENTS.md` (supersede) + design §1-§2 + `harnessed:36-68` (`usage()`) |

> The five "no analog" docs/units are not risky — they're integration of mature external tools (systemd timers) or prose about shipped behavior. The RESEARCH Code Examples (§1-§6) and Pattern 4/5 carry the concrete shape. The planner's job for these is authoring + "does the worked example run as-documented?", not pattern-discovery.

---

## Metadata

**Analog search scope:**
- Repo root: `harnessed`, `CLAUDE.md`, `AGENTS.md`, `.env.schema.example`, `install.sh`
- `lib/`: `harnessed-common.sh`, `harnessed-isolated.sh`, `harnessed-mounts.sh`, `harnessed-services.sh`, `harnessed-transparent.sh`, `pnpm/config.yaml`
- `tools/`: `Dockerfile`, `pyproject.toml`, `harnessed/{cli,scan,assemble,emit,capability,report,schema,synclinks}.py`
- `tools/uat/`: `uat-common.sh`, `phase-04.sh`, `run-uat.sh`
- `base/`: `Dockerfile.harnessed-base`, `Dockerfile.hatago`, `Dockerfile.harnessed-claude`
- `services/ping/`, `recipes/{time,ping}/`, `stacks/{tracer-time,transparent,ping-time}/`
- `docs/harnessed-design.md` (§1-§18), `docs/codebase/INTEGRATIONS.md` (cited lines)

**Files scanned:** 26 source/config files + 6 worked-example manifests
**Pattern extraction date:** 2026-06-18
