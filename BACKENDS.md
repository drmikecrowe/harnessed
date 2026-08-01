# Backend Abstraction — Composition × Execution

> **Status:** Direction confirmed 2026-07-19 (host-native-spike branch, PR #127): **product-for-
> others, container-primary** (see §7). Containers/devcontainers get the investment; the host
> backend stays as a maintained secondary. Companion to
> [docs/harnessed-design.md](docs/harnessed-design.md) (the container-era "why"); fold into the
> wiki once the `run` verb + capability matrix settle.

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
| **materialize config** | Deliver the assembled `.claude/*` profile (skills/commands/rules/CLAUDE.md/settings) to where the harness reads it (bind-mount, copy, or symlink). |
| **provision tools** | Make tools resolvable to the harness: `install:` scripts run on first start (fingerprint-gated), `setup.script` at attach time. Container: baked into the image or run via `podman exec`; host: written to the stack's `$HARNESSED_BIN_DIR`. |
| **wire MCP** | Present the stack's MCP servers to the harness (native `.mcp.json`, or hatago hub). |
| **seed auth** | Give the harness the host's credentials (mount, symlink, or copy). |
| **wire services** | Stand up service-backed dependencies and route the harness to them (pod netns, compose, or N/A). |
| **apply isolation** | Enforce the backend's isolation level (none / landlock / container / VM). |

`launcher._launch_host` is today's ad-hoc implementation of this seam for the host backend;
the container `launch` path is the implementation for the podman backend. The work is to name the
seam explicitly and make both (plus future backends) conform.

## 4. Recipe-capability × backend matrix

Not every recipe primitive is honorable on every backend. The assembler should **warn or refuse**
when a stack uses a primitive its target backend cannot satisfy (build on the existing
capability-test oracle). This gate is not built yet — it is tracked as harnessed-0tk.2.

| Recipe primitive | host | bwrap | container | devcontainer |
|---|:-:|:-:|:-:|:-:|
| `.claude` profile (skills/commands/rules) | ✅ | ✅ | ✅ | ✅ |
| `install:` / `setup.script` (PATH tools) | ✅ | ✅ | bake in image / exec | → Feature |
| Dockerfile recipe layer | ✗ | ✗ | ✅ | ✅ |
| native `.mcp.json` (stdio) | ✅ | ✅ | ✅ / hatago | ✅ |
| service sidecars | ✗ (yet) | ✗ (yet) | ✅ pod | ✅ compose |
| egress control | landlock/proxy | landlock/proxy | netns iptables | init-firewall.sh |
| supply-chain scan | scan provision set | scan provision set | scan image | scan image/features |

Once this matrix exists, today's open questions become cells, not ad-hoc gaps:
- "What happens to Dockerfile recipes host-side?" → the cell says *unsupported; warn*.
- "Does `--host` support services?" → *not yet; tracked per backend*.

## 5. How the three headline props redistribute

- **Composition** — backend-independent. Always harnessed's. The real product.
- **Isolation** — a backend *capability* (none → landlock → container → VM). Not intrinsic.
- **Reproducible pinned env** — a backend *capability* (host toolchain vs. pinned image). Not
  intrinsic. Container/devcontainer/microVM have it; host/bwrap do not (leaf tools pinned via
  `install:` / `setup.script`, substrate is the host — pin the runtime via mise to narrow the gap).

Consequence: **supply-chain scanning changes role by backend.** In a container it is a containment
boundary; on a (sandboxed) host it is advisory hygiene ("warn before installing a bad pinned tool").
Both are worth having; describe them honestly per backend.

## 6. Sequencing (proposed)

1. **Land the host backend additively** (this branch): commit the per-project `host_home` fix; keep
   the container `launch` path intact. Host = backend #2, not a replacement.
2. **Name the seam**: extract the §3 backend interface; make `_launch_host` and the container path
   conform. (Enables everything below.)
3. **Capability matrix + assembler gate** (§4): warn/refuse on unsupported primitive × backend.
4. **`host-run` verb** (`harnessed-ltj`, shipped): `harnessed host-run claude [path]` —
   host-native launch with no podman, sharing no flags with `launch`. The general `--backend`
   selection surface (per-stack default in `stack.yaml`, unified `run` verb) remains open.
5. **Container OAuth-token freshness — host token proxy** (`harnessed-nym`, P1): the root
   frustration behind the host spike, fixed IN the container world. Per-instance credential copies
   diverge (idle side goes stale → silent logout); replace with a host-side token endpoint over a
   bind-mounted unix socket (the `guides/aws-sso.md` pattern) — one refresher, zero divergence.
   The first container investment under the container-primary decision.
6. **Evaluate devcontainer emit** (`harnessed-0tk.4`, promoted to P2): generate a
   `devcontainer.json` + Feature from a composed stack; measure how much of the bespoke layer it
   absorbs (IDE/Codespaces reach, Anthropic's blessed firewall). Decide whether it replaces or
   complements bespoke podman. *(bwrap/landlock — `0tk.3` — deferred to P4: a sandboxed-host
   backend is the personal-tool sweet spot, and the audience decision went the other way.)*
7. **Per-harness backends** (`harnessed-72j/7rh/rlw/w8k`): antigravity/codex/opencode/omp
   materialization — these are "the host/sandbox backend for harness X."
8. **Docs + web** (`harnessed-2nu`): rewrite around composition × backends once the verb + matrix
   settle (avoid documenting a moving interface twice).

## 7. Decisions (2026-07-19) and remaining open questions

Decided (recorded on the beads named below):

- **Audience** (`0tk.5`, closed): **product-for-others, container-primary.** Containers/
  devcontainers get the investment; the host backend stays as a maintained secondary (fast local
  path + auth escape hatch), no new feature investment; bwrap deferred.
- **Container auth** (`harnessed-nym`, P1): host token proxy over a bind-mounted unix socket — not
  per-instance copies, not a shared rw mount.
- **beads dolt-server placement** (`0tk.6`, closed): per-project `beads-server` sidecar is the
  PRIMARY placement; the host shared-server survives only as what `harnessed host-run` uses today.
  `0tk.6` detect+abort guards the seam between them.
- **Unified folder-env contract** (`0tk.7`, closed): recipe `env:` with `{persist:…}` references
  resolves to the mode-correct path (bind-mount target in a container, host persist dir on
  `harnessed host-run`) — one declaration, both modes. Static container-only `ENV` entries in
  Dockerfiles replaced.
- **Non-TTY first-run setup** (`0tk.8`, closed): refuse with guidance when a prompted config item
  has no TTY — a forever-value (e.g. the beads issue prefix) is never set by silence.

Still open:

- **Does devcontainer subsume bespoke podman?** Compose-for-services and bespoke egress are the gaps
  to test (`0tk.4`).
- **Domain-level egress** on host/bwrap backends needs a proxy/DNS story (clawker-style) or is
  declared out of scope for those backends.
- **`--backend` selection surface**: per-stack default in `stack.yaml`? CLI override? Both?
  (Decide inside the unified `run` verb work, `harnessed-ltj`.)
