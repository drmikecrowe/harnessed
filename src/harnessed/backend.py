"""The execution-backend contract (BACKENDS.md §3).

harnessed's product is the COMPOSITION layer — recipes compose into stacks. *Where* a composed
stack runs is a pluggable execution backend, and isolation is one of that backend's capabilities
rather than a property of the product. This module names the contract every backend implements so
a new one (bwrap+landlock, devcontainer-emit, microVM) is a class to write rather than a fork of
the launch path.

The six capabilities are BACKENDS.md §3's, verbatim and in its vocabulary: materialize config /
provision tools / wire MCP / seed auth / wire services / apply isolation. Do not rename them here
without renaming them there.

SEQUENCING IS BACKEND-OWNED — this is the load-bearing design decision, and the reason the
contract is a capability set rather than a pipeline. There is deliberately NO shared driver that
calls the six in a fixed order, because the two implementations that exist today do not agree on
one and cannot be made to without changing behavior:

  - The host backend materializes before it provisions; the container backend provisions the
    tools volume BEFORE it materializes, because podman's copy-up is what lifts the image's
    `~/.claude` into the volume the mount set then references.
  - `provision_tools` has two moments on BOTH backends, which is why it takes a phase: `install:`
    on first start, `setup.script` at attach time (§3's own wording). Host runs the first under
    the home lock and the second outside it (a setup script can prompt, and holding an exclusive
    flock across a TTY prompt would hang a concurrent launch); container runs the first as a
    volume compose before the container exists and the second as `podman exec` after it does.
  - `apply_isolation` likewise has two moments on a network-namespaced backend, which is why it
    takes a phase: establish the boundary, then close egress once first-run provisioning has had
    the network it needs. §4's matrix already tracks "egress control" as its own row.

A backend therefore implements the capabilities and orders its own `launch`. A fixed-order driver
would have to reorder one of the two existing paths, which is a behavior change wearing a
refactor's clothes.

This module imports nothing from launcher.py and never will (tests/test_module_boundaries.py):
the two implementations live in launcher.py, next to the ~100 private helpers they call, so the
dependency points INTO the contract and the seam adds no import cycle.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, TypeVar

# The two moments of "provision tools" (§3: "`install:` scripts run on first start
# (fingerprint-gated), `setup.script` at attach time").
FIRST_START = "first-start"
ATTACH = "attach"
ProvisionPhase = Literal["first-start", "attach"]

# The two moments of "apply isolation": stand the boundary up, then close egress. Separate because
# first-run setup scripts are exactly the step that needs the network, so egress closes after them.
BOUNDARY = "boundary"
EGRESS = "egress"
IsolationPhase = Literal["boundary", "egress"]

# §2's isolation spectrum, as a backend declares it. Not an enum the code branches on — a declared
# capability, so `harnessed` can say what a backend gives you without launching it.
ISOLATION_NONE = "none"
ISOLATION_CONTAINER = "container"


@dataclass(frozen=True)
class LaunchSpec:
    """What a launch is, independent of where it runs.

    Everything here is composition-layer input — the stack, the harness reading it, the project it
    runs against, and the flags that survive into the agent's own argv. Backend-specific state
    (podman instance names, the host config dir, resolved mount args) belongs on the backend
    instance, not here: a field only one backend can honor is a fixed-order driver in disguise.
    """

    stack: str
    harness: str
    project_path: Path
    extra: tuple[str, ...] = ()
    no_strict_mcp: bool = False
    ephemeral: bool = False


class ExecutionBackend(ABC):
    """One place a composed stack can run. See the module docstring for why there is no driver."""

    #: Backend name as the user names it (`host`, `container`). Also the registry key.
    name: ClassVar[str]
    #: What §2's isolation spectrum says this backend gives you. Declared, not enforced here.
    isolation: ClassVar[str]

    @abstractmethod
    def materialize_config(self, spec: LaunchSpec) -> None:
        """Deliver the assembled `.claude/*` profile to where the harness reads it.

        Bind-mount, copy, or symlink — the backend picks. Includes folding the host's live
        preferences into the emitted settings, which is a per-launch recomputation on both
        existing backends rather than a function of the recipe closure.
        """

    @abstractmethod
    def provision_tools(self, spec: LaunchSpec, phase: ProvisionPhase) -> None:
        """Make tools resolvable to the harness.

        `FIRST_START` is the fingerprint-gated `install:`/`tools:` work; `ATTACH` runs each
        recipe's `setup.script`. Both phases are named in §3; see the module docstring for why
        they cannot collapse into one call on either existing backend.
        """

    @abstractmethod
    def wire_mcp(self, spec: LaunchSpec) -> None:
        """Present the stack's MCP servers to the harness (native `.mcp.json`, or the hatago hub).

        Wiring only. Waiting for a hub to become healthy is a readiness gate, not part of the
        contract — the same way a service sidecar's health check is not part of `wire_services`.
        """

    @abstractmethod
    def seed_auth(self, spec: LaunchSpec) -> None:
        """Give the harness the host's credentials by REFERENCE — mount or symlink, never a copy.

        CLAUDE.md's non-negotiable: credentials are referenced, never replicated. A backend that
        cannot reference a live store must fail rather than snapshot one.
        """

    @abstractmethod
    def wire_services(self, spec: LaunchSpec) -> None:
        """Stand up the stack's service sidecars and route the harness to them.

        A `services:` entry is a property of the STACK, not of the backend: a host-native agent
        still needs the service its stack declares.
        """

    @abstractmethod
    def apply_isolation(self, spec: LaunchSpec, phase: IsolationPhase) -> None:
        """Enforce this backend's isolation level (§2's spectrum).

        `BOUNDARY` stands the boundary up; `EGRESS` closes the network once first-run provisioning
        has had it. A backend declaring `ISOLATION_NONE` does nothing in either phase — that is
        the contract being honored, not skipped, and `isolation` is where it says so.
        """


_REGISTRY: dict[str, type[ExecutionBackend]] = {}

#: Bound so the decorator returns the DECORATED class, not the base — otherwise every backend's own
#: `__init__` signature and attributes vanish behind `type[ExecutionBackend]` at the call site.
_BackendT = TypeVar("_BackendT", bound=type[ExecutionBackend])


def register(cls: _BackendT) -> _BackendT:
    """Class decorator: make a backend addressable by name. Used as `@register`."""
    _REGISTRY[cls.name] = cls
    return cls


def get_backend(name: str) -> type[ExecutionBackend]:
    """The backend class registered under `name`. KeyError names what is available."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown backend '{name}' (registered: {', '.join(sorted(_REGISTRY))})")


def registered() -> dict[str, type[ExecutionBackend]]:
    """Every registered backend, by name. A copy — the registry is not a mutable public surface."""
    return dict(_REGISTRY)
