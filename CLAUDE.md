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
- **Credentials referenced, never replicated.** Never baked into an image or committed — and never
  copied, seeded, or snapshotted into a per-stack home (host or container). Reference the live store
  (mount, symlink, or token/broker URL) so a refresh is always visible. A *symlink* counts as a
  reference only while the harness rewrites its store **in place**; a harness that replaces the file
  on refresh silently turns that link into a stale copy (see harnessed-8px.10). This is separate
  from — and does not restrict — symlinking history/session/usage state up for a universal rolled-up
  view, which is deliberate design. See ARCHITECTURE.md §Constraints.
- **Streamable-HTTP MCP** only (SSE is deprecated).
- Authorable content lives under **`catalog/`** (repo) and **`~/.config/harnessed/catalog`** (user
  overlay, wins on clash). Generated profiles go to `$XDG_DATA_HOME/harnessed/profiles/` — never the repo.
- **`catalog/` is shipped inside the wheel** (via the `src/harnessed/catalog` symlink + package-data),
  so an installed `harnessed` needs no repo on disk. Two rules follow — see ARCHITECTURE.md §harnessed home:
  1. **Nothing host-local inside `catalog/`.** It is a published artifact and setuptools follows
     symlinks; the overlay symlinks therefore live in `catalog-local/`, never `catalog/<kind>.local`.
  2. **Never key build/assembly off the CWD.** Anchor to `paths.harnessed_home()` (the dir containing
     `catalog/`), so `harnessed build <stack>` behaves the same from any directory.

## Git workflow (non-negotiable)

**No commits to `main`. Every change flows through a worktree → passing tests → PR.**

1. Start work in a **new git worktree** (never edit/commit on `main` directly).
2. Get the **full test suite passing** in that worktree before proposing to merge.
3. Open a **PR** to `main` — merges happen via PR review, not direct pushes.

This applies to code, catalog content, docs, and config alike. Commits are signed
(see `.claude/rules/signed-commits`).

### Where to stand: start and finish in `main/`

This checkout is **bare + worktrees**: `.bare/` is the git dir, `<repo>/main/` is the canonical `main`
checkout, and task worktrees live under `.claude/worktrees/<name>/` (a few older ones sit directly at
the repo root). Run `git worktree list` if you are unsure where you are.

- **Begin each session in `main/`, and return to `main/` when a task is done.** Do the *work* in a
  task worktree per the rules above — but read, verify, and come to rest in `main/`. Never carry an
  unrelated change into whatever worktree you happen to have inherited; it belongs to another task.
- **Never conclude "file X doesn't exist" from inside a worktree.** Git does not populate a worktree
  with **gitignored** content. Most consequentially `docs/`, which is an unpinned live clone of the
  GitHub wiki (see `.gitignore`) — so `docs/guides/*`, `docs/codebase/*`, and `docs/harnessed-design.md`
  exist **only in `main/`**, even though this file and AGENTS.md link to them freely. An empty
  `ls`/`fd` inside a worktree means "ignored or untracked *here*", never "missing from the project".
  Confirm against `main/`, `git ls-tree`, and `.gitignore` before claiming anything is absent or dead.

## Running the tests

```bash
mise trust && mise exec -- uv sync --extra dev   # once per worktree
mise exec -- uv run pytest -q
```

Two traps, both of which produce **failures that CI never sees**:

- **`--extra dev` is required.** `pytest` lives in `[project.optional-dependencies].dev`. A plain
  `uv sync` installs the project without it, and `uv run pytest` then silently falls through to a
  system `pytest` on a different Python — every test errors with `ModuleNotFoundError: No module
  named 'harnessed'`, which looks like a broken checkout rather than a missing extra.
- **The venv is per-branch.** `mise.toml` sets `UV_PROJECT_ENVIRONMENT` to
  `~/.local/share/harnessed/venvs/<branch>/.venv` (one venv per branch, deliberately outside the
  repo so a container bind-mount cannot corrupt it). A fresh worktree therefore starts with no venv
  and needs the sync above — it is not inherited from `main/`.

**Do not "fix" a color-related assertion failure by changing the assertion.** If a CLI test fails
comparing plain text against ANSI-escaped output (`assert "no such stack 'x'" in "\x1b[1;31merror…"`),
the environment is wrong, not the test. `rich` renders plain when stdout is not a TTY — which is the
case under typer's `CliRunner` — but `FORCE_COLOR` overrides that check, and terminal shell
integration sets it without asking (Ghostty exports `FORCE_COLOR=3`). `tests/conftest.py` pops it at
**module import**, which is early enough only because `rich` reads it when a `Console` is
constructed and `launcher.py` builds its Consoles at import; an autouse fixture runs too late. If you
add a new conftest or run tests outside pytest, preserve that.

## Project skills

Skills live under `.agents/skills/`. See that directory for the current set.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
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

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
