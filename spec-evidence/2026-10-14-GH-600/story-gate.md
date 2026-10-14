# Gate 1, story readiness

verdict: ready
story: GH-600
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 61401/249
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-6-3-gh-600-claude-md-imports-to-rules/822a82ac-ce32-407c-a1c2-695a4dc0e8c1/scratchpad/GH-600-record.json
graded: 2026-10-14T00:48:27.424Z

## Reasons

none

## Record

```json
{"input":"Story","type":"feature","missing":[],"gaps":["prompt 2: the answer `i` is offered in the prompt and used in AC-4, AC-5 and AC-6, but the Story never says what it means. A reader would guess `ignore`, and would also have to guess how it differs from `n`. AC-4 hints at the difference: a stored `n` warns on host-acp, a stored `i` does not.","prompt 2: AC-4 does not give the warning text. AC-7 does not give its text either, beyond the fact that it names the path.","prompt 3: AC-1 lists `build`, `install`, `host-run` and `container-run` as the commands that ask. AC-4 says `host-acp` never asks. A build could therefore satisfy every criterion while an ACP-only user is never asked. That is probably intended, but nothing says so.","prompt 1: nothing covers an import that appears in more than one place, or two imports whose files share a basename in `rules/`. The copies would collide."],"fields":[{"name":"who","state":"present"},{"name":"what","state":"present"},{"name":"done-looks-like","state":"present"},{"name":"example","state":"present"}],"readings":[],"findings":[],"deferred":[{"ac":"AC-2","why":"Whether container-acp loads the stack's rules from the config volume the same way is for engineering to check at the plan review. The Story's author note already defers it as SR-DEFER, and AC-2 is proven on what the Story says."}],"items":[{"ac":"AC-1","status":"proven","evidence":"Put an @-import in ~/.claude/CLAUDE.md, use a stack with no stored answer, and run build, install, host-run and container-run. Falsified if any of them does not print the exact quoted prompt. Then put the import only in a parent or project CLAUDE.md, or remove it from ~/.claude/CLAUDE.md. Falsified if the prompt still appears."},{"ac":"AC-2","status":"proven","evidence":"Answer y, place a random marker in the import target, and run tools/acp-smoke.py --prompt against host-acp and container-acp. Falsified if either does not return the marker, or if the copy in rules/ is a symlink. Before the answer, falsified if the probe returns the marker."},{"ac":"AC-3","status":"proven","evidence":"Run gortex instructions switch so the target's content changes, then launch. Falsified if the new session returns the old marker, or if the copy is only refreshed by a build and not by a plain launch."},{"ac":"AC-4","status":"proven","evidence":"With no stored answer, and again with a stored n, start host-acp and capture stdout and stderr separately. Falsified if rules/ gains a copy, if stderr has no warning, or if stdout has any byte from this. With a stored y or i, falsified if a warning is printed."},{"ac":"AC-5","status":"proven","evidence":"Answer y, n and i on three runs and inspect the stack's stored state. Falsified if the answer is not stored, or if the stack asks a second time. A second stack with no stored answer must still ask. After n or i, falsified if any file appears in rules/."},{"ac":"AC-6","status":"proven","evidence":"After a y copy exists, remove the import and launch. Falsified if the copy remains. Do the same through build --reask-imports answered n and again answered i. Falsified if the copy remains. Answer y instead. Falsified if anything is deleted. Put a user-written file in rules/. Falsified if it is ever deleted."},{"ac":"AC-7","status":"proven","evidence":"Point an @-import at a nonexistent path and run build and a launch. Falsified if stderr does not name the path, or if build or the launch fails. Put an @-import inside an imported file. Falsified if the copy is not the literal text, or if the inner target is also copied."}]}
```

## Story

````
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
````