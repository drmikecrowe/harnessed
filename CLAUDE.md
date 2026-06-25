# CLAUDE.md

Project instructions for AI assistants. The canonical, always-current sources are:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — repo layout, the agent/recipe/service/stack/catalog
  vocabulary, the host-native build/launch model, and the capability-test oracle. **Read it first.**
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — dev setup and how to add a recipe / agent / service / stack.
- **[AGENTS.md](AGENTS.md)** — operational notes (don't run `harnessed` yourself, etc.).
- **[docs/harnessed-design.md](docs/harnessed-design.md)** — the deeper rationale (the *why*).

Do not duplicate layout/vocabulary here — keep it in ARCHITECTURE.md so it can't drift.

## Non-negotiable constraints

- **harnessed is a host Python CLI** (`src/harnessed/`, distributed via pipx/uvx) that drives podman
  directly. No tool container; assembly runs in-process.
- **Claude format is canonical** — every other agent adapts out of the same `.claude/` profile.
- **Recipes are harness-independent** — no `harnesses:` field; harness-specific steps branch on
  `${HARNESS}` inside the recipe Dockerfile.
- **pnpm everywhere** (no npm/npx; `pnpm dlx` replaces npx); **`uvx`** for light Python MCP servers.
- **Pin every download** in recipe Dockerfiles (no `@latest`/`--branch main` — the build rejects them).
- **Credentials referenced from the host, never baked** into an image or committed.
- **Streamable-HTTP MCP** only (SSE is deprecated).
- Authorable content lives under **`catalog/`** (repo) and **`~/.config/harnessed/catalog`** (user
  overlay, wins on clash). Generated profiles go to `$XDG_DATA_HOME/harnessed/profiles/` — never the repo.

## Project skills

Skills live under `.agents/skills/`. See that directory for the current set.
