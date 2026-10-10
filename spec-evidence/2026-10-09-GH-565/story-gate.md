# Gate 1, story readiness

verdict: ready
story: GH-565
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 108284/2256
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-3-1-gh-565-global-launchers/fabf8915-4098-425f-8ab6-4ec1225b3aa7/scratchpad/GH-565-record-v2.json
graded: 2026-10-10T13:43:57.543Z

## Reasons

none

## Record

```json
{"input":"Story","type":"feature","missing":[],"gaps":["prompt 2: AC-1 says 'a launcher whose content already matches is not rewritten' but does not say what counts as a match (byte-for-byte, or ignoring a comment). An engineer has to guess the comparison rule.","prompt 3: every AC could be met by an implementation that leaves old launchers behind when a stack is renamed. No AC covers rename-then-install.","prompt 3: AC-1 and AC-5 are met by a `-container` ACP launcher that never starts `container-acp`. No AC says which verb an ACP launcher runs, though the Design section does."],"fields":[{"name":"who","state":"present"},{"name":"what","state":"present"},{"name":"done-looks-like","state":"present"},{"name":"example","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"author-note","why":"The author flagged 'Does aoe start a row's command in the row's stored path?'. Settling it needs aoe's current behaviour, so engineering checks it at the plan review."}],"items":[{"ac":"AC-1","status":"proven","evidence":"Run `harnessed install default claude`. Check that `~/.local/bin` holds `harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-acp-claude-default-container`. Repeat with the dotted stack `default.codebase-memory-mcp.gh-issue-tracker` and check the `-container` name carries the full dotted stack. Run `harnessed install default codex` and check that `harnessed-acp-codex-default-container` is absent. After any command, check that no `harnessed-acp-*-host` file exists. Re-run install over a matching launcher and compare its inode and mtime; they must not change. It is falsified if a named file is missing, a forbidden file appears, or a matching launcher is rewritten."},{"ac":"AC-2","status":"proven","evidence":"From folder D, run `harnessed-claude-default-container --flag1 -- --flag2`. Inspect the agent invocation: the project path must be D and the arguments must be `--flag1 -- --flag2`. For a non-aoe launch from D, list D before and after; it must gain no file. It is falsified if the project path is not D, an argument is dropped or altered, or D gains a file."},{"ac":"AC-3","status":"proven","evidence":"Make an aoe-registered launch with `--no-strict-mcp-config` from folder D. Open `<harness>-<stack>-<backend>` in D and check that it cds to its own folder and ends with `exec harnessed-<harness>-<stack>-<backend> --no-strict-mcp-config \"$@\"`. Open the global launcher and check the flag is not in it. Check that no local ACP launcher exists in D. It is falsified if the exec line is wrong, the flag is missing locally or present globally, or a local ACP launcher exists."},{"ac":"AC-4","status":"proven","evidence":"Set up three aoe rows: one whose local launcher runs `harnessed-claude-default-container`, one whose older launcher says `--stack default`, and one for `claude-default.x-container --`. Add a row for a different stack too. Run `harnessed rm default`. The first two rows must be gone, and the `default.x` row and the other-stack row must remain. Every global launcher must still exist. It is falsified if the `default.x` or other-stack row is dropped, a matching row survives, or a global launcher is deleted."},{"ac":"AC-5","status":"proven","evidence":"Install `default` and `default.x` for claude, and `default` for codex. Create an aoe row that references a `default` launcher. Run `harnessed uninstall default claude`. Check that `harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-acp-claude-default-container` are deleted. Check that `harnessed-claude-default.x-container`, `harnessed-acp-claude-default.x-container` and `harnessed-codex-default-host` remain. Check that the output prints the path of the referencing aoe row. It is falsified if a launcher that should stay is deleted, one that should go survives, or the referencing row's path is not printed."},{"ac":"AC-6","status":"proven","evidence":"Run `harnessed install default claude` and check that `~/.local/bin/default` does not exist. Create `~/.local/bin/default` with an exec line `container-run --stack default`, run `harnessed uninstall default claude`, and check the file is gone. Run uninstall again and check that the output reports nothing to remove for the shim. Create `~/.local/bin/default` with any other exec line, run uninstall, and check the file is untouched. It is falsified if install creates the shim, a matching shim survives, the second uninstall reports a removal, or a non-matching file is deleted."}]}
```

## Story

````
---
id: GH-565
type: feature
source:
  tracker: github
  external_id: GH-565
  url: https://github.com/drmikecrowe/harnessed/issues/565
  version: "unavailable: state.mjs show returns no updated stamp"
---
# Global launchers: harnessed-<harness>-<stack>-<backend>, local launcher only for aoe
## Description
Who: anyone who starts a harnessed stack from aoe, from an editor, or from a terminal.
What: harnessed writes one global launcher per backend into `~/.local/bin` for each (stack, harness) it installs, builds or launches, and `harnessed uninstall <stack> <harness>` removes them. A launch outside aoe writes nothing into the project. Only an aoe launch keeps an in-repo launcher, and that launcher calls the global one. The old `~/.local/bin/<stack>` shim goes away.
Done looks like: AC-1 to AC-6 below all hold.
Example: `harnessed install default claude` writes `~/.local/bin/harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-acp-claude-default-container`. In `~/proj`, `harnessed-claude-default-container --fresh` starts the container backend for stack `default` with `~/proj` as the project, and `~/proj` gains no file.

### Goal

Replace per-project launcher scripts with global ones, so editors and aoe point at one stable command per stack, and non-aoe launches leave nothing in the repo.

### Design

- **Global launchers** in `~/.local/bin`, one per (harness, stack, backend): `harnessed-claude-<stack>-host`, `harnessed-omp-<stack>-container`, and for ACP `harnessed-acp-claude-<stack>-container`, etc. Each takes the project from `$PWD` and forwards `"$@"`. The global name is the local launcher's name with a `harnessed-` prefix, so the two stay consistent.
- **Written by `harnessed install <stack> <harness>`, `harnessed build <stack> <harness>`, `host-run` and every `container-run`**, one per backend. A launcher that already matches is not rewritten. **Removed by `harnessed uninstall <stack> <harness>`.** These replace the old `~/.local/bin/<stack>` shim. `harnessed rm` removes instances only and leaves launchers alone.
- **aoe launches keep the in-repo launcher**, rewritten to `cd` to its own folder and then `exec harnessed-<harness>-<stack>-<backend> <per-launch flags> "$@"`. Per-launch flags (`--no-strict-mcp-config`, and anything else typed) stay in the local file.
- **Non-aoe launches write nothing to the project.** `_persist_this_launch` writes the local script only when an aoe row is being registered.
- **ACP is global-only, and its launchers carry a backend.** aoe never runs an ACP verb, so there is no local ACP launcher. An ACP launcher is `harnessed-acp-<harness>-<stack>-<backend>`: `-container` runs `container-acp`, and `-host` is reserved for `host-acp`, which is separate work that this story does not write. A harness outside `attachcmd._ACP_HARNESSES` (today `omp` and `claude`) gets no ACP launcher.

Drafted by the assistant from the author's text; approved by the author 2026-10-10.
## Acceptance criteria
- AC-1: `harnessed install <stack> <harness>`, `harnessed build <stack> <harness>`, `harnessed host-run` or `harnessed container-run` for a (stack, harness) leaves `~/.local/bin` holding `harnessed-<harness>-<stack>-host` and `harnessed-<harness>-<stack>-container`, plus `harnessed-acp-<harness>-<stack>-container` when the harness is in `attachcmd._ACP_HARNESSES` (today `omp` and `claude`); boundary: the dotted stack `default.codebase-memory-mcp.gh-issue-tracker` with harness `claude` gives `harnessed-claude-default.codebase-memory-mcp.gh-issue-tracker-container`, and a launcher whose content already matches is not rewritten; negative: `harnessed install default codex` writes no `harnessed-acp-codex-default-container`, because `codex` is not in `attachcmd._ACP_HARNESSES`, and no command writes a `harnessed-acp-<harness>-<stack>-host` launcher yet.
- AC-2: running a global launcher from folder D with arguments A starts that backend, harness and stack with D as the project and passes A on unchanged; boundary: `--` and every argument after it reach the agent, as `"$@"` does today; negative: a launch that registers no aoe row writes no file into D.
- AC-3: a launch that registers an aoe row leaves the project folder holding `<harness>-<stack>-<backend>`, which cds to its own folder and runs `exec harnessed-<harness>-<stack>-<backend> <per-launch flags> "$@"`; boundary: `--no-strict-mcp-config` typed at launch is in the local file and not in the global one; negative: no local launcher is written for ACP.
- AC-4: `harnessed rm <stack>` drops every aoe row whose local launcher runs that stack's global launcher, and every row whose older launcher still says `--stack <stack>`; boundary: the row `claude-default.x-container --` belongs to stack `default.x`, not to `default`; negative: rows of other stacks stay, and `rm` deletes no global launcher.
- AC-5: `harnessed uninstall <stack> <harness>` deletes every `harnessed-<harness>-<stack>-<backend>` and `harnessed-acp-<harness>-<stack>-<backend>` launcher in `~/.local/bin` and prints the path of each aoe row that still references one; boundary: `uninstall default claude` does not delete `harnessed-claude-default.x-container` or `harnessed-acp-claude-default.x-container`; negative: `harnessed-codex-default-host` stays.
- AC-6: `harnessed install <stack> <harness>` writes no `~/.local/bin/<stack>` shim, and `harnessed uninstall <stack> <harness>` removes an existing `~/.local/bin/<stack>` whose exec line runs `container-run --stack <stack>`; boundary: the shim is removed once, and a second `uninstall` reports nothing to remove for it; negative: a `~/.local/bin/<stack>` file whose exec line is anything else is left alone.
## Constraints
- **`aoe._replays_stack` attribution.** `harnessed rm` finds `--stack <name>` in the script's exec line today. The rewritten script names a global launcher instead, so attribution must parse the stack from the global name. Old scripts that still say `--stack` must stay readable, or existing rows become unremovable (the `_is_launcher_script` docstring records that bug from the last rename).
- **`_is_ours` / `_is_launcher_script`.** The row shape `<path>/<harness>-<stack>-<verb> --` does not change, so recognition should hold. Confirm with `trace_path` before editing, per CLAUDE.md.
- **Missing global launcher.** If one is deleted, every aoe row pointing at it fails. `uninstall` must report aoe rows that still reference it.
- **Name parsing.** Stack names contain dots (`default.codebase-memory-mcp.gh-issue-tracker`). The global name is the local name with a `harnessed-` prefix, so strip the prefix and reuse `launchscript.parse_script_name`; do not add a second grammar. An ACP launcher puts `acp-` after the `harnessed-` prefix and keeps the backend `host` or `container`, so the same grammar reads it after both prefixes; `acp` is never a backend.
- **Trade-off.** Terminal-only users lose the in-folder record of what they launched there.
## Author notes
- SR-DEFER: "Does aoe start a row's command in the row's stored path?". engineering checks at the plan review
````
