# Gate 2, evidence

verdict: ready
story: GH-585
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 116365/2000
record: work/evidence-record.json
graded: 2026-10-23T18:48:19.885Z

## Reasons

none

## Record

```json
{"gaps":["AC-5 rests on recorded output in doc-checks-s5.txt (comment text, HTTP 200, origin/master contains the commit). I did not check the GitHub comment itself.","AC-4 says a limit #584 did not find fails. Known limits also holds two other bullets: host-mode no network boundary (P:157) and editor setup is manual (P:158). The report says the diff added only the two #584 bullets, and both extra bullets are host or editor scope, so I did not count them against AC-4.","The page's rendering on GitHub was not checked, per the report."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1-S1.4, P read. P:29 '| Ready for editors | Yes | Yes |'. P:27 container cell 'Taken from each session's `session/new` cwd'. No 'until #566 lands' on the page. P:4 NOTE now reads 'Container mode works in Zed.'. P:18 `<backend>` bullet reads '`host` or `container`', with no 'use host today'. P:150 Troubleshooting line is rewritten. Known limits P:155-158 has no #566 bullet. The rg for unready wording printed no line (doc-checks-green.txt S1.2, exit 1)."},{"ac":"AC-2","status":"proven","evidence":"S2.1-S2.4, P read. P:83 gives the command form `~/.local/bin/harnessed-acp-<harness>-<stack>-container` and says 'Leave `args` empty: do not put a project path there. One entry serves every project you open'. The P:85-102 JSON uses `harnessed-acp-claude-default-container` and `harnessed-acp-omp-zai-acp-container`, both with `\"args\": []`. doc-checks-green.txt shows every args is []."},{"ac":"AC-3","status":"proven","evidence":"S3.1, S3.2, P:140 read. 'the first session in a project also waits for that project's pod to start ... the editor's time limit for `session/new` can run out before the agent is ready'. No number given. The seconds check returned exit 1 (doc-checks-green.txt S3.2)."},{"ac":"AC-4","status":"proven","evidence":"S4.1-S4.3, P read. P:155 stale-profile bullet with 'Run `harnessed build <stack> <harness>`'. P:156 omp egress bullet naming `zai-acp` and `api.z.ai`. Atlas appears only in the host-mode section (P:104-125) and the host clause of the P:4 NOTE. There is no #597 and no stale-credential bullet on the page."},{"ac":"AC-5","status":"proven","evidence":"S5.1, S5.2 in doc-checks-s5.txt. One comment links https://github.com/drmikecrowe/harnessed/wiki/_compare/a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d, HTTP 200. 'origin/master' contains the commit. The commit changes only guides/acp-editors.md."}]}
```
