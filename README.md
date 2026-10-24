<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### Composable, on-demand configuration for agentic harnesses: managed stacks, isolation, controlled upgrades, and security scanning in a repeatable host or container environment

> [!WARNING]
> **Alpha software.** harnessed is under active development, and the field of agentic AI security is very young. Expect breaking changes. Rootless podman is the reference runtime. Docker works with a rootful daemon only: harnessed refuses a rootless daemon, and the 1Password secrets broker does not run under Docker. Apple `container` is pending. The details are in [BACKENDS.md](BACKENDS.md) and [troubleshooting](https://github.com/drmikecrowe/harnessed/wiki/troubleshooting#container-runtimes-podman--docker--apple-container).

harnessed keeps every agent configuration separate, and lets me compose one per project or per task. It drives Claude Code, omp, opencode, Codex, and Antigravity, and nothing it installs lands in `~/.claude` or any other harness's global config.

I built it because plugin suites install globally. Try superpowers for one project and it is in every project. Add a Jira MCP server for a client and it is running while I work on a hobby repo. I also have a set of rules and skills I want everywhere, and I want them there without copying them into every repo. harnessed gives me a baseline stack, a stack per client, and a way to switch one tool on for an afternoon and off again.

I don't type `claude` anymore. I launch a stack.

You can read the [announcement post](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/). Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and rebuilt around rootless podman, composable stacks, and more than one harness.

## Install

```bash
curl -fsSL https://github.com/drmikecrowe/harnessed/releases/latest/download/install.sh | sh
```

The installer prints what it found and every step it will run, then asks y/n before it changes anything. It reads the answer from your terminal, so the prompt works through the pipe. It:

- Requires podman or docker, and stops if it finds neither. It never installs them for you.
- Uses the package manager that already manages harnessed, else the first it finds of mise, uv, or pip (pip installs into a private venv).
- Installs the newest release. Set `HARNESSED_VERSION=<tag>` to pin another one.

It installs two commands into `~/.local/bin`:

- `harnessed`: the CLI.
- `harnessed-self-update`: reinstalls the newest release with the same package manager, without asking.

It also links `harnessed-tools`, the build-time assembler that harnessed uses. You rarely run it yourself.

Each stack you build gets its own launchers in `~/.local/bin` too, named `harnessed-<harness>-<stack>-<backend>`. For the `default` stack with Claude Code:

- `harnessed-claude-default-host`: runs the stack on the host, in the current folder.
- `harnessed-claude-default-container`: runs the same stack in a container.
- `harnessed-acp-claude-default-host`: serves the same stack to an editor over ACP (for harnesses with an ACP mode).

To remove the CLI, run the installer with `--uninstall`. Your config and data stay where they are.

```bash
curl -fsSL https://github.com/drmikecrowe/harnessed/releases/latest/download/install.sh | sh -s -- --uninstall
```

## Three words

- A **recipe** is one thing with its install pinned: a skill suite, a rule set, an MCP server, or a CLI tool. `rtk`, `serena`, `pulumi`, and `superpowers` are recipes.
- A **stack** is a named list of recipes. A stack can `extends:` another one and add to it.
- A **harness** is the CLI that runs the stack: `claude`, `omp`, `opencode`, `codex`, or `antigravity`. You pick it at launch. It is never part of the stack.

Launching a stack assembles its recipes into one profile, points the harness at that profile and nothing else, and puts every MCP server behind one hub. The rest of the vocabulary (agent, service, catalog, overlay, profile) is in [ARCHITECTURE.md](ARCHITECTURE.md). You don't need it to start.

## How I use it

**One baseline, everywhere.** My personal `default` stack lives in my overlay catalog and replaces the one harnessed ships. It holds my status line, my rules and skills, a memory server, and forwarding for my git signing and AWS SSO credentials. Most days I open a project folder and run:

```bash
harnessed-claude-default-host
```

**Small stacks for a task.** When I want to try a tool, I don't touch the baseline. I write a stack that extends it with one to three recipes, and launch that instead:

```yaml
# ~/.config/harnessed/catalog/stacks/graph/stack.yaml
name: graph
extends: default
recipes: [gortex, gh-issue-tracker]
```

**The same stacks in my editor.** Every stack also gets an ACP launcher, such as `harnessed-acp-claude-default-host`. I point the editor at it, and each session the editor opens runs that stack in the session's folder. See [ACP editors](https://github.com/drmikecrowe/harnessed/wiki/acp-editors).

**A container for sensitive work or another account.** Client work runs in its own stack, in a container. It logs in with the client's Claude account (`isolated_auth: true`), carries the client's MCP servers, and has none of my memory or personal skills. The container adds an egress firewall, and neither session can see the other's config.

```bash
harnessed-claude-isolated-container
```

**Other harnesses and model providers.** Stacks are harness-free, so the same stack runs under omp or opencode. One of mine only adds egress to a different model provider for omp.

**My catalog follows me.** `~/.config/harnessed` is a private git repository that I clone on every machine. Secrets are declared in its `.env.schema` and resolved at launch, so none are committed. See [Secrets](https://github.com/drmikecrowe/harnessed/wiki/secrets).

## Getting started

Start on the host. It needs no container, and it proves the composition part in a few minutes. The container boundary comes last, once you have a stack you like. The [getting started guide](https://github.com/drmikecrowe/harnessed/wiki/getting-started) is the longer version, with what each step writes where.

**1. Install** with the one-liner above.

**2. Run the baseline.** The shipped `default` stack is one recipe: the skill that helps you author more recipes.

```bash
cd /path/to/project
harnessed host-run claude
```

Claude starts with a config dir that holds exactly that profile. Your `~/.claude` is untouched.

**3. Add a recipe for this session.**

```bash
harnessed host-run claude --recipe superpowers
```

Now the superpowers skills are loaded. Exit, launch without the flag, and they are gone. Nothing was installed into your host config.

**4. Save it as a stack.** Write the manifest in your overlay catalog. It wins over the shipped catalog, and upgrades never touch it.

```yaml
# ~/.config/harnessed/catalog/stacks/mine/stack.yaml
name: mine
extends: default
recipes: [superpowers, rtk]
```

```bash
harnessed host-run claude --stack mine
```

**5. Build it and use its launchers.** `harnessed build` assembles the stack, builds its container image, and writes its launchers into `~/.local/bin`. From then on, any project folder is one word away.

```bash
harnessed build mine claude
harnessed-claude-mine-host          # on the host
harnessed-claude-mine-container     # in a container, egress firewall on
```

The first build is slow, because it builds the base toolchain image. Later builds are cache hits. `harnessed test mine claude` launches the stack headless and asserts it exposes exactly the skills and MCP servers it declares.

## Command surface

`harnessed --help` has the full surface. These are the commands you will use.

**Launch**

| Command | What it does |
| --- | --- |
| `harnessed host-run <harness> [path] [--stack <name> \| --recipe <name>…]` | Run on the host, no container. Config is isolated per stack; the filesystem and credentials are your real ones. Only harnesses whose config dir is an env var; see [BACKENDS.md](BACKENDS.md) |
| `harnessed container-run <harness> [path] [--stack <name> \| --recipe <name>…]` | Run in a container with the MCP hub, the declared services, and the egress firewall. With neither flag it runs `default`. `--fresh` tears down the existing pod first; `--no-firewall` skips the firewall for one run |
| `harnessed host-exec \| container-exec <harness> [path] … -- <harness args>` | The same, non-interactive: output streams to your terminal and the exit code is the agent's, for scripts and CI |

**Editor (ACP)**

| Command | What it does |
| --- | --- |
| `harnessed host-acp <harness> --stack <name>` | Serve a stack to an editor such as Zed, Atlas, or VS Code over ACP on stdio. One process serves every project the editor opens. Point the editor at `~/.local/bin/harnessed-acp-<harness>-<stack>-host` |
| `harnessed container-acp <harness> [path] --stack <name>` | The same, in a container |

**Build and verify**

| Command | What it does |
| --- | --- |
| `harnessed build [<stack> [<harness>]]` | Build the shared images and reconcile every stale stack, or assemble and build one stack |
| `harnessed test <stack> <harness>` | Launch headless and assert the declared capabilities, written as a markdown report |
| `harnessed context <stack> [<harness>]` | Show what a built stack loads into every session, with token estimates. Exits 1 when a skill is installed twice, a file loads twice, or a memory file leaks in from above the current folder |

**Manage**

| Command | What it does |
| --- | --- |
| `harnessed list` | Authored stacks, which harnesses each is built for, and running instances |
| `harnessed stop \| rm <stack> [<harness>]` | Stop or remove the instances of a stack |
| `harnessed prune` | Tear down instances whose session exited and stayed idle |
| `harnessed clean` | Purge the assembled profile cache |
| `harnessed install \| uninstall <stack> <harness>` | Write or remove a stack's `~/.local/bin/harnessed-<harness>-<stack>-<backend>` launchers |

**Maintain**

| Command | What it does |
| --- | --- |
| `harnessed update [--check] [--yes]` | Find outdated catalog pins and offer to bump them. `upgrade` is the same command; `--check` is the CI mode |
| `harnessed scan <stack> [<harness>]` / `harnessed rescan` | Re-scan built images for vulnerabilities, for one stack or all of them |
| `harnessed svc up \| down \| recreate \| sync \| migrate <service>` | Manage service sidecars |

## Guides

Everything below lives on the [wiki](https://github.com/drmikecrowe/harnessed/wiki).

- [Getting started](https://github.com/drmikecrowe/harnessed/wiki/getting-started): the five steps above, in more detail.
- [Choosing recipes](https://github.com/drmikecrowe/harnessed/wiki/recipe-catalog): what ships, what is planned, and which recipes overlap.
- [Stacks](https://github.com/drmikecrowe/harnessed/wiki/stacks) and [extending stacks](https://github.com/drmikecrowe/harnessed/wiki/extending-stacks): the `stack.yaml` schema, `extends:`, and the build, run, test lifecycle.
- [ACP editors](https://github.com/drmikecrowe/harnessed/wiki/acp-editors): running a stack inside Zed, Atlas, or VS Code.
- [Recipe authoring](https://github.com/drmikecrowe/harnessed/wiki/recipe-authoring): writing `recipe.yaml`, with worked examples.
- [Service authoring](https://github.com/drmikecrowe/harnessed/wiki/service-authoring): shared sidecars.
- [Build and images](https://github.com/drmikecrowe/harnessed/wiki/build-and-images): the base, agent, and stack image lineage, and why the agent installs last.
- [Supply chain and security](https://github.com/drmikecrowe/harnessed/wiki/supply-chain): pnpm everywhere, the advisory in-image scan, secrets as env only, the nightly re-scan.
- [Secrets](https://github.com/drmikecrowe/harnessed/wiki/secrets) and [AWS SSO](https://github.com/drmikecrowe/harnessed/wiki/aws-sso): opt-in credentials, never baked.
- [Egress](https://github.com/drmikecrowe/harnessed/wiki/egress): the firewall and how a recipe opens a host.
- [Troubleshooting](https://github.com/drmikecrowe/harnessed/wiki/troubleshooting): podman setup, runtimes, first-run build, `--fresh`.
- [Alternatives](https://github.com/drmikecrowe/harnessed/wiki/alternatives): how this compares to OpenShell, the Anthropic devcontainer, and Trail of Bits.
- [Design rationale](https://github.com/drmikecrowe/harnessed/wiki/harnessed-design): the why behind every decision.
- [Roadmap](ROADMAP.md): where this is going, at the epic level.

Working on harnessed itself? [CONTRIBUTING.md](CONTRIBUTING.md) has the dev setup.

## Constraints I hold the project to

- Recipes are harness-independent. There is no `harnesses:` field on a recipe; a Dockerfile branches on `${HARNESS}` instead.
- Every download is pinned. `@latest` and `--branch main` fail the build.
- pnpm everywhere, never raw `npm` or `npx`.
- Credentials are referenced, never baked. Claude OAuth, scanner tokens, and 1Password secrets reach the instance as env or read-only mounts.
- All examples in this repo use placeholder values. Never real credentials.
