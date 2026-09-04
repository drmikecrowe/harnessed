---
type: "Reference"
title: "Invariants and deliberate deviations: check before cleaning up"
description: "The catalog of constraints that read like defects but are load-bearing — each with the production failure it prevents and the bd id or issue number the source names. The page to consult before 'fixing' anything in src/harnessed/."
tags: [invariants, deliberate-deviations, fail-closed, cleanup-hazards, sequencing, naming-collisions]
verified:
  - by: openwiki/0.4.3
    at: 2026-09-01T11:08:21.365Z
sources:
  - id: openwiki-source-362e06c30ccfdafd87339cb0
    resource: repo://ARCHITECTURE.md
  - id: openwiki-source-f82224b7b5b27300d9ecc2dc
    resource: repo://catalog/base/egress-firewall.sh
  - id: openwiki-source-78685e9ff43c4c0b3dd78667
    resource: repo://src/harnessed/aoe.py
  - id: openwiki-source-78dc7c6f542f6ce83d4c2629
    resource: repo://src/harnessed/attachcmd.py
  - id: openwiki-source-f566bbdd90ebc6ec3b85626a
    resource: repo://src/harnessed/backend.py
  - id: openwiki-source-bfccb812c84b1bb2eeabf062
    resource: repo://src/harnessed/catalogseed.py
  - id: openwiki-source-6f84913afc580e4d73fac66a
    resource: repo://src/harnessed/ctrquery.py
  - id: openwiki-source-fda34f6ee97382e9146f13b4
    resource: repo://src/harnessed/dynstack.py
  - id: openwiki-source-eea4d18f75a13f889234865d
    resource: repo://src/harnessed/emit.py
  - id: openwiki-source-3d73552d55725e6e392c06df
    resource: repo://src/harnessed/hosthome.py
  - id: openwiki-source-154371253083f8b9b656eefa
    resource: repo://src/harnessed/hostrun.py
  - id: openwiki-source-ecbe6256d6933ca2c8c9678f
    resource: repo://src/harnessed/launcher.py
  - id: openwiki-source-7fc060691d30bff2ff4f6979
    resource: repo://src/harnessed/launchscript.py
  - id: openwiki-source-9e1601e7fac817552c717cd7
    resource: repo://src/harnessed/mounts.py
  - id: openwiki-source-7b2070fd28fc0a337d8c3539
    resource: repo://src/harnessed/paths.py
  - id: openwiki-source-92e9b87061358a8448b6d346
    resource: repo://src/harnessed/persist.py
  - id: openwiki-source-119d5e6ab78274e1552bbcdf
    resource: repo://src/harnessed/proc.py
  - id: openwiki-source-7536da5c015fc2813c7693c5
    resource: repo://src/harnessed/schema.py
  - id: openwiki-source-2e234f8645cb88b1fd759f98
    resource: repo://src/harnessed/setupenv.py
  - id: openwiki-source-5e89566b7a4e43a53be5c7b2
    resource: repo://src/harnessed/svcstate.py
  - id: openwiki-source-4d719c6f3a70a2ece04f213b
    resource: repo://src/harnessed/toollock.py
  - id: openwiki-source-0d783cb9b16f618063f9ca7b
    resource: repo://src/harnessed/volumes.py
generated: { by: "openwiki/0.4.3", at: "2026-09-01T11:08:21.365Z" }
---


# Invariants and deliberate deviations: check before cleaning up

This codebase carries many behaviors that look like defects: a script that refuses to set `-e`, a
variable deliberately left pointing at the user's home, a symlink-into-the-user's-store mount, a
container allowed to write a rw bind of the host's auth database, an abstract contract with six
methods and no driver calling them. Each one is load-bearing, each was paid for by a named failure,
and most name that failure in a comment (`bd harnessed-…` or an issue number). This page is the
catalog. Each entry states:

- the behavior,
- why it looks wrong,
- the failure it prevents (with the issue id where the source names one), and
- what breaks if an agent "fixes" it.

Two reading rules. First, prefer the comment at the site over any general principle: where this
page and a docstring disagree, the docstring is newer. Second, a green test suite proves almost
none of these — the hermetic suite runs no podman, so container-behavior invariants (copy-up,
userns, firewall policy) were verified in measured spikes and live runs, not in pytest. See
[the verification ladder](/openwiki/testing/verification-ladder.md) for what each rung can and
cannot hold; this page points there instead of re-deriving gates.

Related: [execution backends](/openwiki/architecture/backends.md) (the no-driver decision's full
statement), [build pipeline](/openwiki/workflows/build.md),
[container launch](/openwiki/workflows/container-run.md),
[host launch](/openwiki/workflows/host-run.md),
[harness integrations](/openwiki/integrations/harnesses.md),
[precedence rules](/openwiki/concepts/precedence.md).

| Invariant | Looks wrong because | Protects |
| --- | --- | --- |
| One composed config volume | a mount is simpler than a compose step | skill/command visibility (bd harnessed-8px.22: 70/75 skills invisible) |
| Agent-last image lineage | the standalone agent image looks like the natural parent | recipe-layer cache across agent bumps |
| `tools:`/`install:` at runtime into volumes | build layers are the idiomatic home | 307s → 4.3s on a one-line install edit (bd harnessed-8px.21.4) |
| No scan layer in the derived Dockerfile | every other pipeline scans in-build | a green scan of an image with no stack content (bd harnessed-8px.21.5) |
| Egress firewall fail-closed twice over | `set -e` is the bash default for rigor | #429: 43 runs reported "Egress active" with no firewall |
| `USERNS_ARG` pinned to uid 1000; `pod_host_uid()` returns `None` | a fallback number is friendlier than `None` | bd harnessed-rv2.1: six red CI runs; fail-open ownership guard |
| omp runs without `--profile`, rw host agent dir | sharing auth dirs looks like an isolation bug | login, usage ledger, session resume (#307) |
| `MISE_STATE_DIR` not redirected | every other mise var is redirected | the user's trust store (empty store broke every trusted config) |
| One ruamel `YAML` instance per load | a module-level instance is cheaper | parallel `-j` builds loading interleaved nonsense |
| Distinct podman timeouts; `_TIMEOUT_RC = 124` | one timeout constant is simpler | hangs routed into the existing failure branch (bd harnessed-1ao) |
| Trailing `--` on the aoe row, not in the script | a separator belongs in the file it terminates | `./claude-container --fresh` reaching the agent by accident |
| No bare `GIT_COMMON_DIR` export | the value is already in hand | git hijacking its own var when the agent `cd`s |
| dynstack's narrowed `[a-z0-9-]` alphabet | folding `_` and `.` looks gratuitous | silent join collisions onto one manifest/image/volume pair |
| No shared launch driver over the backend contract | an ABC with six methods begs an orchestrator | the two backends' orderings — a "driver" is a reorder in a refactor's clothes |
| Stale overlay symlinks are re-pointed, never user-removed | an abort looks safer than a heuristic | bd harnessed-ng5: the podman-gated suite was unrunnable |

---

## The config volume is composed, never shadowed

`_ensure_config_volume` builds one tree per `(stack, harness)`: podman's copy-up lifts the image's
own `~/.claude` into an empty named volume, then `cp -a <profile>/.claude/. …` merges the fanned
profile content on top, then installs add their output. Nothing is layered over anything by a
mount. The launcher then mounts that single volume at `~/.claude`.

It replaced per-subdir `:ro` bind-mounts of `<profile>/.claude/<subdir>` over the image's own
dirs, and the mount gate was *existence*, not non-emptiness — so an install-script-delivered tree
vanished behind the mount (bd harnessed-8px.22: **70 of 75 skills invisible, including all 34
`gsd-*`**), and an empty profile `commands/` shadowed a real baked one because
`synclinks._fan_into` creates skills/commands/rules unconditionally. The rule to keep: **never
mount a profile directory over a config subtree**. If a future change needs the agent to see
per-stack content, add it to the composition, do not re-introduce a covering mount.

Three supporting facts are just as load-bearing:

- **Copy-up runs exactly once per volume.** Thereafter volume content wins permanently and image
  updates are invisible — which is why the freshness gate `_container_stack_fingerprint` appends
  the *image ID* to the recipe-closure hash (bd harnessed-8px.21.3). Stripping the image component
  because it looks redundant with the recipe hash means a base image that gained a tool never
  reaches an existing stack and nothing signals it.
- **The populate step must use `paths.USERNS_ARG`**, the same mapping the pod is created with. A
  volume first populated under the default userns is unusable by the agent: uid 1000 inside reads
  files owned by 999 and every write EACCESes. Verified in both directions in the harnessed-8px.21.1
  spike.
- **`fresh=` may destroy the config volume only because of what it holds.** Composition is purely
  additive, so the discard-on-fingerprint-change is what stops a dropped recipe's skills lingering
  forever; it is safe because credentials and the rw history dirs are *bind-mounted over* the
  volume at launch and live on the host, not in it. If a change puts host-only state inside the
  volume, the `volume rm` in the fresh path becomes data loss.

## Agent-last image lineage

The launcher's build path states the rule three times: the standalone per-harness agent image
(`harnessed-claude`, …) is **not** the `FROM` parent of the derived stack images. The agent's
Dockerfile body is inlined as the derived image's **last** layers, and the lineage anchor is the
shared `harnessed-base` — hence "agent-last". `_build_agent_image` still runs once per process
because `container-run` falls back to the plain agent image for a stack that has no derived image
yet.

What breaks if it is "simplified" back: parentage on the per-harness agent image makes every agent
pin bump (`CLAUDE_VERSION`, `OMP_VERSION`, …) invalidate the layer cache of **every derived stack
image** — each stack's expensive recipe layers (the apt/root bodies the volumes cannot carry)
rebuild for a change that touched no recipe. Agent-last confines the invalidation to the inlined
final layers.

One reconciliation duty: `emit.write_derived_dockerfile` currently emits
`FROM harnessed-${HARNESS}:latest` with an in-file `ARG HARNESS=<harness>` default (which is also
why `_build_derived_image` passes no `--build-arg` and the tag still resolves). Anyone touching the
lineage — the emitter's `FROM`, the launcher's lineage comments, or the agent Dockerfiles — must
change all of them together and re-check that an agent bump still leaves per-stack recipe layers
cached. The invariant is the cache property, not any single line.

## `tools:` and `install:` run at container runtime, into volumes

The derived Dockerfile deliberately emits **no** `tools:` and **no** `install:` layers. They run in
one-shot containers at compose time, writing into the per-stack `~/.local` tools volume and the
config volume, gated on the fingerprint. What remains in the image is exactly what a volume cannot
carry: recipe `env:` as real image `ENV` (a shell export dies with the script that set it) and
system-level Dockerfile bodies (`USER root`, `apt-get`, writes to `/usr`), which harnessed will not
perform on a host and a volume cannot hold.

Why it looks wrong: build layers are the idiomatic place for tool installs, and the runtime gate
looks like a cache someone forgot to wire into the build. What it prevents is measured: baking
installs as image layers made a **one-line edit to `gsd-core/install.sh` cost 307s** of podman
committing layers over a large tree, against **4.3s** for the same install executed natively —
almost none of it download, since the `--mount=type=cache` mounts already covered that (bd
harnessed-8px.21.4). A volume write skips layer commit entirely. The host twin is the same shape:
installs run on every host launch (the home is wiped each time), and `install.cache` — keyed on a
pinned ref — is what makes that affordable.

Two sub-invariants ride on this:

- **The stamp is written only after the installs succeed**, in both modes (`_stamp_host_home` on
  the host; the container twin writes the fingerprint into the volume after
  `_run_container_installs` returns). A failed install must never certify content that was never
  finished — stamping at copy time left a matching stamp on a half-installed stack and every later
  launch skipped the rebuild silently (bd harnessed-8px.15).
- **`install.cache` bind-mounts the parent, never the leaf.** A cache miss *is* "the leaf does not
  exist", and podman statfs's a bind source before the script runs — a leaf mount turns every miss
  into `statfs …: no such file or directory`, i.e. the first build of any new recipe or bumped pin.
  The parent also keeps the scripts' populate-a-sibling-then-rename idiom atomic instead of a
  cross-device rename onto a busy mountpoint.

## No scan layer in the derived Dockerfile

There is **no** supply-chain scan `RUN` in the emitted Dockerfile (bd harnessed-8px.21.5). The
scanners themselves are still baked into `harnessed-base` so `harnessed rescan` needs no network
install — but the build performs no scan at all.

The layer it replaced looks obviously correct and was worse than nothing: it used to be the final
`RUN`, scanning "the mise globals and recipe trees the build had just installed". After 8px.21.4
moved installs out of the image, the layer scanned **an image containing no stack content** and
still printed "no high/critical advisories" — off 1 of 4 scanners, with osv reporting "no skills/
or commands/ dir to scan". A green-looking result covering almost nothing is worse than no result,
because it launders into the wiki, the report, and the reader's confidence.

The real scan is the credentialed post-build pass: `_scan_image_in_container` runs the baked
scanner in a throwaway container with the stack volumes mounted and tokens resolved host-side, so
snyk and socket actually run and the scan sees what was installed. Its report is the one surfaced.
Do not move scanning back into the Dockerfile; do not "fix" the gap by making the build scan the
bare image either — that recreates the green-over-nothing failure with extra steps.

## The egress firewall fails closed, twice

The script and its caller are both fail-closed, and each covers the other's blind spot.

In `catalog/base/egress-firewall.sh`: it deliberately does **not** `set -e` — the per-domain
resolution loop is allowed to fail for individual hosts (an unresolvable CDN must not abort the
whole firewall) — and instead every call that *must* succeed goes through `require`, which prints
a fatal error and exits 1. The flush and the default-DROP policy are the firewall ("if any one of
them does not take, everything after it is decoration on an open netns"), and before printing
"Egress active" the script re-verifies the end state: `iptables -S OUTPUT` must literally contain
`-P OUTPUT DROP`. The history is #429: for most of this project's life every iptables call failed
with "Permission denied" (no `CAP_NET_ADMIN` in the container) and the script still printed
"Egress active" and exited 0. Adding `set -e` back "for rigor" reintroduces the per-domain
fragility; removing the final `iptables -S` check reintroduces the lie. The one deliberately
unscoped rule is the varlock broker's door (`169.254.1.1`, `require`d unconditionally): the broker
port is chosen at launch and never passed to the script, so a port-scoped rule cannot be written
there — narrowing it is #437's plumbing, and the address must not be widened to a link-local CIDR
(#436).

In the launcher: `_apply_firewall` runs the script in a **throwaway container** that joins the
pod's netns with `--cap-add NET_ADMIN --user root` — the agent container never gets `NET_ADMIN`,
because the agent is the untrusted party and handing its namespace-mates rule-writing rights hands
the confined process the key. The launcher then treats a zero exit as a *claim*, not a fact: it
independently reads the OUTPUT policy back out of the netns (`_firewall_policy_is_drop`), and
anything unreadable counts as "not confined" — "cannot prove it is confined" and "is not confined"
must reach the same branch. Every silent-firewall bug so far has been a script reporting success
it did not achieve; a guard that trusts the thing it guards is not a guard. On either failure the
launch refuses to continue, and the `EGRESS` phase tears the pod down on **any** `BaseException` —
by then the pod exists, so propagating would return the user their shell while an unconfined
container kept running. `NO_FIREWALL=true` is the supported way to opt out; failing closed has to
mean the thing we could not confine does not survive.

## Userns is pinned to uid 1000, and `pod_host_uid()` refuses to guess

`paths.USERNS_ARG` is `--userns=keep-id:uid=1000,gid=1000`, not bare `keep-id`. Bare `keep-id`
maps the *invoking host uid* to the same number inside, while the container process is the image's
uid 1000 — so bind-mounted host dirs are writable only when the user happens to be uid 1000. True
on many dev boxes, false on a GitHub `ubuntu-latest` runner, where `live.yml` failed six runs in a
row with `mkdir: cannot create directory '/data/dolt': Permission denied` (bd harnessed-rv2.1).
Pinning the mapping to the image uid makes the container's uid-1000 process *be* the invoking user
whatever their host uid is; it is a no-op where the host uid already is 1000, which is why the
boxes that never saw the bug cannot regress either.

`paths.pod_host_uid()` reads the answer off the declared argument and returns **`None` when the
mapping does not determine it** — and None means *unresolved*, callers must refuse rather than
guess. An earlier version answered `CONTAINER_UID` and called it fail-safe; it was fail-open: under
bare `keep-id` on a host whose user is 1001, the pod's writes land as a subuid (~100999), so
answering "1000" would accept a persist dir owned by host uid 1000 that the pod cannot write —
precisely the state the original bug produces. `persist.guard_ownership` raises a named
pre-launch error when the writer is unresolved, *before* the absent-path early return, because an
unresolved mapping is a problem even for a dir harnessed is about to create. Replacing the `None`
with any number turns the ownership guard into a rubber stamp again.

The scope is honest in the docstring: this reasons about the *declared* argument only and cannot
observe what podman actually did; a rootful daemon or a missing subuid range still ends in a
silent EACCES, which only the live runner's `podman info` check (bd harnessed-rv2.3) can see.

## omp runs without `--profile`; the rw host agent dir is mechanism 1

Container omp gets `~/.omp/agent` bind-mounted **rw** from the host and runs plain `omp` — no
`--profile`. The shared dir is not an isolation oversight; it is the delivery mechanism:
credentials (`agent.db`), the usage ledger, and sessions all live there, so the mount is what makes
"one login, one usage history, one session list across host and containers" true. The attach
command comment says it outright: `--profile` would isolate auth/sessions/settings into a separate
store that *ignores* the bind mount, and the pod would land on the login screen. Host omp is the
same choice in the other direction: a per-stack `PI_CODING_AGENT_DIR` (with `agent.db` symlinked to
the host's — SQLite rewrites in place, so links hold), because `--profile` is mutually exclusive
with that env var and **wins**, silently discarding the override.

What breaks if an agent "fixes" it by snapshotting the dir per instance: the login breaks, the
usage ledger forks, `/resume` loses the host's sessions, and the host edits stop propagating. The
accepted trade-off (same-kernel SQLite/WAL coordination; avoid heavy simultaneous writes from both
sides) is documented at `_omp_agent_mount` — do not convert it into copy-in/copy-out. Related
narrowness: omp's host config seed only shadows `config.yml` when it names the retired local bridge
path, and the per-instance `mcp.json` seed mounts ro *over* the shared file so the host file is
never mutated.

## `MISE_STATE_DIR` is deliberately not redirected

Every other mise variable a host launch touches is redirected into the stack's own tree:
`MISE_DATA_DIR` and `MISE_CONFIG_DIR` point at the stack's tools dir. `MISE_STATE_DIR` pointed
there too, once — and that broke every trusted project config. The state dir holds mise's **trust
store** (`trusted-configs`, `tracked-configs`), and trust is a fact about the user and a config
file, never about which stack happens to be running. Redirecting it gave every stack an empty
store, so every project `mise.toml` the user had already trusted read as untrusted inside every
harnessed session, and each new stack re-broke one the user had just repaired. The symptom is a
trap: mise reports `error parsing config file: <path>`, which reads as a TOML syntax error and is
not one — the real reason is on the next line — and the file is then not loaded at all, so a
project whose `[env]` carries e.g. `BEADS_DIR` comes up unconfigured for reasons nothing on screen
explains.

Two adjacent rules keep this safe rather than sloppy:

- **harnessed never invents trust.** The obvious "fix" — naming paths in `MISE_TRUSTED_CONFIG_PATHS`
  the way the container path does — grants trust the user never gave, and a mise config can carry
  `_.source`, so auto-trusting is code execution. What the host path does instead is *carry*: it
  forwards `trusted_config_paths` read from the user's own config (bd harnessed-67u), and every
  entry traces to the user or the environment it was handed. The distinction is inventing versus
  carrying, not the variable.
- **Only a value harnessed itself wrote is removable.** `_apply_host_mise_env` actively deletes a
  stale `MISE_STATE_DIR` (a leftover from an outer stack's session — launching one stack from
  inside another is routine), but the predicate recognizes harnessed's own path shape, **resolved
  on both sides**: a lexical compare read a symlink into a stack's dir as "not harnessed's" and let
  an inherited config dir launder that stack's `trusted_config_paths` into the next launch — an
  over-grant (found by adversarial review). Empty is never ours, and must be rejected before the
  resolve: `Path("").resolve()` is the CWD, which made an absent variable match.

## toollock exists because of four measured mise facts

`toollock.py` merges per-recipe `mise.lock` files into the one lockfile a stack's tool install
reads. The module docstring opens with the reason the module exists at all — four facts measured
against mise 2026.8.3 *before* the mechanism was written, because each one would otherwise have
produced a mechanism that verifies nothing:

1. **mise enforces the lockfile** — a wrong checksum fails `mise install` with `Checksum mismatch`,
   exit 1. Without this, merged checksums would be decorative.
2. **The file must be named `mise.lock`**, not after the config: `$MISE_CONFIG_DIR/config.lock` and
   `config.toml.lock` are both silently *ignored*, and install exits 0 on a corrupted checksum.
   This is the failure the module most needed to avoid, and only running it revealed the name. This
   is also why the install step sets `MISE_CONFIG_DIR` explicitly rather than guessing a default —
   a lockfile written anywhere else verifies nothing.
3. **`mise lock` refuses to generate one for a global config** ("No tools configured to lock"), so
   assembly cannot shell out to mise. The merge is harnessed's to perform — that is why this file
   exists instead of a subprocess call.
4. **Each tool's tables are contiguous** (`[[tools."<spec>"]]` followed by its `platforms.*`
   tables), which is what makes verbatim block extraction safe: unknown future fields are copied
   through untouched instead of lost to a re-serialization harnessed would have to own.

The merge rules are fail-closed where the failure is a supply-chain one: two recipes locking the
same spec to different bytes is exactly what a lockfile exists to surface, so `merge_locks` raises
`ToolLockError` naming both recipes rather than picking a winner. An empty merged body must
**delete** the target `mise.lock`, not merely decline to write it — a stale lockfile left behind
keeps asserting checksums for tools (or whole recipes) the stack no longer installs. An absent
recipe lockfile is deliberately *not* an error: adoption is incremental and enforcement is
per-tool, so a recipe without a lock installs unverified, exactly as it does today.

Two parsing decisions close fail-open holes found in review of PR #341: the TOML parse is a
*validity gate* (an unparseable recipe lockfile must not be concatenated into the stack's file and
break every tool in it), and the tool-spec regex accepts both the quoted form (`tools."npm:x"`) and
the bare form mise writes for registered tools (`tools.pulumi`) — requiring the quoted form dropped
pulumi and all seven of its platform checksums: a fail-open in the middle of a mechanism whose
entire job is to fail closed.

## One ruamel `YAML` instance per load

`schema._load_yaml` constructs `YAML(typ="safe", pure=True)` inside the function, every call. A
ruamel instance carries scanner/parser/constructor state across `load()` calls and is **not
thread-safe**; `harnessed build -j` assembles stacks on several threads, all loading recipes at
once. A shared module-level instance interleaves and yields nonsense: marks from one file reported
against another, or a half-built mapping that "loads" with fields silently missing. Hoisting the
constructor to a module global is the exact "cleanup" this invariant forbids — it fails only under
parallelism, so the suite will stay green while production breaks.

The same function wraps `MarkedYAMLError` into `SchemaError` at parse time: ruamel raises before
any harnessed validation runs, and every caller catches `SchemaError`, so a duplicate key or a
tab-indent must arrive as the one-line rejection the launcher prints, not an unhandled traceback.

## Distinct podman timeouts, and `_TIMEOUT_RC = 124`

Podman deadlines are sized by what the command does — query 30s, state-changing write 120s, bounded
exec 120s, readiness probe inside a poll loop 10s — and they are generous on purpose: they are not
performance budgets but the point past which podman is not slow but *stuck*. Do not collapse them
into one constant; a `rm -f` racing a shutting-down container is legitimately slower than an
`inspect`, and a single low number breaks working teardowns. The complement is equally deliberate:
calls whose runtime is dominated by work nobody can bound — a `podman build` over network and layer
cache, an interactive prompt, a `sync:` the user is watching — are left **unbounded on purpose**
(`proc._run` imposes no deadline of its own; callers opt in), because a wrong number there breaks
working builds and working humans. `ctrquery.py` and `svcstate.py` each keep their own copy of the
query timeout rather than importing it from launcher, avoiding a dependency cycle — keep both
duplicates in step (svcstate reuses its copy for a local `git worktree list` as well).

`proc._bounded` **never raises** `TimeoutExpired` (bd harnessed-1ao). On expiry the child is killed
and a `CompletedProcess` comes back with returncode `_TIMEOUT_RC = 124` — the GNU `timeout(1)`
code — and empty output (`""`/`b""` matching what the caller asked for, because callers do both
`.strip()` and `.decode()` and `None` would crash the path meant to degrade). The invariant is the
*routing*: every call site that needs a deadline already branches on "non-zero means it did not
work", so 124 routes a hang into the branch that exists instead of inventing a second failure path
per site. `_bounded` calls sit in `finally:` teardowns and poll loops where an escaping exception
would replace the failure already in flight with a complaint about the cleanup — the reason the
function must not raise.

Polarity matters where 124 meets a semantic branch: a `setup.condition` that never answered must
**not** fall into the suppress branch ("non-zero = already satisfied = say nothing"), or a setup
step the user still has to perform silently disappears. `_collect_setup_notices` checks for
`_TIMEOUT_RC` explicitly and shows the notice on a hang. A redundant notice is recoverable; a
missing one is not.

`_run_tagged` adds the subtler half: **no watchdog timer**. The obvious `threading.Timer` that
kills a late child has a window between `wait()` returning and the pump thread claiming completion
in which the timer fires and reports a timeout for a build that *succeeded*; a lock narrows the
window without closing it. The deadline goes where the stdlib already implements it correctly —
`wait(timeout=…)` — with a pump thread draining the pipe (a full pipe would deadlock the wait) and
`copy_context()` carrying `_BUILD_TAG` across the thread boundary, because a ContextVar is not
inherited by a bare `threading.Thread` and without it every line of a parallel build loses its
tag.

## The launchscript's trailing `--` lives on the aoe row, not in the file

`aoe.replay_command` returns `<script> --` — the separator is part of the *row*, and
`launchscript._body` pops it before writing the file, which ends `exec <harness …> "$@"`. The
history cost a respawn loop to learn. aoe's `auto_resume_on_restart` appends the recorded tool's
resume flags (`--resume <id>` / `--fork-session --session-id <uuid>`) to the row's command;
without a separator those land in harnessed's own Click parsing and it dies with `No such option:
--session-id` — on restart only, which is why the first launch of a row looks fine.

If the `--` moved into the file, the failure inverts: the separator would terminate harnessed's
parsing on *every* invocation, so a human's `./claude-container --fresh` would sail past harnessed
too and reach the agent — flags silently swallowed, no error anywhere. The separator must arrive as
the script's own argument. Quoting stays `command_for`'s, never launchscript's: the exec line is
that function's output minus the separator, so a hostile `--aoe-title` is escaped by the same
`shlex.join` the row already relies on. Re-quoting in launchscript would be a second implementation
of an escaping rule, which is the shape that drifts.

## No bare `GIT_COMMON_DIR` export — and `HARNESS` unprefixed

The folder-env contract exports the git common dir twice, on purpose: as `MAIN_REPO_DIR` and as
`HARNESSED_GIT_COMMON_DIR`. A bare `GIT_COMMON_DIR` is **never** exported. git itself consumes that
variable, so exporting it hijacks common-dir resolution the moment the agent `cd`s into another
repository — subcommands in the wrong repo would resolve against the exported path. Adding the
"missing" export breaks git, not just convention. Its sibling naming trap: `HARNESS` is unprefixed
because it *is* the token a recipe Dockerfile branches on (`ARG HARNESS`), so `$HARNESS` in a
setup script means exactly what the Dockerfile's `${HARNESS}` means — prefixing it for consistency
breaks that symmetry.

## dynstack's narrowed alphabet prevents silent join collisions

`derive_name` joins sanitized recipe refs with `_JOIN = "."` into the stack name — a string that
becomes a directory under the generated catalog root, a volume label value, and (via
`_derived_image`) part of a podman image tag. The OCI name-component grammar is strictly smaller
than a filesystem's: separators may be `.`, `_`, `__` or runs of `-`, with no leading/trailing
separator. The invariant that does the work: **`_JOIN` must be legal in a tag AND impossible for
`_sanitize` to emit.** `.` and `_` are the only tag-legal separators, so the sanitizer's output
alphabet is narrowed to `[a-z0-9-]` and `.` is reserved for the join. If a sanitized ref could
contain the separator, `["a.b", "c"]` and `["a", "b.c"]` would both join to `a.b.c` with *neither*
flagged lossy — a silent collision onto one manifest, one image, and one pair of volumes. Folding
`_` and `.` into `-` also closes the second hole: `_foo`/`.foo` would otherwise survive and produce
a component starting with a separator, which the grammar forbids. Restoring `_` or `.` to the
sanitizer's alphabet reopens both.

The rest of the naming machine assumes sanitization is lossy and detects it: `derive_name` appends
an 8-char digest over the *unsanitized* inputs whenever any ref lost information, when the readable
join exceeds `NAME_MAX`, or when explicit `services` were selected (services never appear in the
readable join, so the digest is their only carrier — omitting them lets two service selections mint
over each other's manifest). The digest itself keeps a `\x1f` between the refs group and the
services group so `(refs a,b; services ())` can never collide with `(refs a; services b)`. Empty,
`.`, and `..` components are refused outright, whatever the alphabet, because they escape or
collapse the target directory.

One refusal protects the authored catalog: the generated root is deliberately **last** in
`paths.catalog_roots()` precedence, so an authored stack of the same name would win resolution and
be launched instead of the derived one while `find_in_catalog` handed both build and launch the
authored manifest. `mint` therefore refuses to write a derived name that collides with an authored
stack instead of shadowing it (PR #176).

## There is no shared launch driver — and the backends stay in launcher.py

The `ExecutionBackend` contract is six capability methods and deliberately **no driver**: no
shared code calls `materialize_config`, `provision_tools`, `wire_mcp`, `seed_auth`,
`wire_services`, `apply_isolation` in a fixed order. This looks like the unfinished half of an
abstraction, and the obvious cleanup — `drive(backend, spec)` — is exactly the wrong move. The two
implementations do not agree on an order and *cannot be made to without changing behavior*: the
host backend materializes before it provisions; the container backend provisions the tools volume
**before** it materializes, because podman's copy-up is what lifts the image's `~/.claude` into the
volume the mount set then references. A fixed-order driver would have to reorder one of the two
existing paths — a behavior change wearing a refactor's clothes. The same docstring records the
second half: `backend.py` imports nothing from `launcher.py` and never will (enforced by
`tests/test_module_boundaries.py`), and the two implementations stay in `launcher.py` next to the
~100 private helpers they call, so the dependency points INTO the contract rather than around it.
Moving them out "for file size" inverts that arrow and buys an import cycle.

## A stale overlay symlink is re-pointed, never made the user's problem

`catalogseed._ensure_local_catalog_links` manages the DX symlinks that point a source checkout's
`catalog-local/` at the user's private overlay. When one of them points at the wrong destination,
the question is *whose* link it is — and `_points_at_a_harnessed_overlay` answers it under two hard
constraints (bd harnessed-ng5):

- **Nothing in the discriminator may raise.** Its two filesystem calls fail in **opposite**
  directions because the two failures mean opposite things: an unreadable link (`readlink` fails)
  returns False — we cannot claim as ours something we cannot read, and the caller prints its
  ordinary remove-it-manually message — while an unreadable *target tree* (the checkout-marker
  checks fail) returns True — undecidable resolves to "ours", so the link is re-pointed rather than
  aborting. Being wrong there costs one convenience symlink to re-make; the hard abort is what this
  function exists to stop doing.
- **The verdict is deliberate about near misses.** The raw `readlink` target is compared, never a
  resolved path (a dangling link's resolution says nothing about what it used to point at); it must
  be absolute with the exact `<xdg>/harnessed/catalog/<kind>` tail (a relative link is by
  construction not ours); and a source checkout is excluded by **both** markers — `pyproject.toml`
  and `src/harnessed/` — because `<x>/harnessed/catalog/<kind>` is also the ordinary shape of a
  clone, and keying on `pyproject.toml` alone would make any XDG root that happens to contain one
  look like a checkout and restore the abort.

Why re-pointing at all: telling the user to hand-remove an artifact harnessed itself wrote "was
never a real choice", and it made the podman-gated suite unrunnable — every test gets a fresh tmp
`$XDG_CONFIG_HOME`, the live tests shell out to the real `harnessed build` in the real checkout, so
the first stale link aborted all the rest, and the links it left pointing into a deleted tmp tree
aborted every later run too. Only a symlink is ever unlinked, never its target; a genuinely foreign
link still aborts with the manual-removal message.

## Smaller traps that read like bugs

- **The detached aoe write batch joins with `;`, not `&&`.** `aoe profile create` and `aoe group
  create` exit 1 when the thing already exists; two launches starting together can both observe a
  missing profile, and under `&&` the loser's chain aborts on that benign exit and its session is
  never registered. The failure `&&` would guard against — aoe being down — already produces no
  row either way.
- **`_volume_read` distinguishes absent (`None`) from empty (`""`).** A failed podman run is
  *absent*, not malformed JSON; returning `""` for a failed read made the settings merge treat an
  unreadable volume as a corrupt file and keep the floor — looking identical to the bd
  harnessed-8px.19 regression ("ccstatusline statusLine gone on every restart") the merge exists to
  prevent.
- **Host harness config vars are pinned, not unset** (`_HARNESS_CONFIG_DIR_ENV`). An inherited
  `CLAUDE_CONFIG_DIR` made gsd-core's install write 69 skills into an *unrelated* stack's home (bd
  harnessed-8px.26); unsetting would send such an installer to `$HOME/.claude` — the user's real
  config dir, a worse landing spot than the parent stack's. Pinned to the stack home, applied last
  so the inherited value cannot survive.
- **mise's `MISE_TRUSTED_CONFIG_PATHS` splits on `:` and nothing else** (verified against
  2026.8.3): a comma-joined value reads as one nonexistent path and every config reads untrusted.
  Entries containing the delimiter are dropped rather than emitted — joining one would hand mise
  two paths the user never wrote.

## Keeping the catalog honest

When a change touches any site above, the check is not "do tests pass" but "does the failure this
invariant prevents have a new witness". Invariants with unit-testable mechanics (toollock merge
rules, dynstack collisions, `_volume_read`'s None/empty split, the ruamel per-load rule) are held
by the hermetic suite; invariants whose mechanics live in podman (copy-up, userns, firewall
policy readback) were established by measured spikes and live runs and are only exercised by the
podman-gated layer. See [the verification ladder](/openwiki/testing/verification-ladder.md) for the
rungs, and keep the issue ids in the comments: they are the provenance that lets the next reader
distinguish a defect from a scar.
