---
id: HF-20261122-private-catalogs-add-two
type: feature
source:
  tracker: local
  external_id: HF-20261122-private-catalogs-add-two
  url: none
  version: "unavailable: local story, no adapter pulled it"
---
# Private catalogs: folder and git sources
## Description
Who: a harnessed user who keeps recipes and stacks outside the shipped catalog and the user overlay.

What: harnessed reads catalog entries from three new sources: a folder named by `--catalog`, a project `.harnessed/catalog`, and a registered git repository. A new `harnessed catalog` command group registers, updates, lists, removes, trusts, and untrusts them.

Done looks like: the criteria AC-1 to AC-13 below.

Example: a user runs `harnessed catalog add git@github.com:drmikecrowe/harnessed-catalog.git --ref main`, then `harnessed list` shows the stacks of that repository beside `default` and `openwiki`.

Drafted by the assistant from the author's text; approved by the author 2026-11-22.
## Acceptance criteria
- AC-1: A command given `--catalog <dir>` resolves agents, recipes, services, and stacks from `<dir>` first; boundary: with two `--catalog` flags, the first one wins a name clash; negative: a `<dir>` that does not exist stops the command with an error and a non-zero exit, and nothing is built.
- AC-2: A launch or build resolves names from a trusted `.harnessed/catalog` found in its project directory or in the nearest parent directory, up to the git top level; boundary: when both the project directory and a parent hold one, the nearest wins and the other is not read, and no directory above the git top level is searched; negative: an untrusted `.harnessed/catalog` is ignored, and one warning names its path and `harnessed catalog trust`.
- AC-3: `harnessed catalog trust <project dir>` records that project's `.harnessed/catalog` path as trusted; boundary: trust belongs to the path, so the same folder moved to another path is untrusted; negative: a project directory with no `.harnessed/catalog` gives an error and records nothing.
- AC-4: `harnessed catalog add git@github.com:drmikecrowe/harnessed-catalog.git --ref main` clones the repository under `$XDG_DATA_HOME/harnessed/catalogs/harnessed-catalog`, writes it to `~/.config/harnessed/catalogs.yaml`, and locks the resolved commit SHA; boundary: with no `--ref`, it locks the head SHA of the remote default branch; negative: when the clone fails, the command exits non-zero, writes no registry entry, and leaves no clone directory.
- AC-5: A build resolves a git catalog from its locked clone and makes no network call; boundary: after new commits reach the remote, a build still reads the locked SHA; negative: when a registered clone is missing, the build stops with an error that names `harnessed catalog update`.
- AC-6: `harnessed catalog update [<name>]` fetches, moves the lock to the current SHA of the recorded ref, and prints the old and new SHA; boundary: a catalog locked to a full SHA reports no change; negative: when the fetch fails, the lock and the clone stay unchanged and the exit is non-zero.
- AC-7: On a name clash the first source in this order wins: `--catalog`, project `.harnessed/catalog`, user overlay, git catalogs in registration order, shipped catalog, generated stacks. Example: recipe `time` in a `--catalog` folder is used over `catalog/recipes/time`; boundary: of two git catalogs that both hold `time`, the one registered first wins; negative: a generated stack never wins over any other source.
- AC-8: A stack from any new source that declares `ssh_keys` has them dropped with the existing "ignoring ssh_keys" note; boundary: the same stack copied into `~/.config/harnessed/catalog` keeps its `ssh_keys`; negative: no flag or trust record makes a new source's `ssh_keys` mount.
- AC-9: Building a stack named `default` from one project's `.harnessed/catalog` leaves unchanged the profile that a launch of `default` uses in any other project; boundary: two projects that each define a stack `default` each launch their own; negative: a launch never reads a profile built from another project's catalog.
- AC-10: When an entry in a new source hides a same-named entry in a lower source, harnessed prints one warning that names both paths; boundary: a name present in only one source prints no warning; negative: the warning never stops the build.
- AC-11: `harnessed catalog list` prints every catalog source in the AC-7 order, each with its path, plus the ref and locked SHA of a git catalog and the trust state of a project catalog; boundary: with no new source registered or found, it prints the user overlay, the shipped catalog, and the generated root when it exists; negative: it makes no network call and changes no file.
- AC-12: `harnessed catalog remove harnessed-catalog` deletes that registry entry and its clone directory; boundary: other registered catalogs keep their entries, clones, and order; negative: a name that is not registered gives an error, a non-zero exit, and no change.
- AC-13: `harnessed catalog untrust <project dir>` removes that project's `.harnessed/catalog` path from the trust record, and the next launch there ignores it with the AC-2 warning; boundary: other trusted paths stay trusted; negative: a path that is not trusted gives an error, a non-zero exit, and no change.
## Constraints
- A git catalog's repository root is the catalog root: it holds `recipes/`, `stacks/`, `services/`, `agents/`.
- Project discovery anchors on the launch's project path, never on the current directory.
- Git authentication is the user's own git and ssh setup. harnessed stores no credential.
- One PR delivers both sources.
