# harnessed — AI assistant instructions

Repo: https://github.com/drmikecrowe/harnessed

**This file is the source of truth for every rule an agent follows in this repo.** CLAUDE.md loads it
with `@AGENTS.md` and adds nothing that applies to other agents. Change a rule here, never there.

Start with **[ARCHITECTURE.md](ARCHITECTURE.md)** (layout + vocabulary + the build/launch model) and
**[CONTRIBUTING.md](CONTRIBUTING.md)** (dev setup + how to add catalog content). The deeper rationale
is in [docs/harnessed-design.md](docs/harnessed-design.md); how-to guides are under
[docs/guides/](docs/guides). One generated map exists: [docs/codebase/](docs/codebase/)
(`/map-codebase`) covers the project AS a project — layout, conventions, stack, known-weak areas.

> [!IMPORTANT]
> **Do not run `harnessed container-run` or `harnessed host-run` yourself.** Both hand the
> terminal to an interactive agent session and are for the user: `container-run` attaches a shell
> inside a pod, and `host-run` execs the harness directly on this machine — no pod, against your
> real home and credentials. To reason about behavior use `harnessed build`, `harnessed test`,
> `harnessed list`, or read the source.

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
| Who calls this symbol? What does a change reach? Show me one function. | `codebase-memory-mcp` — see §Codebase graph below for the tools **and their warnings**. Beats `rg` + `Read`. |
| How is code written? What is tested or known-weak? | [docs/codebase/](docs/codebase/) — CONVENTIONS, TESTING, CONCERNS |
| How do I author a recipe/service/stack? Set up a dev env? | [docs/guides/](docs/guides/), [CONTRIBUTING.md](CONTRIBUTING.md) |
| *Where* does a stack run? What is a backend, and what does each one honor? | [BACKENDS.md](BACKENDS.md) — the `ExecutionBackend` seam, the isolation spectrum, and why `capmatrix` (not a table) is the record. |
| *Why* is it built this way? | [docs/harnessed-design.md](docs/harnessed-design.md) |
| What must I not do operationally? | This file: §Non-negotiable constraints, §Git workflow, §Tests |
| How do I write a Story? What does Gate 1 grade, and what is not wired yet? | §Spec-Evidence below — Gate 1 runs here; Gate 2 and the layout checker do not |
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

## Dev workflow (for working ON harnessed)

harnessed is a host Python CLI in `src/harnessed/`. Set up with
`uv sync --extra dev && export PATH="$PWD/.venv/bin:$PATH"`, and run tests as §Tests says.

The CLI runs on the host (edits under `src/harnessed/` are live). `harnessed build <stack> <harness>`
assembles in-process and builds images. `harnessed test <stack> <harness>` is the capability oracle.

## Customizing (catalog content)

Everything authorable is under `catalog/` (and the user overlay `~/.config/harnessed/catalog`). The
**`harnessed-catalog` skill** (`.agents/skills/harnessed-catalog`) is the working reference for all
of it — field lists, the verification ladder, and the authoring rules below in one place. It also
ships to launched stacks through `catalog/recipes/default`, so any stack that inherits the `default`
baseline carries it; a `--stack` launch or `--no-extends` that omits the recipe does not.

- **Recipe** → `catalog/recipes/<name>/recipe.yaml` — see
  [docs/guides/recipe-authoring.md](docs/guides/recipe-authoring.md) (examples: `catalog/recipes/time`,
  `catalog/recipes/ping`, `catalog/recipes/gstack`). Recipes are harness-independent (no `harnesses:`).
- **Stack** → `catalog/stacks/<recipe>…/stack.yaml` (harness-free), or `harnessed new <name>
  --recipes a,b,c`. The harness is a run-time positional. See [docs/guides/stacks.md](docs/guides/stacks.md).
- **Agent** → `catalog/agents/<name>/agent.yaml` + its Dockerfile. Agents are not recipes.
- **Service** → `catalog/services/<name>/` — see
  [docs/guides/service-authoring.md](docs/guides/service-authoring.md) (example: `catalog/services/ping`).
- **Secrets** (opt-in varlock + 1Password): [docs/guides/secrets.md](docs/guides/secrets.md).
- **AWS SSO** (opt-in creds via the aws-sso ECS server): [docs/guides/aws-sso.md](docs/guides/aws-sso.md).
- **Egress** (firewall allowlist; recipe `egress:` + `tools:` to expose a service): [docs/guides/egress.md](docs/guides/egress.md).
- **Troubleshooting**: [docs/guides/troubleshooting.md](docs/guides/troubleshooting.md).

> You may only modify files **in this repository**. Do not modify the user's home directory (`~/`)
> unless they explicitly ask.

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

**Never commit to `main`.** Every change flows through a worktree → the tests the change needs
(§Tests) → PR. Merges happen via PR review, not direct pushes. Sign every commit
(`.claude/rules/signed-commits`).

1. Start work in a **new git worktree** — never edit or commit on `main` directly.
2. Get the **tests the change needs** passing in that worktree (§Tests, "What a change must run").
3. Open a **PR** to `main`. If the change touches the container path, the PR runs `live` and
   `live-docker` for you; read both jobs before merging (§Tests, "The live layer").

**Open PRs ready for review, never `--draft`.** A draft PR does not request review and does not run
the checks that gate a merge, so it reads as "not finished" for work that is. If it is not ready,
do not open it yet.

**Every PR body states what it closes.** Use a closing keyword — `Closes #<n>`, or the qualified
`Closes drmikecrowe/harnessed#<n>` (`Fixes` is equivalent) — so GitHub records the causal link and
the issue closes on merge. A PR that closes nothing says so in one line. **`Refs #<n>` is a mention,
not a link:** it closes nothing while reading like tracking, which is exactly how finished work
stays open in the backlog.

**Every PR title is a conventional commit.** `.github/workflows/pr-title.yml` fails any title that
is not `<type>(<scope>): <summary>`, with `<type>` one of `feat fix perf refactor revert docs test
build ci chore style` and a lowercase scope. The repo squash-merges, so the title becomes the commit
release-please reads: a wrong title drops the PR from the changelog and the version bump. Reuse the
type and scope of the branch's main commit and end with the issue id:
`feat(acp): run a stack over ACP (GH-571)`. **This outranks any title a skill or command supplies.**
`/spec-evidence:pr` passes `<id>: <story title>`, which always fails — give `repo open-pr` a
conventional title instead. Check the title before `gh pr create`; after it, fix it with
`gh pr edit <n> --title`.

**Never close an epic on one phase.** Close the phase's own sub-issue and `Refs` the epic. If the
phase has no issue, say so in the body instead of letting the epic absorb it — PR #433 shipped two
named gaps (A8, A9) under `Refs #388, #430`, so nothing in the tracker records that they are done.

Covers code, catalog, config, and all repo-tracked Markdown (`ARCHITECTURE.md`, this file,
CLAUDE.md, the `README.md` files, `.agents/skills/**`).

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

Bare + worktrees: `.bare/` is the git dir, `main/` the canonical checkout, every task worktree
under `worktrees/<branch-name>/`, named after its branch. Run `git worktree list` when unsure.

- **Start and end each session in `main/`.** Work in a task worktree; read, verify, and come to rest
  in `main/`. Never carry an unrelated change into an inherited worktree. It belongs to another task.
- **Never conclude "file X does not exist" from a worktree.** Gitignored content is not populated
  there — most consequentially `docs/`, an unpinned live clone of the GitHub wiki, so
  `docs/guides/*`, `docs/codebase/*` and `docs/harnessed-design.md` exist **only in `main/`**, even
  though this file links to them freely. An empty `ls`/`fd` means "ignored here", not "missing".
  Confirm against `main/`, `git ls-tree`, and `.gitignore`.
- **Never run a bare `harnessed` to verify a worktree's code.** The global `harnessed` is an editable
  install of `main/`. An AOE pane resolves `harnessed` to it; an interactive shell resolves the branch
  venv that `mise.toml` activates. Run `tools/run-tests.sh` or `uv run harnessed` from the worktree.
- **Every checkout shares one runtime state.** `~/.local/share/harnessed` (profiles, build stamps) and
  the AOE profile are not per worktree. A branch's `harnessed build <stack>` rewrites the profile live
  sessions use. Test build or launch changes on a throwaway stack, or under an isolated
  `XDG_DATA_HOME`/`XDG_CONFIG_HOME`.
- **`.worktree-include` lists the gitignored files a new worktree needs from `main/`.** The
  `agent-of-empires` skill copies them; add a line when a new local file becomes a build input.

## Tests

```bash
tools/run-tests.sh                        # whole suite
tools/run-tests.sh tests/test_schema.py   # one file
tools/run-tests.sh -k install -x          # filter, stop on first failure
HARNESSED_PODMAN=1 tools/run-tests.sh tests/test_recipes_integration.py   # live container tests
```

Run the script. Do not hand-compose `mise`/`uv`/`pytest`. It handles worktree setup, is idempotent,
and absorbs three traps that fail locally while CI stays green. Record the baseline count before your
change — a drop is a regression even if your new tests pass.

### What a change must run

Run what the change can break, not the whole suite by reflex.

- **Code, catalog or build config** — anything under `src/`, `tests/`, `tools/` or `catalog/`
  (Markdown included: `catalog/` ships in the wheel and the lints read it), or `pyproject.toml`,
  `uv.lock`, `mise.toml`: the full suite, and the spec-evidence gauntlet when the change has a story.
- **Everything else** — repo Markdown (`AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md`, the `README.md`
  files), `.agents/**`, `.claude/**`, `.github/workflows/**`: only the tests that name the changed
  file. Find them with `rg -l '<file name>' tests` and run those files with `tools/run-tests.sh`. No
  hit, no run. A hit means a test may pin that file's content — `test_live_workflow.py` reads
  `live.yml` and parses this file's live-trigger table, and `test_ci_pin_upgrade_workflow.py` holds
  the triggers equal to the job. A hit that only names a stack's generated `CLAUDE.md` or
  `AGENTS.md` is noise; running it costs seconds. A workflow change also gets `actionlint`.

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

**Keep this table and the `changes` job in sync.** They are one filter written three times: this
table, the job, and `LIVE_TRIGGERS` in `tools/pin-upgrade.sh`, which
`tests/test_ci_pin_upgrade_workflow.py` holds equal to the job. The job is what actually runs.

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

## Codebase graph: codebase-memory-mcp

For any structural question — what a symbol is, who calls it, what a change reaches — query the
graph. Do not `rg` + `Read`. The project name is derived from your checkout path, so it differs per
machine — read it from `list_projects` rather than assuming one. Re-run `index_repository` after
substantial edits (~14s on this repo); a stale index gives stale answers.

| Need | Call | Notes |
| --- | --- | --- |
| Read one symbol | `get_code_snippet` | Returns source, docstring, complexity, callers/callees. Replaces `Read`. Get `qualified_name` from `search_graph` first — never guess it. |
| Find code | `search_graph` `query:` | BM25. Returns exact line ranges; follow with a ranged `Read` for surrounding context. Swamped by tests — see below; when you can almost name the symbol, use `name_pattern`. |
| Callers, callees, impact | `trace_path` | **`depth: 1`.** `include_tests: false` to read the design, `true` when you need the blast radius — it names the covering tests. |
| Hot paths, fan-in, outliers | `query_graph` | Cypher. |

Warnings — all hit on this repo, not copied from the tool's docs:

- `trace_path` at `depth: 2` mixes real transitive callers with collisions on common method names,
  and nothing in the output separates them: inbound on `script_name` reported 89 callers against a
  true 3, the extras arriving through unrelated `write` methods. Depth 2 generates leads; only
  depth 1 is an answer. `include_evidence: true` prints each hop's resolver — `lsp 0.95` is sound,
  `heuristic 0.38` is a guess.
- `search_graph` `query:` ranks Methods +10, so on a test-heavy repo every test method outranks the
  function you want: `_is_launcher_script` was absent from the top 12 of 869 matches for a query
  describing it exactly. BM25 is for discovery you cannot name; `name_pattern` is for the rest.
- `file_pattern` **fails silently**. `name_pattern` with `file_pattern: "src/.*"` returned
  `total: 0` and a "check your spelling" hint; dropping `file_pattern` returned the 5 real rows. A
  confident empty set reads as "the symbol does not exist" — never conclude absence from a filtered
  search.
- **One index per checkout, keyed on path.** `main/` and each `worktrees/<name>/` are
  separate entries in `list_projects`. Querying from a worktree under `main`'s project name answers
  about the wrong tree. Read the name from `list_projects` every time; `index_status` also reports
  `not_indexed`, which is by-design exclusion and not a failure.
- `detect_changes` at `depth: 2` is a context bomb: `HEAD~5` over 19 files returned 607 symbols /
  53KB and blew the token cap. Use `depth: 1` or `scope`.
- `semantic_query` without a companion `query:` fills `results` with the whole graph as noise.
  Read `semantic_results`; ignore `results`.
- `get_architecture`: skip `layers` and `clusters`. URLs in Markdown and `catalog/` register as HTTP
  routes, and nearly every cluster is mislabelled `tests`. `hotspots` and `entry_points` are sound.
- The complexity property is `complexity`. The tool's own Cypher example says `cyclomatic`, which
  returns empty for every row.
- Ignore the `fp`/`sp` blobs and the duplicated docstring in `get_code_snippet` output.

## Spec-Evidence: Gate 1 runs here

Set up 2026-09-20. This project is the first adopter of the Spec-Evidence Process
from `drmikecrowe/spec-evidence-aisdlc`, which the `spec-evidence-aisdlc` recipe installs. old-coder
already gave this project the discipline: a SPEC, a gauntlet per task, an evidence report, two
review briefs. What Spec-Evidence adds is a gate BEFORE the SPEC exists.

**What is wired, and only this.** Gate 1: an author writes a Story, a registered `story-readiness`
judge grades it against a rubric, and a parser computes the verdict from the judge's record. The
judge writes nothing and its own verdict field decides nothing; `tools/gate_story.py` upstream
computes the verdict from the record's items, and its exit status IS the verdict, 0 ready and 1
not-ready.

**Where a Story lives.** `docs/spec-evidence/<YYYY-MM-DD>-<id>/STORY.md`, named by the `story_dir`
default. NOT beside the `.old-coder/<timestamp>-<slug>/` task directories, because the date format
inside that directory name is hard-coded upstream and cannot read this project's convention. That is
upstream issue 31. When it lands the two roots can become one.

**Why `spec-evidence.toml` exists at the root.** The parser never reads it. The `PreToolUse` handler
that bounds the Gate 1 judge's reads resolves the artifact root from the nearest file of that name
and denies every read when it finds none, so the file is required and holds one key.

**How the parser is invoked.** From the upstream checkout by absolute path, not from here. Nothing
is copied in, so nothing drifts. The recipe installs the six skills and the five agent briefs; the
checkers are not installed, because four files run Gate 1 and the rest of that directory is that
repository grading itself. Consequence: Gate 1 is host-only, since a container has no view of the
checkout.

**What is NOT wired.** `layout_check.py`, `gate_evidence.py` (Gate 2) and `gate_findings.py` all read
the story directory pattern, so none can grade this project's artifact root until issue 31 lands.
Nothing here is unattended and no tracker write-back is real; both are upstream object S6.

**The runbook** is `docs/adopting.md` in the upstream repository, and every step in it was tested
against a layout like this one. Report anything in it that did not work as written.

**Reporting defects** is in the user-scope rule the recipe installs: one issue per defect, label
`dogfood`, carrying the file, the command, the output and the expectation.

<!-- gortex:communities:start -->
## Community Skills

| Area | Description | Explore |
|------|-------------|---------|
| Harnessed 3 Dirs | 810 symbols | `analyze(operation:"communities", id:"community-57")` |
| Tests 2 Dirs Harnessed Launcher | 570 symbols | `analyze(operation:"communities", id:"community-249")` |
| Tests 2 Dirs Patch All | 325 symbols | `analyze(operation:"communities", id:"community-355")` |
| Tests 3 Dirs Append | 309 symbols | `analyze(operation:"communities", id:"community-54")` |
| Tests 3 Dirs Get | 264 symbols | `analyze(operation:"communities", id:"community-68")` |
| Harnessed 1 Dirs Sync Session | 228 symbols | `analyze(operation:"communities", id:"community-116")` |
| Tests 2 Dirs Build Report | 216 symbols | `analyze(operation:"communities", id:"community-442")` |
| 2 Dirs Write | 175 symbols | `analyze(operation:"communities", id:"community-291")` |
| Tests 2 Dirs Validate Agent Pin | 157 symbols | `analyze(operation:"communities", id:"community-106")` |
| Tests 2 Dirs Run | 151 symbols | `analyze(operation:"communities", id:"community-371")` |
| Tests 1 Dirs Completedprocess | 134 symbols | `analyze(operation:"communities", id:"community-267")` |
| Tests 2 Dirs Mcpserver | 120 symbols | `analyze(operation:"communities", id:"community-406")` |
| Tests 2 Dirs Update | 119 symbols | `analyze(operation:"communities", id:"community-42")` |
| Tests 2 Dirs Strip | 117 symbols | `analyze(operation:"communities", id:"community-64")` |
| Harnessed 2 Dirs Make Entry | 116 symbols | `analyze(operation:"communities", id:"community-337")` |
| Tests 3 Dirs Startswith | 113 symbols | `analyze(operation:"communities", id:"community-101")` |
| Harnessed 2 Dirs Profile Dir | 110 symbols | `analyze(operation:"communities", id:"community-254")` |
| Harnessed 1 Dirs Schema | 108 symbols | `analyze(operation:"communities", id:"community-431")` |
| Tests Sync | 103 symbols | `analyze(operation:"communities", id:"community-112")` |
| Harnessed Launcher | 100 symbols | `analyze(operation:"communities", id:"community-18")` |

<!-- gortex:communities:end -->
