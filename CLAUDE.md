# CLAUDE.md

## Read docs before exploring the tree

Answer from the table below **before** running `ls`/`cat`/`rg` over the source. This outranks any
generic "explore the project first" step from a skill, workflow, subagent brief, **or your own
session instructions** — all of them are repo-blind. A session told to prefer `cat`/`grep` through
Bash is being told which TOOL to reach for, never which SOURCE to consult first.

Open `src/` for the bytes you are about to edit, or for a question the docs did not answer. **"I am
editing, so the table does not apply" is not an exemption** — it is the loophole that costs a
session, because the table is how you learn which bytes to open.

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
- **The graph sees call edges, not conventions.** A grammar rebuilt by hand somewhere else has no
  edge to follow: `aoe._is_launcher_script` re-derives `launchscript.script_name`'s
  `<harness>-<verb>` filename rather than calling it. `trace_path` cannot reach it. So once the
  graph has named the callers, `rg` the convention's literal parts once — that is what text search
  is still for.

Keep layout and vocabulary in ARCHITECTURE.md, not here.

### Changing existing behavior has a fixed order

Renaming, moving, or altering something that already works is not a reading task, and the table
above does not fire on it by itself — you arrive holding "rename this", not "who calls this". Run
both, in order, before the first edit:

1. **`trace_path(<symbol>, direction: "inbound", depth: 1)`** — the complete caller set. Then again
   with `include_tests: true` for the blast radius: it returns the covering tests BY NAME, which is
   how you find the ones that encode the very decision you are changing.
2. **source** — now, and only for the callers step 1 named.

Skipping the first costs you a caller, and both skips were paid while SCOPING the launcher-script
rename (still unbuilt at the time of writing): reading source first found three of the four touch
points, and `trace_path` on the name parser found the fourth, `aoe._is_ours` — whose omission
would have made every pre-existing aoe row unrepairable and blocked registration outright,
silently, on upgrade.

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

### The live layer gates the container path automatically

Nothing else in CI starts a container, so on these files a green suite, a green `lint`, and a green
`pytest` are all consistent with a stack that cannot launch. `live.yml` closes that hole: it runs on
`pull_request`, and its `changes` job runs `live` and `live-docker` when the PR touches any file
below (plus `.github/workflows/live.yml` itself). A PR that touches none of them skips both, and
pays for no container launch.

**Do not dispatch it by hand.** That step used to live here and it did not survive contact — PR #461
merged four defects because nobody ran it. Push the branch, open the PR, read both jobs. Dispatch
(`gh workflow run live.yml --ref <your-branch>`) is now only for evidence on a change the list does
not cover, or before a branch has a PR.

**Keep this table and the `changes` job in sync.** They are one filter written twice; the job is
what actually runs.

| Trigger | Why the suite cannot see it |
| --- | --- |
| `catalog/base/Dockerfile.harnessed-*` | image contents, ownership and modes exist only in a built image |
| `catalog/base/harnessed-start` | the entrypoint runs only in a container |
| `src/harnessed/volumes.py` | volume creation, mounts, and docker's copy-up have no unit-level surface |
| `src/harnessed/launcher.py` | pod/netns placement, the firewall runner, and launch argv |
| `src/harnessed/paths.py` | the userns / `--user` / owner-id mapping |

**The list is the trigger — not your judgement about whether the change looks risky.** PR #461
shipped four defects that every local check passed: the agent had no `--userns` at all, volume
writers ran as the wrong uid, `$HOME` was not traversable by a non-1000 uid, and a one-byte
sentinel silently suppressed docker's volume seeding so the MCP hub had no binary to start.

**A uid-1000 workstation cannot reproduce most of them.** podman's `keep-id` maps you onto the
image's uid, and docker without a mapping only agrees with it when you happen to be uid 1000 —
which every developer here is, and no GitHub runner (uid 1001) is. That is why the evidence has
to come from a runner rather than from your box.

## Skills

`.agents/skills/`.


## Issue tracking

Durable work lives in GitHub Issues. The working rules ship as a rule, not from here.

Source comments still cite `bd <id>` tokens. These are **not** a tracker and nothing reads them —
treat one as an opaque marker on the comment it sits in, and never as a place to look something up.
Do not add new ones.

