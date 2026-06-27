# Immediate / high-priority TODOs

High-priority, confirmed work items — verified against the code, not speculative. Each entry
records the problem, why it matters, and the intended fix so it can be picked up without re-deriving.

---

## 1. `settings.json` must be the post-install artifact, not a from-scratch stub

**Status:** confirmed bug · **Area:** assembly / launch · **Files:** `src/harnessed/emit.py`,
`src/harnessed/launcher.py`

**Problem.** Harnessed generates `settings.json` from scratch at *assemble* time
(`emit.write_settings_json`, `emit.py:59`) containing only the hatago permission grant
(`{"permissions": {"allow": ["mcp__hatago"]}}`), then bind-mounts it **read-only over**
`~/.claude/settings.json` in the container (`launcher.py:408–411`). This **masks** whatever a
recipe's installer wrote to `~/.claude/settings.json` during the image build (hooks, permissions,
etc.). Recipes whose installers update `settings.json` (e.g. hyperpowers, context-mode, agentmemory)
silently lose those changes at runtime.

**Why it matters.** It violates the project's core principle — *replicate the installer, don't
reinterpret it.* `settings.json` is part of what an installer legitimately produces; harnessed must
preserve the artifact that exists **after all recipe Dockerfile steps complete**, not overwrite it.

**Contrast (the asymmetry to fix).** Extension *dirs* (`skills/commands/plugins/agents/hooks/rules`)
are already handled correctly: `_merge_baked_extensions` (`launcher.py:278`) copies image-baked
contents into the profile, then the merged dir is mounted — a union of `baked ⊕ generated`.
`settings.json` is a file, not in `_EXT_SUBDIRS`, so it gets no merge — it's replaced.

**Fix.** Move the final `settings.json` resolution to the **post-build** stage (only point the image
artifact exists), alongside `_merge_baked_extensions`:

```
final settings.json = deep_merge(
    <built image>:~/.claude/settings.json,        # post-install artifact — authoritative
    { permissions: { allow: ["mcp__hatago"] } }   # harnessed's sole required addition (union the array)
)
```

- Deep-merge (JSON), unioning `permissions.allow` rather than replacing it.
- Write the merged result into the profile's `settings.json`, replacing the emit-time stub; the
  existing mount (`launcher.py:408–411`) then carries the correct file.
- Keep `emit.write_settings_json` as the fallback for stacks where no recipe baked a `settings.json`.

**Note.** This closes the corrected "GAP 2" from
[2026-06-27-recipe-stress-test.md](2026-06-27-recipe-stress-test.md) — the real issue is *not* a
`recipe.yaml` `hooks:` field (that would re-declare what installers already do); it's that harnessed
must merge, not clobber, the installer-written `settings.json`.

---

## 2. Recipes must declare persistent data folders → harnessed bind-mounts them

**Status:** confirmed gap · **Area:** recipe schema / launch / authoring · **Files:**
`src/harnessed/schema.py`, `src/harnessed/launcher.py`, `docs/guides/recipe-authoring.md`

**Problem.** A tool's data persists today **only if it writes into the project directory** (which is
bind-mounted rw at its host path, `launcher.py:443`) — e.g. serena `.serena/`, codebase-memory
`.codebase-memory/`, tokensave `.tokensave/`. Data written **outside** the project — `~/.gbrain/`, a
global index, a cache, a tool's home-dir state — has **no persistence path**:

- The `Recipe` model (`schema.py:160–168`) has no `persist:`/`data:`/`mounts:` field — a recipe
  cannot declare which folders need to survive.
- The only rw mounts are hardcoded in `_build_mount_args` (session/history dirs, omp agent, the
  project, per-instance stubs). Nothing recipe-driven.
- Result: out-of-project tool state is ephemeral — **lost on `rm` / `--fresh`**.

**Direction.** Part of recipe authoring is identifying every folder the tool persists; the recipe
declares them and harnessed bind-mounts each to the right host folder (bind mounts under
`~/.local/share/harnessed/...`, **not** named volumes — see Consideration 3 in the stress-test doc):

```yaml
# recipe.yaml (sketch)
persist:
  - ~/.gbrain            # tool state outside the project dir
```

Harnessed creates the host dir (correct ownership, `--userns=keep-id`) and adds an rw `-v` for each.

**Open design question — persistence scope (the crux).** The host target must encode the right key:

- **Per-(stack, project)** — an index/cache *of this project* stored outside the project dir. Key by
  the same `sha1(project_path)` already used for the instance name →
  `~/.local/share/harnessed/<stack>/<project-hash>/<name>/`.
- **Per-stack / global** — personal state independent of any project (a knowledge brain like gbrain)
  → `~/.local/share/harnessed/<stack>/<name>/` (no project hash), or even shared across stacks.

The recipe author likely has to indicate the scope per folder (the tool knows whether its data is
project-scoped or global). Decide the declaration shape before implementing.

**Also a docs/process change.** `docs/guides/recipe-authoring.md` should add a step: enumerate the
tool's persistence paths (in-project → already covered; out-of-project → declare in `persist:`).

**Note.** This is the corrected "GAP 3" from
[2026-06-27-recipe-stress-test.md](2026-06-27-recipe-stress-test.md): in-project data is handled;
the real work is declaring + mounting out-of-project data, and choosing the scope key.

---

## 3. Multi-container services — wrap an existing compose file (don't re-express topology)

**Status:** confirmed gap (feature; likely needs its own design doc) · **Area:** service model /
launch · **Files:** `src/harnessed/schema.py` (`ServiceDef`), `src/harnessed/launcher.py`
(`_ensure_service`, `svc`)

**Problem.** The service model is single-container: `ServiceDef` is name/image/port/volume
(`schema.py:203–208`), and `_ensure_service` (`launcher.py:535–554`) does one `podman build` + one
`podman run -d -p <port>:<port> [-v <volume>:/data]`. It **cannot** express a real multi-container
service — the reference case is hindsight (`~/.config/hindsight/docker-compose.yml`):

- 3 containers with a dependency chain: `db (AlloyDB Omni)` → `alloydb-init` (one-shot) → `app`
- An init step (CREATE DATABASE + CREATE EXTENSION vector, alloydb_scann)
- Two ports (8888 API + 9999 control plane)
- Secrets (varlock `op://` refs → env)
- A specialized DB image

**Direction — compose-file-backed services (delegate, don't reinterpret).** The user already has a
working compose file. Re-expressing its topology in harnessed's own schema (reimplementing
`depends_on`, init ordering, healthcheck gating) is exactly the "reinterpret the install" anti-pattern
this project rejects. Instead, `ServiceDef` gains a `compose:` field (path to a compose file,
mutually exclusive with `image:`); `harnessed svc up` runs `podman compose -f <file> up -d` with
varlock-resolved env, waits on a healthcheck, and the recipe's `service:` MCP ref points at the
app's published port via `host.containers.internal:<port>`.

**Open decisions (resolve before building — candidate for a dedicated design doc):**

1. **Compose runtime dependency.** Compose-backed services need `podman compose` / `podman-compose`
   — a new host requirement *beyond bare podman*. Confirm the tool, or evaluate `podman kube play`.
   Single-image services keep working with no new dep.
2. **Secrets.** Extend the existing varlock layer (today scoped to the harness pod) to resolve
   `op://` refs into the **service** launch env passed to compose.
3. **Volumes — named vs bind (Consideration 3).** The compose file uses named volumes
   (`alloydb_data`). Rewriting to bind mounts under `HARNESSED_DATA_DIR` (per the data-dir
   convention) edges toward reinterpreting the file — decide whether to rewrite, parameterize, or
   leave named volumes as-is for compose-backed services.
4. **Networking.** Compose stack publishes ports to the host; harness reaches
   `host.containers.internal:<primary-port>`. `port:` stays required for reachability.
5. **Lifecycle surface.** Extend `harnessed svc up|down|list` to compose-backed (`up` →
   `compose up -d` + healthcheck wait; `down` → `compose down`).

**Note.** Corrected "GAP 7" from
[2026-06-27-recipe-stress-test.md](2026-06-27-recipe-stress-test.md). This is the largest item here
and the blocker for the Tier-3 hindsight recipe on the README roadmap. GAP 5 (service/recipe
boundary) folds entirely into this; the single-container `service:` path already works (see `ping`).
