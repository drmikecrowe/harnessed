# Gate 2, evidence

verdict: ready
story: GH-582
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 64292/219
record: work/evidence-record.json
graded: 2026-10-12T13:22:09.310Z

## Reasons

none

## Record

```json
{"gaps":["No criterion names an @SC tag, so each was graded from the report's Spec to Test mapping rows. I read no cited source files, because the mapping cites test ids and not path:line.","The story says AC-1 to AC-7 hold on a scheduled run on GitHub's runner. The report says that run has not happened. The signed commit, the dispatched pytest check satisfying the ruleset, and the 0.3.0 Release PR are unobserved. The proof is stub-based tests only.","AC-7 boundary (0.3.0 from 0.2.1) is proven only by a config assertion (S7.3), not by an observed Release PR.","Adversary hunches, recorded but not fixed: no concurrency group (could affect AC-2 and AC-3 under overlapping runs), and a failed GraphQL commit can leave an empty branch."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S1.1 (PS::TestNothingEligible::test_s1_1_no_change_exits_clean_and_calls_nothing), S1.2 (CD window-edge test, release exactly at the edge is offered), S1.3 (no branch reaches origin)"},{"ac":"AC-2","status":"proven","evidence":"Mapping rows S2.1 (ref, then commit, then PR in order), S2.2, S2.3 (nothing pushed with git, so no unsigned commit), S2.4 (two files in one commit); no-second-PR side covered by S3.2 and S3.4"},{"ac":"AC-3","status":"proven","evidence":"Mapping rows S3.1 (rerun stacks on the branch head), S3.2 (nothing new touches nothing), S3.3 (earlier commit not rewritten), S3.4, S3.5"},{"ac":"AC-4","status":"proven","evidence":"Mapping rows S4.1 (dispatch list equals [test.yml], the mise.toml-only boundary), S4.2 (live trigger file also dispatches live.yml), S4.3 (script's live list equals live.yml), S4.5 (a failed dispatch fails the run)"},{"ac":"AC-5","status":"proven","evidence":"Mapping rows S5.1 (no-rebuild never reaches the runtime), S5.3 (a prompt with no input fails instead of waiting), S5.4 (exact args update --yes --no-rebuild, stdin held open), S5.2 (rebuild still offered without the flag)"},{"ac":"AC-6","status":"proven","evidence":"Mapping rows S6.1 (harness major lands with a minor in one run), S6.2 (no pin left behind), S6.3 (args are exactly update --yes --no-rebuild, so no hold-back flag), S6.4"},{"ac":"AC-7","status":"proven","evidence":"Mapping rows S7.1 (commit headline and PR title), S7.2 (title passes the pr-title.yml pattern), S7.3 (feat is a minor bump before 1.0, bump-patch-for-minor-pre-major absent). The Release PR itself is not observed."}]}
```
