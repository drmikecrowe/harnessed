<p align="center">
  <img src=".github/README/banner.png" alt="Banner" />
</p>

#### Composable, on-demand configuration for agentic harnesses: managed stacks, isolation, controlled upgrades, and security scanning in a repeatable host or container environment

> [!WARNING]
> **Alpha software.** harnessed is under active development and the field of agentic AI security
> is very young. Expect breaking changes. Rootless podman is the reference runtime and the only one
> in testing; Docker and Apple `container` are pending. The runtime table and its caveats are in
> [troubleshooting](https://github.com/drmikecrowe/harnessed/wiki/troubleshooting#container-runtimes-podman--docker--apple-container).

harnessed keeps every Claude Code (or omp) configuration separate, and lets me compose one per
project or per task. Nothing it installs lands in `~/.claude`.

I built it because plugin suites install globally. Try superpowers for one project and it is in
every project. Add a Jira MCP server for a client and it is running while I work on a hobby repo.
I also have a set of rules and skills I want everywhere, and I want them there without copying
them into every repo. harnessed gives me a baseline stack, a stack per client, and a way to switch
one tool on for an afternoon and off again.

I don't type `claude` anymore. I launch a stack.

You can read the [announcement post](https://mikesshinyobjects.tech/posts/2026/2026-03-20-code-container-isolating-ai-harnesses/).
Forked from [kevinMEH/code-container](https://github.com/kevinMEH/code-container) and rebuilt
around rootless podman, composable stacks, and more than one harness.

## Three words

- A **recipe** is one thing with its install pinned: a skill suite, a rule set, an MCP server, or a
  CLI tool. `rtk`, `serena`, `pulumi`, and `superpowers` are recipes.
- A **stack** is a named list of recipes. Mine is
  `[default, ccstatusline, local, mikes-universal-setup, context-mode, rtk, openbrain, old-coder]`.
- A **harness** is the CLI that runs the stack: `claude` or `omp` today. You pick it at launch. It
  is never part of the stack.

Launching a stack assembles its recipes into one profile, points the harness at that profile and
nothing else, and puts every MCP server behind one hub. The rest of the vocabulary (agent, service,
catalog, overlay, profile) is in [ARCHITECTURE.md](ARCHITECTURE.md). You don't need it to start.

## Two ways I use it

**A stack per project.** My `default` stack runs everything personal. My `isolated` stack is the
same baseline minus my memory server, plus Jira and Confluence, and it authenticates with the
client's Claude account instead of mine. Both run at the same time in two terminals, and neither
one can see the other's config.

```bash
harnessed container-run claude --stack default  ~/Programming/Personal/blog
harnessed container-run claude --stack isolated ~/Programming/Clients/acme
```

**A recipe for this session only.** I don't want the Pulumi CLI, its egress hosts, and my
`~/.pulumi` login mounted into every session. I want them while I'm doing deployments.

```bash
harnessed container-run claude --recipe pulumi
```

That runs the `default` baseline plus pulumi. Nothing is written to a stack file, and the next
launch without the flag has no Pulumi in it.

You can already put skills and an `.mcp.json` in a repo, and for a lot of people that is enough.
What that doesn't give you is the plugin that insists on installing globally, the rules you want in
every repo without committing them to every repo, or a second identity for client work.

## Getting started

Start in host mode. It needs no podman, and it proves the composition part in a few minutes. The
container boundary comes last, once you have a stack you like. The longer version, with what each
step writes where, is the [getting started guide](https://github.com/drmikecrowe/harnessed/wiki/getting-started).

**1. Install.** harnessed is a host Python CLI (Python 3.12 or newer). `install.sh` checks for uv
(and podman, which it never installs for you), then installs the CLI.

```bash
git clone https://github.com/drmikecrowe/harnessed.git
cd harnessed && ./install.sh          # --install-uv to also install uv; --uninstall to remove
```

Or by hand: `uv tool install ./harnessed` (or `pipx install ./harnessed`). Either way the binary
lands in `~/.local/bin`. Working on the CLI itself? Use the editable env in
[CONTRIBUTING.md](CONTRIBUTING.md) instead.

**2. Run the baseline.** The shipped `default` stack is one recipe: the skill that helps you author
more recipes.

```bash
cd /path/to/project
harnessed host-run claude
```

Claude starts with a config dir that holds exactly that profile. Your `~/.claude` is untouched.

**3. Add a recipe for this session.**

```bash
harnessed host-run claude --recipe superpowers
```

Now the superpowers skills are loaded. Exit, launch without the flag, and they are gone. Nothing
was installed into your host config.

**4. Save it as a stack.** Author the manifest in your overlay catalog. Three lines is a stack.

```yaml
# ~/.config/harnessed/catalog/stacks/mine/stack.yaml
name: mine
recipes: [default, superpowers, rtk]
```

```bash
harnessed host-run claude --stack mine
```

**5. Add the container boundary.** Build the image once, then launch the same stack as a podman pod
with the egress firewall on. `harnessed install` writes a `~/.local/bin/mine` shim so the launch
is one word plus the harness.

```bash
harnessed build mine claude
harnessed container-run claude --stack mine
harnessed install mine && mine claude
```

The first build is slow (it builds the base toolchain image). Later builds are cache hits.
`harnessed test mine claude` launches the stack headless and asserts it exposes exactly the skills
and MCP servers it declares.

## Command surface

| Command | What it does |
| --- | --- |
| `harnessed host-run <claude \| omp> [path] [--stack <name> \| --recipe <name>…]` | Host-native: no podman. Config isolated per stack, your real filesystem and credentials. Only harnesses whose config dir is an env var (`CLAUDE_CONFIG_DIR`, `PI_CODING_AGENT_DIR`); see [BACKENDS.md](BACKENDS.md) |
| `harnessed container-run <harness> [path] [--stack <name> \| --recipe <name>…] [--fresh]` | Isolated podman pod: harness + MCP hub + declared services, egress firewall on. `--stack` and `--recipe` are mutually exclusive; with neither, runs `default` |
| `harnessed build [<stack> [<harness>]]` | Build the shared images and reconcile every stale stack, or assemble and build one stack |
| `harnessed test <stack> <harness>` | Capability test: launch headless and assert the declared capabilities, written as a markdown report |
| `harnessed list` | Authored stacks (with which harnesses are built) and running instances |
| `harnessed stop \| rm <stack> [<harness>]` | Stop or remove instances of a stack |
| `harnessed install \| uninstall <stack>` | Write or remove the `~/.local/bin/<stack>` launcher shim |
| `harnessed svc up \| down \| recreate \| sync \| migrate <service>` | Manage service sidecars |
| `harnessed update [--check] [--yes]` | Find outdated catalog pins and offer to bump them; `--check` is the CI mode |
| `harnessed --fresh …` / `--no-firewall …` | Tear down the existing pod first / skip the egress firewall for one run |

`harnessed --help` has the full surface.

## Guides

Everything below lives on the [wiki](https://github.com/drmikecrowe/harnessed/wiki).

- [Getting started](https://github.com/drmikecrowe/harnessed/wiki/getting-started): the five steps above, in more detail.
- [Choosing recipes](https://github.com/drmikecrowe/harnessed/wiki/recipe-catalog): what ships, what is planned, and which recipes overlap.
- [Stacks](https://github.com/drmikecrowe/harnessed/wiki/stacks): the `stack.yaml` schema and the build, run, test lifecycle.
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

## Constraints I hold the project to

- Recipes are harness-independent. There is no `harnesses:` field on a recipe; a Dockerfile branches on `${HARNESS}` instead.
- Every download is pinned. `@latest` and `--branch main` fail the build.
- pnpm everywhere, never raw `npm` or `npx`.
- Credentials are referenced, never baked. Claude OAuth, scanner tokens, and 1Password secrets reach the instance as env or read-only mounts.
- All examples in this repo use placeholder values. Never real credentials.
