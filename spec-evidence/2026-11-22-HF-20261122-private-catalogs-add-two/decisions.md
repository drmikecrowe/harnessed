# Decisions — Private catalogs: folder and git sources

## Setup plan
- Isolation: worktree — `worktrees/feat-private-catalogs` on branch `feat/private-catalogs`, from `origin/main` at 36624fb, as AGENTS.md §Git workflow requires.
- Git: signed commits on `feat/private-catalogs`; one commit per RED/GREEN pair; one PR to `main` at the end.
- New dependencies: none. The registry uses `ruamel.yaml`, which `schema.py` and `update.py` already import. The trust record uses the standard library `json`.
- New files: `src/harnessed/catalogsources.py`, `tests/test_catalog_sources.py`, `tests/test_catalog_trust.py`, `tests/test_catalog_git.py`, `tests/test_catalog_scope.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck and secrets, and all six run. Mutation is not declared as a layer: mutmut runs once on `catalogsources.py`, and manual mutants cover `launcher.py`, because mutmut makes no mutant for a typer command.
- Merge gate: `.github/workflows/test.yml` (pytest), `lint.yml` (ruff, pyright, shellcheck), `live.yml` (live and live-docker, triggered by `launcher.py` and `paths.py`), `pr-title.yml`, and the `ocr-review.yml` review check — 7 checks transcribed.

## Facts this SPEC rests on
1. `paths.catalog_roots()` takes no argument and returns the user overlay when it exists, the shipped catalog, and the generated root when it exists (`paths.py:415-433`) — read.
2. `find_in_catalog` and `list_catalog` walk `catalog_roots()` and return the first entry that holds its kind's marker file (`paths.py:457-540`) — read.
3. No `@app.callback` exists, so harnessed has no global option today; `main()` at `launcher.py:7011` preprocesses the arguments before `app()` — reported by the read-only survey agent, not read by the author.
4. `container-run`, `host-run`, and `use` take an optional `path` argument and use the current directory when it is absent (`launcher.py:3221`, `3806`, `4818`); `build` and `list` take no project path; `test` has `--project` with a temporary directory as default — survey agent.
5. Stored state is keyed on the bare stack name: `profile_dir` (`paths.py:570`), `_derived_image` (`layout.py:48`), `host_home`, the tool tree (`setupenv.py:248`), the volumes (`volumes.py:37`, `277`), the plugin marketplace directory (`plugin.py:137`), and the Claude imports files. Only `instance_name` also holds a project hash (`paths.py:635`) — survey agent.
6. A global launcher runs `exec <harnessed> <verb> <harness> --stack <stack> "$@"` and relies on the current directory for the project (`launchscript.py:402-408`) — survey agent.
7. The overlay gate for private keys is `stack_dir.resolve().is_relative_to(paths.user_catalog().resolve())`, in `credmounts._stack_from_overlay` (`credmounts.py:268-276`) and in `container_run` (`launcher.py:4900`) — read.
8. `_trusted_ssh_keys` prints `ignoring ssh_keys from shared-catalog stack '<stack>'` (`credmounts.py:259-264`) — read.
9. `_warn_overlay_shadowed_recipes` prints the overlay warning once per recipe in a process and covers recipes only (`schema.py:2400-2454`) — survey agent.
10. `_resolve_parent_stack_dir` checks the user overlay, then the stack's sibling directory, then the other roots (`schema.py:2035-2040`) — read in part.
11. `update.affected_stacks` and two `catalogseed` functions loop over `catalog_roots()` (`update.py:814`, `catalogseed.py:278`, `298`) — survey agent. Whether each loop writes was not read; the Must NOT line holds either way.
12. `catalog_roots()` and `harnessed_home()` are not cached, and no module computes roots at import — survey agent.
13. `tests/test_paths_generated_root.py:29-30` pins the overlay before the generated root. No test pins the number of roots — survey agent.
14. `tests/conftest.py` isolates `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `HOME` for every test. It does not set `XDG_DATA_HOME`, which falls under the temporary `HOME` — survey agent.
15. `catalogseed.py:246` already runs `git clone` through `proc._run`. No code runs `git fetch` — survey agent.

## Rulings made before the plan
The author ruled on four questions before the story was drafted, and on three more in the story rounds (mcrowe, 2026-11-22):
- Trust: an auto-discovered project catalog needs a one-time `harnessed catalog trust`. A `--catalog` folder and a registered git catalog are trusted by the act of naming them.
- Precedence: `--catalog`, project, user overlay, git catalogs in registration order, shipped, generated.
- Git catalogs: a registry file, a clone under `$XDG_DATA_HOME`, a locked SHA, `catalog update` to move it, and no fetch in a build.
- Delivery: one story, one plan, one PR.
- Discovery: the project directory, then each parent up to the git top level.
- Subcommands: `list`, `remove`, and `untrust` are in this PR.
- Example URL: `git@github.com:drmikecrowe/harnessed-catalog.git`.

## Decide calls

### Decide 1. Which directory do `build`, `list`, `test`, and `catalog list` use as the project?
`build` and `list` take no project path today (`launcher.py:5430`, `5631`). The story's constraint says discovery anchors on the launch's project path, never on the current directory. The launch commands already default their project to the current directory (`launcher.py:4818`).

- A. A `--project <dir>` option, and the current directory when it is absent. Cost: `build` and `list` read the current directory for the first time, the same way a launch already does.
- B. A `--project <dir>` option, and no project catalog when it is absent. Cost: `harnessed build mine claude` inside the project fails to find a project stack unless the option is typed every time.

Default: A.
- Ruling: A (mcrowe, 2026-11-22)

Changes: Terms defines the project directory with the current directory as the fallback; S2.1 to S2.8 and S9.1 use `--project`.

### Decide 2. When does a stack get a scoped storage name?
Every stored path is keyed on the bare stack name (fact 5), so two projects that each define `default` would overwrite one profile, image, host home, and volume set.

- A. Only when the stack's closure holds an entry from a folder source. Cost: harnessed loads the stack before it can name its storage, and the storage name must be passed to every stored-state path. A project catalog that adds one unrelated recipe leaves `default` and its host home as they are.
- B. Whenever any folder source is active. Cost: simpler to build, but every stack launched in a project with a catalog gets a new host home, new volumes, and a new image, so login and session state do not carry over from the unscoped stack.

Default: A.
- Ruling: A (mcrowe, 2026-11-22)

Changes: Terms defines a scoped stack by its closure; S9.3 and S9.4 state the two sides of the rule.

### Decide 3. Which catalog does `harnessed catalog trust <dir>` trust?
AC-3 says the command records "that project's `.harnessed/catalog` path". AC-2 finds a project catalog in the project directory or the nearest parent. The intent review found that the plan's S3.4 takes the second reading.

- A. The catalog that discovery finds from `<dir>`: its own, or the nearest parent's up to the git top level. The command prints the path it trusted. Cost: `trust` in a subfolder trusts a catalog in a parent, which the user sees only in the printed path.
- B. Only `<dir>/.harnessed/catalog` itself. Cost: a user who launches from a subfolder and runs the command the warning names gets an error, and must pass the folder that holds the catalog.

Default: A.
- Ruling: A (mcrowe, 2026-11-22)

Changes: S3.1 prints the trusted path; S3.5 added for a subfolder; S3.4 errors only when discovery finds nothing.

## Intent review, round 1
- Finding 1, the current directory default: accepted as Decide 1, which the author rules on.
- Finding 2, no launch scenario: accepted. S2.7 and S2.8 added.
- Finding 3, what `trust` walks: accepted as Decide 3.
- Finding 4, `integrations/` in the new sources: declined. `integrations.find` resolves through `find_in_catalog` and `list_catalog` across every root today, and the author's trust ruling was made on a question that named integration register scripts as the risk. S2.6 pins that an untrusted catalog's integration is never listed.
- Finding 5, `--name`, S4.5, S6.4, S7.4, S7.5: declined as removals. Each is recorded in `agent-decisions.md` (A3, A8, A9) or fixes a case the source order leaves open, and each scenario now names the criterion it serves.

## Revisions
### Revision 1. Intent review round 1
Added S2.7 and S2.8. Named the criterion that S4.5, S6.4, S7.4, and S7.5 serve.
### Revision 2. Decide round
Decide 1, 2, and 3 ruled A (mcrowe, 2026-11-22). Orientation gained three `Decided:` lines, the Summary says no decision is open, and S3.5 was added.
