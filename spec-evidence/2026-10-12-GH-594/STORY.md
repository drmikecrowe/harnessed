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
