---
id: GH-585
type: feature
source:
  tracker: github
  external_id: GH-585
  url: https://github.com/drmikecrowe/harnessed/issues/585
  version: 2026-10-23T11:21:37Z
---
# Docs: container mode in the acp-editors wiki page
## Description
Who: users who run a harnessed stack as the coding agent in an ACP editor, such as Zed.
What: extend the wiki page `guides/acp-editors.md` (live at https://github.com/drmikecrowe/harnessed/wiki/acp-editors) so it documents container mode next to host mode. #566 has landed, and the container live check #584 passed in Zed and headless.
Done looks like: the page covers host and container mode, and a comment on this issue links the wiki commit, as AC-1 to AC-5 state.
Example: a Zed custom agent with the command `harnessed-acp-claude-default-container` and empty args opens a project, and the session runs in that project inside the pod.
Drafted by the assistant from the author's text; approved by the author 2026-10-23.
## Acceptance criteria
- AC-1: A reader opens the "Host or container" section: the `Ready for editors` row says Yes for `container`, the `Project folder` cell for container says the folder comes from each session's `session/new` cwd, and the sentence "until #566 lands" is gone; boundary: the top NOTE ("Container mode from an editor is not ready yet"), the `<backend>` bullet ("Use `host` from an editor today"), the Troubleshooting line about `-container` launchers, and the #566 bullet in Known limits all change to match; negative: any line that still tells the reader container mode is not ready fails this criterion.
- AC-2: The page shows a container-mode editor entry: the command `~/.local/bin/harnessed-acp-<harness>-<stack>-container` with no project path in the args, and the examples `harnessed-acp-claude-default-container` and `harnessed-acp-omp-zai-acp-container`; boundary: one entry serves every project the editor opens; negative: an example that puts a project path in the args fails.
- AC-3: The page tells the reader that the first session in a project waits for the pod to start, and that a slow start can go over the editor's `session/new` time limit; boundary: the page gives no measured times or limits in seconds; negative: a page that leaves out the wait, or states a pod start time or a limit as a number, fails.
- AC-4: Known limits lists the #584 findings that still apply: (1) a version change between the harnessed that launches and the built profile marks the profile stale, fixed with `harnessed build <stack> <harness>`; (2) omp needs a stack whose egress allows its model's API, for example `zai-acp` for `api.z.ai`; boundary: the container-mode text does not mention Atlas, and the stale-credential problem is not listed because #597 is closed; negative: a limit #584 did not find, or one a closed issue fixed, fails.
- AC-5: A comment on GH-585 links the wiki commit after it is pushed to the wiki's default branch; boundary: one link to the commit that holds the page change; negative: a link to a commit that is not pushed fails.
## Constraints
- `docs/` is the separate wiki repository: edit it in `main/docs/`, read the full diff, and push only after the user says yes. There is no PR (AGENTS.md, "Exemption: `docs/`").
