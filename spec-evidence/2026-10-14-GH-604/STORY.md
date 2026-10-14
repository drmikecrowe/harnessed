---
id: GH-604
type: bug
source:
  tracker: github
  external_id: GH-604
  url: https://github.com/drmikecrowe/harnessed/issues/604
  version: "unavailable: the adapter's show output carries no updated stamp"
---
# build's ACP adapter offer suggests npm i -g, which a mise or pnpm install shadows
## Description
Steps: The host has claude-agent-acp 0.85.1 from mise, and mise's directory is first on PATH. The catalog pins 0.89.1 (catalog/agents/claude/agent.yaml, `CLAUDE_AGENT_ACP_VERSION`). Run `harnessed build <stack> claude` and answer `y` to the adapter offer.
Actual: build runs `npm i -g @agentclientprotocol/claude-agent-acp@0.89.1`, which writes to npm's global prefix. `claude-agent-acp --version` still reports 0.85.1, build offers again on every run, and `host-acp claude` keeps warning with the same npm command. Raw `npm` also breaks the repo rule "pnpm, never raw npm/npx" (CLAUDE.md). The PATH order on the reporting machine was not checked; this is read from the code and PATH resolution.
Expected: build's offer and host-acp's messages name the install command of the tool that owns the adapter on PATH: `mise use -g` for mise, `pnpm add -g` for pnpm, and `pnpm add -g` as the fallback when no adapter is on PATH or its location is not recognised. No message names raw `npm`.
Where: src/harnessed/launcher.py: `_acp_adapter_install_cmd`, called by `_offer_acp_adapter` (build) and `_require_acp_adapter` (host-acp claude: the not-installed refusal and the off-pin warning).
Drafted by the assistant from the author's text; approved by the author 2026-10-14.
## Acceptance criteria
- AC-1: With a mise-installed adapter at 0.85.1 and the pin at 0.89.1, build's offer and host-acp's warning both name `mise use -g npm:@agentclientprotocol/claude-agent-acp@0.89.1`; boundary: the adapter on PATH lives under `~/.local/share/mise/installs/npm-agentclientprotocol-claude-agent-acp/0.85.1/bin` or is `~/.local/share/mise/shims/claude-agent-acp`; negative: neither message names `npm i -g`.
- AC-2: With no adapter on PATH, build's offer and host-acp's refusal both name `pnpm add -g @agentclientprotocol/claude-agent-acp@0.89.1`; boundary: no `claude-agent-acp` is on PATH; negative: no message from build or host-acp, on any path, names raw `npm`.
- AC-3: With a pnpm-installed adapter at 0.85.1, build's offer and host-acp's warning both name `pnpm add -g @agentclientprotocol/claude-agent-acp@0.89.1`; boundary: the adapter on PATH lives under pnpm's global bin dir; negative: neither message names `npm` or `mise`.
- AC-4: In the mise, pnpm and no-adapter cases, after the suggested command runs and exits 0, the next build makes no offer; boundary: `claude-agent-acp --version` now reports 0.89.1; negative: when the install exits 0 but a `claude-agent-acp` in an unrecognised location still comes first on PATH and reports a version other than 0.89.1, build checks again right after the install and prints that binary's path and the version it reports.
## Constraints
- pnpm, never raw npm/npx (CLAUDE.md).
- Keep the `c` option, which runs a command the user types, as the escape hatch.
- A failed install never fails the build.
- The pin comes from catalog/agents/claude/agent.yaml (`CLAUDE_AGENT_ACP_VERSION`), read by `_acp_adapter_pin`.
## Author notes
- SR-DEFER: "under pnpm's global dir". engineering checks at the plan review
