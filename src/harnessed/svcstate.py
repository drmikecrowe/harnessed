"""Derive a shared service's identity: container name, data dir, port, password, env and drift.

A service (design §3/§9) is a sidecar shared across the stacks of one project. Everything about it
that can be COMPUTED — the container name, which project it belongs to, where its data lives, the
port it lands on, the password, the env its clients need, and whether a running container has
drifted from the config it was started with — is derived here from the manifest plus the project
path. Starting, stopping and health-checking the container stays in launcher.py.

Deriving rather than storing is what lets a second launch find the same service instead of starting
a duplicate: the name and port fall out of the same inputs every time.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import socket
import subprocess

from pathlib import Path

from . import paths
from .console import _err
from .ctrquery import _container_stale, _inspect_id, _runtime
from .paths import CONTAINER_HOME
from .schema import SchemaError, ServiceDef, load_service, load_stack, load_stack_with_recipes

# The in-container home as a string, for interpolating into paths a client sees. Derived here rather
# than imported from launcher so the dependency points INTO this module; `paths.CONTAINER_HOME`
# stays the single source of truth for the value itself.
_CONTAINER_HOME_STR = str(CONTAINER_HOME)


def _svc_container(name: str, project_key: str = "") -> str:
    """Container name for a service. Project-scoped services are keyed so one runs PER project."""
    if project_key:
        return f"harnessed-svc-{name}-{project_key}"
    return f"harnessed-svc-{name}"


def _svc_project_key(svc: "ServiceDef", project_path: Path | None) -> str:
    """Per-project key for a project-scoped service — git-common-dir keyed (cross-worktree).

    Every worktree of one checkout resolves to the SAME key, so they share ONE server container
    (which is the whole point: a dolt sql-server holds an exclusive lock on its data dir, and the
    worktrees all resolve to the same in-repo `.beads`). Global services get no key.
    """
    if svc.scope != "project" or project_path is None:
        return ""
    gcd = paths.git_common_dir(project_path)
    return paths.project_hash(gcd if gcd is not None else project_path)


def _service_data_dir(
    svc: "ServiceDef", stack: str, project_path: Path, mode: str = "container"
) -> tuple[Path, str, str]:
    """Resolve a project-scoped service's data dir → (host_dir, agent_path, location).

    The service does NOT choose where its bytes live — the RECIPE does. The service names a persist
    entry (`data.persist`), the launcher finds the recipe in this stack that declares it, and
    follows that entry's placement:

      * location: in_repo → host dir is the checkout-root-anchored dir (paths.persist_in_repo_dir),
        and agents see it at the SAME path (the workspace is mounted path-preserving).
      * location: host    → host dir is the persist dir keyed per that entry's scope, and agents
        see it at $HOME/<name> (exactly where _persist_mounts puts it).

    That is the single knob: `beads/team` declares `.beads` in_repo, `beads/stealth` declares it
    host, and the same service manifest follows either one.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    for recipe in recipes:
        for entry in recipe.persist.entries:
            if entry.name is None or entry.name != svc.data_persist:
                continue
            if entry.location == "in_repo":
                host_dir = paths.persist_in_repo_dir(project_path, entry.name)
                return host_dir, str(host_dir), "in_repo"
            if entry.scope == "project":
                host_dir = paths.persist_project_dir(recipe.name, project_path, entry.name)
            else:
                host_dir = paths.persist_workspace_dir(recipe.name, project_path, entry.name)
            # The AGENT-visible path genuinely differs by mode, and only for `location: host`: in a
            # pod the entry is bind-mounted at $CONTAINER_HOME/<name>, while a host launch has no
            # mount at all and the agent sees the real persist dir. Returning the container path
            # unconditionally (bd harnessed-5ek) meant any host-mode consumer got
            # `/home/harnessed/<name>` — a path that does not exist on the machine it would be used
            # on. Same two-modes-disagree problem `{persist:<name>}` solves for recipe `env:`.
            agent_dir = str(host_dir) if mode == "host" else f"{_CONTAINER_HOME_STR}/{entry.name}"
            return host_dir, agent_dir, "host"

    raise SchemaError(
        f"service '{svc.name}' declares data.persist: '{svc.data_persist}', but no recipe in stack "
        f"'{stack}' declares a persist entry with that name"
    )


def svc_socket_env(stack: str, project_path: Path, mode: str = "container") -> dict[str, str]:
    """Container-side socket path for each socket-backed project-scoped service in the stack.

    Exported into the attach shell (see _init_shell_prologue) as HARNESSED_<NAME>_SOCKET so a
    recipe's `setup:` can reference the socket without recomputing the launcher's path arithmetic —
    e.g. `bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET"`. A service
    reached over a published port uses `client_env` (svc_client_env) instead — the port is not a
    path, and it is not known until the container is running.
    """
    env: dict[str, str] = {}
    for name in _service_refs(stack):
        svc = load_service(None, name)
        if not (svc.scope == "project" and svc.is_socket_only):
            continue
        _, agent_dir, _ = _service_data_dir(svc, stack, project_path, mode)
        var = "HARNESSED_" + svc.name.upper().replace("-", "_") + "_SOCKET"
        env[var] = f"{agent_dir}/{svc.socket}"
    return env


def _svc_password(svc: ServiceDef, project_path: Path | None) -> str:
    """Machine-local shared secret for a published service — created once, reused thereafter.

    Stored under XDG state, NEVER in the service's data dir. For `location: in_repo` that dir is
    the user's repo: a secret written there is one `git add -A` from the remote, and bd's own
    `.beads/.gitignore` covers the files bd knows about, not ours. Same reasoning as D6 — the
    machine-local value stays machine-local.

    Why a password at all: `publish: ephemeral` binds the port to 127.0.0.1, which stops the LAN
    but not other local processes and other users on the box. The socket form got its access
    control from filesystem permissions on the data dir; a TCP port has none, so it has to
    authenticate instead. 0600, and the parent dir 0700.
    """
    key = _svc_project_key(svc, project_path) or "global"
    store = paths.xdg_state_home() / "harnessed" / "svc-secrets"
    store.mkdir(parents=True, exist_ok=True)
    store.chmod(0o700)
    secret = store / f"{svc.name}-{key}"
    if not secret.is_file():
        # token_urlsafe, not a hash of the project path: the path is guessable, a secret must not be.
        secret.write_text(secrets.token_urlsafe(24), encoding="utf-8")
        secret.chmod(0o600)
    return secret.read_text(encoding="utf-8").strip()


# High ports, above everything IANA-registered and above the usual container-runtime scratch, so a
# stable allocation is unlikely to sit where something else later wants a fixed port.
_STABLE_PORT_RANGE = (20000, 59999)


def _port_is_free(port: int) -> bool:
    """Can we bind 127.0.0.1:<port> right now? Only ever used to REJECT a candidate."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _svc_stable_port(svc: "ServiceDef", project_path: Path | None) -> int:
    """The permanent host port for a `publish: stable` service — allocated once, reused forever.

    This is the difference between a port harnessed knows and a port the PROJECT knows. An ephemeral
    publish is re-read from `podman port` at every launch and deliberately never written down, so
    nothing outside a harnessed launch can be configured with it: a plain `bd` in the repo, a
    `claude` the user started themselves, a hook. Persisting the port is what lets the project's own
    mise.local.toml carry a beads config that is still correct after a reboot or a `--fresh`.

    ONE machine-wide registry (paths.svc_ports_file), taken under an exclusive lock, because two
    launches racing in different projects must not be handed the same number. An entry is kept even
    when the port is momentarily unbindable — that is the normal case, since OUR OWN sidecar is
    usually holding it. It is only re-allocated when the recorded port is unusable AND no container
    of ours is listening on it, which is the "something else moved in while we were away" case.
    """
    key = f"{svc.name}-{_svc_project_key(svc, project_path) or 'global'}"
    registry_path = paths.svc_ports_file()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                registry = {}
            existing = registry.get(key)
            if isinstance(existing, int):
                return existing
            taken = {p for p in registry.values() if isinstance(p, int)}
            for _ in range(200):
                candidate = secrets.randbelow(_STABLE_PORT_RANGE[1] - _STABLE_PORT_RANGE[0] + 1)
                candidate += _STABLE_PORT_RANGE[0]
                if candidate in taken or not _port_is_free(candidate):
                    continue
                registry[key] = candidate
                registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True), "utf-8")
                return candidate
            raise SchemaError(
                f"could not allocate a free host port for service '{svc.name}' after 200 tries "
                f"in {_STABLE_PORT_RANGE[0]}-{_STABLE_PORT_RANGE[1]}"
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _svc_published_port(rt: str, cname: str, ctr_port: int) -> int:
    """Host port the runtime chose for `ctr_port`, via `podman port` — 0 if it cannot be read.

    The single source of truth for an ephemeral publish. Deliberately not cached anywhere: the
    port changes whenever the container is recreated, and a stale copy in a file or an env var is
    exactly the failure the socket design was avoiding when it refused to persist its own path.
    """
    result = subprocess.run(
        [rt, "port", cname, str(ctr_port)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return 0
    # `podman port <c> 3307` prints e.g. "127.0.0.1:49183"; may print several lines (one per
    # published address family). Take the first that parses.
    for line in result.stdout.splitlines():
        _, _, tail = line.strip().rpartition(":")
        if tail.isdigit():
            return int(tail)
    return 0


def svc_client_env(stack: str, project_path: Path, mode: str = "container") -> dict[str, str]:
    """Resolve each project-scoped service's `client_env` for this launch.

    The service declares what its clients need (`BEADS_DOLT_SERVER_PORT: "{port}"`); this fills in
    the values that only exist once the container is running. Templated rather than hard-coded in
    the launcher so `launcher` knows "a service declares client env", not "beads wants
    BEADS_DOLT_SERVER_PORT" — the same separation `data.persist` gives placement.

    `{host}` differs by mode and that is the entire reason this is resolved per launch rather than
    baked: a host agent dials 127.0.0.1, a containerized agent dials host.containers.internal, and
    both mean the same published port.
    """
    env: dict[str, str] = {}
    for name in _service_refs(stack):
        svc = load_service(None, name)
        if svc.scope != "project" or not svc.client_env:
            continue
        values = {
            "host": "127.0.0.1" if mode == "host" else "host.containers.internal",
            "password": _svc_password(svc, project_path) if svc.wants_password else "",
        }
        if svc.is_socket_only:
            _, agent_dir, _ = _service_data_dir(svc, stack, project_path, mode)
            values["socket"] = f"{agent_dir}/{svc.socket}"
        if svc.is_stable_port:
            # No `podman port` round-trip: harnessed chose this number, so it already knows it —
            # and it stays knowable when the container is stopped, which is exactly when a plain
            # `bd` in the project still needs a configured environment.
            values["port"] = str(_svc_stable_port(svc, project_path))
        if svc.is_ephemeral_port:
            cname = _svc_container(svc.name, _svc_project_key(svc, project_path))
            port = _svc_published_port(_runtime(), cname, svc.port)
            if not port:
                # No silent fallback to a plausible-looking default. A wrong port here is the
                # 2026-07-19 shape: the client cannot reach the server, bd's auto-start is what
                # would normally paper over it, and auto-start is exactly what we disable.
                _err.print(
                    f"[yellow][WARNING][/yellow] service '{svc.name}': could not read the "
                    f"published port for {cname}; clients will not be configured"
                )
                continue
            values["port"] = str(port)
        for key, template in svc.client_env.items():
            env[key] = template.format(**values)
    return env


def _service_refs(stack: str) -> list[str]:
    """Distinct service names a stack requires as host-published sidecars.

    Three sources, unioned (first-seen order, de-duped): (1) recipe `service:` MCP-server refs
    (the assembler proxies these by URL), (2) recipe `services:` — sidecars a RECIPE requires that
    have no MCP surface, and (3) the stack's own `services:` list. (2) is what lets a bare recipe
    list describe a working stack: a `dolt sql-server` speaks MySQL, not MCP, so it can never be a
    `service:` MCP ref, and before harnessed-7rx.1 only a stack could attach it. All three feed
    `_ensure_services`, which starts each one idempotently at launch.
    """
    stk, recipes = load_stack_with_recipes(None, stack)
    names: list[str] = []
    for recipe in recipes:
        for server in recipe.servers:
            if server.service and server.service not in names:
                names.append(server.service)
        for name in recipe.services:
            if name not in names:
                names.append(name)
    for name in (stk.services if stk else []):
        if name not in names:
            names.append(name)
    return names


_SVC_CONFIG_HASH_LABEL = "harnessed.svc-config-hash"


_SVC_STACK_LABEL = "harnessed.svc-stack"


def _svc_config_hash(run_cmd: list[str]) -> str:
    """Fingerprint of a sidecar's create-time configuration, stamped on the container as
    `harnessed.svc-config-hash` and re-derived at every launch to detect drift.

    Same idea as the derived image's `harnessed.recipe-hash`, applied to the one thing a container
    can NEVER pick up later: `podman restart` re-runs the existing container, so mounts, ports and
    env stay frozen at whatever the code emitted the day it was created. Without this label a
    sidecar drifts arbitrarily far from the code that would create it today and nothing notices —
    which is exactly how five beads-servers ran for days without the mount that makes dolt_backup
    work (bd harnessed-ku9), each failing every backup silently.
    """
    return hashlib.sha256("\0".join(run_cmd).encode("utf-8")).hexdigest()[:12]


def _container_label(rt: str, cname: str, label: str) -> str | None:
    """One label off a container (running or stopped), or None if absent."""
    value = _inspect_id(
        rt, "container", cname,
        '{{if .Config.Labels}}{{index .Config.Labels "' + label + '"}}{{end}}',
    )
    return value or None


def _container_config_hash(rt: str, cname: str) -> str | None:
    """The `harnessed.svc-config-hash` label on a container, or None if it predates the label."""
    return _container_label(rt, cname, _SVC_CONFIG_HASH_LABEL)


def _svc_container_stack(rt: str, cname: str) -> str | None:
    """The stack a sidecar was created for, read back off the container itself.

    A `scope: project` sidecar's data dir is chosen by the STACK (which recipe declares the persist
    entry), so rebuilding one needs to know which stack made it. Recording it on the container means
    `svc recreate` does not have to ask: the answer is already there, and it is the exact stack the
    container was built from rather than a guess about which stack this folder "means". Nothing else
    on the machine records project → stack for a service.
    """
    return _container_label(rt, cname, _SVC_STACK_LABEL)


def _repo_project_hashes(project_path: Path) -> set[str]:
    """`project_hash` for this folder AND every sibling worktree of the same repo.

    A sidecar is keyed by git-common-dir, so ONE of them serves every worktree of a bare+worktree
    checkout — while agent instances are keyed per worktree. The stack that owns the sidecar may
    therefore be running from a sibling, not from where you are standing.
    """
    hashes = {paths.project_hash(project_path)}
    result = subprocess.run(
        ["git", "-C", str(project_path), "worktree", "list", "--porcelain"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return hashes
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            hashes.add(paths.project_hash(Path(line[len("worktree "):].strip())))
    return hashes


def _stack_from_instance_name(name: str, harnesses: list[str], hashes: set[str]) -> str | None:
    """`<stack>` out of `harnessed-<harness>-<stack>-<project_hash>`, or None if it is not one.

    Both ends are stripped against KNOWN values rather than split on a delimiter, because stack
    names routinely contain dashes — a generated one looks like
    `default.beads-team.serena.superpowers-f6eb0941`, which `split("-")` would truncate to
    `default.beads`.

    LONGEST harness first: with agents `claude` and `claude-extended` in the catalog, the container
    `harnessed-claude-extended-mystack-<hash>` matches both prefixes, and the shorter one yields the
    plausible-but-wrong stack `extended-mystack`. Longest-match-wins is the only reading that can be
    right, and stopping at the first match keeps one container from contributing two candidates.
    """
    for harness in sorted(harnesses, key=len, reverse=True):
        prefix = f"harnessed-{harness}-"
        if not name.startswith(prefix):
            continue
        for project_hash in hashes:
            suffix = f"-{project_hash}"
            if name.endswith(suffix) and len(name) > len(prefix) + len(suffix):
                return name[len(prefix):-len(suffix)]
        return None
    return None


def _svc_stacks_from_instances(rt: str, project_path: Path) -> list[str]:
    """Stacks that have an agent instance for THIS repo, read out of instance container names.

    The fallback for a sidecar created before `harnessed.svc-stack` existed — which is every sidecar
    predating this code, i.e. exactly the population that most needs recreating. Without it the
    first recreate on any existing machine demands a flag for something harnessed already knows.

    RUNNING instances win outright: a stopped one is a stack you used once, and `harnessed stop`
    leaves it lying around indefinitely, so a stale instance from a stack you have moved on from
    could otherwise be the only candidate and quietly decide which persist entry the rebuilt sidecar
    serves. Stopped instances are still consulted when nothing is running, because the common case
    for this command is a plain shell with no agent up — dropping them would fail the very use it
    exists for.
    """
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}\t{{.State}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    hashes = _repo_project_hashes(project_path)
    harnesses = paths.list_catalog("agents")
    running: set[str] = set()
    stopped: set[str] = set()
    for line in result.stdout.splitlines():
        name, _, state = line.partition("\t")
        stack = _stack_from_instance_name(name.strip(), harnesses, hashes)
        if stack is None:
            continue
        (running if state.strip() == "running" else stopped).add(stack)
    return sorted(running) if running else sorted(stopped)


def _svc_drift_reason(rt: str, cname: str, svc: "ServiceDef", want_hash: str) -> str | None:
    """Why a RUNNING sidecar needs recreating, or None if it is current.

    Two independent kinds of staleness: the image was rebuilt under it (`_container_stale`), or its
    create-time configuration no longer matches what this code would emit (`_svc_config_hash`).
    A missing label is the second kind — the container was created before harnessed recorded any
    configuration, so it cannot be shown to match and by construction predates every fix since.
    """
    if _container_stale(rt, cname, svc.image):
        return f"the image {svc.image} was rebuilt since this container started"
    have = _container_config_hash(rt, cname)
    if have is None:
        return ("it was created before harnessed stamped service configuration, so it may predate "
                "fixes to how the container is built (mounts, ports, env)")
    if have != want_hash:
        return (f"its create-time configuration no longer matches this code "
                f"({have} != {want_hash}) — mounts, ports or env changed, and a restart cannot "
                "pick those up")
    return None
