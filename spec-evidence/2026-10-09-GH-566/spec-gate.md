# Gate 1a, spec readiness

verdict: not-ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 74723/677
record: work/spec-record.json
graded: 2026-10-12T14:33:32.409Z

## Reasons

- finding 1: PR-SCOPE: Name the acceptance criterion S8.3 serves (for example AC-4, which needs proof of which process served each project), or drop the per-child stderr line.

## Record

```json
{"input":"Plan","gaps":["prompt 1: AC-6 says that with the project's pod running the request goes to the pod, but S10.1 returns an empty list when this process has no child even when the pod is up from another process. Decide 4 narrows the story's wording.","prompt 2: S8.3 (the per-child stderr line), S5 (the drift line) and S10.3 (`session/list` with no `cwd`) are SPEC choices that Known limits says the story did not ask for.","prompt 3: S9.7 with exactly one child routes a sessionless request to that child. An implementer could read that as routing to the wrong project's child. S8.1 also leaves open how the agent reports its working directory, though the prompt text is given."],"deferred":[],"findings":[{"rule":"PR-SCOPE","quote":"These rules are this SPEC's choices, not the story's: S5 (the drift line), S8.3 (the per-child stderr line) and S10.3 (`session/list` with no `cwd`).","smallest_fix":"Name the acceptance criterion S8.3 serves (for example AC-4, which needs proof of which process served each project), or drop the per-child stderr line."}]}
```
