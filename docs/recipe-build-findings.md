# Recipe build & test — engineering findings log

Running log from end-to-end exercising the recipe-authoring → `harnessed build` →
`harnessed test` loop in podman, from an end-user's perspective. Each finding records the
symptom, root cause, fix, and verification so guides/FAQ can be derived from it.

The repo HEAD is `WIP: saving all WIP before rework` — several issues below stem from the
assembler/launcher being mid-refactor and internally inconsistent.

---

## F1 — `harnessed build <stack>` fails: `profiles/profiles/<stack>` path doubling

- **Symptom:** `harnessed build tracer-time` aborts with
  `PermissionError: '/…/harnessed/profiles/profiles'` (note the doubled `profiles`).
- **Root cause:** `assemble()` writes to `<build-dir>/profiles/<stack>` (CLI contract: `--build-dir`
  is the dir that *contains* `profiles/`). The launcher's `_build_stack` passed
  `--build-dir = profile_dir(stack).parent` = `…/harnessed/profiles`, so the emit target became
  `…/harnessed/profiles/profiles/<stack>`. It also bind-mounted only the leaf profile dir, which
  `emit.reset_profile()` cannot `rmtree` (it is the mount point).
- **Fix:** `_build_stack` now passes `--build-dir = profiles_root().parent` (`…/harnessed`) and
  bind-mounts that build root writable. (`tools/harnessed/launcher.py`)
- **Verify:** `harnessed build tracer-time` emits `…/profiles/tracer-time/` with the expected files.

## F2 — `harnessed-tools` image is cached and never rebuilt from source

- **Symptom:** After F1's fix, the emitted profile nested `.mcp.json`/`settings.json` under
  `.claude/` — but current source emits them at the profile root.
- **Root cause:** `_ensure_tools_image` builds `harnessed-tools:latest` only when the image is
  absent. Editing `tools/harnessed/*.py` on the host does not rebuild it, so `harnessed build`
  ran *stale* assembler code baked into the image while the launcher (run on the host) used current
  source — the two disagreed on the profile layout.
- **Workaround for development:** rebuild the tools image after touching `tools/harnessed/*`:
  `podman build -t harnessed-tools:latest -f tools/Dockerfile tools`.
- **Follow-up (FAQ):** document that the tools image must be rebuilt after assembler changes, or add
  a `--force`/content-hash rebuild path.

## F3 — assembler no longer fans skills/commands into the profile

- **Symptom:** Current-source `assemble()` emits `.mcp.json`, `settings.json`, `hatago.config.json`,
  the derived Dockerfile, and `baked-servers.json` — but **no `.claude/` tree**. A recipe's skills
  (e.g. `time` ships `time-helper`) never reach the profile, so `harnessed test` cannot find them and
  the skill capability is always missing.
- **Root cause:** the `LinkSyncer` fan-out (skills/commands → `<profile>/.claude/{skills,commands}`)
  still exists in `synclinks.py` but `assemble()` no longer calls it. The launcher's
  `_build_mount_args` still mounts `<profile>/.claude/{skills,commands,…}` at runtime, and the
  capability test still reads `~/.claude/skills` — both expect the fan-out. (A stale phase-09 UAT
  asserts the opposite; it is superseded by the current launcher + recipe-authoring guide.)
- **Fix:** restore `LinkSyncer.add_recipe()/fan()` into `assemble()`, fanning into
  `<profile>/.claude`. (`tools/harnessed/assemble.py`)
- **Verify:** profile contains `.claude/skills/time-helper/SKILL.md`; `harnessed test tracer-time`
  reports the skill present.

## F4 — `harnessed <stack>` launch shorthand was not wired

- **Symptom:** `harnessed test <stack>` failed with `No such command 'tracer-time'`. The capability
  test launches the stack via `harnessed <stack> <project> --fresh`, but Typer parsed `tracer-time`
  as an unknown subcommand.
- **Root cause:** the launcher exposed only named subcommands (`launch`, `build`, …). The
  `harnessed <stack>` shorthand documented in the README/AGENTS had no routing.
- **Fix:** `main()` now injects `launch` when the first non-option token is not a known subcommand,
  so `harnessed <stack> …` ≡ `harnessed launch <stack> …`. (`tools/harnessed/launcher.py`)

## F5 — console-script entry point bypassed `main()`

- **Symptom:** the F4 fix had no effect when invoked through the installed `harnessed` script.
- **Root cause:** `[project.scripts] harnessed = "harnessed.launcher:app"` called the Typer `app`
  object directly, never running `main()` (where the shorthand routing lives).
- **Fix:** entry point is now `harnessed.launcher:main`. Reinstall (`uv sync`) regenerates the
  console script. (`tools/pyproject.toml`)
- **Verify:** `harnessed test tracer-time` → `ok: true` (time MCP connected, time-helper skill
  present), both via auth-free primary checks (hatago `hatago://servers` + mounted-profile listing).

## Milestone — `tracer-time` (claude) green end-to-end

```
harnessed build tracer-time   # emits profile (root .mcp.json + .claude/skills fan-out), builds hatago
harnessed test  tracer-time   # ok: true — time (mcp) connected, time-helper (skill) present
```
No Claude credentials required: the capability test's primary checks are auth-free.

## F6 — build rejections surfaced as Python tracebacks

- **Symptom:** `harnessed build floating-test` / `omp-gstack-test` printed the correct validation
  error **and then** a ~40-line Rich `CalledProcessError` traceback.
- **Root cause:** `_build_stack` ran the assembler via `_run(..., check=True)`; a non-zero exit
  (the intended rejection) raised `CalledProcessError`, which Typer rendered as a crash.
- **Fix:** catch `CalledProcessError` around the assemble subprocess → clean `error:` line + exit 1.
  (`tools/harnessed/launcher.py`)
- **Verify:** both negative stacks exit 1 with a one-line error, no traceback.

## F7 — derived `Dockerfile.harnessed-<stack>` image is emitted but never built or run (KNOWN GAP)

- **Observation:** `assemble` emits `profiles/<stack>/Dockerfile.harnessed-<stack>` (base image +
  concatenated recipe Dockerfile bodies), but `_build_stack` only builds the hatago image, and
  `launch` runs the **base** harness image (`harnessed-<harness>`), never the derived stack image.
  So a Dockerfile recipe's install steps never reach the running container.
- **Impact:** Dockerfile recipes (e.g. `gstack`) cannot deliver tooling into the instance today.
- **Status:** documented as a gap, not yet wired. Wiring it also needs a decision on the
  image-baked-skill vs profile-mount conflict (see F8/limitations) before it is safe to enable.

## F8 — `recipe.expect` is parsed but ignored by the capability oracle (KNOWN GAP)

- **Observation:** `schema.expected_capabilities` derives the oracle from MCP servers +
  skill/command `FileExt`s only. `recipe.expect` (e.g. `gstack`'s `expect: [gstack-skill]`) is
  loaded into the model but never added to the expected set, so `harnessed test gstack-time` does
  **not** assert `gstack-skill`.
- **Impact:** a Dockerfile recipe's declared capability is unverified; `gstack-time` passes only
  because it inherits `time`'s capabilities. Combined with F7, the gstack capability is neither
  delivered nor checked.
- **Status:** documented. Fixing it correctly depends on F7 (the image must actually deliver the
  capability) and on resolving the mount-shadowing limitation below.

### Limitation — whole-dir skill mount shadows image-baked skills

The launcher bind-mounts `<profile>/.claude/skills` over the container's `~/.claude/skills`. If a
recipe instead baked a skill into the image, that whole-dir mount would hide it whenever any other
recipe contributes a fanned skill. Per-skill mounts (or an overlay) would be needed to let
image-delivered and profile-delivered skills coexist.

## F9 — shared-service sidecars were never started (`ping` could not connect)

- **Symptom:** `ping-time` declares a `service: ping` MCP server resolved to
  `host.containers.internal:8080`, but nothing built or ran the ping container, so hatago's proxy
  had no backend and the `ping` capability was missing. `harnessed svc up/down` (documented in
  AGENTS.md/CLAUDE.md) was unimplemented.
- **Fix:** added minimal, idempotent service lifecycle (`tools/harnessed/launcher.py`):
  - `_ensure_services` — for every `service:` a stack's recipes reference, build the service image
    if absent and start it host-published (`-p <port>:<port>`, optional `-v <volume>:/data`),
    skipping any already-running container; called from `launch` before pod creation. Services are
    **not** torn down by `--fresh` (only the pod is) — they outlive instances by design.
  - `harnessed svc up|down <name>` — explicit lifecycle command for parity with the docs.
- **Verify:** `harnessed test ping-time` → `ok: true` with `ping` (mcp) **connected** (plus `time`
  MCP and `time-helper` skill).

## F11 — repo restructured to a standard Python project + `catalog/`; host-native assemble

- **Direction (user):** the package was buried in `tools/`, agents were modeled as recipes, stacks
  ignored the naming convention, and the assembler ran inside a `harnessed-tools` image — none of it
  read coherently for contributors.
- **Changes:**
  - **Layout** → `src/harnessed/` (the app), top-level `tests/`, root `pyproject.toml`; all authorable
    content under `catalog/{agents,base,recipes,services,stacks}`. Deleted `tools/`, the
    `harnessed-tools` image, `DESIGN.md`, dead `lib/manifests`, the bash-era `uat/`.
  - **Host-native assemble** — `harnessed build` calls `assemble()` in-process (no tool container).
  - **Catalog overlay** — `~/.config/harnessed/catalog` overlays the repo `catalog/` (user wins),
    via `paths.catalog_roots()` / `find_in_catalog`.
  - **Agents first-class** — images/Dockerfiles resolved from `catalog/agents/<h>/agent.yaml`; the
    `harnesses:` recipe field and the compat gate are gone (recipes are harness-independent).
  - **Dockerfile-recipe model wired** — the launcher builds the derived `harnessed-<stack>` image and
    merges its baked `~/.claude/{skills,commands,plugins,…}` into the profile (so image-delivered and
    recipe-fanned extensions coexist); `launch` runs the derived image.
  - **`expect:` is structured** (`skills/commands/plugins/mcp`) and **wired into the oracle**, so a
    recipe declares what its Dockerfile delivers and the capability test probes it in the container.
  - **Stacks renamed** to `<agent>_<recipe>…` and consolidated.
  - **Docs** — added `ARCHITECTURE.md` (SoT) + `CONTRIBUTING.md`; trimmed `CLAUDE.md`/`AGENTS.md` to
    point at them; retired the stale planning docs; updated guide paths to `catalog/`.
- **Verify:** 79 fast tests + the live podman suite green; `claude_gstack_ping_time_greet` and
  `omp_gstack_ping_time_greet` both report every skill/command/MCP present in the container.

## Result matrix (podman, auth-free capability tests)

Final stacks (post-restructure, `<agent>_<recipe>…` naming):

| Stack | Agent | Recipes | Result |
| ----- | ----- | ------- | ------ |
| `claude_time` | claude | time | ✅ green (tracer: time MCP + time-helper) |
| `claude_gstack_ping_time_greet` | claude | gstack, ping, time, greet | ✅ green — ping+time MCP, time-helper/greet-helper/gstack-skill, gstack-cmd |
| `omp_gstack_ping_time_greet` | omp | gstack, ping, time, greet | ✅ green — same capabilities via the omp bridge |
| `claude_floating-recipe` | claude | floating-recipe | ✅ correctly rejected (pin gate) |

(Earlier per-recipe coverage — `time`/`greet`/`ping`/`gstack` on claude and omp — is now subsumed by
the two full stacks; the Dockerfile-recipe `expect` gap noted in F7/F8 is closed by F11.)

## F10 — recipes are harness-independent: removed the `harnesses:` field and compat gate

- **Symptom (user-reported):** `gstack`/`floating-recipe` declared `harnesses: [claude]`, and an
  intermediate fix introduced a `claude-only` fixture recipe + `omp-gstack-test` stack to exercise a
  harness-compat rejection gate.
- **Root cause / correction:** the whole concept was wrong. Recipes are **harness-independent** —
  every harness consumes the same Claude-canonical profile, and any harness-specific need belongs
  *inside* the recipe Dockerfile via the `${HARNESS}` build arg, not as a recipe-level exclusion. A
  "claude-only recipe" is a contradiction; a claude stack is just `harness: claude` with whatever
  recipes (or none).
- **Fix:**
  - Removed the `harnesses:` field from the `Recipe` model + parser, and deleted
    `HarnessCompatError` + `validate_harness_compat` + the assemble gate call (`schema.py`,
    `assemble.py`).
  - Removed the field from `recipes/gstack` and `recipes/floating-recipe`; deleted the wasted
    `recipes/claude-only` fixture and the `stacks/omp-gstack-test` stack.
  - Dropped the harness-compat tests (`test_schema.py`, `test_recipes_integration.py`); the
    floating-pin gate remains the one Dockerfile-validation negative test.
  - Updated the authoring guide + FAQ: recipes never carry `harnesses:`.
- **Verify:** `harnessed test gstack-time` (claude) and `harnessed test omp-gstack` (omp) both green
  with the *same* `gstack` recipe and no harness field; unit suite green (89 passed).
