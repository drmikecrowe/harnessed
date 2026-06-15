<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### Code Container: Isolated container environment for autonomous coding harnesses (Claude Code, OpenCode, Codex, Gemini)

You can read my [announcement here](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/)

> Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and extended significantly for rootless Podman, hardware authentication (YubiKey, 1Password), seamless Claude Code auth, and alternative AI providers.

> [!WARNING]
> **Work in progress** — this project is still evolving rapidly and the field of agentic AI security is very young. Use at your own risk.
>
> **Docker users:** the egress firewall and related network changes have only been tested with Podman. Behaviour on Docker may differ.

## Which Container Solution Is Right For You?

Three projects solve adjacent problems — pick the one that matches your threat model and workflow:

|                      | This project                                         | [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)                  | [Anthropic devcontainer](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo) | [Trail of Bits](https://github.com/trailofbits/claude-code-devcontainer) |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Primary use case** | Power-user daily driver across multiple AI harnesses | Enterprise sandboxing with policy enforcement                            | VS Code team dev environments                                                                             | Security auditing of untrusted code                                      |
| **Auth model**       | Seamless — host credentials shared into container    | Credential providers inject keys; never exposed in sandbox               | Per-container setup                                                                                       | Fully isolated                                                           |
| **Threat model**     | Contain the AI, not the repo                         | Full defense-in-depth (filesystem, network, process, inference)          | Consistent team environments                                                                              | Malicious repos / adversarial input                                      |
| **Runtime**          | Podman (rootless) or Docker                          | K3s (Kubernetes) inside Docker                                           | Docker / Dev Containers spec                                                                              | Docker                                                                   |
| **AI harnesses**     | Claude, OpenCode, Codex, Gemini                      | Claude, OpenCode, Codex, Copilot                                         | Claude                                                                                                    | Claude                                                                   |

**Use this project** if you want YOLO-mode AI assistance on your own trusted code without the friction of re-authentication or tool switching every session.

**Use [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)** if you need enterprise-grade sandboxing with declarative security policies, a privacy-aware LLM proxy, and Kubernetes orchestration for multi-agent environments.

**Use [Trail of Bits' devcontainer](https://github.com/trailofbits/claude-code-devcontainer)** if you're doing security audits or reviewing untrusted repos — their threat model explicitly accounts for malicious code trying to escape the container.

**Use Anthropic's official devcontainer** if you're on a team that wants a standardised, VS Code-integrated development environment with Claude Code.

## What's Different From Upstream

The original project runs containers as root via Docker and uses NVM for Node.js. This fork needed:

- **Podman (rootless) support** — prefers Podman, falls back to Docker; uses `--userns=keep-id` so file ownership works correctly without running as root
- **Host username in container** — the container user matches your host username (build-time `ARG`), with home at `/container/$USER` to distinguish container sessions from host sessions
- **Seamless Claude Code auth** — mounts `/etc/machine-id`, `~/.claude/`, and `~/.claude.json` so Claude Code sees the same machine identity and credentials as the host; no re-authentication needed
- **Hardware auth passthrough** — 1Password SSH agent socket, GPG agent socket (for YubiKey SSH), GPG config, and YubiKey USB device passthrough
- **mise instead of NVM** — manages Node, Python, pnpm, and all CLI tools from a single config; core tools include opencode, codex, gemini-cli, beads, gastown, fd, ripgrep; additional tools selected via `extra-tools.txt`
- **`--claude` / `--zai` flags** — launch directly into Claude Code (YOLO mode) or Claude with a Z.AI/GLM endpoint
- **Non-blocking exit** — container stop runs in the background so your terminal returns immediately
- **Egress firewall** — iptables whitelist blocks all outbound traffic except approved endpoints (Anthropic, GitHub, npm, pip, mise, Z.AI); applied at every session start via `--cap-add NET_ADMIN`; `--no-firewall` to opt out
- **XDG-aware git config** — checks `~/.config/git` before `~/.gitconfig`

## Where This Is Headed: `harnessed`

> **Status:** design spec — architecture decisions confirmed, schemas/repo-layout/CLI proposed. Full detail in [docs/harnessed-design.md](docs/harnessed-design.md). `container` keeps working exactly as documented below; `harnessed` is the engine it folds into, and `container` becomes a thin alias for `harnessed transparent`.

`container` does one thing well: build an isolated container that **mirrors your host's tool setup** — auth, config, skills, MCP, plugins all bind-mounted from `~`. That's the right SKU for "my laptop, sandboxed."

It's the **wrong** SKU for *experimenting* with commands, skills, plugins, or memory systems, because it drags every host default into the container. Trying to fix that by **merging** a curated set back into the host config doesn't work either: a single shared host namespace (`~/.claude`, `~/.agents`) can't hold every experiment at once — systems like openbrain and hindsight collide, per-runtime `settingSources` drift, and vendored dependencies pollute `~`.

**The insight:** do the merge **per container**, where each stack is isolated, so the collision that kills a shared-host merge disappears by construction.

### One engine, two modes

There's a single executable, `harnessed`. Every stack it launches shares the same base image, the same host-integration mounts (1Password/GPG agents, YubiKey, SSH/git config, egress firewall, the project folder), and the same host auth. Stacks differ on exactly **one axis** — where the config layer (skills/commands/hooks/MCP) comes from:

| Mode | Config source | Mental model |
| --- | --- | --- |
| **`transparent`** | host `~/.claude` (+ `.codex`/`.opencode`/`.gemini`) bind-mounted live | "my laptop, sandboxed" — today's `container` |
| **`isolated`** | auth seeded + an assembled **stack profile** mounted; nothing from host config | "clean room with exactly what I picked" |

Same engine, same operational mounts, one switch. `transparent` is the degenerate case — harness container only, host config mounted live. `isolated` is authenticated but carries **no host defaults**.

### What a stack is

An `isolated` stack is composed **at runtime** inside a podman pod, not baked at build time (`FROM` is linear inheritance — it can't union two sibling systems). A running stack is:

- **harness container** — runs `claude` or `omp`, auth seeded read-only from `~/.claude/.credentials.json`, the current folder mounted, the stack profile mounted into the harness config dir.
- **hatago** — an MCP hub that aggregates every one of the stack's MCP servers behind **one** HTTP endpoint; the harness's `.mcp.json` just points at it. Light `npx`/`uvx` servers run as hatago's children; heavy ones are proxied over the pod network.
- **shared services** — heavy, stateful systems (hindsight = postgres+MCP, openbrain), each its **own** image/container/volume with a lifecycle independent of any instance.

A stack is assembled from **recipes** — hand-authored, per-integration definitions (hindsight, gsd, caveman, …) declaring an MCP layer and/or a file-extension layer (skills/commands/agents/hooks/rules in Claude-canonical form). Recipes are resolved **ahead of time** into a committed, version-controlled **profile** (mounted into the harness, so it's editable and diffable) plus pinned **images** (so the host stays clean and reproducible). Nothing is assembled at container start.

### Benefits — and how each helps

- **Isolated experimentation, zero host pollution.** Each stack is its own clean room, so you can try a new skill, plugin, or memory system without ever touching `~/.claude` and without two experiments stepping on each other. The collision that sank host-merging is gone by construction.
- **Composable, reproducible stacks.** A stack is just a manifest (`harness` + `recipes` + `services`). Name it, commit it, and rebuild it identically anywhere; `harnessed new`/`build`/`install` scaffold it, assemble it, and drop a launcher on your PATH so `my-stack [path]` works from any directory.
- **Shared memory across harnesses.** Service volumes are *service-scoped*, not instance-scoped (`hindsight-data`, never `harnessed-data-<stack>`), so `claude+hindsight` and `omp+hindsight` read and write **one** memory. Services are long-lived and concurrent: multiple instances attach to the same running postgres/MCP at once, and the service outlives any instance (`harnessed svc up/down`).
- **Supply-chain security as a build gate.** Profiles and images are scanned **before** they're committed or published — osv-scanner + pip-audit (credential-free baseline), snyk/Socket.dev when a token is present. Every JavaScript install routes through **pnpm** with `minimumReleaseAge` cooldowns and lifecycle scripts default-denied. `harnessed build` fails on high-severity findings, and a nightly job re-scans installed images so a CVE disclosed *after* build still surfaces.
- **Secrets and auth referenced, never baked.** Host credentials — Claude OAuth token, scanner tokens, optional 1Password via varlock — reach the instance as env or read-only mounts at launch. They are never written into a committed profile or an image layer.
- **One canonical format.** Claude Code format is the single source of truth for skills/commands/hooks/plugins; `omp` consumes it at runtime through a bridge. Author once, run on either harness — no re-authoring.
- **A single host dependency.** The only thing you install is podman/docker. The host builds and runs containers natively; all assembly logic lives in a containerized `harnessed-tools` image (Python + scanners + pnpm) that only **emits** a Dockerfile + profile + a launcher script — no host Python/node/uv version roulette, and no daemon-in-container.
- **Sessions you can inspect.** By default an isolated instance persists `projects/` + `history.jsonl` to a harnessed-owned dir on the host with a stable, legible project slug, so sessions survive recreation and stay inspectable; `--fresh` gives a throwaway clean-room run instead.
- **Proof it built right.** Each stack ships a capability test: bring the instance up headless and assert it exposes exactly the MCP servers, skills, and commands its manifest declares. The result renders as a per-capability markdown report (✓ connected / ✗ missing) for humans and as a green/red signal for CI — one mechanism, two audiences.

### In practice

- **A/B two memory systems.** Run `claude+hindsight` and `claude+openbrain` as separate stacks side by side; neither touches your host config or the other's state.
- **Compare harnesses on equal footing.** Point `claude+hindsight` and `omp+hindsight` at the **same** memory volume and judge which harness drives it better — same data, different engine.
- **Clean-room a flaky plugin.** `--fresh` a stack to reproduce from zero state, then tear it down leaving no residue in `~`.

## Quickstart

### Prerequisites

- **Podman** (preferred) or **Docker**
- **Linux** — tested on Manjaro; should work on any systemd distro. macOS/WSL untested.

### Install

One command — clones the repo and puts `container` on your PATH:

```bash
curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash
```

The installer is fully verbose and shows every step. It:

1. Clones to `~/.local/share/code-container` (or pulls latest if already installed)
2. Symlinks `container.sh` as `container` into `~/.local/bin` (if on PATH) or `/usr/local/bin` (via sudo)

> [!Tip]
> Don't want to install manually? Ask your AI harness to set up for you:
>
> ```
> Help me setup `container`
> ```

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/uninstall.sh | bash
```

Removes the symlink and cloned repo. Optionally removes all `code-*` containers and the `code:latest` image (prompts first).

### Build

```bash
container --build
```

The image is built with your host username baked in (`--build-arg USERNAME=$USER`). Rebuild if your username changes or you update the Dockerfile.

**Includes**: Ubuntu 24.04, Node 22, Python 3, pnpm, Claude Code, OpenCode, Codex CLI, Gemini CLI, ripgrep, fd, beads, gastown.

## Usage

Navigate to any project and run `container` to mount project and enter container.

```bash
cd /path/to/project
container                    # Enter container shell
container --claude           # Enter directly into Claude Code (YOLO mode)
container --zai              # Enter Claude with Z.AI/GLM models
```

Inside the container:

```bash
claude                       # Claude Code (already authenticated)
opencode                     # Start OpenCode
codex                        # Start OpenAI Codex
npm install <package>        # Persists per container
pip install <package>        # Persists per container
exit                         # Stops container if last session
```

Session state is saved. Resuming a container picks up exactly where you left off.

### Common Commands

```bash
container                    # Enter container (current directory)
container /path/to/project   # Enter container for a specific project
container --build            # Rebuild image (e.g. after Dockerfile changes)
container --list             # List all containers
container --stop             # Stop current project's container
container --remove           # Remove current project's container
container --clean            # Remove all stopped containers
```

## Z.AI / GLM Models

Create `~/.zai.json` on your host:

```json
{
  "apiUrl": "https://your-endpoint",
  "apiKey": "your-key",
  "haikuModel": "glm-4.5-air",
  "sonnetModel": "glm-5.0",
  "opusModel": "glm-5.0"
}
```

Then: `container --zai`

### Customization

**Add mise-managed tools** — on first build you'll be prompted to copy `extra-tools.default.txt` as your personal `extra-tools.txt`. Edit it to select which tools to install:

```
# Modern CLI replacements
bat           # cat replacement
eza           # ls replacement
sd            # sed replacement

# Git tools
lazygit
delta

# etc — one tool per line, inline comments supported
```

`extra-tools.txt` is gitignored so your selections stay local. `extra-tools.default.txt` is the committed template listing all tools known to work with mise — treat it as a menu. Browse additional options with `mise registry`. Rebuild required after changes.

**Add system packages** — edit `Dockerfile` and rebuild:

```dockerfile
RUN apt-get update && apt-get install -y postgresql-client
```

**Add mount points** — edit `start_new_container()` in `container.sh`:

```bash
-v "$HOME/.config/something:/container/$USER/.config/something:ro"
```

No rebuild needed for mount changes; just remove and relaunch the container.

### Persistence

- **Per-Container**: Packages, file changes, databases, shell history
- **Shared Across Projects**: Claude Code config/credentials/history, npm/pip caches
- **Read-only from Host**: Git config, SSH keys, GPG keys

### Simultaneous Work

You and your harness can work on the same project simultaneously.

- **Safe**: Reading files, editing files, most development operations
- **Avoid**: Simultaneous Git operations from both sides, installing conflicting `node_modules`
- **Recommended Workflow**: Let your harness run autonomously in the container while you work; review changes and commit.

## Security

- Containers run rootless (`--userns=keep-id`) — no host root access
- SSH keys and git config mounted read-only
- Project isolation prevents cross-contamination
- Host filesystem access limited to explicitly mounted directories

### Egress Firewall

Every container session starts with an iptables egress firewall that blocks all outbound traffic except an explicit whitelist. This closes the primary exfiltration vector identified in agentic AI security research.

**Whitelisted by default:**

- `api.anthropic.com`, `statsig.anthropic.com` — Claude API
- `github.com` and related domains — git, gh CLI, releases
- `registry.npmjs.org` — npm
- `pypi.org`, `files.pythonhosted.org` — pip
- `mise.jdx.dev` — mise tool manager
- Host gateway — local services on the host machine
- Z.AI endpoint from `~/.zai.json` — automatically added when present

To add more domains, edit `egress-firewall.sh`. To disable for a session:

```bash
container --no-firewall
```

**Limitations:**

- IP-based rules are resolved at session start; long-running sessions may see CDN IPs rotate
- Project files can still be deleted by the harness; use version control

### Firewall in Action

The following exchange was conducted inside a live container session to verify the firewall behaves as expected:

> **User:** Can you get the reddit.com homepage content?

The harness fetched it successfully — via its **MCP `webReader` tool**, which runs server-side outside the container and is not subject to the container's iptables rules.

> **User:** Can you POST data to Reddit's search form?

```
curl -X POST "https://www.reddit.com/search/" ...
```

Result: **connection timed out on all 4 Reddit IPs**. DNS resolved fine (allowed), but the TCP connection to port 443 was dropped by the firewall.

| Method                              | Network Access                |
| ----------------------------------- | ----------------------------- |
| Direct (curl, bash, any shell tool) | ❌ Blocked by iptables        |
| MCP server tools (webReader, etc.)  | ✅ Runs outside the container |

**Key insight:** The firewall blocks the harness from making direct outbound connections — exfiltrating data, phoning home, or hitting unauthorized APIs. MCP tools that run server-side are outside the container's network namespace and unaffected, which is the expected and correct behaviour.
