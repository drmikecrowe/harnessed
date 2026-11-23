# SPEC — Private catalogs: folder and git sources

## Summary
This change lets harnessed read agents, recipes, services, and stacks from three new places: a folder named with `--catalog`, a `.harnessed/catalog` folder inside a project, and a private git repository registered once.

Why: today a catalog entry can live only in the shipped catalog or in the one user overlay. A team cannot share a private catalog, and a project cannot carry its own.

What changes: catalog resolution gains three source kinds in a fixed order. A new `harnessed catalog` command group has six subcommands: `add`, `update`, `list`, `remove`, `trust`, `untrust`. The `build`, `list`, and `test` commands gain a `--project` option. A stack whose content comes from a folder source gets its own storage name, so two projects never share a profile.

The criteria in plain words:
- AC-1: `--catalog <dir>` puts a folder first in the search order.
- AC-2: a project's `.harnessed/catalog` is found from the project directory upward, and is read only when trusted.
- AC-3: `harnessed catalog trust` records a project catalog path.
- AC-4: `harnessed catalog add` clones a git catalog and locks its commit.
- AC-5: builds read the locked clone and never use the network.
- AC-6: `harnessed catalog update` moves the lock.
- AC-7: the search order is fixed, and the first source wins a name clash.
- AC-8: private ssh keys still come only from the user overlay.
- AC-9: a stack built from one project's catalog never changes what another project launches.
- AC-10: a warning names both paths when a new source hides a lower entry.
- AC-11: `harnessed catalog list` shows every source.
- AC-12: `harnessed catalog remove` drops a git catalog.
- AC-13: `harnessed catalog untrust` withdraws trust.

What must not change: with no new source in use, resolution, storage names, and every existing warning stay exactly as they are today. No credential is stored. No build runs git.

How each criterion is proven: every scenario below has a pytest test. Git scenarios use a local bare repository as the URL, so no test needs a network. The full suite, coverage, pyright, ruff, shellcheck, and gitleaks run in the gauntlet. `live` and `live-docker` run on the PR, because `launcher.py` and `paths.py` are live triggers.

Open decisions: none.

## Orientation
- Change: add `--catalog`, project `.harnessed/catalog`, and registered git catalogs as catalog sources, with a `harnessed catalog` command group.
- Why: a catalog entry can live only in the shipped catalog or the user overlay, so a private catalog cannot be shared and a project cannot carry one.
- Touches: `src/harnessed/paths.py`, `src/harnessed/launcher.py`, `src/harnessed/schema.py`, `src/harnessed/credmounts.py`, `src/harnessed/update.py`, `src/harnessed/catalogseed.py`, a new `src/harnessed/catalogsources.py`, four new test files, `ARCHITECTURE.md`, `AGENTS.md`.
- Decided: `build`, `list`, `test`, and `catalog list` take `--project <dir>` and use the current directory when it is absent. This governs the Project directory term and AC-2 (mcrowe, 2026-11-22).
- Decided: a stack gets a scoped storage name only when its closure holds an entry from a folder source. This governs the Scoped stack term and AC-9 (mcrowe, 2026-11-22).
- Decided: `harnessed catalog trust <dir>` trusts the project source that discovery finds from `<dir>`. This governs AC-3 (mcrowe, 2026-11-22).

- Tier: 3 — a new CLI surface, and a change to the resolution seam every build and launch reads.
- Issue: none
- Isolation: worktree — `worktrees/feat-private-catalogs`, branch `feat/private-catalogs`, as AGENTS.md §Git workflow requires.

## Terms
- **Catalog root**: a directory that holds any of `agents/`, `recipes/`, `services/`, `stacks/`, `integrations/`.
- **Flag source**: a catalog root named by one `--catalog <dir>` option. The option repeats. harnessed accepts it before or after the command name.
- **Project directory**: the directory a command works on. For `container-run`, `host-run`, and `use` it is the `path` argument, or the current directory when the argument is absent. This is today's rule. For `build`, `list`, `test`, and `catalog list` it is the new `--project <dir>` option, or the current directory when the option is absent. `test` keeps its temporary project for the launch itself. The current directory as the fallback is a ruling (mcrowe, 2026-11-22). For these four commands it replaces the words "never on the current directory" in the story's constraint.
- **Git top level**: the nearest directory, from the project directory upward, that holds an entry named `.git`. harnessed finds it by reading directories and runs no git command.
- **Project source**: the first `.harnessed/catalog` directory found by checking the project directory and then each parent, stopping after the git top level. When no git top level exists, only the project directory is checked.
- **Trust record**: the JSON file `$XDG_STATE_HOME/harnessed/trusted-catalogs.json`. It holds a list of resolved absolute paths of trusted `.harnessed/catalog` directories.
- **Registry**: the YAML file `~/.config/harnessed/catalogs.yaml` (under `$XDG_CONFIG_HOME` when set). It holds a list `catalogs`, and each item has `name`, `url`, `ref`, and `sha`. `sha` is the lock: a 40-character commit id.
- **Git source**: the clone of one registry item, at `$XDG_DATA_HOME/harnessed/catalogs/<name>`, checked out detached at `sha`. The clone's top directory is the catalog root.
- **User overlay**: `~/.config/harnessed/catalog`. **Shipped catalog**: `harnessed_home()/catalog`. **Generated root**: `$XDG_DATA_HOME/harnessed/generated`, where harnessed writes the stacks it mints for `--recipe`. All three exist today.
- **Source order**: flag sources in command-line order, the trusted project source, the user overlay, git sources in registry order, the shipped catalog, the generated root. `paths.catalog_roots()` returns this order. Two entries that resolve to the same directory count once, at the earlier place.
- **Folder source**: a flag source or a project source.
- **Closure of a stack**: the stack's own directory, each `extends:` parent directory, and the directory of each recipe and service the stack loads.
- **Scoped stack**: a stack whose closure holds one or more directories inside a folder source. A folder source that is active and adds nothing to the closure does not scope the stack (ruled, mcrowe, 2026-11-22).
- **Scope suffix**: `-` and the first 8 hex characters of the SHA-256 of the resolved absolute paths of the active folder sources, joined by a newline, in source order.
- **Storage name**: the name harnessed uses for stored state. For a scoped stack it is the stack name plus the scope suffix. For any other stack it is the stack name, as today. Stored state is the profile directory and its build stamp, the derived image, the instance and pod name, the host home, the tool tree, the config and tools volumes, the plugin marketplace directory, and the Claude imports files. Catalog lookup, `harnessed list`, and global launcher names keep the plain stack name.

## Scenarios
### AC-1: `--catalog` names a folder source
- S1.1 Given `/work/cat/recipes/hello/recipe.yaml` and `/work/cat/stacks/hi/stack.yaml` exist, when `harnessed --catalog /work/cat list` runs, then the output holds the stack `hi`, and `paths.find_in_catalog("recipes", "hello")` returns `/work/cat/recipes/hello`.
- S1.2 Given the same folder, when `harnessed list --catalog /work/cat` runs, then the output also holds `hi`.
- S1.3 (boundary) Given `/work/one/recipes/time/recipe.yaml` and `/work/two/recipes/time/recipe.yaml` exist, when a command runs with `--catalog /work/one --catalog /work/two`, then `find_in_catalog("recipes", "time")` returns `/work/one/recipes/time`.
- S1.4 (negative) Given `/work/none` does not exist, when `harnessed --catalog /work/none build default claude` runs, then it prints an error that names `/work/none`, exits non-zero, runs no build step, and writes no profile.

### AC-2: a trusted project catalog is found from the project directory upward
- S2.1 Given `/work/proj/.git` and `/work/proj/.harnessed/catalog/stacks/mine/stack.yaml` exist and the trust record holds `/work/proj/.harnessed/catalog`, when `harnessed list --project /work/proj/src/app` runs, then the output holds `mine`.
- S2.2 (boundary) Given trusted catalogs at `/work/proj/.harnessed/catalog` and `/work/proj/sub/.harnessed/catalog`, when the project directory is `/work/proj/sub`, then `catalog_roots()` holds `/work/proj/sub/.harnessed/catalog` and does not hold `/work/proj/.harnessed/catalog`.
- S2.3 (boundary) Given `/work/.harnessed/catalog` exists and is trusted, and the git top level is `/work/proj`, when the project directory is `/work/proj`, then `catalog_roots()` does not hold `/work/.harnessed/catalog`.
- S2.4 (boundary) Given `/work/plain` holds no `.git` in itself or any parent, and `/work/.harnessed/catalog` exists and is trusted, when the project directory is `/work/plain`, then no project source is found.
- S2.5 (negative) Given `/work/proj/.harnessed/catalog` exists and the trust record does not hold it, when `harnessed list --project /work/proj` runs, then `catalog_roots()` does not hold it, stderr holds exactly one warning that names `/work/proj/.harnessed/catalog` and `harnessed catalog trust`, and the command exits 0.
- S2.6 (negative) Given the untrusted catalog of S2.5 holds `integrations/evil/register`, when `paths.list_catalog("integrations")` runs, then the result does not hold `evil`.
- S2.7 Given the trusted catalog of S2.1 and the current directory is `/elsewhere`, which holds no `.harnessed/catalog`, when `harnessed container-run claude /work/proj --stack mine` resolves its stack, then `find_in_catalog("stacks", "mine")` returns `/work/proj/.harnessed/catalog/stacks/mine`. The same holds for `host-run` and `use` with the same `path` argument.
- S2.8 (negative) Given the current directory is `/work/proj` of S2.1, when `harnessed container-run claude /elsewhere --stack mine` resolves its stack, then `mine` is not found, because the `path` argument, not the current directory, is the project directory.

### AC-3: `harnessed catalog trust` records a project catalog
- S3.1 Given `/work/proj/.harnessed/catalog` exists, when `harnessed catalog trust /work/proj` runs, then the trust record holds `/work/proj/.harnessed/catalog`, the output names that path, the command exits 0, and a later `harnessed list --project /work/proj` prints no trust warning.
- S3.2 Given the same folder and the current directory is `/work/proj`, when `harnessed catalog trust` runs with no argument, then the trust record holds the same path.
- S3.3 (boundary) Given the path of S3.1 is trusted, when `/work/proj` is renamed to `/work/moved` and `harnessed list --project /work/moved` runs, then the catalog is not read and the S2.5 warning names `/work/moved/.harnessed/catalog`.
- S3.5 (boundary) Given `/work/proj/.git` and `/work/proj/.harnessed/catalog` exist and `/work/proj/src` holds no `.harnessed/catalog`, when `harnessed catalog trust /work/proj/src` runs, then the trust record holds `/work/proj/.harnessed/catalog` and the output names that path. The command trusts the project source that discovery finds from its argument (ruled, mcrowe, 2026-11-22).
- S3.4 (negative) Given `/work/empty` holds no `.harnessed/catalog` in itself or any parent up to its git top level, when `harnessed catalog trust /work/empty` runs, then it prints an error, exits non-zero, and the trust record is byte-identical to before.

### AC-4: `harnessed catalog add` clones and locks a git catalog
- S4.1 Given a git repository at URL `U` whose branch `main` is at commit `C1`, and whose last path segment is `harnessed-catalog.git`, when `harnessed catalog add U --ref main` runs, then `$XDG_DATA_HOME/harnessed/catalogs/harnessed-catalog` is a clone with `HEAD` at `C1`, the registry holds one item with `name: harnessed-catalog`, `url: U`, `ref: main`, `sha: C1`, and the command exits 0. The name is the last path segment of the URL, after the last `/` or `:`, with a trailing `.git` removed.
- S4.2 (boundary) Given the remote default branch of `U` is `trunk` at commit `C2`, when `harnessed catalog add U` runs with no `--ref`, then the registry item has `ref: trunk` and `sha: C2`.
- S4.3 (boundary) Given the registry already holds an item named `harnessed-catalog`, when `harnessed catalog add` runs with another URL whose name is also `harnessed-catalog`, then it prints an error that names `--name`, exits non-zero, and changes nothing. When the same command runs with `--name second`, then the clone lands at `.../catalogs/second` and the registry gains an item `name: second` after the first. `--name` serves AC-4: the name decides the clone path.
- S4.4 (negative) Given URL `/work/no-such-repo.git` does not exist, when `harnessed catalog add /work/no-such-repo.git` runs, then it exits non-zero, the registry file is byte-identical to before or still absent, and `$XDG_DATA_HOME/harnessed/catalogs/` holds no entry named `no-such-repo`.
- S4.5 (negative) Given a name that holds `/`, `..`, or a character outside `a-z`, `A-Z`, `0-9`, `.`, `_`, `-`, when `harnessed catalog add U --name <that name>` runs, then it prints an error, exits non-zero, and changes nothing. This serves AC-4: the name becomes a directory under `$XDG_DATA_HOME/harnessed/catalogs/`, and it must not leave that directory.

### AC-5: builds read the locked clone and use no network
- S5.1 Given the catalog of S4.1 holds `stacks/team/stack.yaml`, when `harnessed build team claude` resolves the stack, then `find_in_catalog("stacks", "team")` returns `.../catalogs/harnessed-catalog/stacks/team`, and no `git` subprocess starts during the command.
- S5.2 (boundary) Given branch `main` of `U` moves to commit `C3` after S4.1, when `harnessed build team claude` runs, then the clone's `HEAD` is still `C1` and the registry `sha` is still `C1`.
- S5.3 (negative) Given the registry holds `harnessed-catalog` and its clone directory is deleted, when `harnessed build team claude` runs, then it prints an error that names `harnessed-catalog` and `harnessed catalog update`, exits non-zero, and runs no build step. The six `harnessed catalog` subcommands do not make this check.

### AC-6: `harnessed catalog update` moves the lock
- S6.1 Given the state of S5.2, when `harnessed catalog update harnessed-catalog` runs, then the clone's `HEAD` is `C3`, the registry `sha` is `C3`, the output holds `C1` and `C3`, and the command exits 0.
- S6.2 Given two registered catalogs, when `harnessed catalog update` runs with no name, then each is updated in registry order. When one fails, the others still update, and the exit is non-zero.
- S6.3 (boundary) Given a catalog added with `--ref <40-character commit id C1>`, when `harnessed catalog update` runs, then the output says the catalog did not change, and `sha` is still `C1`.
- S6.4 (boundary) Given the state of S5.3, when `harnessed catalog update harnessed-catalog` runs, then it clones the catalog again at the current commit of the recorded ref and writes that commit to `sha`. This serves AC-5: the S5.3 error names this command as the repair.
- S6.5 (negative) Given the URL of a registered catalog no longer resolves, when `harnessed catalog update` runs, then the registry file is byte-identical to before, the clone's `HEAD` is unchanged, and the exit is non-zero.
- S6.6 (negative) Given no catalog named `ghost` is registered, when `harnessed catalog update ghost` runs, then it prints an error, exits non-zero, and changes nothing.

### AC-7: the first source in the source order wins
- S7.1 Given recipe `time` exists in a flag source, a trusted project source, the user overlay, two git sources, and the shipped catalog, when `find_in_catalog("recipes", "time")` runs, then it returns the flag source's copy. Each time the winning copy is removed, the next call returns the copy from the next source in the source order.
- S7.2 (boundary) Given git catalogs `first` and `second` were added in that order and both hold `recipes/time/recipe.yaml`, when `find_in_catalog("recipes", "time")` runs with no folder source and no overlay copy, then it returns `.../catalogs/first/recipes/time`.
- S7.3 (negative) Given stack `adhoc` exists in the generated root and in a git source, when `find_in_catalog("stacks", "adhoc")` runs, then it returns the git source's copy, and the generated root is the last item of `catalog_roots()`.
- S7.4 Given stack `mine` in a trusted project source has `extends: default`, and stack `default` exists in that project source, the user overlay, and the shipped catalog, when `mine` loads, then its parent is the project source's `default`. A flag source or project source is checked first for an `extends:` parent, in source order. After them, today's parent order applies unchanged.
- S7.5 Given `/work/cat` is both a flag source and, through a symlink, the trusted project source, when `catalog_roots()` runs, then `/work/cat` appears once, at the flag source's place. S7.4 and S7.5 serve AC-7: each fixes which copy wins in a case the source order alone leaves open.

### AC-8: private ssh keys come only from the user overlay
- S8.1 Given stack `keyed` in a flag source declares `ssh_keys: [id_ed25519]`, when `container-run` prepares its mounts, then no private key is mounted and stderr holds `ignoring ssh_keys from shared-catalog stack 'keyed'`. The same holds when `keyed` is in a trusted project source and when it is in a git source.
- S8.2 (boundary) Given the same `keyed/stack.yaml` is copied to `~/.config/harnessed/catalog/stacks/keyed/` and no higher source holds `keyed`, when `container-run` prepares its mounts, then `id_ed25519` is in the trusted key list, as today.
- S8.3 (negative) Given a flag source whose directory is a symlink to a directory inside the user overlay, when a stack from it declares `ssh_keys`, then the keys are dropped with the S8.1 note. The gate reads which source the stack came from, never the resolved path.
- S8.4 (negative) Given the trusted project source of S2.1 holds stack `keyed` with `ssh_keys`, when a service container of that stack starts, then `_stack_from_overlay("keyed")` is false and the service mounts no private key.

### AC-9: stored state is separate for a scoped stack
- S9.1 Given project `/work/a` has a trusted project source that holds `stacks/default/stack.yaml`, and `profiles/default/claude` already exists from a build with no folder source, when `harnessed build default claude --project /work/a` runs, then the profile is written to `profiles/default-<suffix>/claude`, where `<suffix>` is the scope suffix without its leading `-`, and every file under `profiles/default/claude` is byte-identical to before.
- S9.2 (boundary) Given projects `/work/a` and `/work/b` each have a trusted project source that holds a stack `default`, when each is built with its own `--project`, then the two profile directories differ, and `paths.host_home`, the derived image name, the tool tree path, and both volume names each differ between the two projects.
- S9.3 (boundary) Given project `/work/a` has a trusted project source that holds only `recipes/extra/recipe.yaml`, when stack `default` loads there and its closure holds no directory inside that source, then its storage name is `default`, with no suffix.
- S9.4 (boundary) Given the project source of `/work/a` holds `recipes/time/recipe.yaml`, and the shipped stack `default` loads recipe `time`, when `default` is built with `--project /work/a`, then its storage name is `default-<suffix>`.
- S9.5 (negative) Given the state of S9.1, when `container-run` resolves stack `default` in project `/work/b`, which has no folder source, then it reads `profiles/default/claude` and never `profiles/default-<suffix>/claude`.
- S9.6 Given the state of S9.1, when a global launcher is written for stack `default`, then its file name and its `--stack` argument hold `default` with no suffix.

### AC-10: a warning names both paths when a new source hides an entry
- S10.1 Given recipe `time` exists in a flag source `/work/cat` and in the shipped catalog, when a stack that loads `time` is built, then stderr holds exactly one warning with the text `recipe 'time'`, the path `/work/cat/recipes/time`, and the shipped path of `time`, and the build goes on.
- S10.2 Given stack `team` exists in a git source and in the shipped catalog, when `team` loads, then one warning names `stack 'team'` and both paths. The same rule covers a service and an agent.
- S10.3 (boundary) Given recipe `hello` exists only in a flag source, when a stack that loads `hello` is built, then stderr holds no shadow warning.
- S10.4 (boundary) Given recipe `time` exists in the user overlay and the shipped catalog and in no new source, when a stack that loads `time` is built, then stderr holds today's overlay warning, byte-identical, and no second warning.
- S10.5 (negative) Given the state of S10.1, when the build ends, then its exit status is the same as with the shipped copy removed.

### AC-11: `harnessed catalog list` shows every source
- S11.1 Given one flag source, one trusted project source, the user overlay, one git source `harnessed-catalog` with `ref: main` and `sha: C1`, the shipped catalog, and the generated root, when `harnessed --catalog /work/cat catalog list --project /work/proj` runs, then it prints six rows in source order. Each row holds a kind (`flag`, `project`, `overlay`, `git`, `shipped`, `generated`) and a path. The `git` row also holds `harnessed-catalog`, `main`, and `C1`. The `project` row also holds `trusted`.
- S11.2 Given the untrusted project catalog of S2.5, when `harnessed catalog list --project /work/proj` runs, then its row holds `untrusted`, and the row sits at the project source's place.
- S11.3 (boundary) Given no flag source, no project catalog, an empty registry, and an existing user overlay, when `harnessed catalog list` runs, then it prints the `overlay` row, the `shipped` row, and the `generated` row only when the generated root exists.
- S11.4 (negative) Given any state, when `harnessed catalog list` runs, then no `git` subprocess starts, and the registry, the trust record, and every clone are byte-identical to before.

### AC-12: `harnessed catalog remove` drops a git catalog
- S12.1 Given catalogs `first`, `harnessed-catalog`, and `third` are registered in that order, when `harnessed catalog remove harnessed-catalog` runs, then the registry holds `first` then `third`, `$XDG_DATA_HOME/harnessed/catalogs/harnessed-catalog` does not exist, and the clones of `first` and `third` are unchanged.
- S12.2 (boundary) Given a registered catalog whose clone directory is already gone, when `harnessed catalog remove` names it, then the registry item is removed and the command exits 0.
- S12.3 (negative) Given no catalog named `ghost` is registered, when `harnessed catalog remove ghost` runs, then it prints an error, exits non-zero, and the registry and the clone directory are unchanged.

### AC-13: `harnessed catalog untrust` withdraws trust
- S13.1 Given `/work/proj/.harnessed/catalog` and `/work/other/.harnessed/catalog` are trusted, when `harnessed catalog untrust /work/proj` runs, then the trust record holds only `/work/other/.harnessed/catalog`, and `harnessed list --project /work/proj` prints the S2.5 warning.
- S13.2 (boundary) Given the state after S13.1, when `harnessed list --project /work/other` runs, then the catalog at `/work/other` is read and no warning prints.
- S13.3 (negative) Given `/work/proj/.harnessed/catalog` exists and is not trusted, when `harnessed catalog untrust /work/proj` runs, then it prints an error, exits non-zero, and the trust record is byte-identical to before.

## Deferred from Gate 1
- AC-8, the existing note: `credmounts._trusted_ssh_keys` prints `ignoring ssh_keys from shared-catalog stack '<stack>'`. "AC-8: private ssh keys come only from the user overlay" keeps that text and pins it in S8.1.
- AC-9, which profile a launch uses and where it is stored: a profile is at `$XDG_DATA_HOME/harnessed/profiles/<stack>/<harness>`, keyed on the stack name alone. "Terms" defines the storage name, and "AC-9: stored state is separate for a scoped stack" states where each profile goes.

## Must NOT
- With no flag source, no project catalog, and no registry file, `paths.catalog_roots()` returns exactly today's list: the user overlay when it exists, the shipped catalog, the generated root when it exists.
- The storage name of a stack that is not scoped never changes. No existing profile, image, volume, or host home is renamed or rebuilt by this change.
- The generated root stays last. `tests/test_paths_generated_root.py` passes unchanged.
- The text of today's overlay shadow warning does not change. `tests/test_overlay_shadow_warning.py` passes unchanged.
- No test that exists today is edited to make it pass.
- No file under an untrusted project catalog is read, listed, or run. Only its existence is checked.
- `ssh_keys` from a flag source, a project source, or a git source never mount.
- harnessed stores no git credential and passes none. It runs `git` with the user's own configuration.
- `build`, `container-run`, `host-run`, `use`, `list`, and `test` start no `git` subprocess for catalog resolution.
- `harnessed update` and the `catalogseed` writers never write into a git source's clone.
- Nothing is written under the repository's `catalog/`. `harnessed_home()` is never derived from the current directory.
- No new dependency is added.

## Touches
- `src/harnessed/catalogsources.py` (new): the per-process source state (flag sources, project directory); project discovery; the trust record; the registry; the git clone, fetch, and checkout calls; the scope suffix.
- `src/harnessed/paths.py`: `catalog_roots()` returns the source order; a helper names the source kind of a root; a helper returns the lower paths an entry hides; `user_catalog`, `generated_catalog_root`, and `find_in_catalog` keep their signatures.
- `src/harnessed/launcher.py`: `main()` takes `--catalog` out of the arguments at any position and validates each directory; the `catalog` command group with its six subcommands; `--project` on `build`, `list`, and `test`; the missing-clone check of S5.3; the storage name where `container_run`, `_launch_host`, `use`, and `_build_stack` compute stored-state paths; `stack_from_overlay` reads the source kind.
- `src/harnessed/credmounts.py`: `_stack_from_overlay` reads the source kind, not the resolved path.
- `src/harnessed/schema.py`: `_resolve_parent_stack_dir` checks folder sources first; `_resolve_dir` prints the AC-10 warning, once per kind and name in a process.
- `src/harnessed/catalogseed.py`: the two loops that list recipe and agent dirs for `harnessed update` pin rewrites skip git sources. `update.affected_stacks` only reads, so it is unchanged.
- `src/harnessed/layout.py`, `src/harnessed/setupenv.py`, `src/harnessed/volumes.py`, `src/harnessed/plugin.py`, `src/harnessed/assemble.py`: the image name, the tool tree, the two volume names, the plugin dir and its name, and the assembled profile dir take the storage name.
- `tests/catalog_env.py` (new): the shared fixture tree and the local bare-repository helpers.
- `tests/test_catalog_sources.py` (new): AC-1, AC-2, AC-7, AC-10.
- `tests/test_catalog_trust.py` (new): AC-3, AC-13.
- `tests/test_catalog_git.py` (new): AC-4, AC-5, AC-6, AC-11, AC-12.
- `tests/test_catalog_scope.py` (new): AC-8, AC-9.

## Documentation
- `ARCHITECTURE.md`: the **catalog** entry lists the six source kinds in source order, and the trust rule.
- `AGENTS.md`: the constraint line "Author under `catalog/` or `~/.config/harnessed/catalog`" names the three new sources.
- `catalog/recipes/default/skills/harnessed-catalog/SKILL.md`, which `.agents/skills/harnessed-catalog` links to: one paragraph on where a private catalog can live.
- The wiki guide for private catalogs is a separate delivery, outside this PR, under the AGENTS.md wiki exemption.

## Known limits
- Trust belongs to a path. A later change to a trusted folder's content, for example from `git pull`, is not checked again.
- A global launcher does not record `--catalog`. A stack from a flag source launches only when the command line names the flag again.
- harnessed does not detect a hand edit inside a clone. `harnessed catalog update` restores the checkout of the recorded ref.
- A git catalog must hold its catalog root at the repository's top directory. A subdirectory is not supported.
- A user overlay named again with `--catalog` counts as a flag source, so its `ssh_keys` are dropped.
- Stored state of a scoped stack is not removed when its project is deleted. The existing `host-gc` and `volume-gc` commands are not changed here.
- The two `extends:` security rules of issue 316 stay unimplemented.
- `scan`, `rescan`, `stop`, `rm`, `context`, `install`, `host-gc`, and `volume-gc` set no project directory, so they do not see a project catalog. For a stack scoped by a project catalog they read the plain stack name. A `--catalog` folder reaches them, but `stop` and `rm` match instances on the plain stack name and so miss a scoped instance, and `aoe.forget_stack` receives the plain name.
- `catalog remove` drops the registry entry before it deletes the clone, and ignores a delete failure. A clone that cannot be deleted then blocks `catalog add` of the same name until it is removed by hand.
- A service that a recipe declares, rather than the stack, is not in the closure. Two projects whose private recipes pull different same-named services share one stored state.
- An agent from a folder source does not scope a stack. The agent image is keyed on the harness alone, so two projects that each override `agents/claude` share one agent image.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | behavior regressions and every scenario S1.1 to S13.3 | `tools/run-tests.sh` passes; the count is the baseline plus the new tests |
| coverage | untested branches | `--cov-fail-under=80` passes; `catalogsources.py` branch coverage is 90% or more |
| types | type errors | pyright reports no new error in the touched files |
| lint | style and bug patterns | `ruff check src tests tools` exits 0 |
| shellcheck | shell defects | exits 0 |
| secrets | committed credentials | `gitleaks detect` finds nothing |
| mutation | tests that pass without checking | manual mutants on the source order, the trust check, the ssh_keys source gate, and the scope suffix are each killed; mutmut runs once on `catalogsources.py` |
| live CI | the container path, since `launcher.py` and `paths.py` are live triggers | `live` and `live-docker` green on the PR |
| adversary | defects a self-review misses | every finding fixed or answered |
| manual | the story's example | `harnessed catalog add <a local bare repository> --ref main`, then `harnessed list`, shows that repository's stacks |
