# mikes-universal-setup

A personal baseline: 5 rules (coding stance, tool preferences, confirmation gates, token economy)
plus 16 generic utility skills. Serves as the worked example of what a personal
"how I want my agent to behave" recipe looks like.

Ships as rules + skills; no MCP server, no Dockerfile.

## Provenance

This file used to say "no single upstream — this is a personal recipe assembled inside harnessed",
with `humanizer` as the lone vendored exception. **That was wrong.** A provenance audit on
2026-07-23 found that most of these skills are vendored third-party copies; two of them
(`mise`, `python-uv`) are byte-identical to upstream despite being long believed original.

| skill | upstream | licence |
| --- | --- | --- |
| `application-security`, `mermaid-diagrams`, `mise`, `python-uv`, `skill-management` | [oakoss/agent-skills](https://github.com/oakoss/agent-skills) | MIT *(frontmatter only — see below)* |
| `create-skill`, `handoff`, `map-codebase`, `security-review` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) | MIT |
| `tdd` | [mattpocock/skills](https://github.com/mattpocock/skills), carrying GSD idiom | MIT |
| `defuddle` | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | MIT |
| `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) @ `1b48564898e999219882660237fde01bf4843a0f` | MIT |
| `varlock`, `wrangler` | authored here | — |
| `code-optimizer`, `frontend-design` | **NOT IDENTIFIED** | unknown |

`mise` and `python-uv` were verified byte-for-byte against
`oakoss/agent-skills` (7842 and 8419 bytes, identical). They are not original work.

**The canonical GSD upstream is [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core).** An
earlier `gsd-build/get-shit-done` URL in `map-codebase`'s frontmatter was corrected on 2026-07-23:
that repo was compromised, and nothing here should point at it. If you find that string anywhere in
this tree again, it is a regression — replace it, do not fetch from it.

### Outstanding obligations

1. **Only `humanizer` ships its LICENSE.** Every other vendored skill above is redistributed inside
   the wheel with no copyright notice. MIT requires the notice travel with the copy, so this is a
   real gap, not a formality.
2. **`oakoss/agent-skills` has no LICENSE file** and GitHub reports no repo licence — the MIT claim
   exists only in each `SKILL.md`'s frontmatter. Confirm the grant before relying on it.
3. **`code-optimizer` and `frontend-design` have unknown provenance.** Neither is safe to treat as
   original work. `frontend-design` may be [anthropics/claude-code](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md)'s
   skill of the same name — unverified; diff before attributing.

The intended fix is not to retrofit licence files but to stop vendoring: fetch each upstream at
build time via `install.script` + a pinned `install.cache`, the way `agent-carnet` already does.
That carries the licence with the content and removes the redistribution entirely. Several of these
upstreams ship their own installers (`skills add` for kepano, `agent-browser install` for vercel),
which is better than a hand-rolled fetch.
