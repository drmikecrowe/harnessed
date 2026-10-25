# SPEC — GH-585: container mode in the acp-editors wiki page

## Summary
The wiki page `guides/acp-editors.md` will tell editor users that container mode works, and how to set it up. Today the page says container mode from an editor is not ready, but #566 shipped and the live check #584 passed in Zed and headless. Only that one wiki page changes, plus one comment on GH-585 that links the wiki commit.

The criteria, in plain words:
- AC-1: every line that says container mode is not ready, or that a `-container` launcher uses the editor's folder, is rewritten. The table says container is ready and takes the folder from each session.
- AC-2: the page shows a Zed entry for a `-container` launcher with empty args, and names the two example launchers.
- AC-3: the page says the first session in a project waits for the pod to start, and that a slow start can run past the editor's `session/new` time limit. It gives no numbers.
- AC-4: Known limits lists two container findings from #584: a stale profile after a harnessed version change, and omp's need for an egress-allowed stack such as `zai-acp`. Atlas is not named in container text.
- AC-5: after the push, a comment on GH-585 links the wiki commit.

What must not change: the host-mode instructions, any other wiki page, and anything in this repository except the story directory. The wiki commit holds only `guides/acp-editors.md`.

How each is proven: `rg` checks on the edited page for each scenario, a read of the full wiki diff, gitleaks over the wiki diff, and `gh` reads of the pushed commit and the issue comment.

Open decisions: none.

## Orientation
- Change: rewrite the container-mode parts of the wiki page `guides/acp-editors.md`, and link the wiki commit on GH-585.
- Why: the page still tells readers container mode is not ready, after #566 and #584 made it work.
- Touches: `main/docs/guides/acp-editors.md` (wiki repository); a GH-585 comment.
- Decide: none open. The likeliest wrong call is the exact first-session wording in S3.1.

- Tier: 1
- Issue: GH-585
- Isolation: none for the wiki — it has no branch or PR surface (AGENTS.md, "Exemption: `docs/`"); this worktree holds only the story directory.

## Scenarios
### S1. The page says container mode is ready
- S1.1 Given the edited page, when a reader reads the "Host or container" table, then the `Ready for editors` cell for `container` reads `Yes`, and the `Project folder` cell for `container` says the folder comes from each session's `session/new` cwd.
- S1.2 Given the edited page, when `rg -n -i 'not ready|not yet|until #566 lands|from an editor today|runs in the folder the editor started it from' guides/acp-editors.md` runs in the wiki, then every line it prints is about something other than container mode (a reader checks each hit), and none of the last three phrases matches.
- S1.3 (boundary) Given the edited page, when a reader reads the top NOTE, the `<backend>` bullet, the Troubleshooting "wrong folder" item and Known limits, then none says container mode is unready, and no Known limits bullet links #566 as an open limit.
- S1.4 (negative) Given the edited page, when a reader reads the host column of the table and the host Zed entries, then they say what they said before this change.

### S2. The page shows a container editor entry
- S2.1 Given the edited page, when a reader reads the Zed section, then it shows an `agent_servers` entry whose `command` ends in `-container` and whose `args` is `[]`.
- S2.2 Given the edited page, when `rg -n 'harnessed-acp-claude-default-container|harnessed-acp-omp-zai-acp-container|harnessed-acp-<harness>-<stack>-container'` runs on it, then each of the three strings matches at least once.
- S2.3 (boundary) Given the edited page, when a reader reads the container text, then it says one entry serves every project the editor opens.
- S2.4 (negative) Given the edited page, when a reader reads every container example, then no `args` holds a project path.

### S3. The page states the first-session wait
- S3.1 Given the edited page, when a reader reads "What happens when a session starts", then it says that in container mode the first session in a project waits for the project's pod to start, and that a slow start can run past the editor's `session/new` time limit.
- S3.2 (negative) Given the edited page, when a reader reads the container-mode text, then it states no pod start time and no `session/new` limit as a number of seconds.

### S4. Known limits lists the #584 findings
- S4.1 Given the edited page, when a reader reads Known limits, then it holds a bullet saying a version change between the launching harnessed and the built profile marks the profile stale, fixed with `harnessed build <stack> <harness>`.
- S4.2 Given the edited page, when a reader reads Known limits, then it holds a bullet saying omp needs a stack whose egress allows its model's API, naming `zai-acp` and `api.z.ai`.
- S4.3 (negative) Given the edited page, when a reader reads the container-mode text, then it names no Atlas test, lists no stale-credential problem (#597 is closed), and adds no container limit that #584 did not find.

### S5. The issue links the wiki commit
- S5.1 Given the wiki commit is pushed to the wiki's default branch, when `gh issue view 585 --comments` runs, then one comment holds the link `https://github.com/drmikecrowe/harnessed/wiki/_compare/<sha>` for that commit's full SHA, and `curl -s -o /dev/null -w '%{http_code}'` on that link prints `200`.
- S5.2 (negative) Given the commit SHA in the comment, when `git -C main/docs branch -r --contains <sha>` runs, then it lists the remote default branch.

## Must NOT
- Change the host-mode instructions: the host table column, the host Zed entries, "Before you start" and the host session steps keep their meaning.
- Change any wiki file but `guides/acp-editors.md`. The untracked `spec-evidence/` in `main/docs` stays out of the commit.
- Push the wiki before the user says yes, or open a PR for it.
- Put a credential, an account email or a private path other than `/home/you/...` placeholders into the page.
- Change any file in this repository outside `spec-evidence/2026-10-23-GH-585/`.

## Touches
- `main/docs/guides/acp-editors.md` (wiki repository): the top NOTE, the `<backend>` bullet, the "Host or container" table and the sentence after it, a container entry in the Zed section, a container step in "What happens when a session starts", the Troubleshooting "wrong folder" item, and Known limits.
- GH-585: one comment that links the wiki commit.

## Documentation
- `main/docs/guides/acp-editors.md` is the deliverable itself.

## Known limits
- Zed's real `session/new` time limit is not checked; the page gives no number, by the author's choice.
- Container mode was checked in Zed and headless only (#584). The page does not claim Atlas works in container mode.
- The page's rendering on GitHub is checked only by reading the pushed page, not by a tool.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| doc check | S1.1-S1.4, S2.1-S2.4, S3.1, S3.2, S4.1-S4.3 | each `rg` in a scenario gives the stated result; each read check holds |
| wiki diff | Must NOT: one file changed, host text kept | `git -C main/docs diff --stat` lists only `guides/acp-editors.md`; full diff read before push |
| secrets | Must NOT: no credential in the page | `gitleaks detect --no-git --source main/docs/guides/acp-editors.md` reports 0 leaks |
| issue link | S5.1, S5.2 | one GH-585 comment holds the SHA; `branch -r --contains` lists the default branch |
| tests, coverage, types, lint, shellcheck | nothing: no source, test or shell file changes | skipped; the change is wiki Markdown plus story artifacts |
