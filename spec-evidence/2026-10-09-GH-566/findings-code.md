# Adversary findings, GH-566 Revision 4 build

Range b6e331e...HEAD. Each round is what the adversary printed, unchanged.

## Round 1 (HEAD 2b28533)

```json
{
  "clean_claims": [
    "tools/gauntlet-layers.json lint and types commands match .github/workflows/lint.yml argument for argument (ruff check src tests tools; pyright --pythonpath <uv python>). Only lint.yml was read: test.yml, live.yml and pin-check.yml were not, so the tests and coverage rows are unchecked against their gates.",
    "src/harnessed/acpproxy.py JSON-RPC framing, non-dict, bad-JSON and odd-params handling in handle/requested_project/route: I found no input that kills the reader thread.",
    "Proxy-wide renumbering of agent-to-client request ids (from_agent/client_reply): I found no id collision. bool is excluded by _key, and id 0 is handled correctly.",
    "tools/acp-smoke.py --no-path and drift watcher: no defect found."
  ],
  "finding": [
    {
      "file": "src/harnessed/acpproxy.py",
      "line": 339,
      "severity": "blocking",
      "rule": "none",
      "defect": "run_child catches only typer.Exit from launch(). Any other exception, and the ValueError raised when the launch returns a process without pipes, kills the thread. The child stays in state _LAUNCHING with its pending lines unanswered, and the failed child is never removed from self.children.",
      "trigger": "launch() raises something other than typer.Exit, for example OSError from subprocess.Popen in _acp_relaunch (EMFILE, ENOMEM, or a vanished sys.executable). _resolve_start_dir could also raise something that is not a typer.Exit.",
      "consequence": "The session/new request never gets a response, so the editor hangs on it. Later session requests for that project queue behind the dead _LAUNCHING child and also never answer. The failure shows only as an unhandled thread traceback on stderr."
    },
    {
      "file": "src/harnessed/acpproxy.py",
      "line": 440,
      "severity": "advisory",
      "rule": "none",
      "defect": "A launch failure (the fail() path) never appends to self.codes, so finish() returns 0 when every launch failed.",
      "trigger": "The client sends session/new for a project whose launch exits or whose child dies before initialize, then closes stdin.",
      "consequence": "container-acp exits 0 after a total failure. The docstring says nonzero when any agent failed, and a caller that relies on the exit status cannot detect the failure."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/acpproxy.py",
      "line": 244,
      "rule": "none",
      "defect": "The client-supplied session cwd is accepted as the project to mount into a pod. Any existing absolute directory passes (/, ~, /etc), with no check that it lies under an allowed root.",
      "consequence": "A malicious or buggy ACP client can have the whole host home directory mounted into the agent pod. This widens the trust boundary from 'the path on the command line' to 'whatever the client sends'."
    },
    {
      "file": "src/harnessed/acpproxy.py",
      "line": 269,
      "rule": "none",
      "defect": "self.opening[id] is set before the launch, and is cleared only when that agent's response arrives. On a fail() path, or when an agent dies without replying, the entry leaks.",
      "consequence": "A small leak per failed open. It is harmless unless the client reuses ids."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 489,
      "rule": "none",
      "defect": "The relaunch child inherits the parent's whole environment plus HARNESSED_ACP_DIRECT and HARNESSED_ACP_PROJECT, and I did not check whether those reach the pod's env.",
      "consequence": "If the relaunch env is forwarded into the container, the host project path is exposed there. Not verified."
    }
  ],
  "coverage": {
    "calls_used": "4/10",
    "hunts_not_reached": [
      "2 (callers of acp_stdout and set_acp_mode: the Grep was blocked by a hook, so I could not confirm that acp_stdout() is valid in the parent proxy path before set_acp_mode runs)",
      "6",
      "8",
      "9",
      "10"
    ],
    "sites_not_opened": [
      "src/harnessed/launcher.py:4362-4380 (the code in container_run before the proxy hand-off, and set_acp_mode/acp_stdout definitions)",
      "src/harnessed/launcher.py _resolve_start_dir",
      ".github/workflows/test.yml (coverage and tests gate arguments)",
      "SPEC.md and any EVIDENCE report"
    ]
  }
}
```

## Round 2 (HEAD d2afdd9)

```json
{"clean_claims":["src/harnessed/launcher.py:4351-4377 hand-off: set_acp_mode(acp_mode) at 4351 runs before acp_stdout() at 4373, so the order is right. In the direct child, `path` is set from env after the proxy branch.","acpproxy.py lock order: self.lock is never held while taking child.lock or out_lock, and child.lock is held while taking out_lock (refuse) or self.lock only in fail/run_child, which does not nest them. I found no cycle.","run_child's `except Exception` now covers non-typer.Exit launch failures. The round-1 defect is closed in that function."],"finding":[{"file":"src/harnessed/acpproxy.py","line":351,"severity":"blocking","rule":"none","defect":"finish() closes the stdin of every started child, including one still launching or handshaking. The `closing` comment promises that a starting agent is closed by its own thread once ready, but run_child assigns child.stdin at line 351, before the handshake. From that point on child.close() really closes the pipe.","trigger":"A client writes initialize and session/new, then closes stdin without waiting for the reply (`printf '...' | harnessed container-acp omp`, or an editor that exits quickly). The main loop ends and finish() runs while the launch thread is still launching or in the handshake. If Popen has returned, child.close() closes the agent's stdin. handshake's replay of initialize then fails, or the agent sees EOF before the queued session/new is written. In both cases handshake returns False or the write at line 361 fails.","consequence":"The queued session/new is refused with 'launch failed (exit N)' or 'agent exited', or the agent exits having never received it. Every test uses _serve, which waits for each session reply before closing stdin, so none exercises this order. Fix: close only children whose state is _READY, and let run_child close the rest once it is ready (the `closing` path)."}],"hunch":[{"file":"src/harnessed/acpproxy.py","line":404,"rule":"none","defect":"fail() removes the child from `children` but leaves its `sessions` and `opening` entries. `opening` only drops an entry when a reply arrives, so a failed open leaves an id in the table. Later routes to a stale session id get 'agent exited' instead of 'unknown session'.","consequence":"A minor table leak and a misleading error. I could not show a worse outcome."},{"file":".github/workflows/test.yml","line":39,"rule":"none","defect":"The gate runs a bare `uv run --extra dev pytest`, with no coverage arguments in the lines I grepped. I did not compare it with tools/gauntlet-layers.json, so a scoping mismatch between the layer commands and the gate is unchecked.","consequence":"If the layers use narrower arguments, the gauntlet could pass while the gate fails."}],"coverage":{"calls_used":"3/10","hunts_not_reached":["1 (full comparison of the layer manifest with test.yml and lint.yml)","2 (callers of container_run and the other call sites of serve)","6","9 (whether the Popen relaunch of sys.argv[0] works under pipx and uvx)","10"],"sites_not_opened":["/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/src/harnessed/console.py:68","/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/tools/acp-smoke.py","/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/tools/gauntlet-layers.json","/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/spec-evidence/2026-10-09-GH-566/work/diff.txt (lines 1059-1502: the rest of the tests and the smoke tool)"]}}
```
