# Decisions — Copy ~/.claude/CLAUDE.md @-imports into stack rules for ACP sessions

## Setup plan
- Isolation: worktree — `6-3-gh-600-claude-md-imports-to-rules` on branch `GH-600`, cut from `main` at `74199d2`.
- Git: commit per scenario group, signed, on `GH-600`. The queued label is `4bbd31e`.
- Step 0 of the build, before RED: rerun the GH-594 marker probe (`tools/acp-smoke.py --verb host-acp --prompt`) against the current adapter pin. If an `@`-import marker comes back, imports are expanded upstream, and this work is not needed: stop and report to the engineer. Either way, the engineer gets a drafted upstream note on whether the pin expands imports. Filing it is an outward action, and it waits for the engineer's yes.
- Step 0 also checks Decide 1 live, before RED. Put a marker file by hand in `<host home>/rules/harnessed-imports/` on the throwaway stack and probe `host-acp`. If the marker does not come back, a nested rule is not loaded: stop, and bring Decide 1 back to the engineer with B.
- New dependencies: none.
- New files: `src/harnessed/claude_imports.py`, `tests/test_claude_imports.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests (`tools/run-tests.sh`), coverage (80%, branch), types (pyright), lint (ruff on src, tests, tools), shellcheck and secrets (gitleaks). Mutation is not a declared layer. Tier 2 does not require it, so it does not run.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml` — 4 checks transcribed (pytest, ruff, pyright, shellcheck), the same set GH-594 read. `live.yml` triggers on `src/harnessed/launcher.py` and `src/harnessed/paths.py`, which this change touches.

## Facts this SPEC rests on
1. `_host_launch_plan` (`src/harnessed/launcher.py:2598`) is the host's one per-launch prepare step. It rebuilds the home only on a fingerprint change, then propagates `settings.json` on every launch (`:2627`). Read on 2026-10-14.
2. `_materialize_host_home` rmtree's the host home on a rebuild (comment at `launcher.py:2620`). The owned dir must be written after it, on every launch.
3. The container's `~/.claude` is a named config volume (`launcher.py:864`). `_ensure_config_volume` copies the profile in on every launch and never removes a file (`src/harnessed/volumes.py:168`, docstring and the `fresh` comment). A copy written into the volume would therefore outlive its import. That is why S2.2 uses a bind mount.
4. `ContainerBackend.materialize_config` composes the mounts and states that their order is load-bearing (`launcher.py:3790`). A nested ro mount already has a precedent: `_omp_mcp_seed_mount`.
5. `console._can_prompt()` (`src/harnessed/console.py:103`) is false for a non-TTY stdin and for the `-exec` verbs. Every prompt site uses it.
6. Precedent for a stored per-stack answer: `paths.setup_dismissed_flag` keeps a marker file under `$XDG_STATE_HOME/harnessed/`. The answer file follows it.
7. `container-acp`, `container-run` and `container-exec` are one function, `container_run`, split by `ctx.info_name` (`launcher.py:4367`). `host-exec` is an alias of `host_run` (`launcher.py:6406`). `install` is `install_stack(stack, harness)` at `launcher.py:5616`.
8. Marker results from 2026-10-13 (story, GH-594 Revision 4 and 5): a regular file in the stack home `rules/` reaches a `host-acp` session; an `@`-import and a symlinked rule do not.
9. `catalog/agents/claude/agent.yaml:10` pins `claude-agent-acp` at 0.89.1. The issue's runs observed 0.85.1.

## Gate 1 deferred items
- SR-DEFER "Whether `container-acp` loads the stack's rules from the config volume the same way": fact 3 answers how the rules reach the container (the volume plus the ro mount). S2.4 proves loading live.
- SR-DEFER "Whether a newer `claude-agent-acp` ... expands imports": step 0 of the setup plan checks it on the pin in fact 9.

## Intent review
- Gap 1 (no container refresh step): accepted. S3.4 names `ContainerBackend.materialize_config` as the step that refreshes and prunes the copies dir, and Touches says so.
- Gap 2 (Decide 1 depends on nested-rule loading): accepted. Step 0 of the setup plan checks it live before RED, and falls back to B.
- Gap 3 (S6.5 and S1.5 add behaviour): declined. S1.5 is the existing `_can_prompt()` contract (fact 5): a prompt with no terminal hangs a script, so the non-prompt branch is required, not added. S6.5 is the only meaning `--reask-imports` can have when no one can answer: it clears the answer, as AC-6 says, and the warning names the next step.

- Round 2, gap 1 (S6.5 invents behaviour): declined. The engineer ruled S6.5 on 2026-10-14 (Revision 2).
- Round 2, gap 2 (copies dir and ro mount): declined. Fact 3 shows that a copy written into the config volume outlives its import, which breaks AC-6. Decide 1 is ruled, and step 0 checks it live.
- Round 2, gap 3 (missing target under `n`, `i` or none): accepted. S7.4 states that nothing is read, so no target warning is printed.
- Round 2, gap 4 (no upstream report): declined. Setup step 0 drafts the upstream note in either outcome, and the engineer's yes files it.
- Round 2, gap 5 (whole-line only is narrower than the story): declined. Decide 2 is ruled, and Known limits states it.

## Decide calls

### Decide 1. Where do the copies live in the stack's rules?
Evidence: facts 2, 3 and 4. A directory mount can be refreshed in place for a running container. A file mount pins one file.

- A. One owned subdirectory, `rules/harnessed-imports/`, synced on the host and mounted ro as a directory in the container. Cost: it depends on Claude loading `rules/` subdirectories. Interactive sessions do, and S2.3 and S2.4 prove it for ACP before anything else is built on it.
- B. Flat files `rules/harnessed-import-<name>.md`, one ro file mount per copy in the container. Cost: one mount per import; a running container never sees an import added after it started; deletion depends on a filename prefix.

Default: A. Ruling: A (mcrowe, 2026-10-14).
Changes: Scenarios S2.1, S2.2, S3.3 and S6 use `rules/harnessed-imports/`; Orientation `Decided:` names it.

### Decide 2. What counts as an import?
Evidence: `/home/mcrowe/.claude/CLAUDE.md` line 6 is a whole-line `@` path. Claude also expands inline `@path` tokens outside code spans.

- A. Whole-line `@<path>` only. Cost: an inline import in prose is not copied. Known limit.
- B. Any `@path` token outside code spans and fences, matching Claude's syntax. Cost: a parser that is more complex, and false positives such as `a@b.com` unless it handles them.

Default: A. Ruling: A (mcrowe, 2026-10-14).
Changes: Scenarios terms define an import as a whole line; S1.4 and Known limits state it.

### Decide 3. Which harnesses get copies?
Evidence: the story names `host-acp` and `container-acp` for Claude. The omp harness has a nested Claude config dir (`_host_omp_claude_dir`).

- A. `claude` only. Cost: an omp stack's Claude layer gets no copies.
- B. `claude` and `omp`. Cost: a second sync site in `_plan_host_omp` and a second set of tests, for a harness the story does not name.

Default: A. Ruling: A (mcrowe, 2026-10-14).
Changes: Known limits state claude only; Touches names no omp site.

## Revisions
### Revision 1. Decide 1, 2 and 3 ruled A
The engineer ruled all three Decide calls A on 2026-10-14 (mcrowe), after the intent review. SPEC.md's Orientation and Summary now state the rulings.
### Revision 2. Gate 1a round 1: S6.5 output defined
Gate 1a round 1 found S6.5 read two ways (PR-READINGS): `build --reask-imports` with no terminal could print the warning or nothing. The engineer ruled on 2026-10-14 (mcrowe): build prints its own warning on stderr and exits 0. S6.5 now gives the text and the stream. Two judge gaps were folded in as rewording: the Scenarios terms now define `y`, `n` and `i`, and setup step 0 drafts the upstream note the story's author note asks for.
