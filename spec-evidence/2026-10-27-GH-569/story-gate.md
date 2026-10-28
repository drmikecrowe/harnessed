# Gate 1, story readiness

verdict: ready
story: GH-569
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 107020/3809
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/se-gh569/story-record.json
graded: 2026-10-27T12:03:01.885Z

## Reasons

none

## Record

```json
{"input":"Story","type":"feature","missing":[],"gaps":["prompt 2: AC-1 says a pre-existing aoe row is 'recognised and repaired', but the Story does not say what a repaired row contains or what made the old row wrong.","prompt 2: AC-7 uses 'stale' for a profile without saying what makes one stale. A reader has to guess whether that means the catalog changed, the build stamp is old, or the harness version moved.","prompt 3: AC-5 only says 'that integration runs'. A zellij script that does nothing useful would satisfy it, and the Story never says what a zellij integration should register.","prompt 1: the Story names no criterion for `--register-<name>-only` on a launcher for a harness an integration does not support, other than the VS Code case in AC-4. AC-2 and AC-3 do not say which harnesses they cover."],"fields":[{"name":"who","state":"present"},{"name":"what","state":"present"},{"name":"done-looks-like","state":"present"},{"name":"example","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"AC-1","why":"how an existing aoe row is recognised and repaired depends on the current aoe registration code; the Story's own note defers 'nothing under src/harnessed/ changes' to the plan review"},{"ac":"AC-4","why":"whether the VS Code extension's wrapper arguments work with host-run is an engineering check at the plan review, per the author note"}],"items":[{"ac":"AC-1","status":"proven","evidence":"Run `harnessed-claude-gortex-ghissues-host --register-aoe-only` in the main checkout. Check that the exit code is 0, claude did not start, and `aoe list` shows exactly one row for the project that replays the launcher. Run it again and count rows: more than one falsifies it. With aoe removed from PATH, the command must exit non-zero with a message and write nothing."},{"ac":"AC-2","status":"proven","evidence":"Run the flag, open `~/.config/zed/settings.json`, and check `agent_servers` holds one entry 'harnessed claude (gortex-ghissues)' with type custom and the stated command. Run again and diff the file, comments included: any other change, or a second entry, falsifies it. Put invalid JSON in the file: the command must exit non-zero and the file must be byte-identical."},{"ac":"AC-3","status":"proven","evidence":"Run the flag and open `~/.local/share/dev.atlas.ide/external-agents/installed.json`. Check the entry 'harnessed claude (gortex-ghissues)' with the same command is there. Seed the file with another entry and confirm it survives. Delete the file and confirm it is created. Seed invalid JSON: exit must be non-zero and the file byte-identical."},{"ac":"AC-4","status":"proven","evidence":"Run the flag and read `~/.config/Code/User/settings.json` for the `claudeCode.claudeProcessWrapper` key with the stated path. Register a second stack and check the key holds only the new value and the rest of the file is unchanged. Run `harnessed-omp-gortex-ghissues-host --register-vscode-only`: it must exit non-zero with a claude-only message and leave the file byte-identical."},{"ac":"AC-5","status":"proven","evidence":"Create `~/.config/harnessed/catalog/integrations/zellij/` with an executable script that writes a marker file. Run `--register-zellij-only` and check the marker exists. Add a same-named script under the repo `catalog/integrations/` that writes a different marker: only the ~/.config marker may appear. Run `--register-nosuch-only`: output must list the available integrations and the exit must be non-zero."},{"ac":"AC-6","status":"proven","evidence":"In a project with no aoe row, run the launcher with no register flag. Check claude starts, `aoe list` has no new row, and the Zed, Atlas and VS Code files are untouched. Register an aoe row, run `harnessed rm <stack>` and check the row is gone. Move `catalog/integrations/aoe/` away and run `--register-aoe-only`: it must list the available integrations and exit non-zero."},{"ac":"AC-7","status":"proven","evidence":"Remove the gortex-ghissues claude profile, run `--register-zed-only`, and check a build ran before the integration. Then pipe an ACP `initialize` request to `harnessed-acp-claude-gortex-ghissues-host`: the reply must contain a `\"result\"`. Run again with a current profile and check no build runs. Force a build failure: no integration may run, nothing may be written, and the exit must be non-zero with the build's error."}]}
```

## Story

````
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
````