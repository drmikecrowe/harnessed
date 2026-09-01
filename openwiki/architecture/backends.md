---
type: architecture
title: "Execution backends: the capability contract and why there is no shared driver"
description: "The backend.ExecutionBackend seam — six capabilities (materialize config, provision tools, wire MCP, seed auth, wire services, apply isolation), backend-owned sequencing with no shared driver, the two-phase capabilities FIRST_START/ATTACH and BOUNDARY/EGRESS, LaunchSpec versus backend-instance state, the registry, and the module-boundary rule that keeps backend.py free of launcher imports."
tags: [execution-backends, backend-contract, capability-set, sequencing, launchspec, provision-tools, apply-isolation, seed-auth, capmatrix, module-boundaries, hostbackend, containerbackend]
verified:
  - by: openwiki/0.4.3
    at: 2026-09-01T11:08:21.365Z
sources:
  - id: openwiki-source-f2bd22307a3451ac2519580c
    resource: repo://BACKENDS.md
  - id: openwiki-source-f566bbdd90ebc6ec3b85626a
    resource: repo://src/harnessed/backend.py
  - id: openwiki-source-9a53d80e292611f0100f90b1
    resource: repo://src/harnessed/capmatrix.py
  - id: openwiki-source-3d73552d55725e6e392c06df
    resource: repo://src/harnessed/hosthome.py
  - id: openwiki-source-154371253083f8b9b656eefa
    resource: repo://src/harnessed/hostrun.py
  - id: openwiki-source-ecbe6256d6933ca2c8c9678f
    resource: repo://src/harnessed/launcher.py
  - id: openwiki-source-7536da5c015fc2813c7693c5
    resource: repo://src/harnessed/schema.py
generated: { by: "openwiki/0.4.3", at: "2026-09-01T11:08:21.365Z" }
---

# Execution backends: the capability contract and why there is no shared driver

harnessed's product is the **composition layer** — recipes compose into stacks. *Where* a composed
stack runs (naked host, container, devcontainer, microVM) is a pluggable **execution backend**, and
isolation is one of that backend's **capabilities**, not a property of the product.

The seam is [`src/harnessed/backend.py`](repo://src/harnessed/backend.py). It names six capabilities
every backend implements, so a new backend is a class to write rather than a fork of the launch path.
**`BACKENDS.md` §3 is the authority for the vocabulary**: the six capability names are its, verbatim —
`materialize config` / `provision tools` / `wire MCP` / `seed auth` / `wire services` /
`apply isolation` — and `backend.py`'s own docstring forbids renaming them there without renaming
them in `BACKENDS.md`. This page follows that vocabulary and does not invent synonyms.

Related: [architecture overview](overview.md),
[invariants](/openwiki/concepts/invariants.md),
[container-run](/openwiki/workflows/container-run.md),
[host-run](/openwiki/workflows/host-run.md).

## The six capabilities

`ExecutionBackend` is an ABC with six abstract methods, each corresponding to one row of
`BACKENDS.md` §3:

| Capability (BACKENDS.md §3) | Method | What the backend must do |
| --- | --- | --- |
| **materialize config** | `materialize_config(spec)` | Deliver the assembled profile to where the harness reads it — bind-mount, copy, or symlink; the backend picks. Includes folding the host's live preferences into the emitted settings, which is a **per-launch recomputation on both existing backends**, not a function of the recipe closure the fingerprint covers. |
| **provision tools** | `provision_tools(spec, phase)` | Make tools resolvable to the harness. `FIRST_START` is the fingerprint-gated `install:`/`tools:` work; `ATTACH` runs each recipe's `setup.script`. |
| **wire MCP** | `wire_mcp(spec)` | Present the stack's MCP servers to the harness — native `.mcp.json`, or the hatago hub. Wiring only; waiting for a hub to become healthy is a **readiness gate, not part of the contract** (the same way a service sidecar's health check is not part of `wire_services`). |
| **seed auth** | `seed_auth(spec)` | Give the harness the host's credentials **by reference** — mount or symlink the live store, never a copy or snapshot. A backend that cannot reference a live store **must fail rather than snapshot one**. |
| **wire services** | `wire_services(spec)` | Stand up the stack's service sidecars and route the harness to them. A `services:` entry is a property of the **stack**, not of the backend: a host-native agent still needs the service its stack declares. |
| **apply isolation** | `apply_isolation(spec, phase)` | Enforce this backend's isolation level (BACKENDS.md §2's spectrum). `BOUNDARY` stands the boundary up; `EGRESS` closes the network once first-run provisioning has had it. |

Two ClassVars sit alongside the methods: `name` (the user-facing backend name, also the registry key)
and `isolation` (what §2's isolation spectrum says this backend gives you — **declared, not enforced
here**). `ISOLATION_NONE` and `ISOLATION_CONTAINER` are the two constants; `isolation` is explicitly
*not* an enum the code branches on — it exists so `harnessed` can state what a backend gives you
without launching it.

## Sequencing is backend-owned

This is the load-bearing decision, and the reason the contract is a **capability set rather than a
pipeline**. There is deliberately **no shared driver** that calls the six in a fixed order, because
the two implementations that exist today do not agree on one and **cannot be made to without
changing behavior**:

- The **host** backend materializes before it provisions. `_materialize_host_home` wipes the config
  dir, so an install that ran before it would have its output deleted milliseconds later — silently
  (that is exactly how bd harnessed-8px.1 lost 14 skills with no error).
- The **container** backend provisions **before** it materializes. `provision_tools(FIRST_START)`
  composes the config and tools volumes, and **podman's copy-up is what lifts the image's `~/.claude`
  into the volume that the mount set — composed by `materialize_config` — then delivers**. Reversing
  those two steps produces a volume the mounts reference before it exists.

```mermaid
flowchart TB
    subgraph HOST["host backend - sequenced by _launch_host"]
        H1["wire_services"] --> HL["home lock taken"]
        HL --> H2["materialize_config"]
        H2 --> H3["seed_auth"]
        H3 --> H4["provision_tools FIRST_START"]
        H4 --> HU["lock released"]
        HU --> H5["provision_tools ATTACH"]
        H5 --> H6["wire_mcp"]
        H6 --> H7["apply_isolation BOUNDARY"]
        H7 --> H8["apply_isolation EGRESS"]
    end
    subgraph CTR["container backend - sequenced by container_run"]
        C1["wire_services"] --> C2["provision_tools FIRST_START"]
        C2 --> C3["materialize_config"]
        C3 --> C4["seed_auth"]
        C4 --> C5["wire_mcp"]
        C5 --> C6["apply_isolation BOUNDARY"]
        C6 --> C7["provision_tools ATTACH"]
        C7 --> C8["apply_isolation EGRESS"]
    end
```

*What each sequencer's capability order looks like. The host's `apply_isolation` calls are no-ops on
that backend (isolation `none`); they are made anyway so the host path exercises the whole contract
rather than quietly implementing five sixths of it. Non-contract sequencer steps (assembly, aoe
registration, env setup, the re-attach branch, the CA install between `BOUNDARY` and `ATTACH` on the
container path) are elided.*

A backend therefore **implements the capabilities and orders its own launch**. What a fixed-order
driver would break is precise: it would have to reorder one of the two existing paths, and reordering
either is a behavior change wearing a refactor's clothes. Anyone tempted to add `def
drive(backend, spec)` should read the host and container orders side by side first.

The two conforming implementations live in `launcher.py`:

| | verb | class | sequencer |
| --- | --- | --- | --- |
| backend #1 | `harnessed container-run` | `launcher.ContainerBackend` (`isolation = ISOLATION_CONTAINER`) | `launcher.container_run` |
| backend #2 | `harnessed host-run` | `launcher.HostBackend` (`isolation = ISOLATION_NONE`) | `launcher._launch_host` |

The verb picks the backend and nothing else; both share one grammar and one stack-resolution path
(`launcher._resolve_stack` — they "differ in backend, never in how a stack is chosen", bd
harnessed-s84). Neither backend is a subclass of the other, and neither inherits a launch order.

## The two-phase capabilities, and why they take a `phase` argument

Two of the six capabilities have **two moments on both backends**, which is why they carry a phase
argument rather than collapsing into one call.

### `provision_tools(spec, FIRST_START | ATTACH)`

`backend.py` names the constants and the module docstring quotes §3's own wording: *"`install:`
scripts run on first start (fingerprint-gated), `setup.script` at attach time."*

| | FIRST_START | ATTACH |
| --- | --- | --- |
| **host** | `tools:` then `install:` (`_host_install_tools`, `_host_run_installs`), gated on `self.rebuilt`; the fingerprint stamp is written only after the installs succeed | `_host_run_setups` then `_host_run_inits` |
| **container** | `_ensure_stack_volumes` — composes **both** volumes in one call, because podman's copy-up populates them together | `_run_container_setups` — `podman exec` each pending script |

The host's lock discipline is the reason the two phases cannot merge. `_launch_host` takes the
`_host_home_lock` **across** `materialize_config`, `seed_auth` and `provision_tools(FIRST_START)`,
then releases it **before** calling `provision_tools(spec, ATTACH)`. Both halves are deliberate:

- Holding the lock across the rebuild *and* the installs is what stops a second launch from seeing a
  matching stamp, skipping installs, and exec'ing the agent while the first launch's install scripts
  are still writing into the same dir.
- Releasing it before ATTACH is not a leak — it is the point. **A setup script can prompt, and
  holding an exclusive `flock` across a TTY prompt would hang any concurrent launch of the same
  stack.** Attaching is not logically once-per-stack the way an install is, so it cannot sit inside
  the same critical section.

The container path reaches the same split by a different route: FIRST_START is a volume compose that
runs **before the container exists**, ATTACH is `podman exec` that runs **after it does**. There is
no ordering in which those are one call.

### `apply_isolation(spec, BOUNDARY | EGRESS)`

`BOUNDARY` stands the boundary up; `EGRESS` closes the network once first-run provisioning has had
it. They are separate **because a first-run setup script is exactly the step that needs the
network** (it downloads language servers, toolchains, and so on), so egress closes *after* it.

On the container backend `BOUNDARY` is doing double duty, and this is the subtlest fact on the page:
**the single `podman run` is both the isolation boundary and the only way mounts and env cross it.**
That is why the container's env assembly (folder-env contract, setup env, recipe env, mise trust,
`HATAGO_TRANSPORT`, `--env-file`, `member_mounts`) lives inside `apply_isolation(BOUNDARY)` rather
than in `materialize_config`. The setup env is resolved there too, because a `setup.config` item may
prompt and that must happen before the container starts.

`EGRESS` runs `_apply_firewall` with the union of the recipes' `egress:` domains (default-DROP
otherwise). Its failure semantics are **fail-closed twice over**: a non-zero exit from the firewall
runner refuses to continue (`NO_FIREWALL=true` is the supported way to say "I do not want one"), a
zero exit is then *verified* by asserting the observable OUTPUT policy really is DROP (#429 — the
script once returned 0 while installing nothing, 43 runs running "Egress active" with no firewall),
and any `BaseException` — including Ctrl-C and an `OSError` from a missing podman — tears the pod
down first and then re-raises, because leaving the thing you could not confine running would be
quieter than the old hang and no safer.

On the host backend `apply_isolation` does **nothing in either phase**, because `isolation` is
`none`. That is the contract being honored, not skipped — the host launch is deliberately the escape
hatch with the host's own auth, filesystem and network, and §4 records host egress control as the
future bwrap backend's job (harnessed-0tk.3), not this one's. The sequencer still calls both phases.

## `LaunchSpec` is composition-layer input only

`LaunchSpec` is a frozen dataclass holding exactly what a launch *is*, independent of where it runs:
`stack`, `harness`, `project_path`, `extra`, `no_strict_mcp`, `ephemeral`. Everything in it is
composition-layer input — the stack, the harness reading it, the project it runs against, and the
flags that survive into the agent's own argv.

Backend-specific state — podman instance and pod names, the host config dir, resolved mount args,
whether the host home was rebuilt, the agent's argv, the pending setup list, the resolved
`--env-file` list — lives on the **backend instance** instead. Both classes say so explicitly, and
the reason is the same design decision as the missing driver:

> a field only one backend can honor is a fixed-order driver in disguise.

`HostBackend.__init__(recipes)` carries the recipe closure for the fingerprint gate plus `home`,
`cwd`, `rebuilt`, `argv`. `ContainerBackend.__init__(...)` carries `rt`, `inst`, `pod`, `prof`,
`harness_image`, `mount_path`, the recipe closure, the resolved server set, and accumulates
`mount_args`, `member_mounts`, `config_volume`, `tools_volume`, `pending_setups`,
`secrets_env_files`. If any of that moved into `LaunchSpec`, the spec would begin encoding one
backend's order into a shared type.

Ordering between operations is likewise **enforced by the sequencer, not the contract**: the
implementations use `assert` with an "ordering enforced by caller" note (`seed_auth` and
`wire_mcp` before `materialize_config`, `materialize_config` before `provision_tools`) purely as
type-narrowing. The ABC does not and must not model a call order.

## The registry

Backends are addressed by name:

- `@register` — class decorator; stores the class under `cls.name`. Bound with a `TypeVar` so the
  decorator returns the **decorated** class, not `type[ExecutionBackend]` — otherwise every
  backend's own `__init__` signature and attributes vanish at the call site. Both `HostBackend` and
  `ContainerBackend` use it.
- `get_backend(name)` — returns the registered class; raises `KeyError` **naming what is available**.
- `registered()` — every backend by name, as a **copy**: the registry is not a mutable public
  surface.

## The module-boundary rule

`backend.py` imports nothing from `launcher.py` and never will, and `capmatrix.py` makes the same
pledge. Both cite `tests/test_module_boundaries.py` as the enforced boundary. (That file lives under
`tests/`, which is outside this wiki's read boundary — the citation is carried from the source
comments, where it is the authority.)

The direction of the dependency is the point: the **implementations live in `launcher.py`, beside
the ~100 private helpers they call**, so the dependency points *into* the contract and the seam adds
no import cycle. `launcher.py` imports the contract (`ExecutionBackend`, `LaunchSpec`, the phase and
isolation constants, `register`); `backend.py` imports only `abc`, `dataclasses`, `pathlib` and
`typing`.

This is one instance of the repo-wide dependency-direction invariant: modules that name a contract
do not import the modules that implement it.

## `seed_auth`: referenced, never replicated

The contract's own docstring states the non-negotiable, attributed to `CLAUDE.md`'s constraints
(spelled out at length in `ARCHITECTURE.md` §Constraints):

> Give the harness the host's credentials by REFERENCE — mount or symlink, never a copy.
> A backend that cannot reference a live store must fail rather than snapshot one.

The reason is structural, not stylistic: a harness **rewrites its own credential store on token
refresh**, so any copy harnessed makes rots the moment either side refreshes and the next launch
restores the stale one — a silent logout. "Copy it back if it is newer" is still replication; it just
moves the race.

What "reference" means concretely is the harness's own business, and on the host backend it lives in
the harness's `HostHarness.share_state` row: claude shares `.credentials.json` plus the session dirs
(omp's `agent.db` plus `sessions/`/`blobs/`/`memories/`/`history.db`). A corollary decides whether a
symlink is even available: it is a reference **only while the harness writes in place**. SQLite
rewrites `agent.db` in place so the omp link holds; claude *replaces* `.credentials.json`, which is
why the host path needs a credential **rescue** inside `materialize_config` (bd harnessed-8px.10)
rather than trust in the link. See [credentials](/openwiki/concepts/credentials.md) for the whole SOP.

On the container backend, `seed_auth` resolves launch-time secrets and appends the Claude credential
mount **last**, with a known imprecision tracked as **harnessed-0tk.1.1**: several credential mounts
are composed in `materialize_config` rather than here. They are emitted as one ordered block today,
and this repo's suite runs no `podman run` at all, so regrouping podman `-v` arguments would be an
unverifiable change to the one path no test exercises. The block moves verbatim; splitting it is its
own change with its own evidence.

## The capability matrix (`capmatrix`)

Not every recipe primitive is honored on every backend. Where one is not, **the launch still succeeds
and the declaration is simply inert** — silence, not breakage. [`harnessed.capmatrix`](repo://src/harnessed/capmatrix.py)
is the machine-checked record, deliberately not duplicated in prose:

> A table no test reads rots. BACKENDS.md §4 — the prose version — went stale without anyone noticing:
> it still recorded `service sidecars — host: ✗ (yet)` long after `HostBackend.wire_services` started
> calling `_ensure_services`.

`capmatrix.MATRIX` maps backend name → primitive → `SUPPORTED` or `DEGRADED`. `PRIMITIVES` —
`skills`, `tools`, `install`, `setup_script`, `servers`, `services`, `egress` — is the row axis the
conformance tests iterate, so **adding a primitive without filling its cells is a test failure, not a
silent default**, and a new backend must fill its column deliberately rather than inherit silence.
**Exactly one cell is `DEGRADED` today: `egress` on `host`**, because `HostBackend.isolation` is
`none` and `apply_isolation` does nothing. Everything else the two built-in backends can do, they
both do.

Three properties of the table that matter when extending it:

- **`gaps(backend, recipes)` raises `KeyError` for an unknown backend rather than returning `[]`.**
  An empty result must mean "checked, nothing to report" — returning it for a name nobody has a
  column for would report silence about a backend that was never examined, which is the exact
  failure this table exists to prevent. A `DEGRADED` cell whose detail nobody wrote falls back to a
  generic string rather than raising (`test_every_degraded_cell_has_a_detail` fails the build for the
  developer error; the diagnostic must not abort someone's launch).
- **The container-only half of `install:` is deliberately not a cell.** `install.system` is an
  author-written reason that `schema.validate_container_only_declared` **refuses** to let a recipe
  with an `install:` omit when its Dockerfile still has a `RUN`; the host launcher prints that reason
  verbatim. That is strictly more informative than a generic "unsupported" line, and firing both
  would train people to ignore both.
- **The host omp `skills:` gap is keyed (backend, harness), and `MATRIX`'s axis is the backend
  alone.** Bending the table into two dimensions for one cell would cost every other cell a harness
  column it does not need, so `launcher._note_host_omp_skill_gap` states it at launch instead — same
  `[INFO]` register, same reason. Hooks are **not** in that gap: they are delivered, via the
  claude-hooks bridge and the per-stack `CLAUDE_CONFIG_DIR`.

The gap warning itself is emitted by `launcher._warn_capability_gaps` (bd harnessed-0tk.2) at
**launch**, before anything is materialized, because that is where a concrete backend exists —
`harnessed assemble` has a harness, not a backend. The level is `[INFO]`, not `WARNING` (#359): the
terminal-acknowledge gate counts the word WARNING and holds for a keypress, so a WARNING-level line
would cost every `host-run` of an `egress:`-declaring stack an extra Enter, for a gap the user chose
by typing `host-run` and cannot fix on that backend.

## The host backend is not claude-only

`launcher._HOST_HARNESSES` is the record of harnesses the host backend can run: `claude`
(`CLAUDE_CONFIG_DIR`) and `omp` (`PI_CODING_AGENT_DIR`). The gate is a single lever — an env var
whose value *is* a per-stack config/agent dir — plus `argv0` and a `share_state` callable. A harness
absent from that record is absent because its row has not been established, not because host mode is
claude-shaped. Adding a harness is filling in a row (plus one branch in `_host_launch_plan` for its
directory shape), not threading a second `if harness ==` through five call sites.

## Extension points

- **A new backend** (bwrap+landlock, devcontainer-emit, microVM): subclass `ExecutionBackend`,
  implement the six capabilities, decorate with `@register`, and **sequence your own launch**. Fill
  in a `capmatrix.MATRIX` column deliberately — the conformance tests iterate `PRIMITIVES` and fail
  on an unfilled cell. Aspirational columns for unbuilt backends stay out of the code table for the
  same reason §4 stopped being the matrix: a cell nothing can verify is a claim, not a fact.
- **A new harness on the host backend**: add a `HostHarness` row to `_HOST_HARNESSES` plus the
  `_host_launch_plan` branch for its directory shape, and the corresponding rows in
  `hostrun._HARNESS_CONFIG_DIR_ENV`.
- **A new recipe primitive**: add it to `PRIMITIVES` *and* every column, in the same change — the
  test failure is the feature.
- **Do not** add a shared driver, and do not add a backend-only field to `LaunchSpec`. Both are the
  same mistake in different clothes.

## Related

- [BACKENDS.md](repo://BACKENDS.md) — the authority for the contract vocabulary, the isolation
  spectrum, and the standing decisions (container-primary; container auth as a host token proxy; the
  unified folder-env contract; first-run setup refuses rather than guesses).
- [architecture overview](overview.md) — where the seam sits in the module graph.
- [container-run](/openwiki/workflows/container-run.md) and
  [host-run](/openwiki/workflows/host-run.md) — the two sequencers step by step.
- [invariants](/openwiki/concepts/invariants.md) — the fail-closed firewall, the composed config
  volume, and the other deliberate deviations a backend author must not "clean up".
- [credentials](/openwiki/concepts/credentials.md) — the referenced-never-replicated SOP behind
  `seed_auth`.
