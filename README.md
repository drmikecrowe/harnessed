<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### harnessed — Composable harness stacks (Claude Code / omp / opencode / antigravity / codex + an MCP hub + optional shared services)

> [!WARNING]
> **⚠️ ALPHA SOFTWARE — not production-ready.** harnessed is under active development and the field
> of agentic AI security is very young. Expect breaking changes, rough edges, and incomplete
> features. **Use at your own risk.**
>
> **Container runtimes — all WIP:**
>
> | Runtime | Status | Notes |
> | --- | --- | --- |
> | **podman** (rootless) | 🧪 **in testing** | The reference runtime (pods). Most complete path — verify your host with `HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py`. |
> | **Docker** | ⏳ **pending** | A shared-network-namespace path exists (`--network container:`) but is **not yet verified**. Egress firewall needs rootless `NET_ADMIN` (best-effort — `--no-firewall` to skip). Shared **service sidecars** are not wired (no `host.containers.internal`). |
> | **Apple `container`** | ⏳ **pending** | Tracked follow-up. One VM/IP per container, no shared netns — needs a different networking story. |
>
> Runtime differences (pod vs shared-netns) are handled inside the host CLI (`src/harnessed/launcher.py`). See [troubleshooting](docs/guides/troubleshooting.md).

You can read my [announcement here](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/)

> Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and extended for rootless Podman, hardware authentication (YubiKey, 1Password), Claude Code auth, composable harness stacks, and alternative AI providers.

---

`harnessed` is **one executable** that launches **composable harness stacks** — each a
podman pod running an AI coding harness (`claude` or `omp` today) plus an MCP hub (hatago) plus optional
shared services (hindsight, openbrain, …). You compose a named stack (one harness + chosen recipes)
and launch an authenticated instance that exposes **exactly** the skills/commands/MCP/
services it declares — nothing from the host config — reproducibly, with **podman as the only host
dependency**.

It is for developers who want to compose and trial harness configurations — different
skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent environments
without dragging every host default into the container or polluting `~`.

> The full architecture and design rationale live in **[docs/harnessed-design.md](docs/harnessed-design.md)**
> (the *why*). This README is the *how*: install, build, and run.

## Isolated mode

Every stack runs in **isolated mode**: auth seeded from host credentials, config layer (skills/commands/hooks/MCP) sourced exclusively from an assembled stack profile — **nothing from host config** leaks in. The harness container + hatago MCP hub run as a podman pod. See the [design rationale](docs/harnessed-design.md).

## Install

`harnessed` is a **host Python CLI** (Python ≥ 3.12) that drives podman directly — there is no tool
container. You need two host dependencies: **podman** (rootless; the reference runtime — Docker
support is pending, see the runtime table above) and **[uv](https://docs.astral.sh/uv/)** (or pipx)
to install the CLI.

**Recommended — the checked-in installer.** [`install.sh`](install.sh) detects podman + uv (it never
installs podman for you — that is privileged and distro-specific), then installs the CLI from a
**pinned git tag**:

```bash
git clone https://github.com/drmikecrowe/harnessed.git
cd harnessed && ./install.sh          # --install-uv to also install uv; --uninstall to remove
```

No-clone path — download, **review**, then run (the script is auditable; read it before you trust it):

```bash
curl -fsSL https://raw.githubusercontent.com/drmikecrowe/harnessed/v0.1.0/install.sh -o install.sh
less install.sh && sh install.sh
# fast-and-loose one-liner (pinned to a tag, never a branch — we recommend reading it first):
#   curl -fsSL https://raw.githubusercontent.com/drmikecrowe/harnessed/v0.1.0/install.sh | sh
```

> The `v0.1.0` tag above is a placeholder — **no release tag has been cut yet**. Until one exists,
> use the manual step below or run `install.sh` against a local checkout.

**Manual** (what the installer automates):

```bash
git clone https://github.com/drmikecrowe/harnessed.git
uv tool install ./harnessed          # or: pipx install ./harnessed
```

This puts `harnessed` in `~/.local/bin`. Make sure it is on your PATH; `uv tool update-shell` sets it up.
To uninstall: `./install.sh --uninstall` (or `uv tool uninstall harnessed` / `pipx uninstall harnessed`).
Your `~/.config/harnessed` and `$XDG_DATA_HOME/harnessed` data are preserved.

> **Working on the CLI itself?** Use an editable dev env instead — see [CONTRIBUTING.md](CONTRIBUTING.md)
> (`uv sync --extra dev` + `export PATH="$PWD/.venv/bin:$PATH"`).
>
> **Linux** — tested on Manjaro. It should work on any systemd distro, but this is not tested. macOS/WSL: untested.

## First-run build

Images are built on the host with `podman build` the first time they are needed:

- **`harnessed-base`**: fat toolchain image (mise, node@24, python, pnpm; no harness CLI).
- **`harnessed-<harness>-<stack>`**: the derived stack image, built by `harnessed build <stack> <harness>` — FROM `harnessed-base`, then the stack's recipe Dockerfiles concatenated, then **the agent CLI installed last**, then the supply-chain scan.
- **`harnessed-<agent>`**: FROM `harnessed-base` + the agent CLI (`harnessed-claude`, `harnessed-omp`, …). No longer the derived image's parent — it is the fallback image a run uses for a stack with no derived image yet.

**Why the agent installs last.** Agent CLI pins churn far faster than recipes. When the agent image was the derived image's `FROM` parent, every agent bump changed the parent's id and so invalidated *every recipe layer of every stack* on that harness. With the agent on top, an agent bump rebuilds only the agent layer and the scan — the expensive recipe layers stay cached. It also makes the recipe layers harness-independent (they hang off `harnessed-base` with identical instructions), so a stack declaring `harnesses: [claude, omp]` builds its recipe layers once and both harnesses share them.

A recipe that branches on `${HARNESS}` in a `RUN` necessarily splits that cache from its own layer onward, so keep such recipes late in a stack's `recipes:` list.

Supporting image (not part of the base→agent→stack lineage):

- **`hatago`** — the MCP hub (aggregates a stack's MCP servers behind one HTTP endpoint; light `pnpm dlx`/`uvx` servers baked in).

Assembly runs **host-native in-process** (no tool container) — the host CLI emits the profile and
the `Dockerfile.harnessed-<stack>`, then drives `podman build`.

```bash
harnessed build                    # rebuild the shared images, then reconcile every stale stack
harnessed build -j1                # ... one stack at a time (default: half the cores, capped at 4)
harnessed build <stack>            # build every harness in the stack's `harnesses:` list
harnessed build <stack> <harness>  # assemble one stack for a harness: emit profile + build images (+ supply-chain scan)
```

A bare `harnessed build` rebuilds the shared images once, then builds every stale stack
**concurrently** (`--jobs`/`-j`). Each build's output is prefixed with its own coloured
`stack(harness)` tag so the interleaved podman logs stay readable, and one stack failing does not
cancel the others — the failures are reported together at the end.

A stack may declare which harnesses it is built for:

```yaml
name: my-stack
recipes: [superpowers, serena]
harnesses: [claude, omp]   # build-time only — the harness is still a run-time argument
```

`harnessed build <stack>` then fans out to every name in that list, and bare `harnessed build`
includes those `<stack> <harness>` pairs in its sweep — so a freshly-authored stack is provisioned
without naming it. A stack that declares no `harnesses:` is unchanged: `build <stack>` still
requires an explicit harness, and a bare `build` only reconciles it once it has been built at
least once.

Bare `harnessed build` rebuilds the shared base/agent/hatago images (and reconciles every declared
or already-built `<stack> <harness>` pair). `harnessed build <stack> <harness>` rebuilds the base (so
base-image changes propagate), assembles in-process, then builds the hatago, agent, and derived
`harnessed-<harness>-<stack>` images. The derived image's final layer runs an **in-image,
advisory** supply-chain scan over what actually landed — emitting the profile to
`$XDG_DATA_HOME/harnessed/profiles/<stack>/<harness>/` (the clone stays immutable source) plus an advisory
`scan-report.json` alongside it. Expect first-run latency (images build via host `podman build`);
later runs are cache hits.

## Quickstart

Build and launch the `time` sample stack — the `time` recipe (one light stdio MCP server + one standalone skill) — on the `claude` harness:

```bash
cd /path/to/project
harnessed build time claude && harnessed time claude
```

`time` is the smallest end-to-end stack slice: the `time` recipe (one light stdio MCP server + one
standalone skill), composed into a profile and run as a pod (agent + hatago). The harness is chosen
at run time (`harnessed time omp` runs the same stack on omp). Running an unbuilt stack errors and
tells you to `harnessed build` it first.

After building, verify the stack's declared capabilities with the capability test:

```bash
harnessed test time claude
```

`harnessed test` launches the stack headless, runs the two-oracle capability check, and writes a per-capability report to `$XDG_DATA_HOME/harnessed/profiles/time/claude/capability-report.md` (✓ connected / ✗ missing).

## Command surface

| Command | What it does |
| --- | --- |
| `harnessed container-run <harness> [path] [--stack <name> \| --recipe <name>…] [--fresh]` | Isolated stack on a harness: assembled profile + pod (harness + hatago). `--stack` and `--recipe` (repeatable) are mutually exclusive; with neither, runs the `default` baseline |
| `harnessed host-run claude [path] [--stack <name> \| --recipe <name>…]` | Same stack, host-native — no podman, no container; config isolated per stack, credentials from host |
| `harnessed build [<stack> [<harness>]]` | Build the base/harness/hatago images (+ reconcile declared/built pairs), or assemble + build a stack — for one harness, or for every harness in its `harnesses:` list |
| `harnessed test <stack> <harness>` | Capability test: launch `--fresh` headless + assert declared capabilities (markdown report) |
| `harnessed svc up \| down \| recreate \| sync \| migrate <service>` | Manage service sidecars. `recreate` tears down and rebuilds — mounts and env are fixed at create time, so `podman restart` cannot pick up a change to how the container is built |
| `harnessed list` | List authored stacks (with which harnesses are built) + running instances |
| `harnessed stop \| rm <stack> [<harness>]` | Stop / remove instances of a stack (optionally one harness) |
| `harnessed new <stack> [--recipes a,b,c]` | Scaffold a harness-free stack manifest |
| `harnessed install \| uninstall <stack>` | Write / remove a `~/.local/bin/<stack>` launcher shim (forwards the harness arg) |
| `harnessed rescan` | Re-scan installed harnessed images online (the nightly timer's trigger) |
| `harnessed update [--check] [--yes] [--minimum-release-age MIN]` | Find outdated catalog pins and offer to bump them. `tools:` entries resolve against npm / PyPI / GitHub releases / mise; pins inside install scripts and Dockerfiles are reported as **unresolved** rather than skipped. Pins marked `hold` are never bumped. Modelled on pnpm's `minimumReleaseAge` (same unit — minutes, default 10080 = 7 days): a release younger than the window is not offered, and as in pnpm the newest version that *is* old enough is offered instead, naming the newer one it passed over. `--check` is the CI mode: non-zero exit on a stale pin, writes nothing |
| `harnessed --fresh ...` | Tear down any existing pod/instance first (isolated) |
| `harnessed --no-firewall ...` | Skip the egress firewall for this run |
| `harnessed -h \| --help` | Show help |

Run `harnessed --help` for the full surface. Scanner tokens (e.g. `SNYK_TOKEN`) are read from the
environment — there is no `harnessed auth` command (see [Supply chain & security](#supply-chain--security)).

## Guides

- **[Recipe authoring](docs/guides/recipe-authoring.md)** — writing `recipes/<name>/recipe.yaml` (MCP layer + skills/commands), with worked examples.
- **[Stacks](docs/guides/stacks.md)** — composing recipes into `stacks/<name>/stack.yaml`, scaffolding, and the build/run/test lifecycle.
- **[Service authoring](docs/guides/service-authoring.md)** — adding a shared sidecar under `services/` (image + manifest + server).
- **[Secrets setup](docs/guides/secrets.md)** — opt-in varlock + 1Password (env-only, never baked).
- **[AWS SSO](docs/guides/aws-sso.md)** — opt-in AWS credentials via the aws-sso ECS server (short-lived STS, env-only, never baked).
- **[Egress & exposing services](docs/guides/egress.md)** — the container egress firewall; recipe-declared `egress:` hosts + pinned `tools:` to conditionally open a service (e.g. Pulumi Cloud).
- **[Troubleshooting](docs/guides/troubleshooting.md)** — podman setup, first-run build, `--fresh`, host-persisted sessions, the nightly re-scan timer.
- **[Architecture & design](docs/harnessed-design.md)** — the *why* behind every decision.

## Recipe roadmap

The shipped recipes today are mostly **tracer/development** recipes — minimal slices used to exercise
the assembly pipeline and capability test (`greet`, `ping`, `time`, `floating-recipe`). The
**non-development** recipes — real third-party tooling — are the ones worth tracking:

**Shipped**

- [x] **[gstack](https://github.com/garrytan/gstack)** — Garry Tan's skill suite (browser automation,
  design, PDF, …), installed via its upstream `./setup` (`catalog/recipes/gstack/`). *The first real
  non-development recipe.*

**Planned** — packages classified in [docs/todos/2026-06-27-recipe-stress-test.md](docs/todos/2026-06-27-recipe-stress-test.md)
(repos, install commands, data models, and architecture gaps each one surfaces):

- [ ] **[serena](https://github.com/oraios/serena)** — semantic code intelligence MCP (LSP-backed retrieval/editing, 40+ languages) · *MCP recipe*
- [ ] **[agentmemory](https://github.com/rohitg00/agentmemory)** — persistent memory server (53 MCP tools, 12 hooks, HTTP :3111) · *service + recipe*
- [ ] **[headroom](https://github.com/headroomlabs-ai/headroom)** — context/tool-output compression before it reaches the LLM · *MCP recipe*
- [ ] **[gbrain](https://github.com/garrytan/gbrain)** — knowledge brain (synthesis, graph traversal, gap analysis) · *service + recipe*
- [ ] **[solidspec](https://github.com/jyjeanne/solidspec)** — multi-methodology spec-driven development CLI · *skills recipe*
- [ ] **[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)** — codebase knowledge graph (158 languages, C binary) · *MCP recipe*
- [ ] **[context-mode](https://github.com/mksglu/context-mode)** — context-window optimization / tool-output sandbox (6 hooks) · *MCP + hooks recipe*
- [ ] **[tokensave](https://github.com/aovestdipaperino/tokensave)** — pre-indexed semantic code knowledge graph (80+ MCP tools, Rust) · *MCP recipe*
- [ ] **[caveman](https://github.com/JuliusBrussee/caveman)** — concise-output / token-compression skill · *skills recipe*
- [ ] **[hindsight](https://hindsight.vectorize.io)** — memory/recall sidecar (multi-container Postgres stack) · *existing service*
- [ ] **[Superpowers](https://github.com/obra/Superpowers)** — composable software-development methodology skill suite (TDD, code review, subagent-driven dev) · *skills recipe*
- [ ] **[rtk](https://github.com/rtk-ai/rtk)** — Rust Token Killer: CLI proxy that compresses dev-command output to cut LLM tokens 60–90% · *CLI + hooks recipe*
- [x] **[OB1 / Open Brain](https://github.com/NateBJones-Projects/OB1)** — personal knowledge infrastructure: shared persistent memory + vector search across AI tools (MCP + Supabase/Postgres backend) · *service + recipe*

## Supply chain & security

- **pnpm everywhere** — every JavaScript install (global, per-recipe, hatago's bundled servers) uses **pnpm**, never `npm`/`npx`. `pnpm dlx` replaces `npx`. A managed supply-chain config applies `minimumReleaseAge` cooldowns and lifecycle-script default-deny. Recipe validation flags raw `npm`/`npx` and points at the pnpm equivalent ([design rationale](docs/harnessed-design.md)).
- **In-image supply-chain scan (advisory)** — the derived image's final layer runs **snyk** (over mise node globals + recipe installs, via a synthesized manifest; token-gated by a build *secret*, warn-skips without one), plus credential-free **osv-scanner** (recipe lockfiles) and **pip-audit** (the Python env). It **reports** a compact severity summary and writes `scan-report.json` — it does **not** fail the build. Rationale: harnessed installs third-party agent tooling whose dependency trees always carry open advisories. A hard gate blocks every build on code you do not control. Visibility is the deliverable ([design rationale](docs/harnessed-design.md)).
- **Opt-in secrets** — varlock + 1Password resolve `op://` refs as **env only** (never a profile, image layer, or repo file) — into the pod for `container-run`, into the agent process for `host-run`. Copy `.env.schema.example` to `~/.config/harnessed/.env.schema` to turn it on. See **[docs/guides/secrets.md](docs/guides/secrets.md)**.
- **Nightly re-scan** — a systemd user timer re-runs osv-scanner **online** against installed images so a CVE disclosed *after* build still surfaces. See **[troubleshooting](docs/guides/troubleshooting.md#nightly-re-scan-timer-sec-04)** for setup (including the `loginctl enable-linger` prerequisite).
- **Secrets/auth referenced, never baked** — Claude OAuth, scanner tokens, and 1Password secrets reach the instance as env or read-only mounts; never an image layer.

> All examples in this repo use placeholder values only (`op(op://Private/Snyk/credential)`, dummy
> tokens) — never real credentials.

## How harnessed is built (in practice)

- **A/B two memory systems.** Run `claude+hindsight` and `claude+openbrain` as separate stacks side by side; neither touches your host config or the other's state.
- **Compare harnesses on equal footing.** Point `claude+hindsight` and `omp+hindsight` at the **same** service-scoped memory volume and judge which harness drives it better — same data, different engine.
- **Clean-room a flaky plugin.** `harnessed container-run <harness> --stack <name> --fresh` reproduces from zero state, then tears down leaving no residue in `~`.
- **Proof it built right.** Each stack ships a capability test: bring the instance up headless and assert it exposes exactly the MCP servers/skills/commands its manifest declares — rendered as a per-capability markdown report (✓ connected / ✗ missing).

---

### Which container solution is right for you?

Three projects solve adjacent problems — pick the one that matches your threat model and workflow:

|                      | This project                                         | [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)                  | [Anthropic devcontainer](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo) | [Trail of Bits](https://github.com/trailofbits/claude-code-devcontainer) |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Primary use case** | Power-user daily driver across multiple AI harnesses | Enterprise sandboxing with policy enforcement                            | VS Code team dev environments                                                                             | Security auditing of untrusted code                                      |
| **Auth model**       | Seamless — host credentials shared into container    | Credential providers inject keys; never exposed in sandbox               | Per-container setup                                                                                       | Fully isolated                                                           |
| **Threat model**     | Contain the AI, not the repo                         | Full defense-in-depth (filesystem, network, process, inference)          | Consistent team environments                                                                              | Malicious repos / adversarial input                                      |
| **Runtime**          | Podman (rootless); Docker pending                    | K3s (Kubernetes) inside Docker                                           | Docker / Dev Containers spec                                                                              | Docker                                                                   |
| **AI harnesses**     | Claude, omp (via bridge); more planned   | Claude, OpenCode, Codex, Copilot                                           | Claude                                                                                                    | Claude                                                                   |

**Use this project** if you want composable experimentation across skill/MCP/memory combinations,
without the friction of re-authentication or tool switching every session.

**Use [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)** if you need enterprise-grade sandboxing with declarative security policies, a privacy-aware LLM proxy, and Kubernetes orchestration for multi-agent environments.

**Use [Trail of Bits' devcontainer](https://github.com/trailofbits/claude-code-devcontainer)** if you are doing security audits or reviewing untrusted repos — their threat model explicitly accounts for malicious code trying to escape the container.

**Use Anthropic's official devcontainer** if you are on a team that wants a standardised, VS Code-integrated development environment with Claude Code.
