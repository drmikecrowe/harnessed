---
id: GH-569
type: feature
source:
  tracker: github
  external_id: 569
  url: https://github.com/drmikecrowe/harnessed/issues/569
  version: "unavailable: state.mjs show printed no updated stamp"
---
# Integrations: one pattern for aoe, Zed, Atlas and VS Code, run with --register-<name>-only

## Description
Who: a harnessed user who starts stacks from aoe, Zed, Atlas and VS Code.
What: each external tool is one integration, an executable script in `catalog/integrations/<name>/` or `~/.config/harnessed/catalog/integrations/<name>/`. A user adds or overrides one there, and nothing under `src/harnessed/` changes. Every global launcher takes `--register-<name>-only` for every integration. The flag builds the stack when its profile is stale or missing, runs that integration for the launcher's harness, stack and backend, then exits without starting the agent. Nothing registers automatically: aoe moves onto this pattern and registers only when `--register-aoe-only` is passed.
Done looks like: AC-1 to AC-7 below.
Example: on a stack that was never built, `harnessed-claude-gortex-ghissues-host --register-zed-only` builds `gortex-ghissues` for claude, then adds the entry "harnessed claude (gortex-ghissues)" to `~/.config/zed/settings.json`, with command `/home/mcrowe/.local/bin/harnessed-acp-claude-gortex-ghissues-host`. Zed's agent panel lists the entry, and picking it starts a session.
Drafted by the assistant from the author's text; approved by the author 2026-10-27.

## Acceptance criteria
- AC-1: in `/home/mcrowe/Programming/Personal/harnessed/main`, a user runs `harnessed-claude-gortex-ghissues-host --register-aoe-only`; aoe holds one row for that project that replays the launcher, and the command exits 0 without starting claude; boundary: a second run leaves one row, not two, and a row created before this change is recognised and repaired, not duplicated; negative: with aoe not installed, it says so, exits non-zero and writes nothing.
- AC-2: a user runs `harnessed-claude-gortex-ghissues-host --register-zed-only`; `~/.config/zed/settings.json` holds an `agent_servers` entry "harnessed claude (gortex-ghissues)", type `custom`, command `/home/mcrowe/.local/bin/harnessed-acp-claude-gortex-ghissues-host`; boundary: a second run leaves one entry, and the rest of the file, comments included, is unchanged; negative: when the file is not valid JSON, it says so, exits non-zero and leaves the file unchanged.
- AC-3: a user runs `harnessed-claude-gortex-ghissues-host --register-atlas-only`; `~/.local/share/dev.atlas.ide/external-agents/installed.json` holds the entry "harnessed claude (gortex-ghissues)" with the same command; boundary: entries already in the file stay, and a missing file is created; negative: when the file is not valid JSON, it says so, exits non-zero and leaves the file unchanged.
- AC-4: a user runs `harnessed-claude-gortex-ghissues-host --register-vscode-only`; `~/.config/Code/User/settings.json` holds `"claudeCode.claudeProcessWrapper": "/home/mcrowe/.local/bin/harnessed-claude-gortex-ghissues-host"`, and the Claude Code panel in VS Code then runs claude through that stack; boundary: the setting holds one value, so registering a second stack replaces it, and the rest of the file is unchanged; negative: `harnessed-omp-gortex-ghissues-host --register-vscode-only` says the integration supports claude only, exits non-zero and writes nothing.
- AC-5: a user adds `~/.config/harnessed/catalog/integrations/zellij/` and runs `--register-zellij-only`; that integration runs; boundary: when the repo and `~/.config` both hold the same name, only the `~/.config` copy runs; negative: `--register-nosuch-only` lists the available integrations and exits non-zero.
- AC-6: a user runs `harnessed-claude-gortex-ghissues-host` with no register flag in a project with no aoe row; claude starts and no aoe row, Zed, Atlas or VS Code entry is written; boundary: `harnessed rm <stack>` still removes that stack's aoe rows; negative: with `catalog/integrations/aoe/` absent, `--register-aoe-only` lists the available integrations and exits non-zero.
- AC-7: the `gortex-ghissues` profile for claude is missing or stale, and a user runs any `--register-<name>-only` flag on its launcher; the stack is built for that harness and backend before the integration runs, so after AC-2 the command `harnessed-acp-claude-gortex-ghissues-host` answers an ACP `initialize` request with a `"result"`; boundary: when the profile is current, no build runs; negative: when the build fails, no integration runs, nothing is written, and the command exits non-zero with the build's error.

## Constraints
- An integration receives names and paths (harness, stack, backend, launcher path), never credential values.
- Nothing host-local goes in `catalog/`, because it ships in the wheel.
- Launcher names follow `harnessed-[acp-]<harness>-<stack>-<backend>` (GH-565).
- Replaces the earlier GH-569 design, which ran integrations during `harnessed build`.

## Author notes
- SR-DEFER: "nothing under `src/harnessed/` changes". engineering checks at the plan review
- SR-DEFER: "the Claude Code panel in VS Code then runs claude through that stack". engineering checks at the plan review that the extension's wrapper arguments work with `host-run`
