<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### harnessed — Composable harness stacks (Claude Code / omp / opencode / gemini / antigravity / codex + an MCP hub + optional shared services)

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
> | **Docker** | ⏳ **pending** | A shared-network-namespace path exists (`--network container:`) but is **not yet verified**. Egress firewall needs rootless `NET_ADMIN` (best-effort — `--no-firewall` to skip); shared **service sidecars** aren't wired (no `host.containers.internal`). |
> | **Apple `container`** | ⏳ **pending** | Tracked follow-up. One VM/IP per container, no shared netns — needs a different networking story. |
>
> Runtime differences (pod vs shared-netns) are handled inside the host CLI (`src/harnessed/launcher.py`). See [troubleshooting](docs/guides/troubleshooting.md).

You can read my [announcement here](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/)

> Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and extended significantly for rootless Podman, hardware authentication (YubiKey, 1Password), seamless Claude Code auth, composable harness stacks, and alternative AI providers.

---

`harnessed` is **one executable** that launches **composable harness stacks** — each a
podman pod running an AI coding harness (`claude` or `omp` today) plus an MCP hub (hatago) plus optional
shared services (hindsight, openbrain, …). You compose a named stack (one harness + chosen recipes)
and launch an authenticated instance that exposes **exactly** the skills/commands/MCP/
services it declares — nothing from the host config — reproducibly, with **podman as the only host
dependency**.

It's for developers who want to compose and trial harness configurations — different
skill/plugin/MCP/memory combinations — in clean, reproducible, throwaway-or-persistent environments
without dragging every host default into the container or polluting `~`.

> The full architecture and design rationale live in **[docs/harnessed-design.md](docs/harnessed-design.md)**
> (§1–§18 — the *why*). This README is the *how*: install, build, and run.

## Isolated mode

Every stack runs in **isolated mode**: auth seeded from host credentials, config layer (skills/commands/hooks/MCP) sourced exclusively from an assembled stack profile — **nothing from host config** leaks in. The harness container + hatago MCP hub run as a podman pod. See [design §2](docs/harnessed-design.md).

## Install

`harnessed` is a **host Python CLI** (Python ≥ 3.12) that drives podman directly — there is no tool
container. You need two host dependencies: **podman** (rootless; the reference runtime — Docker
support is pending, see the runtime table above) and **[uv](https://docs.astral.sh/uv/)** (or pipx)
to install the CLI.

Install the CLI onto your PATH from a clone:

```bash
git clone https://github.com/drmikecrowe/harnessed.git
uv tool install ./harnessed          # or: pipx install ./harnessed
```

This puts `harnessed` in `~/.local/bin` (ensure it's on your PATH; `uv tool update-shell` sets it up).
To uninstall: `uv tool uninstall harnessed` (or `pipx uninstall harnessed`).

> **Working on the CLI itself?** Use an editable dev env instead — see [CONTRIBUTING.md](CONTRIBUTING.md)
> (`uv sync --extra dev` + `export PATH="$PWD/.venv/bin:$PATH"`).

> **Linux** — tested on Manjaro; should work on any systemd distro. macOS/WSL untested.

## First-run build

Images are built on the host with `podman build` the first time they're needed. The image lineage is three layers:

- **Layer 1 — `harnessed-base`**: fat toolchain image (mise, node@24, python, pnpm; no harness CLI).
- **Layer 2 — `harnessed-<agent>`**: FROM `harnessed-base` + the agent CLI installed (one image per agent: `harnessed-claude`, `harnessed-omp`).
- **Layer 3 — `harnessed-<stack>`**: derived stack image built by `harnessed build <stack>` — FROM `harnessed-<agent>` + the stack's recipe Dockerfiles concatenated (e.g. `harnessed-claude_gstack_ping_time_greet` FROM `harnessed-claude`).

Supporting image (not part of the base→agent→stack lineage):

- **`hatago`** — the MCP hub (aggregates a stack's MCP servers behind one HTTP endpoint; light `pnpm dlx`/`uvx` servers baked in).

Assembly runs **host-native in-process** (no tool container) — the host CLI emits the profile and
the `Dockerfile.harnessed-<stack>`, then drives `podman build`.

```bash
harnessed build          # (re)build the shared base/agent/hatago images
harnessed build <stack>  # assemble one stack: emit profile + build images (+ supply-chain scan)
```

Bare `harnessed build` rebuilds the shared base/agent/hatago images. `harnessed build <stack>`
rebuilds the base (so base-image changes propagate), assembles in-process, then builds the hatago,
agent, and derived `harnessed-<stack>` images. The derived image's final layer runs an **in-image,
advisory** supply-chain scan over what actually landed — emitting the profile to
`$XDG_DATA_HOME/harnessed/profiles/<stack>/` (the clone stays immutable source) plus an advisory
`scan-report.json` alongside it. Expect first-run latency (images build via host `podman build`);
later runs are cache hits.

## Quickstart

Build and launch the `claude_time` sample stack — the `claude` agent + the `time` recipe (one light stdio MCP server + one standalone skill):

```bash
cd /path/to/project
harnessed build claude_time && harnessed claude_time
```

`claude_time` is the smallest end-to-end stack slice: the `claude` agent + the `time` recipe
(one light stdio MCP server + one standalone skill), composed into a profile and run as a
pod (agent + hatago). Running an unbuilt stack errors and tells you to `harnessed build` it first.

After building, verify the stack's declared capabilities with the capability test:

```bash
harnessed test claude_time
```

`harnessed test` launches the stack headless, runs the two-oracle capability check, and writes a per-capability report to `$XDG_DATA_HOME/harnessed/profiles/claude_time/capability-report.md` (✓ connected / ✗ missing).

## Command surface

| Command | What it does |
| --- | --- |
| `harnessed <stack> [path] [--fresh]` | Isolated stack: assembled profile + pod (harness + hatago) |
| `harnessed build [<stack>]` | Build the base/harness/hatago images, or assemble + build one stack |
| `harnessed test <stack>` | Capability test: launch `--fresh` headless + assert declared capabilities (markdown report) |
| `harnessed svc up \| down \| list <service>` | Manage shared service sidecars (own image + volume) |
| `harnessed list` | List authored stacks + running instances |
| `harnessed stop \| rm <stack>` | Stop / remove every instance of a stack |
| `harnessed new <stack> [--harness claude\|omp] [--recipes a,b,c]` | Scaffold a stack manifest |
| `harnessed install \| uninstall <stack>` | Write / remove a `~/.local/bin/<stack>` launcher shim |
| `harnessed rescan` | Re-scan installed harnessed images online (the nightly timer's trigger) |
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
- **[Troubleshooting](docs/guides/troubleshooting.md)** — podman setup, first-run build, `--fresh`, host-persisted sessions, the nightly re-scan timer.
- **[Architecture & design](docs/harnessed-design.md)** — the *why* behind every decision (§1–§18).

## Recipe roadmap

The shipped recipes today are mostly **tracer/development** recipes — minimal slices used to exercise
the assembly pipeline and capability test (`greet`, `ping`, `time`, `floating-recipe`). The
**non-development** recipes — real third-party tooling — are the ones worth tracking:

**Shipped**

- [x] **[gstack](https://github.com/garrytan/gstack)** — Garry Tan's skill suite (browser automation,
  design, PDF, …), installed via its upstream `./setup` (`catalog/recipes/gstack/`). *The first real
  non-development recipe.*

**Planned** — packages classified in [docs/RECIPE-STRESS-TEST.md](docs/RECIPE-STRESS-TEST.md)
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
- [ ] **[hyperpowers](https://github.com/withzombies/hyperpowers)** — workflow guidance (task tracking, plan management, TDD) · *skills + hooks recipe*

## Supply chain & security

- **pnpm everywhere** — every JavaScript install (global, per-recipe, hatago's bundled servers) uses **pnpm**, never `npm`/`npx`; `pnpm dlx` replaces `npx`. A managed supply-chain config applies `minimumReleaseAge` cooldowns and lifecycle-script default-deny. Recipe validation flags raw `npm`/`npx` and points at the pnpm equivalent ([design §7](docs/harnessed-design.md)).
- **In-image supply-chain scan (advisory)** — the derived image's final layer runs **snyk** (over mise node globals + recipe installs, via a synthesized manifest; token-gated by a build *secret*, warn-skips without one), plus credential-free **osv-scanner** (recipe lockfiles) and **pip-audit** (the Python env). It **reports** a compact severity summary and writes `scan-report.json` — it does **not** fail the build. Rationale: harnessed installs third-party agent tooling whose dependency trees always carry open advisories, so a hard gate would block every build on code you don't control; visibility is the deliverable ([design §7](docs/harnessed-design.md)).
- **Opt-in secrets** — varlock + 1Password resolve `op://` refs into the pod as **env only** (never a profile, image layer, or repo file). Copy `.env.schema.example` to `~/.config/harnessed/.env.schema` to turn it on. See **[docs/guides/secrets.md](docs/guides/secrets.md)**.
- **Nightly re-scan** — a systemd user timer re-runs osv-scanner **online** against installed images so a CVE disclosed *after* build still surfaces. See **[troubleshooting](docs/guides/troubleshooting.md#nightly-re-scan-timer-sec-04)** for setup (including the `loginctl enable-linger` prerequisite).
- **Secrets/auth referenced, never baked** — Claude OAuth, scanner tokens, and 1Password secrets reach the instance as env or read-only mounts; never an image layer.

> All examples in this repo use placeholder values only (`op(op://Private/Snyk/credential)`, dummy
> tokens) — never real credentials.

## How harnessed is built (in practice)

- **A/B two memory systems.** Run `claude+hindsight` and `claude+openbrain` as separate stacks side by side; neither touches your host config or the other's state.
- **Compare harnesses on equal footing.** Point `claude+hindsight` and `omp+hindsight` at the **same** service-scoped memory volume and judge which harness drives it better — same data, different engine.
- **Clean-room a flaky plugin.** `harnessed <stack> --fresh` reproduces from zero state, then tears down leaving no residue in `~`.
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

**Use [Trail of Bits' devcontainer](https://github.com/trailofbits/claude-code-devcontainer)** if you're doing security audits or reviewing untrusted repos — their threat model explicitly accounts for malicious code trying to escape the container.

**Use Anthropic's official devcontainer** if you're on a team that wants a standardised, VS Code-integrated development environment with Claude Code.
