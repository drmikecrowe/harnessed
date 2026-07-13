# mikes-universal-setup

A personal baseline: 5 rules (coding stance, tool preferences, confirmation gates, token economy)
plus 17 generic utility skills. Serves as the worked example of what a personal
"how I want my agent to behave" recipe looks like.

Ships as rules + skills; no MCP server, no Dockerfile.

No single upstream — this is a personal recipe assembled inside harnessed. The one exception is
`skills/humanizer`, vendored from [blader/humanizer](https://github.com/blader/humanizer) (MIT) at
commit `1b48564898e999219882660237fde01bf4843a0f`; its LICENSE ships alongside it. Upstream has no
tags or releases and is a single `SKILL.md`, so it is committed here rather than cloned at build
time the way the `superpowers` recipe pulls its 14-skill tree.
