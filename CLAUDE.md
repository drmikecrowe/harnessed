# CLAUDE.md

## Read docs before exploring the tree

Answer from the table below **before** running `ls`/`cat`/`rg` over the source. This outranks any
generic "explore the project first" step from a skill, workflow, or subagent brief — those are
repo-blind. Open `src/` only with a specific question the docs did not answer, or to edit.

| Question | Read |
| --- | --- |
| What do *agent / recipe / service / stack / catalog* mean? How does build/launch work? | **[ARCHITECTURE.md](ARCHITECTURE.md) — first, always.** The vocabulary is precise; the words are not interchangeable. |
| Where does code live? What calls what? | [docs/codebase/](docs/codebase/) — STRUCTURE, ARCHITECTURE, INTEGRATIONS |
| How is code written? What is tested or known-weak? | [docs/codebase/](docs/codebase/) — CONVENTIONS, TESTING, CONCERNS |
| How do I author a recipe/service/stack? Set up a dev env? | [docs/guides/](docs/guides/), [CONTRIBUTING.md](CONTRIBUTING.md) |
| *Why* is it built this way? | [docs/harnessed-design.md](docs/harnessed-design.md) |
| What must I not do operationally? | [AGENTS.md](AGENTS.md) |
| What work is open or decided? | `bd list`, `bd show <id>` — never a markdown TODO |

- **`docs/codebase/` is generated** (`/map-codebase`) and reproduces stale claims across
  regenerations. Code wins on conflict — fix the map, re-running won't.
- **`docs/` is the GitHub wiki** — separate repo (`harnessed.wiki.git`), gitignored, and present
  only at `main/docs/`; task worktrees do not have it. Read the exemption below before editing it.

Keep layout and vocabulary in ARCHITECTURE.md, not here.

## Non-negotiable constraints

- **Host Python CLI** (`src/harnessed/`, pipx/uvx) driving podman directly. No tool container;
  assembly runs in-process.
- **Claude format is canonical.** Every other agent adapts out of the same `.claude/` profile.
- **Recipes are harness-independent** — no `harnesses:` field. Branch on `${HARNESS}` inside the
  recipe Dockerfile.
- **pnpm, never raw `npm`/`npx`** (`pnpm dlx` replaces `npx`); the lint rejects them. Sole exception:
  `npm install -g npm@<pin>` in the base image. **`uvx`** for light Python MCP servers.
- **Pin every download** — no `@latest`/`--branch main`; the build rejects them.
- **Credentials referenced, never replicated.** Never bake, commit, copy, seed, or snapshot into a
  per-stack home. Reference the live store (mount, symlink, token/broker URL). A symlink counts only
  while the harness rewrites **in place** — one that replaces the file turns the link into a stale
  copy (harnessed-8px.10). Symlinking history/session/usage state up is deliberate design, not a
  violation. See ARCHITECTURE.md §Constraints.
- **Streamable-HTTP MCP only** (SSE deprecated).
- Author under **`catalog/`** (repo) or **`~/.config/harnessed/catalog`** (user overlay, wins on
  clash). Profiles generate to `$XDG_DATA_HOME/harnessed/profiles/` — never the repo.
- **`catalog/` ships inside the wheel** (`src/harnessed/catalog` symlink + package-data), so — see
  ARCHITECTURE.md §harnessed home:
  1. **Nothing host-local in `catalog/`** — setuptools follows symlinks; overlay links live in
     `catalog-local/`.
  2. **Never key build/assembly off the CWD.** Anchor to `paths.harnessed_home()`.

## Git workflow (non-negotiable)

**Never commit to `main`.** Worktree → full suite passing → PR. Sign every commit
(`.claude/rules/signed-commits`).

Covers code, catalog, config, and all repo-tracked Markdown (`ARCHITECTURE.md`, this file, the
`README.md` files, `.agents/skills/**`).

### Exemption: `docs/` (the wiki)

`harnessed.wiki.git` is a different repo with no PR or CI surface. Wiki changes therefore use no
branches, no tests, and no PR — don't try. Pushing its default branch publishes the live pages
immediately and irreversibly, so instead:

1. Edit in place in `main/docs/` (task worktrees don't have it).
2. Read the **whole** diff first, including files you didn't write — credentials, private paths,
   internal names, unreleased plans. This replaces the PR review.
3. Get explicit confirmation to push. Missing "yes" = no.
4. Commit signed, then `git -C docs push`.

Repo and wiki are separate deliveries; a PR never carries wiki edits. Say which half landed where.

### Stand in `main/`

Bare + worktrees: `.bare/` is the git dir, `main/` the canonical checkout, tasks in
`.claude/worktrees/<name>/`. Run `git worktree list` when unsure.

- **Start and end each session in `main/`.** Work in a task worktree; read, verify, and come to rest
  in `main/`. Never carry an unrelated change into an inherited worktree.
- **Never conclude "file X doesn't exist" from a worktree.** Gitignored content isn't populated
  there — notably `docs/`, which exists only in `main/`. An empty `ls`/`fd` means "ignored here", not
  "missing". Confirm against `main/`, `git ls-tree`, and `.gitignore`.

## Tests

```bash
mise trust && mise exec -- uv sync --extra dev   # once per worktree
mise exec -- uv run pytest -q
```

Two traps CI never sees:

- **`--extra dev` is mandatory.** Without it `uv run pytest` falls through to a system pytest and
  every test dies with `ModuleNotFoundError: No module named 'harnessed'` — looks like a broken
  checkout, is a missing extra.
- **The venv is per-branch** (`UV_PROJECT_ENVIRONMENT` → `~/.local/share/harnessed/venvs/<branch>/`,
  outside the repo so a bind-mount can't corrupt it). A fresh worktree has none; sync first.

**Never "fix" a color assertion failure by editing the assertion.** A plain-text-vs-ANSI mismatch
means the environment is wrong: `rich` renders plain off-TTY, but `FORCE_COLOR` overrides that and
Ghostty exports `FORCE_COLOR=3`. `tests/conftest.py` pops it at **module import** — early enough only
because `launcher.py` builds its Consoles at import; an autouse fixture is too late. Preserve that in
any new conftest.

## Skills

`.agents/skills/`.


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
