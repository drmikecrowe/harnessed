# Roadmap

Where harnessed is going. This is the epic-level view — one line per theme, not a task list.
Every item links to the issue that carries the detail. Nothing here is a dated commitment.

harnessed is alpha. The near-term bar is "the container path is trustworthy end to end"; the
longer-term bar is "where a stack runs is a choice, not a constraint".

## Where we are — 2026-09-21

**Green, but hollow:** the hermetic layer (`lint`, `tests`, 3,541+ passing) and, nominally, the
live layer. The live green is not evidence: commit `db0c2d2` deselected the four
`TestVarlockProxyRulesOutput` tests by name, so no run since 2026-09-09 has exercised the
contract they pin. [#462] was reopened on exactly that evidence — the fix is the parser in
`launchenv.py`, then deleting the four `--deselect` lines from `live.yml`.

**Red, eight weeks running:** pin check — 20 outdated pins, three majors, latest failure
2026-09-14. `mise run upgrade-pr` is the vehicle, and whether a check whose normal state is
failure is the right signal is part of the decision — [#469].

**Half-landed:** host-anchored secrets over `varlock proxy` [#388]. The broker lifecycle, the
loopback door and `--no-secrets` shipped in Phase 1. The behaviour change did not — the launcher
still resolves real values into the container env at launch. The chain is [#438], then [#468],
then [#439], with [#440] and [#441] unblocked and parallel.

**Landed since the last snapshot:** the docker userns code work — [#456], [#457], [#458] and
[#459] are all closed. What remains of [#466] is documentation and the capability matrix. The
test-intent audit landed as epic [#503]: 76 findings, to be worked in batches.

**Known gap, now tracked:** the varlock secrets broker does not exist on docker. Its door is a
pasta option on `pod create`, and docker has no pods, so a docker launch starts no broker and falls
back to real values in env. Today that is a note printed at launch and nothing else — no test
asserts it. Once the secrets behaviour change lands, podman gains the property and docker silently
does not — [#468], which blocks [#439] for that reason.

### How we bring the backlog down

This is the one section that is a task list. It is rewritten as waves land.

Work runs in waves of parallel lanes. A **lane** is a file-ownership contract: one agent, one
worktree, one issue, a named set of files nobody else touches. Cross-lane findings are filed,
never fixed in-lane. `launcher.py` is the one serializing constraint, and no wave-1 lane holds it.

**Wave 1 — eight disjoint lanes:**

| Lane | Owns | Issue |
|---|---|---|
| live contract | `launchenv.py`, `live.yml` | [#462] |
| pin supply chain | `pin-check.yml`, catalog lockfiles | [#469] |
| broker cert mount | `mounts.py` | [#438] |
| secrets report | `aoe.py` | [#440] |
| @proxy classification | `catalog/**/recipe.yaml` | [#441] |
| backend truth | `BACKENDS.md`, capmatrix rows | [#466] |
| audit batch 1 | `tests/` only | [#503] |
| audit batch 2 | `tests/` only | [#503] |

**Wave 2 — unblocked by wave-1 merges:** [#467] (required check; needs a live layer that can
fail), [#468] (docker secrets decision; needs [#438]'s landed shape), [#439] (the behaviour
change that makes "zero secrets in the initial container environment" true; needs [#462]'s
contract, [#438], and [#468]), [#460] (unblocks the [#485] battery), [#390], and audit batches
3-4. Wave-2 stories are drafted and gated during wave-1 review windows, so review latency
absorbs the prep instead of idling the lanes.

**Wave 3:** the [#454] split, after every launcher-touching fix has landed — pure-move commits,
taken so the split starts from a stable shape. Then the [#485] credentialed battery.

### The process a lane runs

Every lane works the spec-evidence process in its own worktree, with two human review gates per
wave, batched into one sitting each:

1. **Story** pulled from the issue's own words into `docs/spec-evidence/<date>-GH-<n>/`.
2. **Gate 1**: the story-readiness judge grades it, and `gate_story.py` computes the verdict
   from the record. Two rounds, then it names the human.
3. **Review gate A**: approve, revise, or drop each story. A story the gate marks not-ready
   comes back with its named gap for the author to fill.
4. **SPEC** approved and committed, then the old-coder loop: RED → GREEN → gauntlet → EVIDENCE,
   with intent review from Tier 2 and adversary review at Tier 3.
5. **Review gate B**: the EVIDENCE reports.
6. PRs open in roadmap order and merge serially, [#462] first. The loop never pushes; opening
   the PR is the integrator's act, after review gate B.

The gauntlet scales by tier so the process stays proportionate. **Tier 3** — parsers and
secrets: [#462], [#438], and wave-2's [#468], [#439] — adds a failure model, mutation,
hostile-input, and adversary review. **Tier 2** — [#469], [#440], [#460], the [#503] batches —
runs the full loop. **Tier 1** — [#466] docs, [#441] catalog content — keeps story and SPEC with
a content-grade gauntlet. The [#503] batches are `tests/`-only by contract: their evidence is
the test diff that replaces a source-text assertion with a behaviour assertion, and production
bugs found on the way are filed on the epic, never fixed in-batch.

Repo-specific wiring, codified because it bites:

- Two artifact roots coexist. Stories pulled from now on live in
  `docs/spec-evidence/<date>-GH-<n>/`. The thirteen `.old-coder/<timestamp>-<slug>/` task
  directories from the old-coder era stay where they are as history — they are never renamed
  into the new root. The two unite only when upstream issue 31 lets one date format serve both.
- `spec-evidence.toml` is untracked, so a fresh worktree lacks it — and its absence makes the
  Gate 1 judge handler deny every read. Each worktree gets a copy before Gate 1 runs.
- `docs/` is the gitignored wiki clone, so story artifacts do not travel with PRs. After each
  merge, the story directory is consolidated into `main/docs/spec-evidence/`. Closed stories
  stay, and are never renamed.
- Gate 2, `layout_check` and the findings gates are not wired in this repo yet (upstream issue
  31), and the tracker adapter is a no-op. EVIDENCE is therefore human-reviewed at gate B, and
  gate outcomes surface in the story directory, not on GitHub.

## Both runtimes, or say so

harnessed claims podman and docker. "Supported" that is not continuously verified is a claim, not
a fact, and until recently no PR check ran a container runtime at all.

- [x] Make every site that emits, parses or strips a runtime flag ask which runtime it is
      talking to, instead of assuming podman — [#456]
- [x] Map the invoking user correctly on a runtime with no `keep-id`, so a container does not
      write as somebody else — [#457]
- [x] Give the agent a network namespace that exists on a runtime with no pods — [#458]
- [x] Close the creation and detection sites that missed the mapping — [#456], [#457],
      [#458], [#459]
- [ ] Put an enumeration test on the runtime-flag class, so the next site that misses the
      mapping fails the suite instead of a launch — [#466]
- [ ] Say what docker honors and what it does not, in `BACKENDS.md` and `capmatrix`. Three fixes
      in one day were all found by running a container, not by reading the docs — [#466]
- [ ] Decide what a docker launch does about the secrets broker, and put a test on the
      answer — [#468]
- [ ] Make `harnessed test` work for an installed harnessed, not only a repo checkout — [#460]

## Run anywhere: pluggable execution backends

Today a stack means a container. The composition layer (recipes to stacks) and the execution
backend should be separate concerns, so isolation and reproducibility become backend capabilities
you pick, not the one thing the product does.

- [ ] Name the backend seam, so host, container, and future backends implement one
      contract — [#232]
- [ ] Publish the recipe-capability x backend matrix, and warn or refuse when a stack asks
      for something its backend cannot honor — [#235]
- [ ] Share one stack-semantics routine between container-run and host-run, so the two
      verbs cannot drift — [#317]
- [ ] Evaluate a devcontainer-emit backend — [#237]
- [ ] Spike a sandboxed-host backend (bwrap + landlock): isolation without a
      container — [#236]
- [ ] Collapse the per-agent images into a single base, and measure the size
      tradeoff — [#270]

## Secrets that never land in the stack

The standing rule is that credentials are referenced, never replicated. The work is making that
true at runtime, not just at build time. The broker is running; the secrets are still real.

- [ ] Host-anchored runtime secrets over `varlock proxy` — the epic, and the shape the four
      items below serve — [#388]
- [ ] Bind the broker's cert directory into the pod, so the CA paths it emits
      resolve — [#438]
- [ ] Build the launch env from the broker instead of resolving real values on the host. This
      is the point where "zero secrets in the initial container environment" becomes
      true — [#439]
- [ ] Report every schema item's mode in `harnessed test`, with zero values printed by
      construction — [#440]
- [ ] Classify every schema item with a proxy rule. Unclassified items do not fail at launch —
      they surface later as a 401 — [#441]
- [ ] Gate the effective rule set before starting the broker, so a schema edit made inside a pod
      cannot become policy at the next launch — [#388] Phase 2
- [ ] Finish the SSH identity story in container mode: agent-only identities, correct key
      selection, host-only agent sockets — [#303], [#300], [#301], [#302]
- [ ] Separate credential seeding from config materialization, so auth has one auditable
      path — [#234]
- [ ] Enforce the cross-catalog inheritance and credential-forwarding provenance rules that
      were specced but never implemented — [#316]

## Every harness, first class

Claude format is canonical and every other agent adapts out of the same profile. That promise has
to hold on the host path too, and the rules a stack declares have to actually bind.

- [ ] Host-native identity and rules for opencode, codex, antigravity, and
      omp — [#313], [#265], [#263], [#321]
- [ ] Make declared permission rules effective and durable across launches, instead of
      whatever an upstream installer last wrote — [#269]
- [ ] Give background sessions the same MCP servers as foreground ones — [#239]
- [ ] Wire installed tooling into agent instructions, so a recipe that installs something
      also tells the agent it exists — [#309]

## Authoring a stack should be pleasant

- [ ] Interactive stack wizard: pick a harness, an agent, and recipes, and get a working
      stack — [#298]
- [ ] Let a stack add an MCP server without authoring a recipe for it — [#447]
- [ ] Shell completions for bash, zsh, and fish, including live stack and harness
      names — [#312]
- [ ] Let a recipe declare its footprint — the paths it writes outside its bounds — for
      conflict detection and host consent — [#267]
- [ ] Let tools be declared container-only, so a source-built recipe can migrate — [#345]
- [ ] Extend lockfile coverage across the recipe catalog — [#243]
- [ ] Make `harnessed update` more useful: distance-from-tag reporting, and a way to trust a
      package and skip the wait — [#350], [#258]

## Prove it, don't assert it

The live layer now runs on push and nightly, which was the goal — and its recent green is
hollow: the four contract tests are deselected by name, so no run can fail. A check that cannot
fail verifies as much as the skip it replaced, so making it honestly green outranks extending it.

- [ ] Fix the drifted `varlock proxy rules` contract, re-include the four deselected tests,
      and keep the live layer green — [#462]
- [ ] Make both runtimes gate a PR, once there is a green job to gate with — [#467]
- [ ] Cover the untested seams: service lifecycle, proxy CA injection, update-registry
      contracts — [#392], [#397], [#396]
- [ ] Turn mutation and diff coverage into a number that gates, not a tool that is merely
      declared — [#264]
- [ ] Keep the suite fast and deterministic — no network-bound outliers, no timing-sensitive
      flakes — [#256], [#349]

## Supply chain and content safety

- [ ] Get pin check green, and decide whether a check whose normal state is failure is the right
      signal: 20 outdated pins, three majors, red since 2026-07-27 — [#469]
- [ ] Advisory scanning of agent content for prompt injection and tool poisoning — [#253]
- [ ] Pin the CI actions the way harnessed makes everyone else pin theirs — [#288]
- [ ] Decide the fate of the legacy gating scanner — [#296]

## Carrying cost

Not damage, and not urgent — but it is where the work above has to happen, so it sets the price of
everything else.

- [ ] Split `launcher.py`: 5,682 lines holding a facade, both execution backends, and the whole
      CLI surface — [#454]

## Docs that match the product

- [ ] Overhaul the website to the current vocabulary and model — [#247]
- [ ] Document the two run verbs, `container-run` and `host-run`, and when each
      applies — [#271]
- [ ] Fix the docs that contradict the code or give harmful
      instructions — [#324], [#348], [#283]

## Ongoing

Correctness fixes, error-path hardening, and internal cleanups are tracked as individual issues
rather than as epics. See the [full issue list] for everything open.

[full issue list]: https://github.com/drmikecrowe/harnessed/issues
[#232]: https://github.com/drmikecrowe/harnessed/issues/232
[#234]: https://github.com/drmikecrowe/harnessed/issues/234
[#235]: https://github.com/drmikecrowe/harnessed/issues/235
[#236]: https://github.com/drmikecrowe/harnessed/issues/236
[#237]: https://github.com/drmikecrowe/harnessed/issues/237
[#239]: https://github.com/drmikecrowe/harnessed/issues/239
[#243]: https://github.com/drmikecrowe/harnessed/issues/243
[#247]: https://github.com/drmikecrowe/harnessed/issues/247
[#253]: https://github.com/drmikecrowe/harnessed/issues/253
[#256]: https://github.com/drmikecrowe/harnessed/issues/256
[#258]: https://github.com/drmikecrowe/harnessed/issues/258
[#263]: https://github.com/drmikecrowe/harnessed/issues/263
[#264]: https://github.com/drmikecrowe/harnessed/issues/264
[#265]: https://github.com/drmikecrowe/harnessed/issues/265
[#267]: https://github.com/drmikecrowe/harnessed/issues/267
[#269]: https://github.com/drmikecrowe/harnessed/issues/269
[#270]: https://github.com/drmikecrowe/harnessed/issues/270
[#271]: https://github.com/drmikecrowe/harnessed/issues/271
[#283]: https://github.com/drmikecrowe/harnessed/issues/283
[#288]: https://github.com/drmikecrowe/harnessed/issues/288
[#296]: https://github.com/drmikecrowe/harnessed/issues/296
[#298]: https://github.com/drmikecrowe/harnessed/issues/298
[#300]: https://github.com/drmikecrowe/harnessed/issues/300
[#301]: https://github.com/drmikecrowe/harnessed/issues/301
[#302]: https://github.com/drmikecrowe/harnessed/issues/302
[#303]: https://github.com/drmikecrowe/harnessed/issues/303
[#309]: https://github.com/drmikecrowe/harnessed/issues/309
[#312]: https://github.com/drmikecrowe/harnessed/issues/312
[#313]: https://github.com/drmikecrowe/harnessed/issues/313
[#316]: https://github.com/drmikecrowe/harnessed/issues/316
[#317]: https://github.com/drmikecrowe/harnessed/issues/317
[#321]: https://github.com/drmikecrowe/harnessed/issues/321
[#324]: https://github.com/drmikecrowe/harnessed/issues/324
[#345]: https://github.com/drmikecrowe/harnessed/issues/345
[#348]: https://github.com/drmikecrowe/harnessed/issues/348
[#349]: https://github.com/drmikecrowe/harnessed/issues/349
[#350]: https://github.com/drmikecrowe/harnessed/issues/350
[#388]: https://github.com/drmikecrowe/harnessed/issues/388
[#390]: https://github.com/drmikecrowe/harnessed/issues/390
[#392]: https://github.com/drmikecrowe/harnessed/issues/392
[#396]: https://github.com/drmikecrowe/harnessed/issues/396
[#397]: https://github.com/drmikecrowe/harnessed/issues/397
[#438]: https://github.com/drmikecrowe/harnessed/issues/438
[#439]: https://github.com/drmikecrowe/harnessed/issues/439
[#440]: https://github.com/drmikecrowe/harnessed/issues/440
[#441]: https://github.com/drmikecrowe/harnessed/issues/441
[#447]: https://github.com/drmikecrowe/harnessed/issues/447
[#454]: https://github.com/drmikecrowe/harnessed/issues/454
[#456]: https://github.com/drmikecrowe/harnessed/issues/456
[#457]: https://github.com/drmikecrowe/harnessed/issues/457
[#458]: https://github.com/drmikecrowe/harnessed/issues/458
[#459]: https://github.com/drmikecrowe/harnessed/issues/459
[#460]: https://github.com/drmikecrowe/harnessed/issues/460
[#462]: https://github.com/drmikecrowe/harnessed/issues/462
[#466]: https://github.com/drmikecrowe/harnessed/issues/466
[#467]: https://github.com/drmikecrowe/harnessed/issues/467
[#468]: https://github.com/drmikecrowe/harnessed/issues/468
[#469]: https://github.com/drmikecrowe/harnessed/issues/469
[#485]: https://github.com/drmikecrowe/harnessed/issues/485
[#503]: https://github.com/drmikecrowe/harnessed/issues/503
