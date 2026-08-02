---
name: harnessed-catalog
description: Author harnessed catalog content — recipes, stacks, and services — in the user overlay (~/.config/harnessed/catalog) or the repo catalog. Use when asked to create, edit, split, or debug a recipe.yaml / stack.yaml / service.yaml, to add an MCP server, skills, commands or rules to a stack, to compose several stacks that share a base (extends:), or when a build fails on "unknown recipe field", "unknown stack field", a pin-validation error, or a name collision in the assembled profile.
---

# Authoring harnessed catalog content

Three things are authorable, and they are not interchangeable:

| Kind | Lives at | Is |
| --- | --- | --- |
| **recipe** | `<catalog>/recipes/<name>/recipe.yaml` | one capability bundle (MCP servers, skills/commands/rules, an install step) added **onto** a harness |
| **stack** | `<catalog>/stacks/<name>/stack.yaml` | a **harness-free** chosen set of recipes + policy |
| **service** | `<catalog>/services/<name>/service.yaml` | a sidecar container a recipe or stack references |

An **agent** (`claude`, `omp`, …) is the harness itself, not a recipe. The harness is a run-time
argument, never a stack field. Full vocabulary: `ARCHITECTURE.md`.

## Decide what you are writing

- Adding a capability (an MCP server, a skill set, a CLI) → **recipe**. One recipe, one capability.
- Choosing which capabilities and which policy a session gets → **stack**.
- Several stacks sharing house recipes/policy → one base stack + `extends:` children. See
  [stack-fields.md](stack-fields.md).
- One-off, no manifest wanted → no authoring at all: `harnessed container-run <harness> --recipe a
  --recipe b` mints a content-named stack under the generated catalog root.

## Where to author

Two catalog roots, searched **overlay first** (it wins on a name clash):

| Root | Use for |
| --- | --- |
| `~/.config/harnessed/catalog/` | anything private, host-local, or carrying a real key/URL/path. Also anything you just want to keep out of the repo. |
| `<repo>/catalog/` | content meant to ship — it is **packaged into the wheel**. |

Rules that follow from that split, and they are hard:

- **Never put a real credential, private hostname, or `/home/<user>` path in `<repo>/catalog/`.**
  A repo recipe carrying a live URL key is a published secret. Ship a placeholder template
  (`catalog/recipes/openbrain-example`) and keep the real one in the overlay.
- **Nothing host-local in `<repo>/catalog/`, including symlinks** — setuptools follows them into the
  wheel. Symlinking a recipe's `skills:`/`rules:` entries at content you edit elsewhere on the host
  (`~/.agents/skills/...`) is a good overlay pattern and only ever an overlay pattern; the fan-out
  resolves and copies, so the real content lands in the profile.
- `<repo>/catalog-local/{agents,recipes,services,stacks}` are gitignored symlinks to the overlay, so
  you can browse and edit the overlay from inside the checkout. Edit through them freely; never
  create such a link inside `catalog/`.
- `harnessed new <name> --recipes a,b` scaffolds into the **repo** catalog, not the overlay. For an
  overlay stack, create the directory and write `stack.yaml` by hand.

Every manifest starts with the schema header so the editor validates as you type:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/recipe.schema.json
```

(`recipe.schema.json` / `stack.schema.json` / `service.schema.json` / `agent.schema.json`, all under
`schemas/` in the repo.)

## The workflow

1. **Read the shape first.** [recipe-fields.md](recipe-fields.md) for a recipe,
   [stack-fields.md](stack-fields.md) for a stack. Both are the verified field lists — the parser
   rejects anything not on them.
2. **Write the manifest.** Only the fields you exercise; everything else has a default.
3. **Assemble — the fast gate.** No podman, no secrets, seconds:

   ```bash
   harnessed-tools assemble <stack> <harness> --build-dir "$(mktemp -d)"
   ```

   This resolves the whole catalog closure: schema validity, unknown fields, `extends:` chains,
   recipe conflicts, pin *format*, and the skill/command name-collision check. It prints the MCP
   servers it wired. Run it after every edit — it catches most authoring errors before anything
   slower runs.
4. **Build — the real gate.** `harnessed build <stack> <harness>` fetches real artifacts and runs
   the real Dockerfile. This is where a drifted pin, a wrong asset name, or a bad install path
   surfaces; assembly and pytest cannot see any of them. `harnessed build` **never needs secrets**,
   so there is no reason to skip it.
5. **Test — the oracle.** `harnessed test <stack> <harness>` launches `--fresh` headless and asserts
   every declared capability is live (skills in `~/.claude/skills`, MCP connected through hatago, …).
   A recipe whose Dockerfile installs things must declare them under `expect:` or the test cannot
   see them.

Steps 4 and 5 are what "done" means for a new or changed recipe. A green `pytest` is not enough.

**Do not run `harnessed container-run` or `harnessed host-run` yourself** — both hand the terminal
to an interactive agent session, so they are the user's to run (the harnessed repo states this
explicitly in `AGENTS.md`). `build`, `test`, `list`, and `harnessed-tools assemble` are yours.

## Non-negotiables when authoring

- **Recipes are harness-independent.** No `harnesses:` field on a recipe, ever. If a step genuinely
  differs per harness, branch on `${HARNESS}` *inside* the recipe Dockerfile.
- **Stacks are harness-free.** `harness:` (singular) is rejected. `harnesses:` is only a build-time
  convenience listing which harnesses a bare `harnessed build <stack>` should cover.
- **A stack may not be named after a harness**, and `name:` must equal the directory name.
- **Pin every download.** `@latest`, `--branch main`, a bare `:latest`, `HEAD` — all rejected before
  a layer is built. Pin to a tag or a commit SHA.
- **pnpm, never `npm`/`npx`** (`pnpm dlx` replaces `npx`); **`uvx`** for light Python MCP servers.
  Enforced inside `install.sh` and Dockerfiles alike.
- **Streamable HTTP only.** SSE is deprecated; do not author it.
- **A recipe Dockerfile may not write to `~/.claude`** — that content is invisible on a host launch
  and shadowed by the profile mount in a container. Use `install.script` writing to
  `$HARNESSED_CONFIG_DIR`.
- **A recipe Dockerfile carries no `FROM` and no `ARG HARNESS`** — the assembler prepends both.
- **Credentials are referenced, never copied.** Do not bake, seed, or snapshot a credential store
  into a recipe. See `ARCHITECTURE.md` §Constraints.

## Failure messages and what they mean

| Message | Cause |
| --- | --- |
| `unknown recipe field(s) in --strict mode` | typo — the message suggests the intended field |
| `unknown stack field(s)` | same, and stack fields are **always** strict. A silently-ignored key is how an `extends:` went dead for months. |
| `PinValidationError` | a floating ref in a Dockerfile, `tools:`, or `install.cache` |
| a name collision on assemble | two recipes fan a skill/command with the same leaf name. Rename one; the assembler fails fast by design. |
| `SchemaError: … conflicts` | two recipes in one stack declare each other in `conflicts:` (or are siblings of one family) |
| `extends: 'x' — no such stack` | the parent is not in the child's catalog root or the search path |

## Reference

- [recipe-fields.md](recipe-fields.md) — every `recipe.yaml` field, the three MCP shapes, `persist:`,
  `install:` vs `setup:` vs `init:`, `env:`.
- [stack-fields.md](stack-fields.md) — every `stack.yaml` field and the `extends:` merge table.
- [services.md](services.md) — when a sidecar is the answer, and the two service scopes.
- `docs/guides/recipe-authoring.md`, `stacks.md`, `extending-stacks.md`, `service-authoring.md`,
  `egress.md`, `secrets.md` — the long-form guides (present only in `main/`; `docs/` is the wiki
  clone and is not populated in a task worktree).
- `src/harnessed/schema.py` — the typed models. Code wins on any conflict with prose.
