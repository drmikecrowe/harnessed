# Gate 2a, evidence against the plan

verdict: ready
story: GH-585
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 121649/2372
record: work/evidence-plan-record.json
graded: 2026-10-23T18:48:20.179Z

## Reasons

none

## Record

```json
{"gaps":["S1.4 rests on the report's claim that the wiki diff (work/diff.txt) changes no host cell or entry. I did not open that file. The current host table cells (P:26-29) and host Zed entries (P:62-79) are consistent with the claim.","S5.1 and S5.2 rest on the recorded output in doc-checks-s5.txt. I cannot run gh, curl or git."],"items":[{"scenario":"S1.1","status":"proven","evidence":"P:27 'Taken from each session's `session/new` cwd, so one entry works everywhere'; P:29 '| Ready for editors | Yes | Yes |'"},{"scenario":"S1.2","status":"proven","evidence":"doc-checks-green.txt '## S1.2' exit 1 (the rg prints no line). I also read the page: no 'not ready', 'not yet', 'until #566 lands' or 'from an editor today'."},{"scenario":"S1.3","status":"proven","evidence":"P:4 'Container mode works in Zed.'; P:18 backend bullet has no unready wording; P:150 wrong-folder item says a -container launcher takes the folder from session/new; Known limits P:155-158 has no #566 bullet"},{"scenario":"S1.4","status":"proven","evidence":"P:26-29 host column and P:62-79 host Zed entries read as host instructions; diff stat shows 31 insertions and 7 deletions in one file; mapping row cites work/diff.txt (not opened)"},{"scenario":"S2.1","status":"proven","evidence":"P:90 command ends in 'harnessed-acp-claude-default-container', P:96 ends in 'harnessed-acp-omp-zai-acp-container'; P:91 and P:97 '\"args\": []'"},{"scenario":"S2.2","status":"proven","evidence":"doc-checks-green.txt '## S2.2' counts 2, 2, 1; P:83, P:90 and P:96 hold the strings"},{"scenario":"S2.3","status":"proven","evidence":"P:83 'One entry serves every project you open, and each project gets its own agent.'"},{"scenario":"S2.4","status":"proven","evidence":"P:91 and P:97 container args are []; P:83 'do not put a project path there'; the page's other args lines are all empty (doc-checks-green.txt '## S2.1/S2.4 args')"},{"scenario":"S3.1","status":"proven","evidence":"P:140 'the first session in a project also waits for that project's pod to start ... the editor's time limit for `session/new` can run out before the agent is ready'"},{"scenario":"S3.2","status":"proven","evidence":"P:140 and the container text hold no seconds figure; doc-checks-green.txt '## S3.2 seconds' exit 1"},{"scenario":"S4.1","status":"proven","evidence":"P:155 'A version change makes the profile stale ... Run `harnessed build <stack> <harness>` with the harnessed that launches it.'"},{"scenario":"S4.2","status":"proven","evidence":"P:156 'omp needs egress to its model's API ... needs `api.z.ai`, which the `zai-acp` stack allows and `default` does not.'"},{"scenario":"S4.3","status":"proven","evidence":"Atlas appears only in the host sections (P:4 host clause, P:104-125); no #597 on the page; Known limits holds only S4.1 and S4.2 for container, plus the host and editor-setup bullets"},{"scenario":"S5.1","status":"proven","evidence":"doc-checks-s5.txt '## S5.1 comment' holds https://github.com/drmikecrowe/harnessed/wiki/_compare/a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d and 'HTTP: 200'"},{"scenario":"S5.2","status":"proven","evidence":"doc-checks-s5.txt '## S5.2' lists 'origin/master' (and origin/HEAD -> origin/master) as containing a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d"}],"decisions":[{"id":"A1","status":"complete"}]}
```
