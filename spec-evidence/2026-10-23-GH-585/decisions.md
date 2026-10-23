# Decisions — GH-585: container mode in the acp-editors wiki page

## Setup plan
- Isolation: none for the wiki, because `harnessed.wiki.git` has no branch or PR surface (AGENTS.md, "Exemption: `docs/`"). The story directory lives in worktree `GH-585-acp-docs` on branch `GH-585-acp-docs`.
- Git: one signed wiki commit in `main/docs`, pushed only after the user says yes. Story artifacts are committed on the task branch.
- New dependencies: none.
- New files: none in the wiki. In this repository, only the story directory `spec-evidence/2026-10-23-GH-585/`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck and secrets. Only secrets applies (gitleaks, run on the one page). The others gate no file this change touches. Missing: a Markdown link checker; nothing declares one, so link checks are manual reads.
- Merge gate: AGENTS.md "What a change must run" — repo Markdown outside `catalog/` runs only tests that name the changed file. `rg -l 'acp-editors' tests` is run at build time; a hit runs that file.

## Facts this SPEC rests on
1. #566 is closed (2026-10-13) — `gh issue view 566`.
2. #584 passed headless for claude (`default`) and omp (`zai-acp`), and in Zed for both; Atlas was dropped and not run — #584 comments.
3. #584 found a stale profile after a harnessed version change, fixed by `harnessed build default claude` — #584 comments.
4. #584 found omp needs `zai-acp` for egress to `api.z.ai` — #584 comments.
5. #597 (the stale credential copy in an old pod) is closed — `gh issue view 597`.
6. The proxy answers `initialize` itself and starts a project's agent on the first `session/new` for that project — `src/harnessed/acpproxy.py:1-10`.
7. The page lines to change: the NOTE (line 4), the `<backend>` bullet (line 18), the table and sentence (lines 24-31), Troubleshooting (line 127), Known limits (#566 bullet) — `main/docs/guides/acp-editors.md`.
8. `main/docs` has an untracked `spec-evidence/` directory — `git -C main/docs status --short`.

## Decide calls

none

## Revisions
### Revision 1. Intent review folded in
Accepted: S1.2 widened to any "not ready" or "not yet" line, with a read of each hit. Accepted: S5.1 names the wiki commit URL form `wiki/_compare/<sha>` and checks it returns 200. Declined: dropping the gitleaks layer, because it is the only check on the Must NOT line about credentials and costs one command.
