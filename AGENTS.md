# harnessed — AI assistant instructions

Repo: https://github.com/drmikecrowe/harnessed

Start with **[ARCHITECTURE.md](ARCHITECTURE.md)** (layout + vocabulary + the build/launch model) and
**[CONTRIBUTING.md](CONTRIBUTING.md)** (dev setup + how to add catalog content). This file holds only
operational notes. The deeper rationale is in [docs/harnessed-design.md](docs/harnessed-design.md);
how-to guides are under [docs/guides/](docs/guides). One generated map exists:
[docs/codebase/](docs/codebase/) (`/map-codebase`) covers the project AS a project — layout,
conventions, stack, known-weak areas.

> [!IMPORTANT]
> **Do not run `harnessed container-run` or `harnessed host-run` yourself.** Both hand the
> terminal to an interactive agent session and are for the user: `container-run` attaches a shell
> inside a pod, and `host-run` execs the harness directly on this machine — no pod, against your
> real home and credentials. To reason about behavior use `harnessed build`, `harnessed test`,
> `harnessed list`, or read the source.

## Dev workflow (for working ON harnessed)

harnessed is a host Python CLI in `src/harnessed/`. Set up and verify with:

```bash
uv sync --extra dev && export PATH="$PWD/.venv/bin:$PATH"
uv run pytest -q                                    # fast unit + assembly tests
HARNESSED_PODMAN=1 uv run pytest tests/test_recipes_integration.py   # live container tests
```

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

## Git workflow (non-negotiable)

**No commits to `main`. Every change flows through a worktree → passing tests → PR.**

1. Start work in a **new git worktree** — never edit or commit on `main` directly.
2. Get the **full test suite passing** in that worktree before proposing to merge.
3. If the change touches the container path — any `Dockerfile.harnessed-*`, `harnessed-start`,
   `volumes.py`, `launcher.py`, or `paths.py` — also run the live layer against your branch
   (`gh workflow run live.yml --ref <branch>`). It is not on `pull_request`, and nothing else in
   CI starts a container. See CLAUDE.md §Tests for the file list and why a green suite does not
   cover it.
4. Open a **PR** to `main`. Merges happen via PR review, not direct pushes.

Applies to code, catalog content, docs, and config alike. Commits are signed
(see `.claude/rules/signed-commits`). This overrides the "PUSH TO REMOTE" step in the Beads
Session Completion block below: push the **worktree branch** and open a PR — never push to `main`.

### Where to stand: start and finish in `main/`

This checkout is **bare + worktrees**: `.bare/` is the git dir, `<repo>/main/` is the canonical `main`
checkout, and every task worktree lives under `<repo>/worktrees/<branch-name>/`, named after its
branch. Run `git worktree list` if you are unsure where you are.

- **Begin each session in `main/`, and return to `main/` when a task is done.** Do the *work* in a
  task worktree per the rules above — but read, verify, and come to rest in `main/`. Never carry an
  unrelated change into whatever worktree you happen to have inherited. It belongs to another task.
- **Never conclude "file X does not exist" from inside a worktree.** Git does not populate a worktree
  with **gitignored** content. Most consequentially `docs/`, which is an unpinned live clone of the
  GitHub wiki (see `.gitignore`) — so `docs/guides/*`, `docs/codebase/*`, and `docs/harnessed-design.md`
  exist **only in `main/`**, even though this file and CLAUDE.md link to them freely. An empty
  `ls`/`fd` inside a worktree means "ignored or untracked *here*", never "missing from the project".
  Confirm against `main/`, `git ls-tree`, and `.gitignore` before claiming anything is absent or dead.

## Conventions

See [CLAUDE.md](CLAUDE.md) for the non-negotiable constraints: host-native CLI, Claude format
canonical, recipes harness-independent, pnpm everywhere, pinned downloads, credentials referenced
(never replicated), Streamable-HTTP MCP.

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

