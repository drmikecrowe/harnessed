# Gate 1, story readiness

verdict: ready
story: HF-20261122-private-catalogs-add-two
process: spec-evidence 1.7.2-local-2026-11-19
model: claude-opus-5-5
tokens: 118901/5186
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/work/story-record.json
warning: 13 criteria; a story with 10 or more criteria is hard to build and review
graded: 2026-11-22T16:44:13.182Z

## Reasons

none

## Record

```json
{"input":"Story","type":"feature","missing":[],"gaps":["prompt 1: the Story does not say what `harnessed catalog update` with no name does. AC-6 shows `[<name>]` but gives no outcome for the omitted name.","prompt 2: a reader has to guess how the clone name `harnessed-catalog` is derived from the repository URL, and what happens when two repositories yield the same name.","prompt 2: `generated stacks` and `generated root` (AC-7, AC-11) are used without a definition in the Story. They look like existing harnessed terms, so plan review can confirm them.","prompt 3: AC-9 constrains only the `default` profile across projects. An implementation could still let one project's catalog change the profile of a differently named stack in another project and satisfy every criterion.","prompt 3: AC-2 says an untrusted catalog is ignored with a warning, but no criterion says how often the warning prints across repeated launches."],"fields":[{"name":"who","state":"present"},{"name":"what","state":"present"},{"name":"done-looks-like","state":"present"},{"name":"example","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"AC-8","why":"the existing 'ignoring ssh_keys' note can only be matched against the current code. The criterion is graded proven on the behaviour the Story states."},{"ac":"AC-9","why":"which profile a launch uses and where it is stored depends on the current build and launch code. The criterion is graded proven on the behaviour the Story states."}],"items":[{"ac":"AC-1","status":"proven","evidence":"Put recipe `time` in two `--catalog` dirs and run `harnessed list` or a build. The first dir's copy must win; if the second wins, it is false. Pass a nonexistent dir and check for a non-zero exit, an error and no build output."},{"ac":"AC-2","status":"proven","evidence":"Create a trusted `.harnessed/catalog` in a parent and another in the project dir. Launch from the project and check that only the nearest is read. Place one above the git top level and check it is not read. Make one untrusted and check for exactly one warning that names its path and `harnessed catalog trust`."},{"ac":"AC-3","status":"proven","evidence":"Run `harnessed catalog trust <dir>` and check that the trust record holds that path. Move the folder and check it is untrusted. Run it on a dir with no `.harnessed/catalog` and check for an error and an unchanged record."},{"ac":"AC-4","status":"proven","evidence":"Run `harnessed catalog add <url> --ref main` and check for the clone at `$XDG_DATA_HOME/harnessed/catalogs/harnessed-catalog`, an entry in `~/.config/harnessed/catalogs.yaml` and a locked SHA equal to the ref's commit. Omit `--ref` and compare the lock with the remote default branch head. Add an unreachable URL and check for a non-zero exit, no registry entry and no clone dir."},{"ac":"AC-5","status":"proven","evidence":"Run a build with the network disabled and check that it succeeds. Push a commit to the remote and check that the build still reads the locked SHA. Delete the clone and check that the build errors with text naming `harnessed catalog update`."},{"ac":"AC-6","status":"proven","evidence":"Push a commit, run `harnessed catalog update <name>` and check that the old and new SHA print and the lock equals the ref's new head. Update a catalog locked to a full SHA and check for no change. Block the network and check that the lock and clone are unchanged and the exit is non-zero."},{"ac":"AC-7","status":"proven","evidence":"Put recipe `time` in `--catalog`, the project catalog, the overlay, two git catalogs, the shipped catalog and a generated stack. Remove the winner one source at a time and check that the next in the stated order wins. If the order differs, it is false."},{"ac":"AC-8","status":"proven","evidence":"Put a stack that declares `ssh_keys` in a `--catalog` folder, build it and check that the note prints and no ssh key mounts. Copy the same stack into `~/.config/harnessed/catalog` and check that the keys are kept."},{"ac":"AC-9","status":"proven","evidence":"Build `default` from project A's `.harnessed/catalog`. Compare the profile used by a `default` launch in project B before and after, and check that it is unchanged. Define `default` in both projects and check that each launches its own."},{"ac":"AC-10","status":"proven","evidence":"Define a same-named recipe in a `--catalog` dir and in the shipped catalog. Build and check for exactly one warning naming both paths and a successful build. With a name in only one source, check for no warning."},{"ac":"AC-11","status":"proven","evidence":"Run `harnessed catalog list` with each source type present. Check that the output order matches AC-7 and that each row shows the path, ref, locked SHA or trust state. Run it with no new sources and check for overlay, shipped and generated root only. Run it offline and diff the file tree before and after to check nothing changed."},{"ac":"AC-12","status":"proven","evidence":"Register two catalogs and run `harnessed catalog remove harnessed-catalog`. Check that its entry and clone dir are gone and the other's entry, clone and order are intact. Remove an unregistered name and check for an error, a non-zero exit and no change."},{"ac":"AC-13","status":"proven","evidence":"Trust two dirs, run `harnessed catalog untrust <dir>` on one and check that the other stays trusted. Launch in the untrusted one and check for the AC-2 warning. Untrust a path that is not trusted and check for an error, a non-zero exit and an unchanged record."}]}
```

## Story

````
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
````
