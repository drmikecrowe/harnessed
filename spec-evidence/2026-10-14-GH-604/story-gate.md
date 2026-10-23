# Gate 1, story readiness

verdict: ready
story: GH-604
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 61324/165
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/gh604/story-record.json
graded: 2026-10-14T11:39:38.413Z

## Reasons

none

## Record

```json
{"input":"Story","type":"bug","missing":[],"gaps":["prompt 2: AC-1 to AC-3 say the message 'names' a command but not whether the full line must match exactly or the command only has to appear. A reader has to guess the offer's surrounding wording.","prompt 3: the Story covers mise and pnpm only. An adapter installed by another tool, such as a system package or a nix profile, would fall back to `pnpm add -g` and shadow the same way. AC-4's negative case prints the path and version but does not say what the fallback suggestion should be afterwards.","prompt 1: the Story says a failed install never fails the build, but no criterion states what the user sees when the suggested command exits non-zero."],"fields":[{"name":"steps","state":"present"},{"name":"actual","state":"present"},{"name":"expected","state":"present"},{"name":"where","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"AC-3","why":"The Story names 'pnpm's global bin dir' without a path. Where that directory is on a given host is settled against the code and pnpm configuration at the plan review, as the author note says."}],"items":[{"ac":"AC-1","status":"proven","evidence":"Put a stub claude-agent-acp reporting 0.85.1 under ~/.local/share/mise/installs/npm-agentclientprotocol-claude-agent-acp/0.85.1/bin first on PATH, with the pin at 0.89.1. Run `harnessed build <stack> claude` and `harnessed host-acp claude`. Repeat with the stub at ~/.local/share/mise/shims/claude-agent-acp. Fails if either message lacks `mise use -g npm:@agentclientprotocol/claude-agent-acp@0.89.1` or contains `npm i -g`."},{"ac":"AC-2","status":"proven","evidence":"Empty PATH of any claude-agent-acp. Run build and host-acp claude. Fails if the offer or the refusal lacks `pnpm add -g @agentclientprotocol/claude-agent-acp@0.89.1`. Also fails if any output from either command on any path contains raw `npm`; scan the captured output."},{"ac":"AC-3","status":"proven","evidence":"Put a stub reporting 0.85.1 in the pnpm global bin dir, first on PATH. Run build and host-acp claude. Fails if either message lacks `pnpm add -g @agentclientprotocol/claude-agent-acp@0.89.1`, or if either contains `npm` or `mise`."},{"ac":"AC-4","status":"proven","evidence":"For each of the mise, pnpm and no-adapter setups, run the suggested command, then run build again. Fails if an offer appears or `claude-agent-acp --version` is not 0.89.1. For the negative case, put a stub reporting 0.80.0 at an unrecognised path first on PATH, accept the offer, and let the install exit 0. Fails if the build does not re-check right after the install and print that stub's path and the version 0.80.0."}]}
```

## Story

````
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
````