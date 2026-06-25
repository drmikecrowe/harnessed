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
> | **podman** (rootless) | 🧪 **in testing** | The reference runtime (pods). Most complete path — verify your host with `./tools/uat/run-uat.sh 6`. |
> | **Docker** | ⏳ **pending** | A shared-network-namespace path exists (`--network container:`) but is **not yet verified**. Egress firewall needs rootless `NET_ADMIN` (best-effort — `--no-firewall` to skip); shared **service sidecars** aren't wired (no `host.containers.internal`). |
> | **Apple `container`** | ⏳ **pending** | Tracked follow-up. One VM/IP per container, no shared netns — needs a different networking story. |
>
> Runtime differences are abstracted by [`lib/harnessed-runtime.sh`](lib/harnessed-runtime.sh). See [troubleshooting](docs/guides/troubleshooting.md).

You can read my [announcement here](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/)

> Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and extended significantly for rootless Podman, hardware authentication (YubiKey, 1Password), seamless Claude Code auth, composable harness stacks, and alternative AI providers.

---

`harnessed` is **one executable** that launches **composable harness stacks** — each a
podman pod running an AI coding harness (`claude`, `omp`, `opencode`, `gemini`, `antigravity`, or `codex`) plus an MCP hub (hatago) plus optional
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

**Podman (rootless) is the only host dependency** — it's the reference runtime (Docker support is pending; see the runtime table above). No host Python/node/uv is required —
all assembly logic lives in a containerized `harnessed-tools` image ([design §15](docs/harnessed-design.md)).

```bash
curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash
```

The installer clones the repo to `~/.local/share/code-container` (or pulls latest if already
installed) and symlinks `harnessed` onto your PATH (`~/.local/bin` if it's on PATH, else
`/usr/local/bin` via sudo). The installer is fully verbose.

To uninstall, remove the symlinks and the cloned directory.

> **Linux** — tested on Manjaro; should work on any systemd distro. macOS/WSL untested.

## First-run build

Images are built on the host with `podman build` the first time they're needed. The image lineage is three layers:

- **Layer 1 — `harnessed-base`**: fat toolchain image (mise, node@24, python, pnpm; no harness CLI).
- **Layer 2 — `harnessed-<harness>`**: FROM `harnessed-base` + harness CLI installed (one image per harness: `harnessed-claude`, `harnessed-omp`, `harnessed-opencode`, `harnessed-gemini`, `harnessed-antigravity`, `harnessed-codex`).
- **Layer 3 — `harnessed-<stack>`**: derived stack image built by `harnessed build <stack>` — FROM `harnessed-<harness>` + recipe Dockerfiles concatenated (e.g. `harnessed-gstack-time` FROM `harnessed-claude`).

Supporting images (not part of the base→agent→stack lineage):

- **`hatago`** — the MCP hub (aggregates a stack's MCP servers behind one HTTP endpoint; light `pnpm dlx`/`uvx` servers baked in).
- **`harnessed-tools`** — the emit-only assembler image (Python + scanners + pnpm + varlock + `op`). Needed for stack assembly.

```bash
harnessed build          # (re)build the base/claude/hatago images
harnessed build <stack>  # assemble one stack: emit profile + build hatago (+ supply-chain scan)
```

Bare `harnessed build` rebuilds the shared base/harness/hatago images. `harnessed build <stack>`
runs the assembler (emit-only), a scoped source/dependency scan, the host hatago image build, and an
image scan — producing a committed `profiles/<stack>/` tree. Expect first-run latency (images build
via host `podman build`); later runs are cache hits.

## Quickstart

Build and launch the `tracer-time` sample stack — the claude harness + the `time` recipe (one light stdio MCP server + one standalone skill):

```bash
cd /path/to/project
harnessed build tracer-time && harnessed tracer-time
```

`tracer-time` is the smallest end-to-end stack slice: the `claude` harness + the `time` recipe
(one light stdio MCP server + one standalone skill), composed into a committed profile and run as a
pod (harness + hatago). Running an unbuilt stack errors and tells you to `harnessed build` it first.

After building, verify the stack's declared capabilities with the capability test:

```bash
harnessed test tracer-time
```

`harnessed test` launches the stack headless, runs the two-oracle capability check, and writes a per-capability report to `profiles/tracer-time/capability-report.md` (✓ connected / ✗ missing).

## Command surface

| Command | What it does |
| --- | --- |
| `harnessed <stack> [path] [--fresh]` | Isolated stack: assembled profile + pod (harness + hatago) |
| `harnessed build [<stack>]` | Build the base/harness/hatago images, or assemble + build one stack |
| `harnessed test <stack>` | Capability test: launch `--fresh` headless + assert declared capabilities (markdown report) |
| `harnessed svc up \| down \| list <service>` | Manage shared service sidecars (own image + volume) |
| `harnessed list` | List authored stacks + running instances |
| `harnessed stop \| rm <stack>` | Stop / remove every instance of a stack |
| `harnessed new <stack> [--harness claude\|omp\|opencode\|gemini\|antigravity\|codex] [--recipes a,b,c]` | Scaffold a stack manifest |
| `harnessed install \| uninstall <stack>` | Write / remove a `~/.local/bin/<stack>` launcher shim |
| `harnessed auth snyk \| socket` | Set a scanner token (persisted to host `~/.config`; never an image layer) |
| `harnessed rescan` | Re-scan installed harnessed images online (the nightly timer's trigger) |
| `harnessed --fresh ...` | Tear down any existing pod/instance first (isolated) |
| `harnessed --no-firewall ...` | Skip the egress firewall for this run |
| `harnessed -h \| --help` | Show help |

Run `harnessed --help` for the full surface. The legacy `--list`/`--stop`/`--remove`/`--clean` flags
remain for muscle memory (they dispatch to the per-instance path).

## Guides

- **[Recipe authoring](docs/guides/recipe-authoring.md)** — writing `recipes/<name>/recipe.yaml` (MCP layer + skills/commands), with worked examples.
- **[Stacks](docs/guides/stacks.md)** — composing recipes into `stacks/<name>/stack.yaml`, scaffolding, and the build/run/test lifecycle.
- **[Service authoring](docs/guides/service-authoring.md)** — adding a shared sidecar under `services/` (image + manifest + server).
- **[Secrets setup](docs/guides/secrets.md)** — opt-in varlock + 1Password (env-only, never baked).
- **[Troubleshooting](docs/guides/troubleshooting.md)** — podman setup, first-run build, `--fresh`, host-persisted sessions, the nightly re-scan timer.
- **[Architecture & design](docs/harnessed-design.md)** — the *why* behind every decision (§1–§18).

## Supply chain & security

- **pnpm everywhere** — every JavaScript install (global, per-recipe, hatago's bundled servers) uses **pnpm**, never `npm`/`npx`; `pnpm dlx` replaces `npx`. A managed supply-chain config applies `minimumReleaseAge` cooldowns and lifecycle-script default-deny. Recipe validation flags raw `npm`/`npx` and points at the pnpm equivalent ([design §7](docs/harnessed-design.md)).
- **Build-time scan gate** — `harnessed build` runs **osv-scanner** + **pip-audit** (credential-free, always) and **snyk**/**Socket.dev** when a token is present (warn-and-skip otherwise, so the build stays non-interactive). It **fails on high-severity** findings ([design §7](docs/harnessed-design.md)).
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
| **AI harnesses**     | Claude, omp (via bridge), opencode, gemini, antigravity, codex   | Claude, OpenCode, Codex, Copilot                                           | Claude                                                                                                    | Claude                                                                   |

**Use this project** if you want composable experimentation across skill/MCP/memory combinations,
without the friction of re-authentication or tool switching every session.

**Use [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)** if you need enterprise-grade sandboxing with declarative security policies, a privacy-aware LLM proxy, and Kubernetes orchestration for multi-agent environments.

**Use [Trail of Bits' devcontainer](https://github.com/trailofbits/claude-code-devcontainer)** if you're doing security audits or reviewing untrusted repos — their threat model explicitly accounts for malicious code trying to escape the container.

**Use Anthropic's official devcontainer** if you're on a team that wants a standardised, VS Code-integrated development environment with Claude Code.
