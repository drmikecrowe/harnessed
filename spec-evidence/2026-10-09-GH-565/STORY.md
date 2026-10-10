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
