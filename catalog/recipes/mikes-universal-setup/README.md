# mikes-universal-setup

A personal baseline: 9 always-on rules (coding stance, precedence, response style, confirmation
gates, prompt defense, token economy, cwd stability, denied shell commands, anti-drift) plus 19
skills — 13 vendored in-tree and 6 fetched at build time from pinned upstreams. Serves as the
worked example of what a personal "how I want my agent to behave" recipe looks like.

A rule here is injected on every turn; a skill loads when its description matches the work. Seven
of the vendored skills (`blameless-debugging`, `commit-hygiene`, `load-bearing-comments`,
`no-speculative-code`, `pre-publish-review`, `search-tools`, `tests-are-authority`) were always-on
rules until the split described in `recipe.yaml`: a rule earns permanent context only when
violating it is silent or irreversible, and everything with a trigger legible in advance became a
skill. The rules that referenced them keep a one-line pointer.

Ships as rules + skills + an `install.script`. No MCP server, no Dockerfile.

## Provenance

This file used to say "no single upstream — this is a personal recipe assembled inside harnessed",
with `humanizer` as the lone vendored exception. **That was wrong.** A provenance audit on
2026-07-23 found that most of these skills are vendored third-party copies; several were
byte-identical to upstream despite being long believed original.

| skill | upstream | licence | status |
| --- | --- | --- | --- |
| `application-security`, `mermaid-diagrams`, `mise`, `python-uv`, `skill-management` | [oakoss/agent-skills](https://github.com/oakoss/agent-skills) | MIT *(frontmatter only — see below)* | **fetched at build**, pinned SHA — not vendored |
| `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) | MIT | **removed 2026-09-09** — folded into `mikes-voice`, see below |
| `simple-english` | [AminBlg/SimpleEnglish](https://github.com/AminBlg/SimpleEnglish) | MIT *(repo LICENSE file)* | unmodified at `379728b5` — **fetched at build**, pinned SHA — not vendored |
| `map-codebase` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) | MIT | derived, then decoupled + modified — stays vendored |
| `tdd` | **origin unresolved** (not mattpocock — matches no upstream commit) | — | treated as authored-here |
| `defuddle` | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | MIT | derived + locally modified (stronger trigger) — vendored **with LICENSE + PROVENANCE.md** |
| `mikes-voice` | authored here (from Mike's captured drafting-guide note, 2026-08-21) | — | original; absorbed `humanizer` + `no-ai-slop` on 2026-09-09 |
| `varlock`, `wrangler` | authored here | — | original |

The oakoss five were verified byte-for-byte against their upstream (`0283bed3` — `SKILL.md` + every
`references/` file). Unmodified third-party work, so they are fetched, not vendored — see below.
`simple-english` was added the same way on 2026-08-01 (`AminBlg/SimpleEnglish@379728b5`): a
directory-skill taken unmodified, only `skills/simple-english/` copied — the repo's `evals/`,
`prompts/`, and `examples/` are not installed.

### Prose-quality upstreams: references, not dependencies

`humanizer` was fetched here until 2026-09-09. It is gone, and `petergyang/no-ai-slop` was never
kept: both are folded into `mikes-voice`, which now owns prose quality alone.

Two reasons. They **conflicted**, not merely overlapped: humanizer rewrites in place, preserves
paragraph count, and its own worked example injects opinions the source never had ("I genuinely
don't know how to feel about this one"); no-ai-slop makes the minimum edit and forbids inventing any
claim or opinion. They also disagree on em dashes — humanizer bans them outright while contradicting
itself in its own false-positive list; no-ai-slop allows one or two in longer drafts. Arbitrating two
upstreams on every draft is worse than owning one file. And `mikes-voice` had already reinvented
roughly two thirds of both independently.

Skim these when you want new patterns. They are prose taste, not an API, so nothing breaks by not
tracking them:

| upstream | what to look for | last skimmed |
| --- | --- | --- |
| [blader/humanizer](https://github.com/blader/humanizer) | new numbered patterns (was 33 at `1b48564`, v2.8.2); its "What NOT to flag" and "Signs of human writing" lists are the best part | 2026-09-09 |
| [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop) | new entries under "Patterns to cut" and "Words to cut" (skimmed at `000650b1`) | 2026-09-09 |

What was ported into `mikes-voice`: the portability test, metadiscourse, colon reveals, faux-insight
setups, fake-profound kickers, weasel attribution, synonym cycling, and fake-strong verbs from
no-ai-slop; the restraint list ("Leave these alone") from humanizer. Everything else either already
existed in `mikes-voice` or was judged not worth the tokens.

**Removed 2026-07-23** (unused or unattributable): `create-skill`, `handoff`, `security-review`
(GSD-derived, not needed here), and `code-optimizer`, `frontend-design` (provenance never
identified — not safe to keep as if original). `agent-browser` was removed earlier for the same
audit.

**The canonical GSD upstream is [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core).** An
earlier `gsd-build/get-shit-done` URL in `map-codebase`'s frontmatter was corrected: that repo was
compromised, and this tree must not reference it. If you find that string anywhere in this tree
again, it is a regression — replace it, do not fetch from it.

### How the fetched skills are installed — and why it is a bridge (bd harnessed-197)

The seven unmodified third-party skills are **not** vendored. `install.sh` fetches them at build time
(both container build and host launch) from GitHub archives pinned to **commit SHAs**, and installs
them into `$HARNESSED_CONFIG_DIR/skills/`. `expect.skills` makes the capability test verify they
landed.

The intended end state is to *consume the ecosystem* — the vercel [`skills`](https://github.com/vercel-labs/skills)
CLI + a `skills-lock.json`, rather than a hand-rolled fetcher. But the CLI cannot do it safely yet,
confirmed empirically 2026-07-24:

- **No SHA pinning.** `skills add repo#<sha>` runs `git clone --branch <sha>`, which fails on a
  commit (`Remote branch … not found`). Branches/tags only — both movable.
- **No integrity check.** `skills experimental_install` installs a skill even when the lockfile's
  `computedHash` is deliberately wrong. Upstream acknowledges this (issue #806).

So `skills-lock.json` today = an unpinned, unverified fetch from a mutable branch — the gsd-build
exposure. Until upstream ships pinning + verification (PRs #1439, #463/#549), `install.sh` supplies
the pin+verify the ecosystem lacks. **When those merge, delete `install.sh` and switch to the CLI +
`skills-lock.json`** — tracked in `harnessed-197`.

Pin to a **SHA, not a tag** — a tag is a movable pointer, and a repo compromise (gsd-build) moves
tags. The SHAs in `install.sh` and the `install.cache` marker in `recipe.yaml` are bumped together.

**These pins are HOLD / manual-upgrade-only.** A skill is agent instructions. Upgrading it pulls new
instructions no scanner can vet, so a bump means a human reads the upstream diff and re-approves.
`harnessed-tfm` (the pin auto-updater) must never auto-bump them. See bd memory
`skill-pins-are-manual-upgrade-only`.

### Outstanding obligations

1. **The licence gap is discharged for everything fetched** — the oakoss five and `humanizer` are
   fetch-not-vendor, so they are no longer redistributed in the wheel at all. `defuddle` stays
   vendored (locally modified) and ships its LICENSE. Still outstanding: `map-codebase` is a vendored
   copy derived from `open-gsd/gsd-core` (MIT) whose LICENSE is **not** committed alongside it.
   (`tdd` needs none — origin unresolved, treated as authored-here.) MIT requires the notice travel
   with the copy.
2. **`oakoss/agent-skills` has no LICENSE file** and GitHub reports no repo licence — the MIT claim
   exists only in each `SKILL.md`'s frontmatter. Confirm the grant before relying on it.
