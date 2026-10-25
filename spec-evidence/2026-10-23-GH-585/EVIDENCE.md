## Evidence Report — GH-585: container mode in the acp-editors wiki page (Tier 1)

## Summary
Delivered: the wiki page `guides/acp-editors.md` now documents container mode next to host mode, in wiki commit `a1fc378`, pushed to the wiki's `master` and linked on GH-585. The page had said container mode from an editor was not ready, but #566 shipped and the #584 live check passed in Zed and headless.

How each criterion was proven, all by reading the pushed page or by recorded command output:
- AC-1: the table marks container ready and takes the folder from `session/new`; an `rg` for unready wording prints no line; host text is unchanged (S1.1-S1.4).
- AC-2: a Zed container entry with empty `args` and both example launchers is on the page (S2.1-S2.4).
- AC-3: the page states the first-session wait for the pod and the `session/new` time limit, with no seconds figure (S3.1, S3.2).
- AC-4: Known limits holds the stale-profile and omp-egress findings; container text names no Atlas test and no #597 problem (S4.1-S4.3).
- AC-5: one GH-585 comment links the commit; the link returns 200 and the commit is on `origin/master` (S5.1, S5.2).

Not proven: nothing. The page's rendering on GitHub was not checked by a tool (Review risks).

## Agent decisions
### A1. Put the container editor entry in the existing Zed section
- Other option: a new "Container mode" section that holds the entry, the first-session wait and the limits.
- Why: the page is organized by editor and by session step, so each container fact goes where a reader already looks; a separate section would repeat the Zed setup.
- Command: plan

### Review risks
- The adversary could not open `src/harnessed/acpproxy.py` (a Gortex hook blocked its Read), so its two hunches on the page's proxy claims were closed by the doer, not by the reviewer: `initialize` is answered at once (`src/harnessed/acpproxy.py:222-225`); `session/new` waits in `child.pending` until the agent launches and its handshake completes (`src/harnessed/acpproxy.py:333-360`); a path argument wins over the session cwd (`src/harnessed/acpproxy.py:235-236`, `src/harnessed/acpproxy.py:274-278`).
- Rendering on GitHub was checked only by the `_compare` link returning 200, not by viewing the rendered page.

### Not reached by review
- Round 1: calls 3/10; hunts not reached: 1 (gate comparison: the repo range is empty and the wiki is exempt from CI), 2 (call sites: no code changed), 4, 5, 6, 9 (the claims about acpproxy.py and the launcher names harnessed-acp-<harness>-<stack>-container were not verified), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/GH-585-acp-docs/src/harnessed/acpproxy.py (blocked by hook), /home/mcrowe/Programming/Personal/harnessed/GH-585-acp-docs/spec-evidence/2026-10-23-GH-585/work/log.txt, /home/mcrowe/Programming/Personal/harnessed/GH-585-acp-docs/spec-evidence/2026-10-23-GH-585/work/show.txt, /home/mcrowe/Programming/Personal/harnessed/main/docs/guides/acp-editors.md (HEAD file, line numbers above are estimates from the diff hunks)

## Orientation
- Verdict: PASSED
- Delivered: the acp-editors wiki page covers container mode (wiki commit `a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d`), linked on GH-585.
- Proven: 17/17 scenarios mapped and passing
- Not proven: nothing

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-23-GH-585/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit `6de2298`, `GH-585: spec approved`)
- Intent review: S1.2 widened to any "not ready"/"not yet" line with a read of each hit; S5.1 names the `wiki/_compare/<sha>` URL form and a 200 check (decisions.md, Revision 1)
- Source state: commit 6de22983165402564ba85db1f5a5ccd1deb9ebaa, dirty only by untracked story artifacts (`baseline-stamp.json`, `findings-code.md`); no source file differs. The deliverable is wiki commit `a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d`, which the review read.
- Baseline: baseline-stamp.json at commit 6de22983165402564ba85db1f5a5ccd1deb9ebaa, green

<details>
<summary>Stamp: green, 6/6 layers</summary>

```json
{
  "result": "green",
  "mode": "full",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 286.862, "coverage": 349.062, "types": 13.515, "lint": 0.113, "shellcheck": 1.385, "secrets": 2.461},
  "layers": {
    "tests": {"baseline": "reused", "selection": "off"},
    "coverage": {"baseline": "reused", "selection": "off"},
    "types": {"baseline": "reused", "selection": "off"},
    "lint": {"baseline": "reused", "selection": "off"},
    "shellcheck": {"baseline": "reused", "selection": "off"},
    "secrets": {"baseline": "reused", "selection": "off"}
  },
  "failed": null,
  "exit_code": 0,
  "commit": "6de22983165402564ba85db1f5a5ccd1deb9ebaa",
  "dirty": true,
  "written": "2026-10-23T18:46:02.355Z"
}
```

</details>

### Spec → Test mapping
Every row passes. `P` is `/home/mcrowe/Programming/Personal/harnessed/main/docs/guides/acp-editors.md` at wiki commit `a1fc378`. Check outputs are in the story directory: `doc-checks-red.txt` (before the edit), `doc-checks-green.txt` (after), `doc-checks-s5.txt` (push, link, gitleaks).

<details>
<summary>17/17 scenarios mapped and passing; 15/15 criterion clauses mapped and passing</summary>

| Scenario | Test | Status |
|---|---|---|
| S1.1 | `P:27` container Project folder reads "Taken from each session's `session/new` cwd"; `P:29` reads `\| Ready for editors \| Yes \| Yes \|` | pass |
| S1.2 | `doc-checks-green.txt` "## S1.2": the `rg` prints no line, exit 1 (red run printed lines 4, 18, 29, 31, 127 in `doc-checks-red.txt`) | pass |
| S1.3 (boundary) | NOTE `P:4` "Container mode works in Zed."; `<backend>` bullet `P:18`; Troubleshooting `P:150`; Known limits `P:155-158` holds no #566 bullet (`doc-checks-green.txt` "## S4.3" lists no `#566`) | pass |
| S1.4 (negative) | host column `P:26-29` and host Zed entries `P:62-79` match the pre-edit text; wiki diff in `work/diff.txt` changes no host cell or host entry | pass |
| S2.1 | `P:90` and `P:96` `command` ends in `-container`; `P:91`, `P:97` `"args": []` | pass |
| S2.2 | `doc-checks-green.txt` "## S2.2": counts 2, 2, 1 for the three strings | pass |
| S2.3 (boundary) | `P:83` "One entry serves every project you open" | pass |
| S2.4 (negative) | `doc-checks-green.txt` "## S2.1/S2.4 args": every `args` is `[]` | pass |
| S3.1 | `P:140` "the first session in a project also waits for that project's pod to start ... the editor's time limit for `session/new` can run out" | pass |
| S3.2 (negative) | `doc-checks-green.txt` "## S3.2 seconds": no seconds figure, exit 1 | pass |
| S4.1 | `P:155` stale-profile bullet with `harnessed build <stack> <harness>` | pass |
| S4.2 | `P:156` omp egress bullet naming `zai-acp` and `api.z.ai` | pass |
| S4.3 (negative) | `doc-checks-green.txt` "## S4.3": Atlas appears only in the host-mode Atlas section `P:104-125` and the host clause of `P:4`; no `#597`; Known limits adds only S4.1 and S4.2 | pass |
| S5.1 | `doc-checks-s5.txt` "## S5.1": one comment holds `https://github.com/drmikecrowe/harnessed/wiki/_compare/a1fc3788a4c7c1aa5fdc5483ee6bff2a82c28c0d`; HTTP 200 | pass |
| S5.2 (negative) | `doc-checks-s5.txt` "## S5.2": `origin/master` contains the commit | pass |
| AC-1 condition | S1.1, S1.2 | pass |
| AC-1 boundary | S1.3 | pass |
| AC-1 negative | S1.2, S1.3 | pass |
| AC-2 condition | S2.1, S2.2 | pass |
| AC-2 boundary | S2.3 | pass |
| AC-2 negative | S2.4 | pass |
| AC-3 condition | S3.1 | pass |
| AC-3 boundary | S3.2 | pass |
| AC-3 negative | S3.1, S3.2 | pass |
| AC-4 condition | S4.1, S4.2 | pass |
| AC-4 boundary | S4.3 | pass |
| AC-4 negative | S4.3 | pass |
| AC-5 condition | S5.1 | pass |
| AC-5 boundary | `doc-checks-s5.txt` "## S5.1": exactly one link, to the commit that changes `guides/acp-editors.md` ("## wiki commit files") | pass |
| AC-5 negative | S5.2 | pass |

</details>

### Gauntlet (final fresh run)
All layers PASSED. No source, test or shell file changed, so each layer ran over an unchanged tree.

<details>
<summary>6/6 layers PASSED</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4552 passed, 80 skipped | reused | off | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.28% (≥ 80%) | reused | off | work/coverage.log |
| types | pyright (manifest command) | PASSED — 0 errors, 0 warnings | reused | off | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | reused | off | work/lint.log |
| shellcheck | shellcheck over tracked `*.sh` (manifest command) | PASSED — 0 findings | reused | off | work/shellcheck.log |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — no leaks found | reused | off | work/secrets.log |
| wiki secrets (contract) | `gitleaks detect --no-git --source main/docs/guides/acp-editors.md` | PASSED — no leaks found | n-a | n-a | doc-checks-s5.txt |
| wiki diff (contract) | `git -C main/docs show --stat a1fc378` | PASSED — 1 file, `guides/acp-editors.md` | n-a | n-a | doc-checks-s5.txt |

</details>

### Layers not run as specified
- N-A: none
- UNAVAILABLE: Markdown link checker; nothing in the project declares one, so links were checked by reading.
- SUBSTITUTED: none

### Defect classes closed
- Generator: page text that predates #566 and says container mode is unready or uses the editor's folder.
- Enumerated by: `rg -n -i 'not ready|not yet|until #566 lands|from an editor today|runs in the folder the editor started it from' guides/acp-editors.md`
- Sites: 5 — `P:4` fixed; `P:18` fixed; `P:29` fixed; `P:31` fixed; old line 127 (now `P:150`) fixed. Also `P:27` (no keyword hit) fixed, and the #566 Known limits bullet replaced.

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 107418/1835 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 66219/704 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 122217/1673 |

### Process notes
- The deliverable lives in the wiki repository, so this repository's adversary range (`6de2298...HEAD`) is empty; `work/diff.txt`, `work/log.txt` and `work/show.txt` add the wiki range `c42f7e6...a1fc378`.
- Two claims in the first draft (one pod per project; host launchers honor a path in `args`) were not verified and were narrowed before the commit to what `src/harnessed/acpproxy.py:1-10` states.
- The wiki push had the user's explicit yes in this session.
