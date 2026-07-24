# mikes-universal-setup

A personal baseline: 5 rules (coding stance, tool preferences, confirmation gates, token economy)
plus 11 generic utility skills — 6 vendored in-tree and 5 fetched at build time from a pinned
upstream. Serves as the worked example of what a personal "how I want my agent to behave" recipe
looks like.

Ships as rules + skills + an `install.script`; no MCP server, no Dockerfile.

## Provenance

This file used to say "no single upstream — this is a personal recipe assembled inside harnessed",
with `humanizer` as the lone vendored exception. **That was wrong.** A provenance audit on
2026-07-23 found that most of these skills are vendored third-party copies; several were
byte-identical to upstream despite being long believed original.

| skill | upstream | licence | status |
| --- | --- | --- | --- |
| `application-security`, `mermaid-diagrams`, `mise`, `python-uv`, `skill-management` | [oakoss/agent-skills](https://github.com/oakoss/agent-skills) | MIT *(frontmatter only — see below)* | **fetched at build** via `install.sh`, pinned SHA — not vendored |
| `map-codebase` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) | MIT | derived, then decoupled + modified — stays vendored |
| `tdd` | **origin unresolved** (not mattpocock — matches no upstream commit) | — | treated as authored-here |
| `defuddle` | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | MIT | derived + locally modified (stronger trigger) — vendored **with LICENSE + PROVENANCE.md** |
| `humanizer` | [blader/humanizer](https://github.com/blader/humanizer) @ `1b48564898e999219882660237fde01bf4843a0f` | MIT | legacy pin, byte-identical — fetch candidate, vendored with LICENSE for now |
| `varlock`, `wrangler` | authored here | — | original |

All five oakoss skills were verified byte-for-byte against `oakoss/agent-skills` at HEAD `0283bed3`
(`SKILL.md` + every file under `references/`). They are not original work, so they are no longer
vendored — see below.

**Removed 2026-07-23** (unused or unattributable): `create-skill`, `handoff`, `security-review`
(GSD-derived, not needed here), and `code-optimizer`, `frontend-design` (provenance never
identified — not safe to keep as if original). `agent-browser` was removed earlier for the same
audit.

**The canonical GSD upstream is [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core).** An
earlier `gsd-build/get-shit-done` URL in `map-codebase`'s frontmatter was corrected: that repo was
compromised, and nothing here should point at it. If you find that string anywhere in this tree
again, it is a regression — replace it, do not fetch from it.

### How the five oakoss skills are installed (bd harnessed-s8l)

They are **not** vendored. `install.sh` fetches them at build time (both container build and host
launch) from a GitHub archive pinned to a **commit SHA** (`0283bed3…`), extracts the five skill dirs,
and copies them into `$HARNESSED_CONFIG_DIR/skills/`. `expect.skills` makes the capability test
verify they landed. Delivered by a pinned tarball, not the vercel `skills` CLI: the CLI installs by
agent convention relative to cwd (no target-path flag) and conflates fetch with placement, so it
would re-clone on every host launch and need a symlink shim; a pinned archive fits harnessed's
`install.cache` per-launch-re-run model directly and is more auditable.

Pin to a **SHA, not a tag** — a tag is a movable pointer, and a repo compromise (see gsd-build) moves
tags. The SHA in `install.sh` and `install.cache` in `recipe.yaml` must stay equal.

**This pin is HOLD / manual-upgrade-only.** A skill is agent instructions; upgrading it pulls new
instructions no scanner can vet, so a bump means a human reads the diff of the new SHA and
re-approves. `harnessed-tfm` (the pin auto-updater) must never auto-bump it. See bd memory
`skill-pins-are-manual-upgrade-only`.

### Outstanding obligations

1. **The oakoss licence gap is now discharged** for these five — fetch-not-vendor means they are no
   longer redistributed in the wheel at all. `humanizer` and `defuddle` now ship their upstream
   LICENSE. Still outstanding: `map-codebase` is a vendored copy derived from `open-gsd/gsd-core`
   (MIT) whose LICENSE is **not** committed alongside it. (`tdd` needs none — origin unresolved,
   treated as authored-here.) MIT requires the notice travel with the copy.
2. **`oakoss/agent-skills` has no LICENSE file** and GitHub reports no repo licence — the MIT claim
   exists only in each `SKILL.md`'s frontmatter. Confirm the grant before relying on it.
