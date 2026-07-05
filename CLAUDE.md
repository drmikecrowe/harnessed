# CLAUDE.md

Project instructions for AI assistants. The canonical, always-current sources are:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — repo layout, the agent/recipe/service/stack/catalog
  vocabulary, the host-native build/launch model, and the capability-test oracle. **Read it first.**
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — dev setup and how to add a recipe / agent / service / stack.
- **[AGENTS.md](AGENTS.md)** — operational notes (don't run `harnessed` yourself, etc.).
- **[docs/harnessed-design.md](docs/harnessed-design.md)** — the deeper rationale (the *why*).
- **[docs/codebase/](docs/codebase/)** — generated codebase maps (regenerate with `/map-codebase`):
  STACK, STRUCTURE, ARCHITECTURE, CONVENTIONS, INTEGRATIONS, TESTING, CONCERNS. The *where the code
  lives, how it's written, and what's wired to what* reference — start here before navigating `src/`.

Do not duplicate layout/vocabulary here — keep it in ARCHITECTURE.md so it can't drift.

## Non-negotiable constraints

- **harnessed is a host Python CLI** (`src/harnessed/`, distributed via pipx/uvx) that drives podman
  directly. No tool container; assembly runs in-process.
- **Claude format is canonical** — every other agent adapts out of the same `.claude/` profile.
- **Recipes are harness-independent** — no `harnesses:` field; harness-specific steps branch on
  `${HARNESS}` inside the recipe Dockerfile.
- **pnpm for package installs** — the recipe lint rejects raw `npm`/`npx` (`pnpm dlx` replaces `npx`).
  The one exception is upgrading npm itself in the base image (`npm install -g npm@<pin>`) — there is
  no pnpm equivalent. **`uvx`** for light Python MCP servers.
- **Pin every download** in recipe Dockerfiles (no `@latest`/`--branch main` — the build rejects them).
- **Credentials referenced from the host, never baked** into an image or committed.
- **Streamable-HTTP MCP** only (SSE is deprecated).
- Authorable content lives under **`catalog/`** (repo) and **`~/.config/harnessed/catalog`** (user
  overlay, wins on clash). Generated profiles go to `$XDG_DATA_HOME/harnessed/profiles/` — never the repo.

## Project skills

Skills live under `.agents/skills/`. See that directory for the current set.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
