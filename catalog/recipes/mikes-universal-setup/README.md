# mikes-universal-setup

A personal baseline: 5 rules (coding stance, tool preferences, confirmation gates, token economy)
plus 11 generic utility skills. Serves as the worked example of what a personal
"how I want my agent to behave" recipe looks like.

Ships as rules + skills; no MCP server, no Dockerfile.

## Provenance

This file used to say "no single upstream — this is a personal recipe assembled inside harnessed",
with `humanizer` as the lone vendored exception. **That was wrong.** A provenance audit on
2026-07-23 found that most of these skills are vendored third-party copies; several were
byte-identical to upstream despite being long believed original.

| skill | upstream | licence | status |
| --- | --- | --- | --- |
| `application-security`, `mermaid-diagrams`, `mise`, `python-uv`, `skill-management` | [oakoss/agent-skills](https://github.com/oakoss/agent-skills) | MIT *(frontmatter only — see below)* | byte-identical → migrate to `skills` fetch |
| `map-codebase` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) | MIT | derived, then decoupled + modified — stays vendored |
| `tdd` | [mattpocock/skills](https://github.com/mattpocock/skills) | MIT | modified ~114 lines — stays vendored |
| `defuddle` | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | MIT | modified — stays vendored |
| `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) @ `1b48564898e999219882660237fde01bf4843a0f` | MIT | vendored with LICENSE |
| `varlock`, `wrangler` | authored here | — | original |

All five oakoss skills were verified byte-for-byte against `oakoss/agent-skills` at HEAD `0283bed3`
(`SKILL.md` + every file under `references/`). They are not original work.

**Removed 2026-07-23** (unused or unattributable): `create-skill`, `handoff`, `security-review`
(GSD-derived, not needed here), and `code-optimizer`, `frontend-design` (provenance never
identified — not safe to keep as if original). `agent-browser` was removed earlier for the same
audit.

**The canonical GSD upstream is [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core).** An
earlier `gsd-build/get-shit-done` URL in `map-codebase`'s frontmatter was corrected: that repo was
compromised, and nothing here should point at it. If you find that string anywhere in this tree
again, it is a regression — replace it, do not fetch from it.

### Migration plan (the five oakoss skills)

Because they are byte-identical, they should stop being hand-copied and instead be fetched at build
time, pinned to a commit SHA, via the vercel `skills` CLI:

```
skills add oakoss/agent-skills#<sha> --skill mise      # #<sha> pins to an immutable commit
```

Pin to a **SHA, not a tag** — a tag is a movable pointer, and a repo-compromise (see gsd-build) moves
tags. Two constraints from this repo apply: the recipe lint rejects raw `npx` (use `pnpm dlx skills`)
and rejects floating refs, so the SHA pin is mandatory, not optional. The CLI installs by agent
convention relative to the working directory rather than to an arbitrary path, so the install script
must run it from a location whose skills dir maps to the profile — that wiring is the open work.

### Outstanding obligations

1. **Only `humanizer` ships its LICENSE.** Every other vendored skill is redistributed inside the
   wheel with no copyright notice. MIT requires the notice travel with the copy — a real gap. The
   migration above removes it for the oakoss five by not vendoring at all; `map-codebase`, `tdd`,
   `defuddle` still need their upstream LICENSE committed alongside them.
2. **`oakoss/agent-skills` has no LICENSE file** and GitHub reports no repo licence — the MIT claim
   exists only in each `SKILL.md`'s frontmatter. Confirm the grant before relying on it.
