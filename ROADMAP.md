# Roadmap

Where harnessed is going. This is the epic-level view — one line per theme, not a task list.
Every item links to the issue that carries the detail. Nothing here is a dated commitment.

harnessed is alpha. The near-term bar is "the container path is trustworthy end to end"; the
longer-term bar is "where a stack runs is a choice, not a constraint".

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
true at runtime, not just at build time.

- [ ] Host-anchored runtime secrets over `varlock proxy`, so a container resolves a secret
      without ever holding the backend credential — [#388]
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
- [ ] Shell completions for bash, zsh, and fish, including live stack and harness
      names — [#312]
- [ ] Let a recipe declare its footprint — the paths it writes outside its bounds — for
      conflict detection and host consent — [#267]
- [ ] Let tools be declared container-only, so a source-built recipe can migrate — [#345]
- [ ] Extend lockfile coverage across the recipe catalog — [#243]
- [ ] Make `harnessed update` more useful: distance-from-tag reporting, and a way to trust a
      package and skip the wait — [#350], [#258]

## Prove it, don't assert it

The suite is green and hermetic, which is the point — and also the gap. The layer that touches
podman, registries, and real services is gated off, and therefore rarely runs.

- [ ] Run the live-verification layer in CI, covering the external contracts the hermetic
      suite cannot reach — [#250]
- [ ] Cover the untested seams: service lifecycle, proxy CA injection, update-registry
      contracts — [#392], [#397], [#396]
- [ ] Turn mutation and diff coverage into a number that gates, not a tool that is merely
      declared — [#264]
- [ ] Keep the suite fast and deterministic — no network-bound outliers, no timing-sensitive
      flakes — [#256], [#349]

## Supply chain and content safety

- [ ] Advisory scanning of agent content for prompt injection and tool poisoning — [#253]
- [ ] Pin the CI actions the way harnessed makes everyone else pin theirs — [#288]
- [ ] Decide the fate of the legacy gating scanner — [#296]

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
[#250]: https://github.com/drmikecrowe/harnessed/issues/250
[#253]: https://github.com/drmikecrowe/harnessed/issues/253
[#256]: https://github.com/drmikecrowe/harnessed/issues/256
[#258]: https://github.com/drmikecrowe/harnessed/issues/258
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
[#350]: https://github.com/drmikecrowe/harnessed/issues/350
[#388]: https://github.com/drmikecrowe/harnessed/issues/388
[#392]: https://github.com/drmikecrowe/harnessed/issues/392
[#396]: https://github.com/drmikecrowe/harnessed/issues/396
[#397]: https://github.com/drmikecrowe/harnessed/issues/397
