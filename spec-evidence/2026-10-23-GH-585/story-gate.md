# Gate 1, story readiness

verdict: ready
story: GH-585
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 107075/2177
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/gh585-gate1/story-record.json
graded: 2026-10-23T12:32:16.696Z

## Reasons

none

## Record

```json
{"input":"Story","type":"feature","missing":[],"gaps":["prompt 2: AC-1 says the Troubleshooting line and the Known limits #566 bullet 'change to match' but does not say what they should become, so a reader has to guess the new wording.","prompt 3: A page could satisfy AC-1 to AC-5 and still leave host-mode text that contradicts container mode, or leave the page's other sections untouched. No criterion covers this.","prompt 1: The Story gives no check that the wiki page renders correctly or that its links work."],"fields":[{"name":"who","state":"present"},{"name":"what","state":"present"},{"name":"done-looks-like","state":"present"},{"name":"example","state":"present"}],"readings":[],"findings":[],"deferred":[],"items":[{"ac":"AC-1","status":"proven","evidence":"Open the wiki page's 'Host or container' section. The check fails if the `Ready for editors` row for `container` is not Yes, if the container `Project folder` cell does not say the folder comes from each session's `session/new` cwd, or if 'until #566 lands' is still present. Then search the page for 'not ready yet', 'Use `host` from an editor today', and the #566 bullet. The check fails if any line still says container mode is not ready."},{"ac":"AC-2","status":"proven","evidence":"Open the page and find the container editor entry. The check fails if the command is not `~/.local/bin/harnessed-acp-<harness>-<stack>-container`, if the args hold a project path, or if either `harnessed-acp-claude-default-container` or `harnessed-acp-omp-zai-acp-container` is missing."},{"ac":"AC-3","status":"proven","evidence":"Read the page for the first-session wait and the `session/new` time-limit warning. The check fails if either statement is missing, or if the container text holds a number of seconds for pod start or for the limit."},{"ac":"AC-4","status":"proven","evidence":"Open Known limits. The check fails if it lacks the stale-profile limit (fix `harnessed build <stack> <harness>`) or the omp egress limit (`zai-acp`, `api.z.ai`). It also fails if the container text mentions Atlas, lists the stale-credential problem, or lists any limit beyond these two."},{"ac":"AC-5","status":"proven","evidence":"Open GH-585 and check its comments. The check fails if there is no comment with exactly one link to a wiki commit, or if that commit is absent from the wiki repo's default branch (compare with `git -C docs ls-remote` or open the link)."}]}
```

## Story

````
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
````