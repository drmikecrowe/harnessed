# Backend Abstraction — Composition × Execution

> **Container-primary.** Containers and devcontainers get the investment; the host backend is a
> maintained secondary — the fast local path and the auth escape hatch. Companion to
> [ARCHITECTURE.md](ARCHITECTURE.md) (what the words mean) and
> [docs/harnessed-design.md](docs/harnessed-design.md) (why the system is shaped this way).

## 1. The insight

The `--host` spike surfaced a false binary. We kept framing the choice as **host vs. container**,
when isolation is not *the* choice — it is one **axis**. harnessed's durable value is the
**composition layer** (recipes → stacks → reusable agent systems). *Where* a composed stack runs —
naked host, sandboxed host, container, devcontainer, microVM — is a pluggable **execution backend**.

> harnessed = one composition model targeting N execution backends.

None of the comparable tools (harness-coding, openharness, clawker, aerovato/container) separate these
two concerns; each hard-wires a single container backend. Separating them is the differentiator.

```
        ┌───────────────────────────────────────────────┐
        │   COMPOSITION LAYER  (harnessed's real value)   │
        │   recipes → stacks → reusable agent systems     │
        │   skills · commands · rules · MCP · tools · id   │
        └────────────────────────┬────────────────────────┘
                                 │  one composed stack
        ┌──────────┬─────────────┼─────────────┬──────────┐
        ▼          ▼             ▼             ▼          ▼
      host     bwrap+       container     devcontainer  microVM
             landlock       (podman)      (emit json)
                        ── EXECUTION BACKENDS ──
```

This reframes the `--host` work: it is **not a pivot away from containers**, it is **backend #2**.
The container path stays as backend #1. The user picks a backend per stack, per need (fast local vs.
IDE-integrated vs. locked-down CI).

## 2. The isolation spectrum (backend menu)

| Backend | Isolation | Reproducible env | Host integration | IDE | Cost |
|---|---|---|---|---|---|
| **host (naked)** | none | host toolchain | full | runs on host | trivial |
| **bwrap + landlock** | FS + network + PID (process) | ✗ — host libs/tools | high (same host, fenced) | host IDE works | low |
| **container (podman)** | full (own rootfs) | ✅ pinned image | via mounts | attach only | medium |
| **devcontainer** | full − holes the json opens | ✅ pinned image | mounts + IDE | first-class | medium |
| **microVM (Firecracker/Kata)** | kernel-level | ✅ | minimal | remote | high |

Notes:
- **bwrap/landlock** buys *isolation without reproducibility*: it fences a host process (FS view via
  bubblewrap mount namespaces; per-path/per-port rights via the Landlock LSM, kernel ≥ 5.13, network
  ports ≥ 6.7) but runs the host's own binaries. This is the [`srt`/Codex] pattern (bubblewrap +
  seccomp on Linux, Seatbelt on macOS). Egress is coarse (port-level / all-or-nothing) — domain
  allowlisting still needs a proxy/DNS layer.
- **devcontainer** IDE hooks *soften* the boundary: `initializeCommand` runs on the **host**, and the
  repo-committed `devcontainer.json` can bind-mount host paths, mount the Docker socket, forward
  ports, and set `remoteUser`. The permission surface moves into a (possibly untrusted) repo file —
  hence VS Code Workspace Trust. Full isolation *minus whatever the json opens*.

## 3. The backend interface (contract)

Every backend implements the same seam so a composed stack can run on any of them:

| Capability | What the backend must do |
|---|---|
| **materialize config** | Deliver the assembled profile to where the harness reads it (bind-mount, copy, or symlink) — the `.claude/*` tree for claude, the harness's own shape otherwise (omp: `APPEND_SYSTEM.md` / `RULES.md` / `mcp.json` / `config.yml` in its agent dir). |
| **provision tools** | Make tools resolvable to the harness: `install:` scripts run on first start (fingerprint-gated), `setup.script` at attach time. Container: baked into the image or run via `podman exec`; host: written to the stack's `$HARNESSED_BIN_DIR`. |
| **wire MCP** | Present the stack's MCP servers to the harness (native `.mcp.json`, or hatago hub). |
| **seed auth** | Give the harness the host's credentials **by reference** — bind-mount or symlink the live store, never a copy or snapshot (CLAUDE.md non-negotiable). A backend that cannot reference the live store must fail rather than replicate it. |
| **wire services** | Stand up service-backed dependencies and route the harness to them (pod netns, compose, or N/A). |
| **apply isolation** | Enforce the backend's isolation level (none / landlock / container / VM). |

The seam is `harnessed.backend.ExecutionBackend`. `launcher.HostBackend` and
`launcher.ContainerBackend` are the two conforming implementations; `_launch_host` and
`container_run` are their sequencers.

**The host backend is not claude-only.** It runs any harness that exposes one lever: an env var
whose value *is* a per-stack config/agent dir. `launcher._HOST_HARNESSES` is the record of them —
`CLAUDE_CONFIG_DIR` for claude, `PI_CODING_AGENT_DIR` for omp — pairing that var with the harness's
live host dir and with what it deliberately shares back (claude: `.credentials.json` + session dirs;
omp: `agent.db` + `sessions/`/`blobs/`/`memories/`/`history.db`). A harness is absent from that
record because its row has not been established, not because host mode is claude-shaped.

**Sequencing is backend-owned.** The contract is a capability set, not a pipeline — there is no
shared driver calling the six in a fixed order, because the two implementations do not agree on one
and cannot be made to without changing behavior. The host backend materializes before it provisions
(materializing rmtree's the dir installs write into); the container backend provisions before it
materializes (podman's copy-up populates the volume the mount set then delivers). Two capabilities
are two-phase for the same kind of reason and take a phase argument: *provision tools* runs
`install:` at first start and `setup.script` at attach, and *apply isolation* stands the boundary up
before setup scripts run and closes egress after, since a first-run setup is the step that needs the
network. A backend implements the capabilities and orders its own launch.

## 4. Recipe-capability × backend matrix

Not every recipe primitive is honored on every backend. Where one is not, the launch still
**succeeds** and the declaration is simply inert — silence, not breakage — so the launcher names the
gap.

**The matrix lives in `harnessed.capmatrix`, not here.** This section is a pointer on purpose:
**a table no test reads rots.** A prose matrix drifts from the code silently, claiming a backend
cannot do something it has done for months, and nothing fails when it does. `capmatrix.MATRIX` is
read by conformance tests that fail if a registered backend has no column or a primitive has no
cell, so a new backend must fill its column deliberately.

Exactly one cell is DEGRADED: **`egress:` on `host`**, because `HostBackend.isolation` is `none`
and `apply_isolation` does nothing — the allowlist is not enforced. Everything else the two built
backends can do, they both do.

Two gaps that look like matrix cells are handled better elsewhere, and `capmatrix` deliberately
stays out of their way:

- **The container-only half of `install:`** — `install.system` is an author-written reason for what
  a host launch does not get. `schema.validate_container_only_declared` refuses to let a recipe with
  an `install:` leave a Dockerfile `RUN` undeclared, and the host launcher prints the reason
  verbatim. That is strictly more informative than a generic "unsupported" line.
- **Supply-chain scan** — a property of what is scanned, not of what a recipe declares.
- **Claude-shaped `skills:` under `host` + `omp`** — the claude-hooks bridge covers command hooks
  only, and omp's own skill surface (`managed-skills`) is a format harnessed does not emit, so a
  stack's skills land in the profile and are read by nothing on that path. Real, and inert in
  exactly capmatrix's sense — but its key is (backend, **harness**), and `MATRIX`'s axis is the
  backend alone. Bending the table into two dimensions for one cell would cost every other cell a
  harness column it does not need, so `launcher._note_host_omp_skill_gap` states it at launch
  instead, in the same `[INFO]` register. **`hooks:` are NOT in this gap** — they are delivered, via
  the bridge and the per-stack `CLAUDE_CONFIG_DIR` the launcher exports for omp.

Aspirational columns for the unbuilt backends are kept out of the code table for the same reason
this section stopped being the matrix: a cell nothing can verify is a claim, not a fact.

## 5. How the three headline props redistribute

- **Composition** — backend-independent. Always harnessed's. The real product.
- **Isolation** — a backend *capability* (none → landlock → container → VM). Not intrinsic.
- **Reproducible pinned env** — a backend *capability* (host toolchain vs. pinned image). Not
  intrinsic. Container/devcontainer/microVM have it; host/bwrap do not (leaf tools pinned via
  `install:` / `setup.script`, substrate is the host — pin the runtime via mise to narrow the gap).

Consequence: **supply-chain scanning changes role by backend.** In a container it is a containment
boundary; on a (sandboxed) host it is advisory hygiene ("warn before installing a bad pinned tool").
Both are worth having; describe them honestly per backend.

## 6. Standing decisions

- **Container-primary.** Containers and devcontainers get the investment. The host backend is a
  maintained secondary — the fast local path and the auth escape hatch — not a replacement and not
  a target for new features.
- **Container auth is a host token proxy**, over a bind-mounted unix socket: one refresher, zero
  divergence. Not per-instance credential copies, which go stale on the idle side and present as a
  silent logout, and not a shared read-write mount.
- **The folder-env contract is unified.** A recipe's `env:` with `{persist:…}` references resolves
  to the mode-correct path — bind-mount target in a container, host persist dir on a host launch.
  One declaration, both modes; no container-only `ENV` entries in Dockerfiles.
- **First-run setup refuses rather than guesses.** When a prompted config item has no TTY, fail
  with guidance. A forever-value — a tracker prefix, an account id — must never be set by silence.

## 7. Open questions

- **Does devcontainer subsume bespoke podman?** Compose-for-services and bespoke egress are the
  gaps to test.
- **Domain-level egress** on host and sandboxed-host backends needs a proxy/DNS story, or is
  declared out of scope for those backends.
- **The `--backend` selection surface**: a per-stack default in `stack.yaml`, a CLI override, or
  both.
