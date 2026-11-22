# Agent decisions: Private catalogs: folder and git sources

### A1. The trust record is a JSON file under `$XDG_STATE_HOME/harnessed/`
- Other option: a YAML file beside the registry under `~/.config/harnessed/`.
- Why: trust is machine state about paths on this host, not configuration a user copies between hosts, and the standard library writes JSON.
- Command: hotfix

### A2. The lock is the `sha` field of each registry item, not a separate lock file
- Other option: a `catalogs.lock` file beside `catalogs.yaml`.
- Why: one file keeps the name, the ref, and the locked commit together, so the two can never disagree about which catalogs exist.
- Command: hotfix

### A3. `harnessed catalog add` takes `--name` to choose the catalog's name
- Other option: refuse a second repository whose URL gives a name already registered, with no way to add it.
- Why: Gate 1 noted that the story does not say what happens when two repositories give the same name, and the name decides the clone path of AC-4.
- Command: hotfix

### A4. `--catalog` is accepted before or after the command name
- Other option: a global option that is valid only before the command name.
- Why: a global launcher appends the user's arguments after the command name, so a flag that is valid only before it could never reach a launch through a launcher.
- Command: hotfix

### A5. The shadow warning of AC-10 covers recipes, stacks, services, and agents
- Other option: recipes only, as today's overlay warning does.
- Why: AC-10 says "an entry", and a hidden stack or service changes a build as much as a hidden recipe does.
- Command: hotfix

### A6. With no git top level, only the project directory is checked for `.harnessed/catalog`
- Other option: walk every parent up to the filesystem root.
- Why: the author ruled that the walk stops at the git top level, and with none there is no bound, so a catalog in a home directory or `/tmp` would be picked up by accident.
- Command: hotfix

### A7. `harnessed catalog update` with no name updates every registered catalog and goes on after a failure
- Other option: stop at the first catalog that fails.
- Why: Gate 1 noted that the story gives no outcome for the omitted name, and one unreachable remote must not block the others from updating.
- Command: hotfix

### A8. `harnessed catalog update` clones again when the clone directory is missing
- Other option: fail and tell the user to remove and add the catalog.
- Why: the AC-5 error names `harnessed catalog update` as the repair, so that command must repair a missing clone.
- Command: hotfix

### A9. An `extends:` parent is looked up in folder sources first, then in today's order
- Other option: look up every parent in the full source order, which replaces today's rule of overlay, then sibling, then the other roots.
- Why: adding the folder sources in front changes nothing for a stack that exists today, and the full source order would change which parent a generated stack finds.
- Command: hotfix
