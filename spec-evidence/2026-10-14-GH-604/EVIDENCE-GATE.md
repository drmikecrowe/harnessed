# Gate 2, evidence

verdict: ready
story: GH-604
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 65832/210
record: work/evidence-record.json
graded: 2026-10-14T12:59:14.043Z

## Reasons

none

## Record

```json
{"gaps":["The mapping cites test ids only, with no path:line, and I did not open the test files. I graded the mapping rows, not the test bodies.","The story's SR-DEFER on 'under pnpm's global dir' is met by the report's choice of `pnpm bin -g` (Decide 1 B). The report records that a mise layout outside MISE_DATA_DIR/{installs,shims} gets the pnpm command. The story does not cover that layout.","The report says 'Adversarial review for commits 3f069ca, eb998b5, 89ccd04' was not run. Those commits change only tests and story files."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows 'AC-1 condition', 'AC-1 boundary' and 'AC-1 negative'. Tests: B::TestS1MiseGetsTheMiseCommand::test_s1_1 (installs dir) and test_s1_3 (shim); H::TestTheAdapterCommandFollowsTheOwner::test_s1_2 and test_s1_3 (host-acp warning). The report says test_s1_1 and test_s1_2 assert `npm i -g` is absent."},{"ac":"AC-2","status":"proven","evidence":"Mapping rows 'AC-2 condition', 'AC-2 boundary' and 'AC-2 negative'. Tests: B::TestS2NoAdapterGetsPnpm::test_s2_1 (PATH is an empty dir); H::TestTheAdapterAtLaunch::test_s6_8 (refusal on stderr); test_s2_3 sweeps (10, 5 and 5 cases) with a whole-word npm/npx check across build and host-acp."},{"ac":"AC-3","status":"proven","evidence":"Mapping rows 'AC-3 condition', 'AC-3 boundary' and 'AC-3 negative'. Tests: B::TestS3PnpmGetsPnpm::test_s3_1 and H::...::test_s3_1 (assert `mise` and `npm i -g` absent); test_s3_2 and test_s3_3 cover the outside-pnpm-dir classification as `other`; test_s2_3 pnpm cases check for no whole-word npm."},{"ac":"AC-4","status":"proven","evidence":"Mapping rows 'AC-4 condition', 'AC-4 boundary' and 'AC-4 negative'. Tests: B::TestS5TheVersionIsCheckedAgain::test_s5_1[none],[pnpm],[other] and test_s5_3 (mise, no re-check) for no second offer, with the stub reporting the pin; test_s5_2 names the shadowing copy's path and version after the install; test_s5_4 covers a typed command."}]}
```
