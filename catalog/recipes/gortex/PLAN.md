# gortex recipe — implementation plan

Goal: expose gortex's graph code intelligence in a stack — MCP tools over the mounted repo's
symbol/call graph — with its daemon up before the harness starts, reusing an already-running
daemon rather than fighting it.

Upstream: <https://github.com/zzet/gortex> (Go, single static binary, Apache-2.0). Pinned
**v0.64.5** (latest release 2026-09-23; assets `gortex_linux_{amd64,arm64}.tar.gz` +
`checksums.txt`, cosign-signed, SLSA-3).

## Shape

`tools:` (binary) + `mcp:` (stdio child behind a one-line daemon-ensure wrapper) + `init.run`
(daemon + track) + `persist:` (store) + `install.sh` (upstream's own agent wiring) + `hooks:`
(upstream's own hook set). No Dockerfile, no service, no egress entries (100% local once
installed; telemetry opt-in and additionally opted out via `DO_NOT_TRACK=1`).

## Measured facts this design turns on (all v0.64.5, real binary, isolated HOME)

- **`gortex mcp` does NOT auto-start the daemon** — it exits
  (`daemon is unavailable and embedded MCP mode is disabled by default`). Upstream's
  onboarding doc says otherwise; the binary wins. Two consequences: the daemon must be ensured
  BEFORE the child spawns, and "not connected" is the correct degraded signal when it cannot be.
- **A HEADLESS pod never runs `init.run`** — the launcher returns before `_attach` (the attach
  shell is the only init runner), while hatago spawns stdio children at pod start. A
  daemon-ensure that lives only in init.run leaves `harnessed test`/CI permanently red for this
  recipe; the ensure therefore lives in the MCP entry itself (`bash -c 'status || start; exec
  gortex mcp'`), with init.run keeping its own idempotent copy plus the track step.

- **`daemon status` exit code is the gate**: 1 when down (with stale socket files too), 0 when
  up. `daemon start --detach` exits 0 instantly and forks; a second start errors "already
  running" — hence status-check-first (also correct on a host where the user's own daemon is
  serving; reuse, don't restart).
- **With no `XDG_*` vars, everything lands under `~/.gortex/`**: `store/store.sqlite` (graph),
  `cache/{daemon.sock,daemon.pid,daemon.log}`, sidecar ledgers. harnessed exports no XDG vars
  in the pod, so ONE persist entry (`name: .gortex`) captures socket, store and ledger; the
  workspace mount is path-mirrored, so the store's absolute repo paths are mode-invariant.
- **`--claude-config-dir` writes INSIDE the given root** (skills/, commands/, agents/,
  settings.json, .claude.json) — never `$HOME`. With `--agents=claude-code` nothing else is
  written anywhere. The stray `.claude.json` inside the config dir is inert (Claude Code reads
  it at `$HOME` root, and harnessed owns MCP wiring anyway).
- **Upstream's hook set** (from a real install): 8 events, all `<abs-path>/gortex hook`, with
  `timeout: 3000/5000` and `statusMessage` on each. Declared here as bare `gortex hook`
  (PATH is the stable contract) with upstream's matchers verbatim; the schema cannot carry
  timeout/statusMessage.
- **Plain `gortex track` does not block** — `--wait` is the explicit blocking form. Without
  tracking, every tool call returns a structured `repo_not_tracked` error, so `init.run` tracks
  `"$PROJECT_DIR"` after ensuring the daemon (a live daemon attaches its watcher immediately;
  with the daemon down the registration persists for the next start).
- **Daemon restart reopens the persisted store** and re-indexes only changed files — what the
  `persist:` entry protects (first index of this repo ≈4s; large repos, minutes).

## Decisions

| Decision | Why | Alternative rejected |
| --- | --- | --- |
| daemon via `init.run`, every path exits 0 | the headroom seam: the only place a daemon starts before the harness; a failing init aborts the attach, which an optional sidecar must not do | hard-fail (blocks the launch on a code-intelligence tool); MCP auto-start (does not exist at this pin) |
| binary via `tools: github:` | both modes, attestations, no Dockerfile; rtk precedent | hand-rolled tarball+checksum in install.sh (another fetch path to maintain) |
| `gortex install --agents=claude-code --no-hooks --no-claude-md --claude-config-dir …` | replicate the upstream installer (gstack principle); the three suppressions each remove a fight with the assembler (settings.json regen drops installer hooks; identity CLAUDE.md is assembler-rendered; other adapters' user files are not ours to write) | vendoring 40+ skill files into the repo (forks upstream, drifts on every bump) |
| hooks in `recipe.yaml`, `--no-hooks` at install | assembler owns settings.json and regenerates it after install.sh (rtk's 0.06% delivery measurement is exactly this failure) | letting the installer write settings.local.json (double-fire with the declared set) |
| `persist: scope: workspace` | concurrent worktree pods must not share one SQLite store between two daemons | `scope: project` (1:1 daemon:store broken the moment two worktree pods run) |
| PostToolUse matcher kept verbatim (native `mcp__gortex__*`) | through the hatago hub tools are `mcp__hatago__*`; widening to the hub fires gortex's hook for every other recipe's MCP tools | matcher widening (cross-recipe hook chatter) |
| daemon ensure in the MCP entry (wrapper), echoed in `init.run`; both status-gated; `init.run` also tracks `$PROJECT_DIR`; every init path exits 0 | headless pods spawn the MCP child at pod start but never run an attach shell — only the entry itself can ensure the daemon there; the wrapper also self-heals a mid-session daemon crash; init.run remains the place that knows the workspace path | init.run as sole owner (`harnessed test` red forever: no daemon in headless pods); MCP auto-start (does not exist at this pin); hard-fail init (an optional sidecar must not block the launch) |

## Risks / checks

- **First-attach latency**: `daemon start` and `track` both return instantly (measured);
  indexing stays in the daemon's background. No attach delay beyond two fast subprocess calls.
- **Two attach shells racing `daemon start`**: the loser gets "already running" (rc=1),
  swallowed by the warn-and-continue chain; the next `status` sees the winner.
- **Store version skew** after a pin bump: the new daemon migrates/re-indexes the persisted
  store (upstream's restart path); worst case is a re-index, not corruption.
- **Stale socket/pid in the persisted dir** after a pod kill: `daemon status` correctly reports
  down (measured with leftover files) and `start` recovers.
- Verified by: fast suite (schema + JSON-schema + assembly sweep cover the new recipe and
  stack), recipe test script (binary runs, hooks wired, skills baked) in both install contexts,
  and a real `harnessed build` + `harnessed test gortex-default` (expect mcp transitively
  proves the daemon came up — the MCP child exits without one).
