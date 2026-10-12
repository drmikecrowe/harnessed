# Gate 1a, spec readiness

verdict: not-ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 81515/675
record: work/spec-record.json
graded: 2026-10-12T14:29:41.258Z

## Reasons

- finding 1: PR-REFERENT: Define what Revision 3 is, or delete the reference and state the reason inline (the story's AC-5 now names only protocolVersion and agentCapabilities).
- finding 2: PR-REFERENT: Define Revision 2 in the plan, or remove the reference.
- finding 3: PR-SCOPE: Name the acceptance criterion S4.5 (a child that exits, error for its sessions, relaunch) serves, or drop the relaunch behaviour.
- finding 4: PR-SCOPE: Say which acceptance criterion S9.7 serves, or drop the scenario and keep the single Known limits error.

## Record

```json
{"input":"Plan","gaps":["prompt 1: AC-6 says that with the project's pod running the request goes to the pod and the agent's own reply comes back, but S10.1 returns an empty list when this process has no child, even when the pod is up from another process; Decide 4 narrows the story's wording.","prompt 2: S4.5 (relaunch after a child exits), S9.7 (requests that name no session), S8.3 (the per-child stderr line) and the S5 drift line are SPEC choices no acceptance criterion names; Known limits admits this for S4.5, S5, S9.7 and S10.3.","prompt 3: S8.1 still leaves open how the agent is asked to report its working directory (the prompt text is given, but the story's ambiguity stands), and S9.7 with exactly one child routes a sessionless request to it, which an implementer could build as routing to the wrong project's child."],"deferred":[],"findings":[{"rule":"PR-REFERENT","quote":"`authMethods` depends on the agent's login state (Revision 3), so the story drops it from AC-5.","smallest_fix":"Define what Revision 3 is, or delete the reference and state the reason inline (the story's AC-5 now names only protocolVersion and agentCapabilities)."},{"rule":"PR-REFERENT","quote":"no agent runs for that project, and sessions in other projects go on working (Revision 2).","smallest_fix":"Define Revision 2 in the plan, or remove the reference."},{"rule":"PR-SCOPE","quote":"a later `session/new` for P launches a new child.","smallest_fix":"Name the acceptance criterion S4.5 (a child that exits, error for its sessions, relaunch) serves, or drop the relaunch behaviour."},{"rule":"PR-SCOPE","quote":"then the reply is a JSON-RPC error with code -32600 and the message `cannot route <method>: it names no session`.","smallest_fix":"Say which acceptance criterion S9.7 serves, or drop the scenario and keep the single Known limits error."}]}
```
