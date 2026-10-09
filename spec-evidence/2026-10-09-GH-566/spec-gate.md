# Gate 1a, spec readiness

verdict: not-ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 51111/395
record: work/spec-record.json
graded: 2026-10-09T23:00:12.781Z

## Reasons

- finding 1: PR-REFERENT: State in the Touches section whether '--agent-start-folder' is an existing flag in launcher.py or a new one to add.

## Record

```json
{"input": "Plan", "gaps": ["prompt 1: Story AC-4 specifies verification by the agent reporting its working directory but does not name the mechanism (tool call, log line, or prompt response); the plan's S8.1 inherits this ambiguity without resolving it.", "prompt 2: S5.1–S5.3 build a specific stderr format 'harnessed: ACP initialize drift: <harness>: <field>' that no acceptance criterion names; the story only requires that a mismatched reply fails.", "prompt 3: S3.2 uses '--agent-start-folder' as a known flag but the plan never says whether it is an existing option or one to add, so an implementer cannot tell whether to define it."], "deferred": [], "findings": [{"rule": "PR-REFERENT", "quote": "Given path argument A and `--agent-start-folder sub`, when the session starts, then the child receives `cwd` = the container path of `A/sub`.", "smallest_fix": "State in the Touches section whether '--agent-start-folder' is an existing flag in launcher.py or a new one to add."}]}
```
