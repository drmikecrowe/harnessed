# Comments on GH-565

Oldest first, pulled from the tracker.

## 1. drmikecrowe, 2026-10-09T22:46:31Z

# Gate 1, story readiness

verdict: ready
story: GH-565
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 47648/236
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-3-1-gh-565-global-launchers/fabf8915-4098-425f-8ab6-4ec1225b3aa7/scratchpad/GH-565-record.json
graded: 2026-10-09T22:46:25.995Z

## Reasons

none

## Record

```json
{
  "input": "Story",
  "type": "feature",
  "missing": [],
  "gaps": [
    "prompt 2: AC-1 says 'a launcher whose content already matches is not rewritten' but does not say what constitutes a match (byte-for-byte? ignoring a timestamp comment?); an engineer must guess the comparison rule",
    "prompt 3: all six ACs could be satisfied by an implementation that never cleans up launchers when a stack is renamed — no AC covers the rename-then-install scenario"
  ],
  "fields": [
    {"name": "who", "state": "present"},
    {"name": "what", "state": "present"},
    {"name": "done-looks-like", "state": "present"},
    {"name": "example", "state": "present"}
  ],
  "readings": [],
  "findings": [],
  "deferred": [
    {"ac": "author-note", "why": "Author explicitly flagged: 'Does aoe start a row's command in the row's stored path?' — requires checking current aoe behaviour; engineering checks at the plan review"}
  ],
  "items": [
    {
      "ac": "AC-1",
      "status": "proven",
      "evidence": "Run `harnessed install default claude`; check `~/.local/bin/harnessed-claude-default-host`, `harnessed-claude-default-container`, and `harnessed-claude-default-acp` exist. Run `harnessed install default codex`; check `harnessed-codex-default-acp` is absent. Pre-create a matching launcher, run install again, check the file was not rewritten (mtime or inode unchanged). Falsified if any named file is absent, the ACP file appears for codex, or the file is rewritten when content matched."
    },
    {
      "ac": "AC-2",
      "status": "proven",
      "evidence": "From folder D, run `harnessed-claude-default-container --flag1 -- --flag2`; inspect the agent invocation's project path (must be D) and argument list (must include `--flag1 -- --flag2`). Then run a non-aoe launch from D and confirm no new file appears in D. Falsified if project path differs from D, any argument is dropped, or a file is written to D."
    },
    {
      "ac": "AC-3",
      "status": "proven",
      "evidence": "Perform an aoe-registered launch with `--no-strict-mcp-config` from project folder D; open the local launcher `<harness>-<stack>-<backend>` in D; confirm its body contains `cd` to its own folder and `exec harnessed-<harness>-<stack>-<backend>` with `--no-strict-mcp-config` present and no ACP local launcher exists. Falsified if exec line is wrong, the flag is absent, or an ACP local launcher was written."
    },
    {
      "ac": "AC-4",
      "status": "proven",
      "evidence": "Set up aoe rows: one whose local launcher calls `harnessed-claude-default-container`, one whose old launcher has `--stack default`, and one for `claude-default.x-container`. Run `harnessed rm default`; confirm the first two rows are gone, the `default.x` row remains, and `~/.local/bin/harnessed-claude-default-host` still exists. Falsified if the `default.x` row is removed, other-stack rows are removed, or any global launcher is deleted."
    },
    {
      "ac": "AC-5",
      "status": "proven",
      "evidence": "Install stacks `default` (claude) and `default.x` (claude) so both have launchers. Run `harnessed uninstall default claude`; confirm `harnessed-claude-default-host` and `harnessed-claude-default-container` and `harnessed-claude-default-acp` are deleted, `harnessed-claude-default.x-container` is NOT deleted, `harnessed-codex-default-host` is NOT deleted, and the command printed the path of any aoe row still referencing the deleted launchers. Falsified if the `default.x` launcher is deleted, codex launcher is deleted, or referencing aoe rows are not reported."
    },
    {
      "ac": "AC-6",
      "status": "proven",
      "evidence": "Run `harnessed install default claude`; check `~/.local/bin/default` does not exist. Pre-create `~/.local/bin/default` with exec line `container-run --stack default`; run `harnessed uninstall default claude`; confirm the shim is gone; run uninstall again and confirm output says nothing to remove for it. Pre-create `~/.local/bin/default` with an exec line that does NOT say `container-run --stack default`; run uninstall; confirm the file is left alone. Falsified if install creates the shim, uninstall fails to remove the matching shim, second uninstall reports a removal, or non-matching shim is deleted."
    }
  ]
}
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
Example: `harnessed install default claude` writes `~/.local/bin/harnessed-claude-default-host`, `harnessed-claude-default-container` and `harnessed-claude-default-acp`. In `~/proj`, `harnessed-claude-default-container --fresh` starts the container backend for stack `default` with `~/proj` as the project, and `~/proj` gains no file.

### Goal

Replace per-project launcher scripts with global ones, so editors and aoe point at one stable command per stack, and non-aoe launches leave nothing in the repo.

### Design

- **Global launchers** in `~/.local/bin`, one per (harness, stack, backend): `harnessed-claude-<stack>-host`, `harnessed-omp-<stack>-container`, `harnessed-claude-<stack>-acp`, etc. Each takes the project from `$PWD` and forwards `"$@"`. The global name is the local launcher's name with a `harnessed-` prefix, so the two stay consistent.
- **Written by `harnessed install <stack> <harness>`, `harnessed build <stack> <harness>`, `host-run` and every `container-run`**, one per backend. A launcher that already matches is not rewritten. **Removed by `harnessed uninstall <stack> <harness>`.** These replace the old `~/.local/bin/<stack>` shim. `harnessed rm` removes instances only and leaves launchers alone.
- **aoe launches keep the in-repo launcher**, rewritten to `cd` to its own folder and then `exec harnessed-<harness>-<stack>-<backend> <per-launch flags> "$@"`. Per-launch flags (`--no-strict-mcp-config`, and anything else typed) stay in the local file.
- **Non-aoe launches write nothing to the project.** `_persist_this_launch` writes the local script only when an aoe row is being registered.
- **ACP is global-only.** aoe never runs `container-acp`, so there is no local ACP launcher. A harness outside `attachcmd._ACP_HARNESSES` (today `omp` and `claude`) gets no ACP launcher.

Drafted by the assistant from the author's text; approved by the author 2026-10-09.
## Acceptance criteria
- AC-1: `harnessed install <stack> <harness>`, `harnessed build <stack> <harness>`, `harnessed host-run` or `harnessed container-run` for a (stack, harness) leaves `~/.local/bin` holding `harnessed-<harness>-<stack>-host` and `harnessed-<harness>-<stack>-container`, plus `harnessed-<harness>-<stack>-acp` when the harness is in `attachcmd._ACP_HARNESSES` (today `omp` and `claude`); boundary: the dotted stack `default.codebase-memory-mcp.gh-issue-tracker` with harness `claude` gives `harnessed-claude-default.codebase-memory-mcp.gh-issue-tracker-container`, and a launcher whose content already matches is not rewritten; negative: `harnessed install default codex` writes no `harnessed-codex-default-acp`, because `codex` is not in `attachcmd._ACP_HARNESSES`.
- AC-2: running a global launcher from folder D with arguments A starts that backend, harness and stack with D as the project and passes A on unchanged; boundary: `--` and every argument after it reach the agent, as `"$@"` does today; negative: a launch that registers no aoe row writes no file into D.
- AC-3: a launch that registers an aoe row leaves the project folder holding `<harness>-<stack>-<backend>`, which cds to its own folder and runs `exec harnessed-<harness>-<stack>-<backend> <per-launch flags> "$@"`; boundary: `--no-strict-mcp-config` typed at launch is in the local file and not in the global one; negative: no local launcher is written for ACP.
- AC-4: `harnessed rm <stack>` drops every aoe row whose local launcher runs that stack's global launcher, and every row whose older launcher still says `--stack <stack>`; boundary: the row `claude-default.x-container --` belongs to stack `default.x`, not to `default`; negative: rows of other stacks stay, and `rm` deletes no global launcher.
- AC-5: `harnessed uninstall <stack> <harness>` deletes every `harnessed-<harness>-<stack>-<backend>` launcher in `~/.local/bin` and prints the path of each aoe row that still references one; boundary: `uninstall default claude` does not delete `harnessed-claude-default.x-container`; negative: `harnessed-codex-default-host` stays.
- AC-6: `harnessed install <stack> <harness>` writes no `~/.local/bin/<stack>` shim, and `harnessed uninstall <stack> <harness>` removes an existing `~/.local/bin/<stack>` whose exec line runs `container-run --stack <stack>`; boundary: the shim is removed once, and a second `uninstall` reports nothing to remove for it; negative: a `~/.local/bin/<stack>` file whose exec line is anything else is left alone.
## Constraints
- **`aoe._replays_stack` attribution.** `harnessed rm` finds `--stack <name>` in the script's exec line today. The rewritten script names a global launcher instead, so attribution must parse the stack from the global name. Old scripts that still say `--stack` must stay readable, or existing rows become unremovable (the `_is_launcher_script` docstring records that bug from the last rename).
- **`_is_ours` / `_is_launcher_script`.** The row shape `<path>/<harness>-<stack>-<verb> --` does not change, so recognition should hold. Confirm with `trace_path` before editing, per CLAUDE.md.
- **Missing global launcher.** If one is deleted, every aoe row pointing at it fails. `uninstall` must report aoe rows that still reference it.
- **Name parsing.** Stack names contain dots (`default.codebase-memory-mcp.gh-issue-tracker`). The global name is the local name with a `harnessed-` prefix, so strip the prefix and reuse `launchscript.parse_script_name`; do not add a second grammar. `acp` is a backend only in a global name, never in a local one.
- **Trade-off.** Terminal-only users lose the in-folder record of what they launched there.
## Author notes
- SR-DEFER: "Does aoe start a row's command in the row's stored path?". engineering checks at the plan review
````
