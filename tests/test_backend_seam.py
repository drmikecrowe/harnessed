"""The backend contract (BACKENDS.md §3, bd harnessed-0tk.1).

Two things are worth testing here and they are different questions:

  - CONFORMANCE — both backends really implement the whole contract. One implementation is an
    indirection, not a seam, so "every registered backend overrides every operation" is the
    acceptance bar for this child and the thing a third backend will be held to.
  - BEHAVIOR — the operations still do what the launch paths did before they had names. Most of
    that evidence lives in the existing suite (test_launch_host.py, test_launch_parity.py,
    test_project_scoped_services.py), which now exercises these methods through the sequencers.
    What is added here is the behavior that only became addressable once the operations were
    separable: calling one in isolation.

The container backend's operations are deliberately NOT unit-tested here. Every one of them ends in
podman, and this suite runs no `podman run` at all (CLAUDE.md) — a test that mocks the runtime would
assert the mock, not the backend. Its conformance is checked below; its behavior is checked where it
always was, by the structural guards in test_launch_parity.py.
"""

from __future__ import annotations

import inspect
import json

import pytest

from harnessed import backend as backend_mod
from harnessed import launcher
from harnessed.backend import ATTACH, BOUNDARY, EGRESS, FIRST_START, ExecutionBackend, LaunchSpec

_OPERATIONS = (
    "materialize_config",
    "provision_tools",
    "wire_mcp",
    "seed_auth",
    "wire_services",
    "apply_isolation",
)


def _spec(tmp_path, **kw) -> LaunchSpec:
    return LaunchSpec(stack="s", harness="claude", project_path=tmp_path, **kw)


class TestContractConformance:
    """One conforming implementation is an indirection. Two is a seam."""

    def test_the_contract_is_exactly_the_six_named_capabilities(self):
        """§3's table is the vocabulary. A seventh abstract operation means the doc drifted."""
        declared = {
            name for name, obj in vars(ExecutionBackend).items()
            if getattr(obj, "__isabstractmethod__", False)
        }
        assert declared == set(_OPERATIONS)

    def test_both_backends_are_registered(self):
        assert set(backend_mod.registered()) == {"host", "container"}
        assert backend_mod.get_backend("host") is launcher.HostBackend
        assert backend_mod.get_backend("container") is launcher.ContainerBackend

    @pytest.mark.parametrize("cls", [launcher.HostBackend, launcher.ContainerBackend])
    def test_backend_implements_every_operation_itself(self, cls):
        """Concrete AND overriding — not merely inheriting a base that happens to be non-abstract.

        `inspect.isabstract` alone would keep passing if an operation lost its @abstractmethod, so
        assert the override explicitly: an operation a backend does not define is one the seam
        claims parity for and does not have.
        """
        assert not inspect.isabstract(cls)
        missing = [op for op in _OPERATIONS if op not in vars(cls)]
        assert not missing, f"{cls.__name__} does not implement {missing}"

    @pytest.mark.parametrize("cls", [launcher.HostBackend, launcher.ContainerBackend])
    def test_backend_declares_its_isolation_level(self, cls):
        """§2's spectrum. A no-op `apply_isolation` is only honest if the backend says `none`."""
        assert cls.isolation in (backend_mod.ISOLATION_NONE, backend_mod.ISOLATION_CONTAINER)
        assert cls.name

    def test_unknown_backend_names_what_is_available(self):
        with pytest.raises(KeyError, match="container"):
            backend_mod.get_backend("microvm")


class TestHostWireMcp:
    """`wire_mcp` on the host backend: the stack's servers, and the isolation flag that goes with
    them. Separable from a launch for the first time, so assert it directly."""

    def _backend(self, monkeypatch, tmp_path, servers):
        monkeypatch.setattr(launcher, "_host_native_mcp", lambda stack: servers)
        b = launcher.HostBackend([])
        b.home = tmp_path
        return b

    def test_writes_the_stacks_servers_and_points_claude_at_the_file(self, monkeypatch, tmp_path):
        b = self._backend(monkeypatch, tmp_path, {"serena": {"command": "serena"}})
        b.wire_mcp(_spec(tmp_path))
        written = json.loads((tmp_path / ".mcp.json").read_text())
        assert written == {"mcpServers": {"serena": {"command": "serena"}}}
        assert b.argv[:3] == ["claude", "--mcp-config", str(tmp_path / ".mcp.json")]

    def test_empty_server_set_still_writes_the_file(self, monkeypatch, tmp_path):
        """ALWAYS write it: --strict-mcp-config makes claude load ONLY this file, so an empty set is
        what stops the host's global mcpServers leaking into an isolated stack."""
        b = self._backend(monkeypatch, tmp_path, {})
        b.wire_mcp(_spec(tmp_path))
        assert json.loads((tmp_path / ".mcp.json").read_text()) == {"mcpServers": {}}
        assert "--strict-mcp-config" in b.argv

    def test_no_strict_mcp_opts_out_of_the_isolation(self, monkeypatch, tmp_path):
        b = self._backend(monkeypatch, tmp_path, {})
        b.wire_mcp(_spec(tmp_path, no_strict_mcp=True))
        assert "--strict-mcp-config" not in b.argv
        assert "--mcp-config" in b.argv, "the file is still passed — only strictness is opted out"

    def test_passthrough_args_come_last(self, monkeypatch, tmp_path):
        """They are the user's own argv for claude; anything appended after them would be read as
        an argument TO them."""
        b = self._backend(monkeypatch, tmp_path, {})
        b.wire_mcp(_spec(tmp_path, extra=("-p", "hello")))
        assert b.argv[-2:] == ["-p", "hello"]


class TestHostWireServices:
    def test_a_service_less_stack_needs_no_container_runtime(self, monkeypatch, tmp_path):
        """The guard is the whole point: a host launch of a stack with no `services:` must not
        reach for podman at all."""
        monkeypatch.setattr(launcher, "_service_refs", lambda stack: [])
        monkeypatch.setattr(launcher, "_runtime", lambda: pytest.fail("resolved a container runtime"))
        monkeypatch.setattr(launcher, "_ensure_services", lambda *a, **k: pytest.fail("started services"))
        launcher.HostBackend([]).wire_services(_spec(tmp_path))

    def test_a_declared_service_is_started(self, monkeypatch, tmp_path):
        """A `services:` entry is a property of the STACK, not the backend — host mode makes the
        AGENT host-native, it does not remove the service the stack says it needs."""
        seen = {}
        # Deliberately NOT the project path: the sidecar must get the same git surface whichever
        # entry point starts it (bd harnessed-wnf), so passing project_path here would make the
        # create-time svc-config-hash differ by entry point and recreate the container on every
        # alternation between host-run and container-run. A fake that returned project_path could
        # not tell the two apart.
        mounted = tmp_path.parent / "worktree-root"
        monkeypatch.setattr(launcher, "_service_refs", lambda stack: ["beads"])
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_resolve_mount_path", lambda p, f: mounted)
        monkeypatch.setattr(
            launcher, "_ensure_services",
            lambda rt, stack, **kw: seen.update(rt=rt, stack=stack, **kw),
        )
        launcher.HostBackend([]).wire_services(_spec(tmp_path))
        assert seen == {
            "rt": "podman", "stack": "s", "project_path": tmp_path, "mount_path": mounted,
        }


class TestHostIsolationIsDeclaredNotSkipped:
    def test_apply_isolation_is_a_no_op_in_both_phases(self, tmp_path):
        """`isolation` is `none` on this backend (§2), so doing nothing IS the contract. Pinned so
        that a future host backend which DOES isolate cannot land without revisiting the
        declaration — the two must never disagree."""
        assert launcher.HostBackend.isolation == backend_mod.ISOLATION_NONE
        b = launcher.HostBackend([])
        b.apply_isolation(_spec(tmp_path), BOUNDARY)
        b.apply_isolation(_spec(tmp_path), EGRESS)


class TestOperationsFailLoudlyOutOfOrder:
    """Sequencing is backend-owned, so an operation that depends on an earlier one must say so
    rather than silently working on `None`."""

    def test_seed_auth_before_materialize_config_raises(self, tmp_path):
        with pytest.raises(AssertionError, match="materialize_config"):
            launcher.HostBackend([]).seed_auth(_spec(tmp_path))

    def test_first_start_provisioning_before_materialize_config_raises(self, tmp_path):
        with pytest.raises(AssertionError, match="materialize_config"):
            launcher.HostBackend([]).provision_tools(_spec(tmp_path), FIRST_START)

    def test_attach_provisioning_does_not_need_the_home(self, monkeypatch, tmp_path):
        """The attach phase runs outside the home lock and against the project, not the config dir
        — so it must NOT inherit the first-start phase's precondition."""
        calls = []
        monkeypatch.setattr(launcher, "_host_run_setups", lambda *a, **k: calls.append("setups"))
        monkeypatch.setattr(launcher, "_host_run_inits", lambda *a, **k: calls.append("inits"))
        launcher.HostBackend([]).provision_tools(_spec(tmp_path), ATTACH)
        assert calls == ["setups", "inits"], "install bakes content that setup then configures"
