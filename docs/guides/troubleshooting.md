# Troubleshooting & ops

Operational guidance for `harnessed`: podman setup, first-run builds, sessions, secrets, and the
nightly re-scan timer. For the *why* behind any of this, see
[docs/harnessed-design.md §15 & §17](../harnessed-design.md); for the secrets workflow specifically,
see [secrets.md](secrets.md).

## podman / rootless setup

`harnessed` is **host-native**: every `podman`/`docker` command runs on the host directly. There is
**no daemon-in-container, no Docker-out-of-Docker, and no rootless API socket mounted**
([design §15](../harnessed-design.md)). Assembly (Dockerfile + profile generation) runs in-process
inside the host Python CLI; the host then runs ordinary `podman build` / `podman run`.

- You do **not** need to `systemctl --user enable --now podman.socket` for harnessed's core flow. The
  socket is only relevant if a container must *drive* the host engine — and harnessed never does.
- Run rootless (`--userns=keep-id` is applied automatically) so file ownership works without host root.
- `podman` ≥ 5.6 is recommended (current 5.8.x). Docker works as a fallback (the egress firewall is
  tested on Podman).

## Container runtimes (podman / Docker / Apple `container`)

`harnessed` is provider-agnostic. The harness stack — the harness container + the hatago hub sharing
one `localhost:3535` — is expressed per-runtime by [`src/harnessed/launcher.py`](../../src/harnessed/launcher.py):

- **podman** — a pod (`pod create` + `run --pod`); rootless uid mapping via `--userns=keep-id`.
- **Docker** — a shared network namespace: hatago runs first, the harness joins it with
  `--network container:<hatago>` (same localhost); rootless Docker remaps uids daemon-side (no
  `--userns` flag). The two members are flat containers (`<instance>` + `<instance>-hatago`).
- **Apple `container`** — not yet supported (one lightweight VM + IP per container, no shared
  netns / `--network container:`); tracked as a follow-up (needs a named-network + a non-localhost
  MCP endpoint).

`detect_runtime` prefers podman, else docker. Force one with `CONTAINER_RUNTIME=docker harnessed …`.

### Full integration test on a fresh host (e.g. a Docker NAS)

After `git pull` on the target host:

```bash
cd /path/to/harnessed
# build + capability-test every stack in catalog/stacks/ (auto-discovered):
HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py
# fast unit / assembly checks (no containers):
uv run pytest -q
```

The integration suite builds each stack in `catalog/stacks/`, launches it `--fresh` headless,
asserts declared MCP servers are reachable and declared skills are present, then tears it down.
Real stacks today: `claude_time` (smallest), `claude_gstack_ping_time_greet`,
`omp_gstack_ping_time_greet`, `claude_floating-recipe`. Add a stack → it is picked up automatically.

### Docker caveats

- **Egress firewall** needs rootless `NET_ADMIN` + iptables in the shared netns. If it can't apply,
  the launcher warns and continues; pass `--no-firewall` to skip it explicitly.
- **File ownership** — rootless Docker remaps uids daemon-side (there is no `--userns=keep-id`). If
  mounted project/profile files end up unwritable inside the container, configure the daemon's
  `userns-remap`, or run the build/UAT as the same uid that owns the repo.
- **Shared service sidecars** (`services:` / `harnessed svc`) are **not wired for Docker yet** — the
  hatago proxy resolves them via `host.containers.internal`, a podman-only name. The harness-matrix
  proof stacks declare no services, so the UAT itself is unaffected.

## First-run build issues

Images build on the host via `podman build` the first time they're needed. If a build fails:

- **podman version / disk / context** — confirm `podman --version` ≥ 5.6, that you have disk space,
  and that you're running from the repo root (the build context).
- **`harnessed build` aborts on HIGH** — see [Supply-chain scan failures](#supply-chain-scan-failures).
- **A `harnessed` upgrade that touched `src/harnessed/*.py`** takes effect immediately — the
  assembler runs in-process on the host (there is no tools image to rebuild). If behaviour still
  looks stale, confirm your shell's `harnessed` resolves to the updated install
  (`which harnessed` / `pipx upgrade harnessed`).
- **Running an unbuilt stack** errors with `Stack '<stack>' has no assembled profile (run:
  harnessed build <stack>)`. Build it first:

  ```bash
  harnessed build <stack> && harnessed <stack>
  ```

## `~/.claude.json` onboarding prompt

A stack instance authenticates by mounting `~/.claude/.credentials.json` read-only plus a
**generated, token-free `.claude.json` stub** that boots headlessly with no onboarding/login prompt
(AUTH-02).

- **If `claude` prompts for onboarding in a stack instance**, the stub is missing a required
  field. The proven field set (`hasCompletedOnboarding`, `firstStartTime`, `numStartups`,
  `oauthAccount`, `userID`) is sufficient for a headless no-prompt boot; a re-build regenerates it.
- When running with host config mounted live, the host `.claude.json` is never rw-mounted — it uses a **copy-on-start**
  per-instance copy (MNT-03). If the host file is the source of trouble, the per-instance copy is
  unaffected.

## `--fresh` clean-room runs

`harnessed <stack> --fresh` tears down any existing pod/instance for the project, wipes the
per-instance state dir, and reseeds it from the committed profile — a true clean-room run with no
state bleed (design §9, [`src/harnessed/launcher.py`](../../src/harnessed/launcher.py)):

```bash
harnessed claude_time --fresh      # wipe + reseed, then attach
```

A **normal** run (no `--fresh`) **reuses** the accumulated per-instance `.claude` (projects/,
history.jsonl, …) — that is the point of a memory system. `--fresh` is meaningfully distinct from a
normal run: it wipes; a normal run accumulates.

## Host-persisted sessions

By default a stack instance persists harness session state (`projects/` + `history.jsonl`) to a
harnessed-owned dir on the host under a **legible, flattened project path** (STA-02):

```
$XDG_STATE_HOME/harnessed/<flattened-project-path>/<stack>/.claude
# default XDG: ~/.local/state/harnessed/<flattened-project-path>/<stack>/.claude
```

`<flattened-project-path>` is the home-relative project path with `/` → `-` (e.g.
`projects-personal-code-container`), so the slug is readable — not the opaque hash instance name.
Sessions survive instance recreation and stay inspectable. `state.session_state: volume` in the stack
manifest opts into a throwaway per-instance volume instead.

## Nightly re-scan timer (SEC-04)

A systemd **user** timer re-runs osv-scanner **online** against installed harnessed images so a CVE
disclosed *after* build still surfaces. The static unit files live at
[`systemd/harnessed-rescan.{timer,service}`](../../systemd/).

> **Prerequisite (Pitfall 5): enable lingering.** Without it the user systemd instance is torn down
> on logout and the timer **never fires overnight**. This is the single most common "my nightly scan
> silently stopped" cause.

```bash
# 1. Enable lingering (HARD prerequisite) and confirm it:
loginctl enable-linger "$USER"
loginctl show-user "$USER" --property=Linger      # expect: Linger=yes

# 2. Install the user units + enable the timer:
mkdir -p ~/.config/systemd/user
cp systemd/harnessed-rescan.timer systemd/harnessed-rescan.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now harnessed-rescan.timer
```

The timer (`OnCalendar=daily`, `Persistent=true`) drives `harnessed-rescan.service`
(`Type=oneshot`, `ExecStart=%h/.local/bin/harnessed rescan`) — so the manual trigger and the nightly
trigger exercise the **identical** code path. Ensure the launcher is on PATH at
`~/.local/bin/harnessed` (`harnessed install` shim, or a symlink).

**Diagnostics:**

```bash
systemctl --user list-timers harnessed-rescan.timer               # is it scheduled?
systemctl --user start harnessed-rescan.service                   # run it now (one-shot)
journalctl --user -u harnessed-rescan.service --no-pager          # what did it find?
```

**Network:** the nightly re-scan uses the **online** osv.dev database — it requires network egress
to `osv.dev` at scan time. (The build-time gate uses the **offline** DB by design, for determinism;
the nightly cannot.)

**Warning sign — "0 findings forever" (Pitfall 6):** if the nightly *always* reports clean even
after a widely-disclosed CVE, confirm the scan is using **`scan-image-online`** (online), not
`scan-image` (offline). The online variant deliberately drops the `--offline` flags so osv-scanner
sees newly-disclosed advisories — using the offline DB here would defeat the entire purpose (it only
knows about CVEs at build time). You can see the contrast directly:

- offline build-time scan: `Supply-chain image scan clean (HIGH < CVSS 7.0)`
- online nightly scan: `Supply-chain image scan clean (HIGH < CVSS 7.0; online)` — note the `(online)` marker.

## Secrets / varlock

The opt-in secrets workflow is documented in **[secrets.md](secrets.md)**. Common issues:

- **`op://` refs unresolved / "cannot connect to 1Password app"** — resolution runs `varlock`
  **on the host** (the desktop app authorizes your terminal; an in-container `op` cannot be
  authorized — that error is expected from inside a container). Check, in order: (1) host
  `varlock` is installed — `command -v varlock` (`npm i -g varlock`); (2) the 1Password desktop
  app is running, unlocked, with **Settings → Developer → "Integrate with 1Password CLI"**
  enabled; (3) you **Authorized** your terminal at the 1Password prompt on first use. For
  headless/CI (no desktop app), set a narrowly-scoped `OP_SERVICE_ACCOUNT_TOKEN` instead — see
  [secrets.md](secrets.md) "Headless / CI fallback".
- **Resolved value missing from the pod env** — confirm `~/.config/harnessed/.env.schema` exists and
  has a non-`@optional` entry for the key; the schema's `op(op://Vault/Item/field)` ref must point at
  a real vault item.
- **A resolved value reached the pod with surrounding quotes** — this was a fixed bug (varlock's
  `--format env` quoting); update to the current launcher.

## Supply-chain scan (advisory)

The derived image's final layer runs an **advisory** in-image scan — snyk (token-gated by a build
secret) plus credential-free osv-scanner + pip-audit. It **never fails the build**; it reports a
compact severity summary in the build log and writes a report.

- **Read the report.** After a build, `harnessed` copies the in-image report to
  `profiles/<stack>/scan-report.json` and prints a one-line summary (`⚠ supply-chain (advisory): N
  critical · M high …`). The JSON lists per-source counts and notable packages. Set
  `HARNESSED_SCAN_VERBOSE=1` in the build to dump the raw scanner JSON.
- **snyk warn-skips without a token** — if you expected snyk findings, check that
  `~/.config/harnessed/.env.schema` declares `SNYK_TOKEN` and `varlock` is installed (the token is
  passed as a build `--secret`). Without it you'll see `snyk skipped (no SNYK_TOKEN build secret)` —
  correct non-interactive behavior, not a failure. osv-scanner + pip-audit still run.
- **Why advisory, not a gate** — harnessed installs third-party agent tooling whose dependency trees
  (and node's own bundled npm) always carry open advisories; a hard gate would block every build on
  code you can't fix. To act on a finding, bump the upstream pin (e.g. a recipe's `*_REF`) so upstream
  owns the fix. A CVE disclosed *after* you built surfaces in the **online** nightly re-scan — see
  [Nightly re-scan timer](#nightly-re-scan-timer-sec-04).

## Recipe build & test FAQ

Hard-won answers from exercising the recipe → `build` → `test` loop end to end. The full
engineering log (symptom → root cause → fix per issue) is in
[docs/recipe-build-findings.md](../recipe-build-findings.md).

- **I edited `src/harnessed/*.py` but `harnessed build` still behaves the old way.** The assembler
  runs in-process on the host, so edits under `src/harnessed/` take effect immediately with no image
  rebuild. Verify your shell resolves to the edited install: `which harnessed`. If you installed via
  `uv tool install` or `pipx`, re-install from the local clone (`uv tool install -e .` /
  `pipx install -e .`) or confirm the venv on PATH is the one you edited.

- **What exactly does `harnessed test <stack>` assert?** It launches the stack `--fresh` headless and
  diffs the running instance against the manifest oracle: each declared **MCP server** must be
  connected (read from hatago's `hatago://servers` resource) and each declared **skill/command** must
  be present (read from the mounted `~/.claude` profile). Both checks are **auth-free** — you do *not*
  need Claude credentials for a green capability report. `--json` prints the structured result; exit
  code 0 means every declared capability is present.

- **A `service:` recipe (e.g. `ping`) reports its MCP server as not connected.** The service sidecar
  must be running and host-published. `harnessed <stack>` now starts referenced services
  automatically before creating the pod; you can also manage one explicitly:
  ```bash
  harnessed svc up ping     # build (if needed) + start host-published; persists across --fresh
  harnessed svc down ping   # stop + remove
  ```
  Services intentionally **outlive** instances — `--fresh` tears down only the pod, not the service.

- **My OMP stack runs the same skills as the Claude stack.** Expected. The profile is
  Claude-canonical (single source of truth); OMP consumes the same `.claude/` tree via the
  pre-installed `claude-hooks-bridge`. Compose an OMP stack with the same capability recipes plus the
  `omp` base recipe, e.g. `harnessed new omp-multi --harness omp --recipes time,greet,omp`.

- **A build I *expected* to fail (floating pin) — what should I see?** A one-line `error:` and a
  non-zero exit, not a traceback. Floating Dockerfile refs (`@latest`, `--branch main`) trip the pin
  gate, validated *before* any image layer is written.

- **Can a recipe be restricted to one harness?** No — recipes are harness-independent by design.
  Every harness consumes the same Claude-canonical profile, so a recipe never declares a `harnesses:`
  field. If a recipe needs harness-specific install steps, branch on the `${HARNESS}` build arg
  *inside* its Dockerfile. (A "claude stack" is simply `harness: claude` with whatever recipes you
  want — there is no such thing as a claude-only *recipe*.)

- **A Dockerfile recipe's `expect:` capability isn't verified.** Known gap — `recipe.expect` is parsed
  but not yet wired into the capability oracle, and the derived `Dockerfile.harnessed-<stack>` image
  is emitted but not yet built/run by the launcher. See findings F7/F8.

## See also

- [docs/recipe-build-findings.md](../recipe-build-findings.md) — the engineering findings log behind this FAQ.
- [docs/harnessed-design.md §15 & §17](../harnessed-design.md) — the *why* (host-native execution, docs cadence).
- [secrets.md](secrets.md) — the opt-in varlock + 1Password workflow.
- [README.md](../../README.md) — the command surface and quickstart.
