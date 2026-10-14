---
id: GH-600
type: feature
source:
  tracker: github
  external_id: GH-600
  url: https://github.com/drmikecrowe/harnessed/issues/600
  version: 2026-10-13T19:18:36Z
---
# Convert CLAUDE.md @-imports to stack rules, because ACP sessions drop them
## Description
Who: a harnessed user whose `~/.claude/CLAUDE.md` pulls in other files with `@`-imports, and who starts `host-acp` or `container-acp` sessions.

What: harnessed finds the `@`-imports in `~/.claude/CLAUDE.md` and, if the user agrees, keeps a real copy of each imported file in the stack home's `rules/`, rewritten on every launch. A headless ACP session started by `claude-agent-acp` 0.85.1 loads CLAUDE.md files but expands none of their `@`-imports, and a symlink in `rules/` is not loaded either, so today every ACP session runs without the imported instructions and nothing says so. Found in GH-594 S4.2 (`spec-evidence/2026-10-12-GH-594/decisions.md`, Revision 4); verified 2026-10-13 with random markers on the `hostspike` stack.

Done looks like: AC-1 through AC-7 below pass, each checked with `tools/acp-smoke.py --prompt` or on a terminal.

Example: `/home/mcrowe/.claude/CLAUDE.md` line 6 imports `~/.local/share/gortex/instructions/active.md`. On the `hostspike` stack the user runs `harnessed build` and answers `y`; a fresh `host-acp` session then returns a random marker placed in `active.md`. Today it does not.

Drafted by the assistant from the author's text; approved by the author 2026-10-13.
## Acceptance criteria
- AC-1: `harnessed build`, `install`, `host-run` and `container-run` find an `@`-import in `~/.claude/CLAUDE.md` while the stack has no stored answer, and each asks "Your ~/.claude/CLAUDE.md uses @import syntax that ACP sessions do not expand. Copy the imported files into this stack's rules? [y/n/i]"; boundary: only imports in `~/.claude/CLAUDE.md` count, and parent and project CLAUDE.md imports are never converted; negative: with no `@`-import in `~/.claude/CLAUDE.md`, nothing asks.
- AC-2: after the user answers `y`, a `host-acp` session and a `container-acp` session on the stack each return a random marker line placed in the import target, using `tools/acp-smoke.py --prompt`; boundary: the copy in `rules/` is a regular file, not a symlink; negative: before the answer, the same probe does not return the marker.
- AC-3: after `gortex instructions switch` changes the import target's content, the next launch's session returns the new marker and not the old one; boundary: the copy is rewritten from the import target on every launch, not only at build; negative: a session started before the switch is not required to change.
- AC-4: with no stored answer, or a stored `n`, `host-acp` copies nothing and prints a warning on stderr; boundary: stdout gets no bytes from this, because stdout carries the ACP protocol; negative: with a stored `y` or `i`, no warning is printed.
- AC-5: a `y`, `n` or `i` answer is stored per stack, and that stack does not ask again; boundary: a second stack with no stored answer still asks; negative: after `n` or `i`, no file is copied into `rules/`.
- AC-6: when an import is removed from `~/.claude/CLAUDE.md`, or the user runs `harnessed build <stack> --reask-imports` (which clears the stack's stored answer and asks again) and answers `n` or `i`, the next launch deletes the copy harnessed made for that import; boundary: only files harnessed recorded as its own copies are deleted; negative: a rule file the user wrote in `rules/` is never deleted, and `--reask-imports` answered `y` deletes nothing.
- AC-7: an import whose target does not exist gets a stderr warning that names the path, and the launch goes on; boundary: an `@`-import inside an imported file is copied as text and not followed; negative: a missing target never fails `build` or a launch.
## Constraints
- No symlinks: a symlinked rule is not loaded (verified 2026-10-13).
- The copy is refreshed on every launch, the same way `settings.json` is re-propagated in `src/harnessed/launcher.py`.
- An interactive session gets the content twice, once by the import and once as the rule. Accepted: harmless, more tokens.
## Author notes
- SR-DEFER: "Whether `container-acp` loads the stack's rules from the config volume the same way." engineering checks at the plan review
- SR-DEFER: "Whether a newer `claude-agent-acp`, or an Agent SDK setting, expands imports, which would make this unnecessary. Report upstream either way." engineering checks at the plan review
