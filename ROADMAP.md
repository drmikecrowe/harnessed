# Roadmap

Where harnessed is going. This is the epic-level view — one line per theme, not a task list.
Every item links to the issue that carries the detail. Nothing here is a dated commitment.

harnessed is alpha. The near-term bar is "the container path is trustworthy end to end"; the
longer-term bar is "where a stack runs is a choice, not a constraint".

## Where we are — 2026-09-09

Two threads are in flight at once, and they intersect. This section says what is actually true
today so the themes below read as future work rather than as a description of the product.

**Green:** the hermetic layer. `lint` and `tests` pass on every push to main; the latest run is
3,541 passed.

**Red, and has been for a while:**

- The **live layer** (real podman) has failed every run since 2026-08-28. Four tests, all in
  `TestVarlockProxyRulesOutput` — `varlock proxy rules` output no longer parses. The other ~3,584
  live tests pass, so this is one drifted contract, not a broken layer — [#462]
- **pin check** has failed every weekly run since at least 2026-07-27: 20 outdated pins, three of
  them majors. `mise run upgrade-pr` is the vehicle. No issue tracks it yet.

**Half-landed:** host-anchored secrets over `varlock proxy` [#388]. The broker lifecycle, the
loopback door and `--no-secrets` shipped in Phase 1. The behaviour change did not — the launcher
still resolves real values into the container env at launch. Both halves are needed before the
security property is real, and only the first is in.

**In flight:** docker as a first-class runtime. The userns handling was written as if podman were
the only runtime [#456]; the fixes are on a branch, not on main.

**Known gap with no issue:** the varlock secrets broker does not exist on docker. Its door is a
pasta option on `pod create`, and docker has no pods, so a docker launch starts no broker and falls
back to real values in env. Today that is a note printed at launch and nothing else — no test
asserts it. Once the secrets behaviour change lands, podman gains the property and docker silently
does not.

### The order that follows from that

1. Fix the live layer's four red tests, so the runtime layer can gate anything at all — [#462]
2. Land the docker runtime fixes, but keep the change that makes live a per-PR check separate:
   turning a red job into a required check blocks every PR — [#456]
3. Finish docker parity: the invoking user's identity, the netns anchor, the remaining
   creation sites — [#457], [#458], [#459]
4. Decide and test what a docker launch does about secrets, before the behaviour change makes the
   gap load-bearing. Needs an issue.
5. Then retire real-value env seeding — [#438], [#439]
6. In parallel, and unblocked: classify every schema item, and grow the secrets report — [#441],
   [#440]

## Both runtimes, or say so

harnessed claims podman and docker. "Supported" that is not continuously verified is a claim, not
a fact, and until recently no PR check ran a container runtime at all.

- [ ] Make every site that emits, parses or strips a runtime flag ask which runtime it is
      talking to, instead of assuming podman — [#456]
- [ ] Map the invoking user correctly on a runtime with no `keep-id`, so a container does not
      write as somebody else — [#457]
- [ ] Give the agent a network namespace that exists on a runtime with no pods — [#458]
- [ ] Close the remaining creation and detection sites that still miss the mapping — [#459]
- [ ] Decide what a docker launch does about the secrets broker, and put a test on the
      answer. Needs an issue.
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

The live layer now runs on push and nightly, which was the goal — and it has been red since the
day after it started. A check nobody can merge against verifies as much as the skip it replaced,
so getting it green outranks extending it.

- [ ] Get the live layer green, then keep it that way — [#462]
- [ ] Make both runtimes gate a PR, once there is a green job to gate with — [#456]
- [ ] Cover the untested seams: service lifecycle, proxy CA injection, update-registry
      contracts — [#392], [#397], [#396]
- [ ] Turn mutation and diff coverage into a number that gates, not a tool that is merely
      declared — [#264]
- [ ] Keep the suite fast and deterministic — no network-bound outliers, no timing-sensitive
      flakes — [#256], [#349]

## Supply chain and content safety

- [ ] Get pin check green: 20 outdated pins, red since 2026-07-27. Needs an issue.
- [ ] Advisory scanning of agent content for prompt injection and tool poisoning — [#253]
- [ ] Pin the CI actions the way harnessed makes everyone else pin theirs — [#288]
- [ ] Decide the fate of the legacy gating scanner — [#296]

## Carrying cost

Not damage, and not urgent — but it is where the work above has to happen, so it sets the price of
everything else.

- [ ] Split `launcher.py`: 5,500 lines holding a facade, both execution backends, and the whole
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
