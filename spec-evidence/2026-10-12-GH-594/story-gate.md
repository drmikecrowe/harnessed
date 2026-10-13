# Gate 1, story readiness

verdict: ready
story: GH-594
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 65931/376
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-gh-594-merge-claude-json/6c6f7777-a69e-4046-8322-986c551c950a/scratchpad/GH-594-r2/story-record.json
graded: 2026-10-13T19:24:09.074Z

## Reasons

none

## Record

```json
{"input":"Story","type":"bug","missing":[],"gaps":["prompt 2: the Constraints name 'a short allowlist from the host file' for the host path but never list its keys, so a reader has to guess which host keys are carried over; AC-4 and AC-5 name only oauthAccount, userID and mcpServers.","prompt 2: AC-1 and AC-2 say 'the three prompts' by reference to the Description steps, so a reader of the criteria alone has to look back to know which three.","prompt 3: an implementation could satisfy AC-1 to AC-5 and still show the API key prompt on every first launch, because AC-1 says it is not required to be absent and apiKeyHelper is only a 'candidate'. If the author wants the key prompt gone on first launch, no criterion says so.","prompt 1: the author wants trust and import approval seeded for the launch's project path only. No criterion states that for the interactive paths (no other project path marked approved). The ACP criterion that covered it was removed, and the Constraints now cover only host-acp folder trust.","prompt 1: the Constraints say this story seeds folder trust for each new host-acp session folder, but no acceptance criterion covers it."],"fields":[{"name":"steps","state":"present"},{"name":"actual","state":"present"},{"name":"expected","state":"present"},{"name":"where","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"AC-1","why":"the key names (hasTrustDialogAccepted, hasClaudeMdExternalIncludesApproved) come from recall per the author's notes. Engineering confirms them against the installed Claude Code version at the plan review."},{"ac":"AC-2","why":"whether the API key prompt answer persists, and whether apiKeyHelper avoids the prompt, needs the installed Claude Code version. The plan review takes it."}],"items":[{"ac":"AC-1","status":"proven","evidence":"On 8451 with an empty host ~/.claude.json, launch stack S on project P on the container path and again on the host path. Open the stack's .claude.json and check projects[P].hasTrustDialogAccepted and projects[P].hasClaudeMdExternalIncludesApproved. Either value not true, or a trust or import prompt appearing, falsifies it."},{"ac":"AC-2","status":"proven","evidence":"Launch S on P, answer the API key prompt with approve, exit, relaunch on both paths. Any of the three prompts appearing falsifies it. Then repeat answering decline. A relaunch that records or shows the key as approved falsifies the negative."},{"ac":"AC-3","status":"proven","evidence":"Launch S on P, approve a project MCP server, relaunch on both paths. The approval missing from the stack's .claude.json, or the prompt reappearing, falsifies it. Set hasCompletedOnboarding to a different value in the live file, relaunch. If it is not reset to harnessed's value, the negative is falsified."},{"ac":"AC-4","status":"proven","evidence":"Put oauthAccount and userID in the host ~/.claude.json, set isolated_auth on, launch on both paths, and inspect the stack's .claude.json. Either host value present falsifies it. With isolated_auth off on the host path, either value absent falsifies the negative."},{"ac":"AC-5","status":"proven","evidence":"Add a global mcpServers entry to the host ~/.claude.json, launch on the host path, and inspect the stack's .claude.json. The entry present falsifies it. A stack MCP server from its profile failing to load falsifies the negative."}]}
```

## Story

````
---
id: GH-594
type: bug
source:
  tracker: github
  external_id: GH-594
  url: https://github.com/drmikecrowe/harnessed/issues/594
  version: 2026-10-12T18:08:56Z
---
# Merge ~/.claude.json like settings.json so trust, import, and API-key answers persist

## Description
Steps:
  1. On 8451, a machine with an API-key-only login and an empty host ~/.claude.json, launch stack S on project P.
  2. Answer the three prompts: trust this folder; allow the external import of ~/.local/share/gortex/instructions/active.md; use this API key.
  3. Exit, then launch the same stack S on the same project P.
Actual: All three prompts appear again on every launch.
  Container path: `_claude_config_seed_mount` (src/harnessed/mounts.py) writes a fresh stub on every launch, and its `write_text` is unconditional. The stub holds only hasCompletedOnboarding, firstStartTime, numStartups, oauthAccount and userID.
  Host path: `_share_host_claude_state` (src/harnessed/hosthome.py) runs `shutil.copy2` from the host ~/.claude.json onto the stack copy on every launch. A fresh host file holds none of the three answers.
Expected: An answer given in a stack persists across launches. harnessed seeds trust and import approval for the launch's project path, so those two prompts do not appear on the first launch either.
Where: src/harnessed/mounts.py `_claude_config_seed_mount` (container path) and src/harnessed/hosthome.py `_share_host_claude_state` (host path).
Drafted by the assistant from the author's text; approved by the author 2026-10-13.

## Acceptance criteria
- AC-1: Launch stack S on project P for the first time on 8451. No trust prompt and no external-import prompt appear; boundary: both the container and host paths; negative: the API key prompt is not required to be absent on the first launch, because harnessed writes no key fragment.
    Example: after that launch, the stack's .claude.json holds projects["<P>"].hasTrustDialogAccepted = true and projects["<P>"].hasClaudeMdExternalIncludesApproved = true.
- AC-2: After the user answers the API key prompt in stack S, the next launch of S on P shows none of the three prompts; boundary: both paths, with the same stack and project; negative: when the user declined the key, the relaunch does not turn that answer into an approval.
- AC-3: An answer given inside a stack (for example, approval of a project MCP server) is still in the stack's .claude.json after a relaunch, and the prompt does not appear again; boundary: both paths; negative: a key that harnessed owns (hasCompletedOnboarding) is reset to harnessed's value, because the profile wins.
- AC-4: With isolated_auth on, and a host ~/.claude.json that holds oauthAccount and userID, the stack's .claude.json holds neither of the host's values; boundary: both paths; negative: with isolated_auth off, the host path copies oauthAccount and userID as it does today.
- AC-5: A global mcpServers entry in the host ~/.claude.json does not appear in the stack's .claude.json; boundary: the host path; negative: the stack's own MCP servers from its profile still load.

## Constraints
- Merge `.claude.json` the way `settings.json` is merged (src/harnessed/jsonmerge.py: the profile wins, and `carry_live_permissions` keeps live answers). The base is the stack's live .claude.json. The overlay is only the keys that harnessed owns: the onboarding fields; for the launch's project path, hasTrustDialogAccepted, hasClaudeMdExternalIncludesApproved and hasClaudeMdExternalIncludesWarningShown; and on the host path only, a short allowlist from the host file.
- Never merge the host file wholesale. It is mostly runtime state: oauthAccount/userID are dropped under isolated_auth so a client stack does not carry the host account's identity; launcher.py (~2991) already keeps global mcpServers out of a stack; the host projects{} is per-path history, trust and MCP approvals for every host repo.
- harnessed writes no API key fragment to disk. Claude Code records approval as customApiKeyResponses.approved holding the last 20 characters of the key, and seeding it conflicts with "credentials referenced, never replicated". A candidate alternative is an apiKeyHelper in settings.json that prints the env var.
- ACP: headless ACP sessions expand no `@`-imports at all, approved or not (verified in this story's S4.2), so `.claude.json` seeding cannot load the active.md import. That work moved to #600. This story still seeds folder trust for each new host-acp session folder, and marks no other project path approved.

## Author notes
- SR-DEFER: "The key names above come from recall, not from the installed Claude Code version". engineering checks at the plan review
- SR-DEFER: "Whether apiKeyHelper avoids the API key prompt". engineering checks at the plan review
````