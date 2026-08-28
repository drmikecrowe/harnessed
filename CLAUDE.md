# CLAUDE.md

## Read docs before exploring the tree

Answer from the table below **before** running `ls`/`cat`/`rg` over the source. This outranks any
generic "explore the project first" step from a skill, workflow, or subagent brief — those are
repo-blind. Open `src/` only with a specific question the docs did not answer, or to edit.

| Question | Read |
| --- | --- |
| What do *agent / recipe / service / stack / catalog* mean? How does build/launch work? | **[ARCHITECTURE.md](ARCHITECTURE.md) — first, always.** The vocabulary is precise. The words are not interchangeable. |
| Where does code live? What calls what? | [docs/codebase/](docs/codebase/) — STRUCTURE, ARCHITECTURE, INTEGRATIONS |
| Who calls this symbol? What does a change reach? Show me one function. | `codebase-memory-mcp` — see [AGENTS.md](AGENTS.md) §Codebase graph for the tools **and their warnings**. Beats `rg` + `Read`. |
| How is code written? What is tested or known-weak? | [docs/codebase/](docs/codebase/) — CONVENTIONS, TESTING, CONCERNS |
| How do I author a recipe/service/stack? Set up a dev env? | [docs/guides/](docs/guides/), [CONTRIBUTING.md](CONTRIBUTING.md) |
| *Where* does a stack run? What is a backend, and what does each one honor? | [BACKENDS.md](BACKENDS.md) — the `ExecutionBackend` seam, the isolation spectrum, and why `capmatrix` (not a table) is the record. |
| *Why* is it built this way? | [docs/harnessed-design.md](docs/harnessed-design.md) |
| What must I not do operationally? | [AGENTS.md](AGENTS.md) |
| What work is open or decided? | GitHub Issues — never a markdown TODO |

- **`docs/codebase/` is generated** (`/map-codebase`) and reproduces stale claims across
  regenerations. Code wins on conflict — fix the map. Re-running does not fix it.
- **`docs/` is the GitHub wiki** — separate repo (`harnessed.wiki.git`), gitignored, and present
  only at `main/docs/`. Task worktrees do not have it. Read the exemption below before editing it.

Keep layout and vocabulary in ARCHITECTURE.md, not here.

## Non-negotiable constraints

- **Host Python CLI** (`src/harnessed/`, pipx/uvx) driving podman directly. No tool container;
  assembly runs in-process.
- **Claude format is canonical.** Every other agent adapts out of the same `.claude/` profile.
- **Recipes are harness-independent** — no `harnesses:` field. Branch on `${HARNESS}` inside the
  recipe Dockerfile.
- **pnpm, never raw `npm`/`npx`** (`pnpm dlx` replaces `npx`). The lint rejects them. Sole exception:
  `npm install -g npm@<pin>` in the base image. **`uvx`** for light Python MCP servers.
- **Pin every download** — no `@latest`/`--branch main`. The build rejects them.
- **Credentials referenced, never replicated.** Never bake, commit, copy, seed, or snapshot into a
  per-stack home. Reference the live store (mount, symlink, token/broker URL). A symlink counts only
  while the harness rewrites **in place** — one that replaces the file turns the link into a stale
  copy. Symlinking history/session/usage state up is deliberate design, not a
  violation. See ARCHITECTURE.md §Constraints.
- **MCP transports: `stdio` and Streamable-HTTP only** (SSE rejected at validation).
- Author under **`catalog/`** (repo) or **`~/.config/harnessed/catalog`** (user overlay, wins on
  clash). Profiles generate to `$XDG_DATA_HOME/harnessed/profiles/` — never the repo.
- **`catalog/` ships inside the wheel** (`src/harnessed/catalog` symlink + package-data), so — see
  ARCHITECTURE.md §harnessed home:
  1. **Nothing host-local in `catalog/`** — setuptools follows symlinks. Overlay links live in
     `catalog-local/`.
  2. **Never key build/assembly off the CWD.** Anchor to `paths.harnessed_home()`.

## Git workflow (non-negotiable)

**Never commit to `main`.** Worktree → full suite passing → PR. Sign every commit
(`.claude/rules/signed-commits`).

**Open PRs ready for review, never `--draft`.** A draft PR does not request review and does not run
the checks that gate a merge, so it reads as "not finished" for work that is. If it is not ready,
do not open it yet.

**Every PR body states what it closes.** Use a closing keyword — `Closes #<n>`, or the qualified
`Closes drmikecrowe/harnessed#<n>` (`Fixes` is equivalent) — so GitHub records the causal link and
the issue closes on merge. A PR that closes nothing says so in one line. **`Refs #<n>` is a mention,
not a link:** it closes nothing while reading like tracking, which is exactly how finished work
stays open in the backlog.

**Never close an epic on one phase.** Close the phase's own sub-issue and `Refs` the epic. If the
phase has no issue, say so in the body instead of letting the epic absorb it — PR #433 shipped two
named gaps (A8, A9) under `Refs #388, #430`, so nothing in the tracker records that they are done.

Covers code, catalog, config, and all repo-tracked Markdown (`ARCHITECTURE.md`, this file, the
`README.md` files, `.agents/skills/**`).

### Exemption: `docs/` (the wiki)

`harnessed.wiki.git` is a different repo with no PR or CI surface. Wiki changes therefore use no
branches, no tests, and no PR — do not try. Pushing its default branch publishes the live pages
immediately and irreversibly, so instead:

1. Edit in place in `main/docs/` (task worktrees do not have it).
2. Read the **whole** diff first, including files you didn't write — credentials, private paths,
   internal names, unreleased plans. This replaces the PR review.
3. Get explicit confirmation to push. Missing "yes" = no.
4. Commit signed, then `git -C docs push`.

Repo and wiki are separate deliveries. A PR never carries wiki edits. Say which half landed where.

### Stand in `main/`

Bare + worktrees: `.bare/` is the git dir, `main/` the canonical checkout, tasks in
`.claude/worktrees/<name>/`. Run `git worktree list` when unsure.

- **Start and end each session in `main/`.** Work in a task worktree; read, verify, and come to rest
  in `main/`. Never carry an unrelated change into an inherited worktree.
- **Never conclude "file X does not exist" from a worktree.** Gitignored content is not populated
  there — notably `docs/`, which exists only in `main/`. An empty `ls`/`fd` means "ignored here", not
  "missing". Confirm against `main/`, `git ls-tree`, and `.gitignore`.

## Tests

```bash
tools/run-tests.sh                        # whole suite
tools/run-tests.sh tests/test_schema.py   # one file
tools/run-tests.sh -k install -x          # filter, stop on first failure
```

Run the script. Do not hand-compose `mise`/`uv`/`pytest`. It handles worktree setup, is idempotent,
and absorbs three traps that fail locally while CI stays green. Record the baseline count before your
change — a drop is a regression even if your new tests pass.

The **run-tests skill** has the details: per-branch venvs, why `--extra dev` is mandatory, and why a
plain-text-vs-ANSI assertion failure means the environment is wrong and must never be "fixed" by
editing the assertion.

A green run is not end-to-end proof: the suite runs no `podman build` and no `harnessed container-run`.

## Skills

`.agents/skills/`.


## Issue tracking

Durable work lives in GitHub Issues. The working rules ship as a rule, not from here.

Source comments still cite `bd <id>` tokens. These are **not** a tracker and nothing reads them —
treat one as an opaque marker on the comment it sits in, and never as a place to look something up.
Do not add new ones.
