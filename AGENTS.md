# harnessed — AI assistant instructions

Repo: https://github.com/drmikecrowe/code-container

This file tells AI coding assistants how to set up and customize **`harnessed`**. The user-facing
entry point is **[README.md](README.md)** — read it first for install, the two config modes
(transparent / isolated), the quickstart, and the command surface. Full architecture rationale is in
[docs/harnessed-design.md](docs/harnessed-design.md); how-to guides are under
[docs/guides/](docs/guides).

> [!IMPORTANT]
> **Do not run `harnessed` or `container` yourself.** Both launch an interactive shell inside a
> container (transparent attaches a live harness; isolated attaches a pod). They are for user
> consumption only. Use `harnessed build`, `harnessed test`, `harnessed list`, or read the source to
> reason about behavior instead.

## Setup instructions

If the user asks you to set up harnessed, walk them through it one step at a time (do not dump the
whole sequence):

1. **Prerequisite:** Podman (preferred) or Docker is the only host dependency. No host
   Python/node/uv is needed.
2. **Install:** have the user run the installer (it clones to `~/.local/share/code-container` and
   symlinks `harnessed` + the `container` alias onto their PATH):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/drmikecrowe/code-container/main/install.sh | bash
   ```
3. **First-run build** (user runs these):
   ```bash
   harnessed build                       # build the shared base/harness/hatago images
   harnessed build tracer-time           # assemble an isolated stack (emit profile + scan + hatago build)
   ```
4. **Run** (user runs): `harnessed transparent` (host-mirror sandbox) or `harnessed tracer-time`
   (the isolated sample stack). See the [quickstart](README.md#quickstart).

## Customizing harnessed

- **Add a recipe** (MCP layer + skills/commands): author `recipes/<name>/recipe.yaml`. See
  [docs/guides/recipe-authoring.md](docs/guides/recipe-authoring.md) (worked examples:
  `recipes/time`, `recipes/ping`).
- **Compose a stack**: author `stacks/<name>/stack.yaml`, or scaffold with `harnessed new <stack>
  --harness <claude|omp|opencode|gemini|antigravity|codex> --recipes a,b,c`. See [docs/guides/stacks.md](docs/guides/stacks.md).
- **Add a shared service sidecar**: `services/<name>/` (its own `Dockerfile` + `service.yaml` +
  server). See [docs/guides/service-authoring.md](docs/guides/service-authoring.md) (worked example:
  `services/ping`).
- **Opt-in secrets** (varlock + 1Password): see [docs/guides/secrets.md](docs/guides/secrets.md).
- **Troubleshoot** (podman, first-run build, `--fresh`, sessions, the nightly re-scan timer): see
  [docs/guides/troubleshooting.md](docs/guides/troubleshooting.md).

> Note: you may only modify files **in this repository**. Do not modify files in the user's home
> directory (`~/`) unless they explicitly ask.

## Harness permissions

If the user asks to configure harnesses to run without permission prompts inside a transparent
instance, read and follow [Permissions.md](Permissions.md).

## Conventions

Follow [CLAUDE.md](CLAUDE.md) for project conventions and constraints (pnpm everywhere; Claude Code
format is canonical; credentials referenced from host, never baked; SSE MCP transport is deprecated
in favor of Streamable HTTP).
