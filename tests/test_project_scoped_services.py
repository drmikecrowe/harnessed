"""Project-scoped, socket-backed services (the beads-server shape).

A `scope: project` service is one container PER PROJECT whose data dir is a BIND MOUNT of a persist
entry declared by a recipe in the stack — so the SERVICE follows the RECIPE's placement choice rather
than owning a named volume. It is reached through a unix socket inside that dir, so it publishes no
port at all.

The motivating case: a `dolt sql-server` holds an EXCLUSIVE flock on its data dir. bd used to spawn
one per container, and every container of a checkout resolves to the same `.beads`, so all but the
first died on `database "dolt" is locked by another dolt process`. One server per project with N
socket clients removes the contention by construction.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import launcher, paths, svcguards
from harnessed.schema import PersistEntry, PersistSpec, Recipe, SchemaError, load_service
from support import patch_all


def _svc_yaml(tmp_path: Path, body: str, name: str = "beads-server") -> Path:
    svc_dir = tmp_path / "services" / name
    svc_dir.mkdir(parents=True)
    (svc_dir / "service.yaml").write_text(body)
    return tmp_path


def _beads_recipe(location: str, scope: str = "project") -> Recipe:
    entry = PersistEntry(
        name=".beads",
        path=None,
        scope=scope,
        location=location,
        vcs="tracked" if location == "in_repo" else None,
    )
    return Recipe(
        name="beads-team" if location == "in_repo" else "beads-stealth",
        persist=PersistSpec(entries=[entry]),
        root=Path("/tmp/fake-recipe"),
    )


PROJECT_SVC = """\
name: beads-server
image: harnessed-beads-server:latest
scope: project
socket: run/mysql.sock
data:
  persist: .beads
"""


class TestLoadServiceScopeAndSocket:
    def test_project_socket_service_loads_without_a_port(self, tmp_path):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        assert svc.scope == "project"
        assert svc.is_socket_only
        assert svc.socket == "run/mysql.sock"
        assert svc.data_persist == ".beads"
        assert svc.port == 0
        # A project-scoped service never gets the default `<name>-data` named volume: its bytes live
        # in the bind-mounted persist dir, where agent containers can also see the socket.
        assert svc.volume == ""

    def test_global_service_still_requires_a_port(self, tmp_path):
        root = _svc_yaml(tmp_path, "name: ping\nimage: harnessed-ping:latest\n", name="ping")
        with pytest.raises(SchemaError, match="port"):
            load_service(root, "ping")

    def test_global_service_keeps_its_default_named_volume(self, tmp_path):
        root = _svc_yaml(tmp_path, "name: ping\nimage: harnessed-ping:latest\nport: 8080\n", name="ping")
        svc = load_service(root, "ping")
        assert svc.scope == "global" and svc.volume == "ping-data" and not svc.is_socket_only

    def test_socket_requires_project_scope(self, tmp_path):
        root = _svc_yaml(
            tmp_path, "name: s\nimage: i:1\nsocket: run/x.sock\n", name="s"
        )
        with pytest.raises(SchemaError, match="scope: project"):
            load_service(root, "s")

    def test_absolute_socket_rejected(self, tmp_path):
        # The socket path is resolved against the data dir, whose host path differs per project —
        # an absolute path would silently escape it.
        root = _svc_yaml(
            tmp_path,
            "name: s\nimage: i:1\nscope: project\nsocket: /tmp/x.sock\ndata:\n  persist: .beads\n",
            name="s",
        )
        with pytest.raises(SchemaError, match="RELATIVE"):
            load_service(root, "s")

    def test_project_scope_requires_data_persist(self, tmp_path):
        root = _svc_yaml(tmp_path, "name: s\nimage: i:1\nscope: project\nport: 3307\n", name="s")
        with pytest.raises(SchemaError, match="data.persist"):
            load_service(root, "s")


class TestServiceContainerNaming:
    def test_global_service_is_unkeyed(self):
        assert launcher._svc_container("ping") == "harnessed-svc-ping"

    def test_project_service_is_keyed_per_project(self, tmp_path):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        key = launcher._svc_project_key(svc, tmp_path)
        assert key and launcher._svc_container("beads-server", key) == f"harnessed-svc-beads-server-{key}"

    def test_worktrees_of_one_checkout_share_one_server(self, tmp_path, monkeypatch):
        # THE contention fix: every worktree of a checkout resolves to the same git common dir, so it
        # must resolve to the SAME server container — one flock holder, not one per worktree.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        common = tmp_path / "checkout" / ".bare"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: common)
        wt_a, wt_b = tmp_path / "checkout" / "main", tmp_path / "checkout" / "feature"
        assert launcher._svc_project_key(svc, wt_a) == launcher._svc_project_key(svc, wt_b)

    def test_separate_checkouts_get_separate_servers(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: Path(p) / ".git")
        assert launcher._svc_project_key(svc, tmp_path / "a") != launcher._svc_project_key(svc, tmp_path / "b")


class TestServiceDataDir:
    """The service follows the RECIPE's placement — that is the single knob."""

    def test_in_repo_recipe_puts_the_data_dir_in_the_repo(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        host_dir, agent_dir, location = launcher._service_data_dir(svc, "any", project)
        assert location == "in_repo"
        assert host_dir == project / ".beads"
        # Path-preserving workspace mount: agents see the same path the host does.
        assert agent_dir == str(project / ".beads")

    def test_in_repo_data_dir_is_checkout_anchored_for_worktrees(self, tmp_path, monkeypatch):
        # bd resolves `.beads` off the git common dir (verified with `bd where`), so in a bare +
        # linked-worktree layout it lands at <bare>/.beads — NOT <worktree>/.beads. The server must
        # mount the same dir the client resolves, or they'd open different databases.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        bare = tmp_path / "checkout" / ".bare"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: bare)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        host_dir, _, _ = launcher._service_data_dir(svc, "any", tmp_path / "checkout" / "main")
        assert host_dir == bare / ".beads"

    def test_host_recipe_puts_the_data_dir_outside_the_repo(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: Path(p) / ".git")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("host")])
        )
        project = tmp_path / "repo"
        host_dir, agent_dir, location = launcher._service_data_dir(svc, "any", project)
        assert location == "host"
        assert (tmp_path / "persist") in host_dir.parents
        assert agent_dir == "/home/harnessed/.beads"

    def test_missing_persist_entry_is_a_schema_error(self, tmp_path, monkeypatch):
        # A stack that attaches beads-server but has no beads recipe cannot say where the data lives.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, []))
        with pytest.raises(SchemaError, match="data.persist"):
            launcher._service_data_dir(svc, "no-beads-stack", tmp_path)

    def test_host_mode_sees_the_real_dir_not_the_container_mount(self, tmp_path, monkeypatch):
        """bd harnessed-5ek: `location: host` is bind-mounted at $CONTAINER_HOME/<name> in a pod,
        but a host launch has no mount — the agent there sees the real persist dir. Returning the
        container path in both modes handed host-mode consumers /home/harnessed/..., which does not
        exist on the machine it would be used on."""
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: Path(p) / ".git")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("host")])
        )
        project = tmp_path / "repo"
        host_dir, agent_dir, _ = launcher._service_data_dir(svc, "any", project, "host")
        assert agent_dir == str(host_dir)
        assert not agent_dir.startswith("/home/harnessed")

    def test_in_repo_placement_is_identical_in_both_modes(self, tmp_path, monkeypatch):
        # `location: in_repo` is mounted path-preserving, so there is nothing to switch on.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: Path(p) / ".git")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        project = tmp_path / "repo"
        ctr = launcher._service_data_dir(svc, "any", project, "container")
        host = launcher._service_data_dir(svc, "any", project, "host")
        assert ctr == host


class TestClientVisibleSocketPath:
    """The path a service advertises to clients is THEIR path, never the service's own /data view.

    beads writes this into .beads/metadata.json, which bd (in a different container, with a different
    mount namespace) then reads. Advertise /data/run/mysql.sock and every client dials a path that
    does not exist for it.
    """

    def test_socket_env_is_the_agent_path_not_the_service_data_path(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "_service_refs", lambda _s: ["beads-server"])
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        sock = launcher.svc_socket_env("any", project)["HARNESSED_BEADS_SERVER_SOCKET"]
        assert sock == f"{project}/.beads/run/mysql.sock"
        assert not sock.startswith("/data"), "clients must never be handed the service's own mount path"

    def test_host_mode_socket_is_a_path_that_exists_on_the_host(self, tmp_path, monkeypatch):
        """bd harnessed-162/-5ek: the socket env used to be container-only, so a host launch never
        got it and the beads recipes' `:?` guard always fired. Exporting it in host mode is only
        correct because the agent path is now resolved per mode — otherwise this would hand a host
        process /home/harnessed/..."""
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "_service_refs", lambda _s: ["beads-server"])
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("host")])
        )
        sock = launcher.svc_socket_env("any", project, "host")["HARNESSED_BEADS_SERVER_SOCKET"]
        assert sock.startswith(str(tmp_path / "persist"))
        assert not sock.startswith("/home/harnessed")


class TestSocketEnvExport:
    def test_socket_path_is_exported_for_the_attach_shell(self, tmp_path, monkeypatch):
        # Recipes reference $HARNESSED_BEADS_SERVER_SOCKET in their `setup:` rather than recomputing
        # the launcher's path arithmetic.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "_service_refs", lambda _s: ["beads-server"])
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        env = launcher.svc_socket_env("any", project)
        assert env == {"HARNESSED_BEADS_SERVER_SOCKET": f"{project}/.beads/run/mysql.sock"}

    def test_global_services_export_nothing(self, tmp_path, monkeypatch):
        root = _svc_yaml(tmp_path, "name: ping\nimage: harnessed-ping:latest\nport: 8080\n", name="ping")
        patch_all(monkeypatch, "load_service", lambda _r, _n: load_service(root, "ping"))
        patch_all(monkeypatch, "_service_refs", lambda _s: ["ping"])
        assert launcher.svc_socket_env("any", tmp_path) == {}


PUBLISHED_SVC = """\
name: beads-server
image: harnessed-beads-server:latest
scope: project
port: 3307
publish: ephemeral
data:
  persist: .beads
client_env:
  BEADS_DOLT_SERVER_HOST: "{host}"
  BEADS_DOLT_SERVER_PORT: "{port}"
  BEADS_DOLT_PASSWORD: "{password}"
  BEADS_DOLT_AUTO_START: "false"
"""


class TestPublishValidation:
    """`publish: ephemeral` is the only accepted spelling, and it cannot coexist with a socket."""

    def test_socket_and_publish_are_mutually_exclusive(self, tmp_path):
        body = PUBLISHED_SVC + "socket: run/mysql.sock\n"
        with pytest.raises(SchemaError, match="mutually exclusive"):
            load_service(_svc_yaml(tmp_path, body), "beads-server")

    def test_publish_requires_a_container_port(self, tmp_path):
        """`publish` names HOW to expose a port, so a manifest without one is incomplete. Caught by
        the pre-existing port/socket requirement rather than a second check of its own."""
        body = "name: s\nimage: i\nscope: project\npublish: ephemeral\ndata:\n  persist: .beads\n"
        with pytest.raises(SchemaError, match="required field 'port' is missing"):
            load_service(_svc_yaml(tmp_path, body, name="s"), "s")

    def test_unknown_client_env_token_is_rejected(self, tmp_path):
        body = PUBLISHED_SVC.replace('"{password}"', '"{hostname}"')
        with pytest.raises(SchemaError, match="unknown token"):
            load_service(_svc_yaml(tmp_path, body), "beads-server")

    def test_host_port_tokens_rejected_on_a_socket_service(self, tmp_path):
        body = PROJECT_SVC + 'client_env:\n  X: "{port}"\n'
        with pytest.raises(SchemaError, match="socket-only service"):
            load_service(_svc_yaml(tmp_path, body), "beads-server")


class TestPublishedPortReadback:
    """The published port is READ BACK from the runtime, never assumed or recorded.

    An ephemeral publish means the runtime chose the host port; `svc.port` is the CONTAINER port.
    Anything that treats them as interchangeable dials a port nothing is listening on — or, worse,
    a port some unrelated process owns.
    """

    def test_parses_podman_port_output(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="127.0.0.1:49183\n", stderr=""),
        )
        assert launcher._svc_published_port("podman", "c", 3307) == 49183

    def test_ipv6_form_parses(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="[::]:49184\n", stderr=""),
        )
        assert launcher._svc_published_port("podman", "c", 3307) == 49184

    def test_failure_reports_zero_rather_than_guessing(self, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="no such container"),
        )
        assert launcher._svc_published_port("podman", "c", 3307) == 0


class TestClientEnvResolution:
    """The SERVICE declares what its clients need; the launcher fills in the launch-time values."""

    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PUBLISHED_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "_service_refs", lambda _s: ["beads-server"])
        patch_all(monkeypatch, "_runtime", lambda: "podman")
        patch_all(monkeypatch, "_svc_published_port", lambda *a: 49183)
        return project

    def test_host_mode_dials_loopback(self, wired):
        env = launcher.svc_client_env("any", wired, "host")
        assert env["BEADS_DOLT_SERVER_HOST"] == "127.0.0.1"
        assert env["BEADS_DOLT_SERVER_PORT"] == "49183"

    def test_container_mode_dials_the_host_gateway(self, wired):
        """127.0.0.1 inside a container is the CONTAINER — the loopback trap the socket form was
        chosen to avoid. `{host}` resolving per mode is what replaces that guarantee."""
        env = launcher.svc_client_env("any", wired, "container")
        assert env["BEADS_DOLT_SERVER_HOST"] == "host.containers.internal"
        assert env["BEADS_DOLT_SERVER_PORT"] == "49183"

    def test_autostart_interlock_is_exported(self, wired):
        """This once came from socket mode; it now comes from the environment. Losing it is
        how a client that cannot reach the server initializes the data dir as a database (§10)."""
        assert launcher.svc_client_env("any", wired, "host")["BEADS_DOLT_AUTO_START"] == "false"

    def test_password_is_stable_across_calls_and_never_empty(self, wired):
        first = launcher.svc_client_env("any", wired, "host")["BEADS_DOLT_PASSWORD"]
        second = launcher.svc_client_env("any", wired, "host")["BEADS_DOLT_PASSWORD"]
        assert first and first == second

    def test_unreadable_port_exports_nothing_for_that_service(self, wired, monkeypatch):
        """No plausible-looking default. A wrong port is the 2026-07-19 shape: the client cannot
        reach the server, and the auto-start that would normally paper over it is disabled."""
        patch_all(monkeypatch, "_svc_published_port", lambda *a: 0)
        assert launcher.svc_client_env("any", wired, "host") == {}




class TestNeverHealthyAbortsTheLaunch:
    """harnessed-dwt: a service that starts, stays up, and never becomes healthy must ABORT.

    harnessed-709 closed the DIES case; this closes the other half. A service that is up but
    unusable used to warn and let the launch proceed, so the agent came up attached to something it
    could not talk to and every command failed far away from the cause. With MySQL auth on the
    beads sidecar that state is reachable: a wrong password gives a running server whose healthcheck
    can never pass.
    """

    @pytest.fixture
    def svc(self, tmp_path):
        # socket-backed so there is no TCP probe to stub, and WITH a healthcheck — without one the
        # function returns early and every assertion here would pass for the wrong reason.
        return load_service(
            _svc_yaml(tmp_path, PROJECT_SVC + 'healthcheck: "dolt sql -q \'SELECT 1\'"\n'),
            "beads-server",
        )

    @pytest.fixture(autouse=True)
    def _no_sleeping(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda _s: None)

    def _health(self, monkeypatch, rc: int, out: bytes = b"", err: bytes = b"", status="running"):
        patch_all(monkeypatch, "_service_container_status", lambda *a: status)
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=out, stderr=err),
        )

    def test_timeout_aborts_instead_of_warning(self, svc, monkeypatch):
        self._health(monkeypatch, rc=1)
        with pytest.raises(typer.Exit) as exc:
            launcher._wait_service_healthy("podman", "c", svc, timeout=2)
        assert exc.value.exit_code == 1

    def test_the_last_healthcheck_output_is_surfaced(self, svc, monkeypatch, capsys):
        """The container log shows a server running contentedly; the healthcheck holds the reason.
        Print the log alone and the user looks in the one place that cannot tell them."""
        self._health(monkeypatch, rc=1, err=b"Error 1045 (28000): Access denied for user 'root'")
        with pytest.raises(typer.Exit):
            launcher._wait_service_healthy("podman", "c", svc, timeout=2)
        assert "Access denied" in capsys.readouterr().err

    def test_a_healthy_service_returns_quietly(self, svc, monkeypatch, capsys):
        self._health(monkeypatch, rc=0)
        launcher._wait_service_healthy("podman", "c", svc, timeout=2)  # must not raise
        assert "never became healthy" not in capsys.readouterr().err

    def test_a_dead_container_still_takes_the_dead_path(self, svc, monkeypatch):
        """709's abort must survive: a container that died gets the container LOG, not a 60s wait."""
        self._health(monkeypatch, rc=1, status="exited")
        called = []
        patch_all(monkeypatch, "_abort_dead_service",
                            lambda *a: called.append(a) or (_ for _ in ()).throw(typer.Exit(1)))
        with pytest.raises(typer.Exit):
            launcher._wait_service_healthy("podman", "c", svc, timeout=5)
        assert called, "a dead container must route to _abort_dead_service, not the timeout branch"

    def test_a_service_with_no_healthcheck_cannot_fail(self, tmp_path, monkeypatch):
        """Nothing was declared, so there is nothing to hold it to — must not abort."""
        self._health(monkeypatch, rc=1)
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        assert not svc.healthcheck
        launcher._wait_service_healthy("podman", "c", svc, timeout=2)  # must not raise


class TestServiceSecretPlacement:
    def test_secret_never_lands_in_the_service_data_dir(self, tmp_path, monkeypatch):
        """For `location: in_repo` the data dir IS the user's repo. A secret written there is one
        `git add -A` from the remote, and bd's own .beads/.gitignore covers bd's files, not ours."""
        svc = load_service(_svc_yaml(tmp_path, PUBLISHED_SVC), "beads-server")
        project = tmp_path / "repo"
        project.mkdir()
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        launcher._svc_password(svc, project)
        assert not list(project.rglob("*")), "nothing may be written under the project"
        written = list((tmp_path / "state").rglob("*"))
        assert written, "the secret must be persisted under XDG state"

    def test_secret_file_is_not_world_readable(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PUBLISHED_SVC), "beads-server")
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: tmp_path / ".git")
        monkeypatch.setattr(paths, "xdg_state_home", lambda: tmp_path / "state")
        launcher._svc_password(svc, tmp_path)
        secret = next(p for p in (tmp_path / "state").rglob("*") if p.is_file())
        assert secret.stat().st_mode & 0o077 == 0, "a TCP port has no filesystem ACL to hide behind"


class TestInRepoServiceGetsTheRemoteGitSurface:
    """An `in_repo` service does the project's REMOTE git traffic (bd's `dolt clone` at init, `bd
    dolt push` at sync), because bd shells out to a dolt CLI that only talks to a server on its own
    loopback. So the service container needs the same surface an agent container needs to reach the
    remote — not a hand-picked subset of it.

    Regression: it used to mount only `known_hosts` + legacy `~/.gitconfig`, which broke two ways.
    (1) No `~/.ssh/config` and no `*.pub`: a repo pinning its identity with
    `core.sshCommand = ssh -o IdentityAgent=... -i ~/.ssh/<key>.pub` (the 1Password multi-account
    pattern) hit "Identity file ... not accessible", silently fell back to the agent's first key —
    the wrong GitHub account — and GitHub answered `ERROR: Repository not found.` while the same
    clone worked fine from an agent container. (2) A host whose git config lives at the XDG path
    (`~/.config/git/config`) got NO git config at all in the service.
    """

    def _capture_run_cmd(self, tmp_path, monkeypatch, home: Path):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        project.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        patch_all(monkeypatch, "_image_exists", lambda _rt, _img: True)
        patch_all(monkeypatch, "_container_running", lambda _rt, _c: False)
        monkeypatch.setattr(launcher, "_install_corp_proxy_ca_in_container", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_wait_service_healthy", lambda *a, **k: None)
        # `_run` is stubbed, so no container is ever created — liveness is not what this asserts.
        patch_all(monkeypatch, "_assert_service_running", lambda *a, **k: None)
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        )
        captured: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, **k: captured.append(cmd))
        launcher._ensure_service(
            "podman", "beads-server", stack="any", project_path=project, mount_path=project
        )
        return " ".join(captured[0])

    def test_the_data_mount_pins_the_userns_to_the_image_uid(self, tmp_path, monkeypatch):
        """bd harnessed-rv2.1. Plain `--userns=keep-id` maps the invoking host uid to the SAME
        number inside, while the image runs as uid 1000 — so the bind-mounted `/data` is writable
        only when the host user happens to BE 1000. On a GitHub runner it is not, and the service
        dies at startup with `mkdir: cannot create directory '/data/dolt': Permission denied`.
        The emitted argument must carry an explicit uid mapping, not the bare form."""
        home = tmp_path / "home"
        home.mkdir(parents=True)

        cmd = self._capture_run_cmd(tmp_path, monkeypatch, home)

        assert paths.USERNS_ARG in cmd.split(), (
            f"the service run does not pin the userns mapping: {cmd}"
        )
        assert not re.search(r"--userns=keep-id(?![:\w])", cmd), (
            "an unpinned --userns=keep-id survives; it EACCESes on any host whose uid is not "
            f"{paths.CONTAINER_UID}"
        )

    def test_ssh_config_pubkeys_and_xdg_git_config_are_mounted(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "config").write_text("Host *\n")
        (home / ".ssh" / "known_hosts").write_text("")
        (home / ".ssh" / "id_rsa_work.pub").write_text("ssh-rsa AAAA")
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".config" / "git" / "config").write_text("[user]\n\temail = a@b.c\n")

        cmd = self._capture_run_cmd(tmp_path, monkeypatch, home)

        # The identity `core.sshCommand -i` points at — without it ssh picks the wrong agent key.
        assert f"{home}/.ssh/id_rsa_work.pub" in cmd
        assert f"{home}/.ssh/config" in cmd
        assert f"{home}/.ssh/known_hosts" in cmd
        # XDG git config, not just the legacy ~/.gitconfig.
        assert f"{home}/.config/git" in cmd

    def test_private_keys_are_not_mounted_without_stack_opt_in(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_rsa_work").write_text("PRIVATE")
        (home / ".ssh" / "id_rsa_work.pub").write_text("ssh-rsa AAAA")

        cmd = self._capture_run_cmd(tmp_path, monkeypatch, home)

        assert f"{home}/.ssh/id_rsa_work.pub" in cmd
        assert f"{home}/.ssh/id_rsa_work:" not in cmd, "private key mounted without ssh_keys opt-in"


class TestServiceDataDirPathPreservingMount:
    """The service data dir is mounted at BOTH /data AND its own host-absolute path.

    Root cause: a host-side `bd` calls `CALL dolt_backup('add', ..., '<abs-host-path>')`,
    and Dolt inside the container resolves that absolute path against the CONTAINER filesystem.
    Without the second mount the parent directories (e.g. `.bare/`) are absent from the container
    and `os.MkdirAll` fails with EACCES when the unprivileged `harnessed` user tries to create
    them under a root-owned stub. The /data alias must be kept — container-internal config and
    the socket path depend on it.
    """

    def _capture_cmd(self, tmp_path: Path, monkeypatch, location: str) -> tuple[str, Path]:
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        project.mkdir(parents=True, exist_ok=True)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        # Route persist_root inside tmp_path so the test never writes outside it.
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "load_stack_with_recipes",
            lambda _r, _s: (None, [_beads_recipe(location)]),
        )
        patch_all(monkeypatch, "_image_exists", lambda _rt, _img: True)
        patch_all(monkeypatch, "_container_running", lambda _rt, _c: False)
        monkeypatch.setattr(launcher, "_install_corp_proxy_ca_in_container", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_wait_service_healthy", lambda *a, **k: None)
        patch_all(monkeypatch, "_assert_service_running", lambda *a, **k: None)
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        )
        captured: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, **k: captured.append(cmd))
        mount_path = project if location == "in_repo" else None
        launcher._ensure_service(
            "podman", "beads-server", stack="any", project_path=project, mount_path=mount_path
        )
        if location == "in_repo":
            host_dir = paths.persist_in_repo_dir(project, ".beads")
        else:
            host_dir = paths.persist_project_dir("beads-stealth", project, ".beads")
        return " ".join(captured[0]), host_dir

    def test_in_repo_data_dir_also_mounted_at_host_absolute_path(self, tmp_path, monkeypatch):
        """in_repo placement: data dir accessible at its host-absolute path inside the container.

        Reproduces the auto-backup failure: bd passes the host absolute path to dolt_backup,
        Dolt resolves it in the container, and without this mount the parent dir (.bare/) is
        absent and mkdir fails EACCES.
        """
        cmd, host_dir = self._capture_cmd(tmp_path, monkeypatch, "in_repo")
        assert f"-v {host_dir}:{host_dir}:rw" in cmd, (
            "data dir must be mounted at its host-absolute path so bd's dolt_backup absolute "
            "path resolves to the same directory inside the container"
        )
        # /data alias must still be present — container-internal config depends on it.
        assert f"-v {host_dir}:/data:rw" in cmd

    def test_host_data_dir_also_mounted_at_host_absolute_path(self, tmp_path, monkeypatch):
        """host placement: data dir accessible at its host-absolute path inside the container."""
        cmd, host_dir = self._capture_cmd(tmp_path, monkeypatch, "host")
        assert f"-v {host_dir}:{host_dir}:rw" in cmd, (
            "data dir must be mounted at its host-absolute path so bd's dolt_backup absolute "
            "path resolves to the same directory inside the container"
        )
        assert f"-v {host_dir}:/data:rw" in cmd


class TestSvcEntryPointUsesTheSameMountAsALaunch:
    """`harnessed svc up` must path-mirror the SAME folder a launch does (harnessed-wnf).

    `launch` auto-widens the mount to the parent of a bare repo, so sibling worktrees are visible;
    `svc up` passed the raw cwd. In a bare + linked-worktree checkout an `in_repo` `.beads` lives
    beside `.bare/` — OUTSIDE the worktree — so a service started via `svc up` got a git surface
    that excluded exactly the directory its data dir sits in, and `bd dolt push` from that container
    could not see the repo the launch-started one does.

    It matters twice over now: `recreate` routes through this same call, so an un-widened mount here
    would be baked into every recreated container, and the create-time config hash would differ by
    entry point — flagging drift on every alternating launch.
    """

    def _capture_ensure_kwargs(
        self, tmp_path, monkeypatch, action: str, *, stack: str = "any", label: str | None = None,
        instances: list[str] | None = None,
    ) -> dict:
        checkout = tmp_path / "proj"
        project = checkout / "main"
        project.mkdir(parents=True)
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "_runtime", lambda: "podman")
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: checkout / ".bare")
        # The bare + linked-worktree layout: the widened mount is the dir CONTAINING the bare repo.
        monkeypatch.setattr(paths, "bare_worktree_container", lambda _p: checkout)
        patch_all(monkeypatch, "_svc_container_stack", lambda _rt, _c: label)
        patch_all(monkeypatch, "_svc_stacks_from_instances", lambda _rt, _p: list(instances or [])
        )
        seen: dict = {}
        monkeypatch.setattr(launcher, "_ensure_service", lambda *a, **k: seen.update(k))
        monkeypatch.chdir(project)
        launcher.svc(action, "beads-server", stack=stack)
        seen["_checkout"] = checkout
        seen["_project"] = project
        return seen

    def test_svc_up_widens_the_mount_like_launch_does(self, tmp_path, monkeypatch):
        seen = self._capture_ensure_kwargs(tmp_path, monkeypatch, "up")
        assert seen["mount_path"] == seen["_checkout"], (
            "svc up must mount the bare-repo parent, like launch — not just the worktree, which "
            "excludes the .bare-sibling .beads the service serves"
        )
        assert seen["project_path"] == seen["_project"]

    def test_recreate_uses_the_same_widened_mount(self, tmp_path, monkeypatch):
        seen = self._capture_ensure_kwargs(tmp_path, monkeypatch, "recreate")
        assert seen["mount_path"] == seen["_checkout"]
        assert seen["force_recreate"] is True, (
            "recreate must force a teardown — a container that is merely 'up' returns early and "
            "nothing is rebuilt"
        )

    def test_up_does_not_force_a_recreate(self, tmp_path, monkeypatch):
        seen = self._capture_ensure_kwargs(tmp_path, monkeypatch, "up")
        assert seen.get("force_recreate") is False

    def test_recreate_reads_the_stack_off_the_container(self, tmp_path, monkeypatch):
        """No --stack from inside the project: the container records the stack it was built from.

        Asking for it again would be asking for something the machine already knows, and a typo
        would silently rebuild against a different persist entry — a different data dir.
        """
        seen = self._capture_ensure_kwargs(
            tmp_path, monkeypatch, "recreate", stack="", label="beads-team"
        )
        assert seen["stack"] == "beads-team"
        assert seen["force_recreate"] is True

    def test_an_explicit_stack_wins_over_the_label(self, tmp_path, monkeypatch):
        seen = self._capture_ensure_kwargs(
            tmp_path, monkeypatch, "recreate", stack="chosen", label="beads-team"
        )
        assert seen["stack"] == "chosen"

    def test_recreate_without_a_container_to_read_asks_for_the_stack(
        self, tmp_path, monkeypatch, capsys
    ):
        """Nothing to infer from — say so, rather than guessing at a data dir."""
        with pytest.raises(typer.Exit):
            self._capture_ensure_kwargs(tmp_path, monkeypatch, "recreate", stack="", label=None)
        err = capsys.readouterr().err
        assert "pass --stack" in err
        assert "no agent instance to infer from" in err

    def test_recreate_falls_back_to_the_repo_s_agent_instance(self, tmp_path, monkeypatch, capsys):
        """The bootstrap case: EVERY sidecar predates the label the first time this code runs.

        Without a fallback, the first recreate — the one that fixes a container built before some
        fix landed — would demand a flag for something harnessed already knows.
        """
        seen = self._capture_ensure_kwargs(
            tmp_path, monkeypatch, "recreate", stack="", label=None, instances=["beads-team"]
        )
        assert seen["stack"] == "beads-team"
        assert "Using stack 'beads-team'" in capsys.readouterr().out, (
            "inferring a stack must be reported, never silent"
        )

    def test_the_container_label_beats_the_instance_scan(self, tmp_path, monkeypatch):
        seen = self._capture_ensure_kwargs(
            tmp_path, monkeypatch, "recreate", stack="", label="from-label",
            instances=["from-instance"],
        )
        assert seen["stack"] == "from-label"

    def test_two_candidate_stacks_refuse_to_guess(self, tmp_path, monkeypatch, capsys):
        """Picking one would rebuild against the wrong persist entry — a different data dir."""
        with pytest.raises(typer.Exit):
            self._capture_ensure_kwargs(
                tmp_path, monkeypatch, "recreate", stack="", label=None,
                instances=["stack-a", "stack-b"],
            )
        err = capsys.readouterr().err
        assert "more than one stack" in err
        assert "stack-a, stack-b" in err

    def test_up_still_requires_an_explicit_stack(self, tmp_path, monkeypatch, capsys):
        """`up` may have no container at all, so there is nothing to read a stack off of."""
        with pytest.raises(typer.Exit):
            self._capture_ensure_kwargs(tmp_path, monkeypatch, "up", stack="", label="beads-team")
        assert "pass --stack" in capsys.readouterr().err

    def test_unknown_action_is_rejected(self, tmp_path, monkeypatch, capsys):
        """`restart` is the trap this whole bead exists for — it must not silently be an alias."""
        with pytest.raises(typer.Exit):
            self._capture_ensure_kwargs(tmp_path, monkeypatch, "restart")
        assert "unknown svc action 'restart'" in capsys.readouterr().err

    def test_an_unknown_action_is_rejected_before_the_stack_guard(
        self, tmp_path, monkeypatch, capsys
    ):
        """Order matters for the diagnosis, not just the exit code.

        The scope/stack guard interpolates the action into the command it suggests. Reaching it
        first answers `svc restart beads-server` with "pass --stack ... e.g. harnessed svc restart
        beads-server --stack my-stack" — a command that is ALSO invalid, sending the user to a
        second failure instead of the real one.
        """
        with pytest.raises(typer.Exit):
            self._capture_ensure_kwargs(tmp_path, monkeypatch, "restart", stack="")
        err = capsys.readouterr().err
        assert "unknown svc action 'restart'" in err
        assert "--stack" not in err, "an invalid action must not be echoed back as a suggestion"


class TestReadingTheStackOutOfInstanceNames:
    """Instance containers carry no labels, so `harnessed-<harness>-<stack>-<hash>` is the record.

    Both ends are stripped against KNOWN values — the catalog's agents and this repo's worktree
    hashes — rather than split on a delimiter, because stack names routinely contain dashes. A
    generated stack is named like `default.beads-team.serena.superpowers-f6eb0941`; splitting that
    on `-` yields `default.beads` and loses the rest.
    """

    def _scan(
        self, monkeypatch, names, hashes: set[str], harnesses=("claude", "codex", "omp")
    ) -> list[str]:
        """`names` is either plain names (treated as stopped) or (name, state) pairs."""
        rows = [n if isinstance(n, tuple) else (n, "exited") for n in names]
        monkeypatch.setattr(paths, "list_catalog", lambda _kind: list(harnesses))
        patch_all(monkeypatch, "_repo_project_hashes", lambda _p: hashes)
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="".join(f"{n}\t{s}\n" for n, s in rows), stderr="",
            ),
        )
        return launcher._svc_stacks_from_instances("podman", Path("/repo"))

    def test_a_stack_name_containing_dashes_survives(self, monkeypatch):
        name = "harnessed-omp-default.beads-team.serena.superpowers-f6eb0941-59258991"
        assert self._scan(monkeypatch, [name], {"59258991"}) == [
            "default.beads-team.serena.superpowers-f6eb0941"
        ]

    def test_only_this_repo_s_instances_count(self, monkeypatch):
        names = [
            "harnessed-claude-mine-11111111",
            "harnessed-claude-someone-elses-22222222",
        ]
        assert self._scan(monkeypatch, names, {"11111111"}) == ["mine"]

    def test_sibling_worktrees_are_searched_too(self, monkeypatch):
        """One sidecar serves every worktree (it is keyed by git-common-dir), so the stack that
        owns it may be running from a sibling rather than from where you are standing."""
        names = ["harnessed-claude-from-a-sibling-22222222"]
        assert self._scan(monkeypatch, names, {"11111111", "22222222"}) == ["from-a-sibling"]

    def test_an_unknown_harness_is_not_mistaken_for_a_stack(self, monkeypatch):
        assert self._scan(monkeypatch, ["harnessed-nosuch-x-11111111"], {"11111111"}) == []

    def test_the_sidecars_own_containers_are_not_instances(self, monkeypatch):
        assert self._scan(monkeypatch, ["harnessed-svc-beads-server-11111111"], {"11111111"}) == []

    def test_no_instances_is_not_an_error(self, monkeypatch):
        assert self._scan(monkeypatch, [], {"11111111"}) == []

    def test_a_running_instance_beats_a_stale_stopped_one(self, monkeypatch):
        """`harnessed stop` leaves instances lying around indefinitely, so a stack you have moved
        on from must not get a vote while a stack you are actually running has one — it would
        quietly decide which persist entry the rebuilt sidecar serves."""
        names = [
            ("harnessed-claude-abandoned-11111111", "exited"),
            ("harnessed-claude-current-11111111", "running"),
        ]
        assert self._scan(monkeypatch, names, {"11111111"}) == ["current"]

    def test_stopped_instances_still_count_when_nothing_is_running(self, monkeypatch):
        """The common case for this command is a plain shell with no agent up — ignoring stopped
        instances outright would fail the very use the fallback exists for."""
        names = [("harnessed-claude-only-one-11111111", "exited")]
        assert self._scan(monkeypatch, names, {"11111111"}) == ["only-one"]

    def test_a_longer_harness_name_wins_the_prefix_match(self, monkeypatch):
        """With `claude` and `claude-extended` both in the catalog, the shorter prefix also matches
        and yields the plausible-but-WRONG stack `extended-mystack` — one container would offer two
        candidates, and picking the wrong one rebuilds against a different persist entry."""
        names = [("harnessed-claude-extended-mystack-12345678", "running")]
        got = self._scan(
            monkeypatch, names, {"12345678"}, harnesses=("claude", "claude-extended")
        )
        assert got == ["mystack"]


class TestRepoProjectHashesUsesRealGit:
    """`_repo_project_hashes` shells out to git — the mocked tests above never exercise that."""

    def test_a_plain_repo_yields_its_own_hash(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        hashes = launcher._repo_project_hashes(repo)
        assert paths.project_hash(repo) in hashes

    def test_a_linked_worktree_sees_its_siblings(self, tmp_path):
        """The reason this walks `git worktree list`: ONE sidecar (keyed by git-common-dir) serves
        every worktree, while instances are keyed per worktree — so the stack that owns the sidecar
        may be running from a sibling rather than from where you are standing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
        }
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "init", "--no-gpg-sign"], cwd=repo, check=True, env=env
        )
        sibling = tmp_path / "sibling"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(sibling)], cwd=repo, check=True, env=env
        )
        hashes = launcher._repo_project_hashes(repo)
        assert paths.project_hash(sibling) in hashes, (
            "a sibling worktree's instance must be findable from here"
        )

    def test_outside_a_git_repo_it_still_returns_this_folder(self, tmp_path):
        """git fails here; the fallback must degrade to the current folder, not raise."""
        assert launcher._repo_project_hashes(tmp_path) == {paths.project_hash(tmp_path)}


class TestServiceConfigHashDetectsStaleContainers:
    """A running sidecar carries a `harnessed.svc-config-hash` label; a launch re-derives it.

    Mounts, ports and env are fixed at CREATE time, so a container drifts from the code that would
    create it today and nothing notices — `podman restart` cannot fix it and reports success anyway.
    Observed (harnessed-ku9): every beads-server on the machine predated the path-preserving mirror
    mount, so every auto-backup failed silently for days. The label is the services-side equivalent
    of the derived image's `harnessed.recipe-hash`.
    """

    def _run_ensure(
        self, tmp_path, monkeypatch, *, running: bool, label: str | None, force: bool = False
    ) -> tuple[list[list[str]], list[list[str]]]:
        """Drive `_ensure_service` against a fake runtime. Returns (created_cmds, subprocess_cmds).

        Callable twice per tmp_path — the tests that compare a BEFORE hash against a running
        container's label need exactly that.
        """
        if not (tmp_path / "services" / "beads-server").is_dir():
            _svc_yaml(tmp_path, PROJECT_SVC)
        svc = load_service(tmp_path, "beads-server")
        project = tmp_path / "repo"
        project.mkdir(parents=True, exist_ok=True)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        patch_all(monkeypatch, "load_service", lambda _r, _n: svc)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        patch_all(monkeypatch, "_image_exists", lambda _rt, _img: True)
        patch_all(monkeypatch, "_container_running", lambda _rt, _c: running)
        patch_all(monkeypatch, "_container_stale", lambda _rt, _c, _i: False)
        patch_all(monkeypatch, "_container_config_hash", lambda _rt, _c: label)
        monkeypatch.setattr(launcher, "_install_corp_proxy_ca_in_container", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_wait_service_healthy", lambda *a, **k: None)
        patch_all(monkeypatch, "_assert_service_running", lambda *a, **k: None)
        # Headless: the recreate confirm is skipped, so the decision itself is what's under test.
        monkeypatch.setenv("HARNESSED_HEADLESS", "true")
        calls: list[list[str]] = []
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda cmd, *a, **k: (
                calls.append(list(cmd)),
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            )[1],
        )
        created: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, **k: created.append(list(cmd)))
        launcher._ensure_service(
            "podman", "beads-server", stack="any", project_path=project, mount_path=project,
            force_recreate=force,
        )
        return created, calls

    def _current_hash(self, created: list[list[str]]) -> str:
        cmd = created[0]
        return cmd[cmd.index("--label") + 1].split("=", 1)[1]

    def test_new_container_is_stamped_with_its_config_hash(self, tmp_path, monkeypatch):
        created, _ = self._run_ensure(tmp_path, monkeypatch, running=False, label=None)
        assert len(created) == 1
        cmd = created[0]
        assert "--label" in cmd
        assert any(a.startswith(f"{launcher._SVC_CONFIG_HASH_LABEL}=") for a in cmd)
        assert cmd[-1].startswith("harnessed-beads-server"), "the image ref must stay last"

    def test_the_container_records_the_stack_it_was_built_from(self, tmp_path, monkeypatch):
        """What makes `svc recreate` need no --stack: the answer is on the container."""
        created, _ = self._run_ensure(tmp_path, monkeypatch, running=False, label=None)
        assert f"{launcher._SVC_STACK_LABEL}=any" in created[0]

    def test_the_stamped_hash_is_the_hash_of_the_argv_that_created_it(self, tmp_path, monkeypatch):
        """The label must describe the container it is on — otherwise every launch reports drift."""
        created, _ = self._run_ensure(tmp_path, monkeypatch, running=False, label=None)
        cmd = created[0]
        without_labels = [
            a for i, a in enumerate(cmd)
            if a != "--label" and (i == 0 or cmd[i - 1] != "--label")
        ]
        assert self._current_hash(created) == launcher._svc_config_hash(without_labels)

    def test_a_matching_label_is_left_alone(self, tmp_path, monkeypatch):
        current = self._current_hash(self._run_ensure(tmp_path, monkeypatch, running=False, label=None)[0])
        created, _ = self._run_ensure(tmp_path, monkeypatch, running=True, label=current)
        assert created == [], "a sidecar whose config still matches must not be torn down"

    def test_a_mismatched_label_recreates(self, tmp_path, monkeypatch):
        created, calls = self._run_ensure(tmp_path, monkeypatch, running=True, label="deadbeef")
        assert len(created) == 1, "a container whose create-time config changed must be recreated"
        assert any(c[:3] == ["podman", "rm", "-f"] for c in calls), (
            "it must be REMOVED and recreated — `podman restart` reuses the existing container and "
            "cannot pick up a mount or env change"
        )

    def test_a_container_predating_the_label_is_recreated(self, tmp_path, monkeypatch):
        """The population this bead was filed over: created before harnessed recorded anything."""
        created, _ = self._run_ensure(tmp_path, monkeypatch, running=True, label=None)
        assert len(created) == 1

    def test_force_recreate_tears_down_a_current_container(self, tmp_path, monkeypatch):
        current = self._current_hash(self._run_ensure(tmp_path, monkeypatch, running=False, label=None)[0])
        created, calls = self._run_ensure(
            tmp_path, monkeypatch, running=True, label=current, force=True
        )
        assert len(created) == 1, "`svc recreate` must rebuild even a container that looks current"
        assert any(c[:3] == ["podman", "rm", "-f"] for c in calls)

    def test_a_mount_change_moves_the_hash(self, tmp_path, monkeypatch):
        """The regression that motivated the label: a mount added by newer code must be visible."""
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        project.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        base = launcher._svc_run_cmd("podman", svc, "c", "any", project, project)
        widened = launcher._svc_run_cmd("podman", svc, "c", "any", project, project.parent)
        assert launcher._svc_config_hash(base) != launcher._svc_config_hash(widened)

    def test_building_the_argv_creates_nothing_on_disk(self, tmp_path, monkeypatch):
        """`_svc_run_cmd` also runs against ALREADY-RUNNING containers, to work out what the current
        code would create. A write there would fire for a container nobody asked to touch.

        The published shape is what makes this bite: a `publish: stable` port and a password both
        come from allocate-once registries that CREATE machine-local state on a miss. Those are
        resolved by `_ensure_service` and passed in, so the builder itself writes nothing.
        """
        # `stable`, not the fixture's `ephemeral`: a stable port is the one that gets allocated and
        # written to the machine-wide registry. With `{password}` in client_env this covers both
        # allocate-once registries at once.
        stable = PUBLISHED_SVC.replace("publish: ephemeral", "publish: stable")
        svc = load_service(_svc_yaml(tmp_path, stable), "beads-server")
        project = tmp_path / "repo"
        project.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        monkeypatch.setattr(paths, "xdg_state_home", lambda: state)
        patch_all(monkeypatch, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        launcher._svc_run_cmd("podman", svc, "c", "any", project, project)
        assert not paths.persist_in_repo_dir(project, ".beads").exists(), (
            "building the argv must not create the data dir"
        )
        assert not state.exists(), (
            "building the argv must not allocate a port or mint a secret — those write "
            "machine-local state for a container we are only inspecting"
        )


class TestExclusiveLockPreflight:
    """A host process on the data dir must abort the launch BEFORE the sidecar is started.

    The sidecar shape removes lock contention between CONTAINERS by construction, but a HOST
    `dolt sql-server` on the same data dir still wins the flock. The sidecar then exits at startup
    and every client fails against a socket that was never created — a symptom that lands nowhere
    near its cause (observed 2026-07-21, harnessed-9rw).
    """

    def test_exclusive_lock_is_parsed(self, tmp_path):
        root = _svc_yaml(
            tmp_path,
            "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
            "data:\n  persist: .beads\nexclusive_lock: dolt\n",
        )
        assert load_service(root, "beads-server").exclusive_lock == "dolt"

    def test_exclusive_lock_requires_project_scope(self, tmp_path):
        root = _svc_yaml(
            tmp_path,
            "name: pinger\nimage: x:latest\nport: 8080\nexclusive_lock: dolt\n",
            name="pinger",
        )
        with pytest.raises(SchemaError, match="requires scope: project"):
            load_service(root, "pinger")

    def test_finds_a_real_host_process_running_in_the_data_dir(self, tmp_path):
        """Matches on cwd, which is what identifies the contended resource."""
        proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
        try:
            found = svcguards._host_process_in_dir("sleep", tmp_path.resolve())
            assert found is not None, "host process in the data dir was not detected"
            assert found[0] == proc.pid
        finally:
            proc.kill()
            proc.wait()

    def test_ignores_a_process_of_another_name(self, tmp_path):
        proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
        try:
            assert svcguards._host_process_in_dir("dolt", tmp_path.resolve()) is None
        finally:
            proc.kill()
            proc.wait()

    def test_ignores_a_process_outside_the_data_dir(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        proc = subprocess.Popen(["sleep", "30"], cwd=elsewhere)
        try:
            assert svcguards._host_process_in_dir("sleep", data_dir.resolve()) is None
        finally:
            proc.kill()
            proc.wait()

    def test_launch_aborts_and_names_the_offending_pid(self, tmp_path):
        svc = load_service(
            _svc_yaml(
                tmp_path,
                "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
                "data:\n  persist: .beads\nexclusive_lock: sleep\n",
            ),
            "beads-server",
        )
        proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
        try:
            with pytest.raises(typer.Exit):
                launcher._assert_data_dir_unlocked(svc, tmp_path)
        finally:
            proc.kill()
            proc.wait()

    def test_a_service_without_exclusive_lock_is_never_blocked(self, tmp_path):
        svc = load_service(
            _svc_yaml(
                tmp_path,
                "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
                "data:\n  persist: .beads\n",
            ),
            "beads-server",
        )
        proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
        try:
            launcher._assert_data_dir_unlocked(svc, tmp_path)  # must not raise
        finally:
            proc.kill()
            proc.wait()






def _dolt_db_at(path):
    """Minimal on-disk shape of an initialized Dolt database."""
    (path / ".dolt").mkdir(parents=True, exist_ok=True)
    (path / ".dolt" / "repo_state.json").write_text('{"head": "refs/heads/main"}')
    (path / ".dolt" / "noms").mkdir(exist_ok=True)
    (path / ".dolt" / "noms" / "manifest").write_text("x" * 128)
    return path








class TestPlacementIsRecordedAndEnforced:
    """The direction `_assert_placement_matches` cannot see.

    A stealth dir is keyed by recipe name + project hash, so a team launch cannot enumerate it.
    Recording which placement ran first closes that: the second, disagreeing launch is refused
    rather than silently starting an empty workspace whose missing issues read as data loss.
    """

    def _svc(self, tmp_path):
        return load_service(
            _svc_yaml(
                tmp_path,
                "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
                "data:\n  persist: .beads\nexclusive_lock: dolt\n",
            ),
            "beads-server",
        )

    def _repo(self, tmp_path, monkeypatch):
        gcd = tmp_path / ".git"
        gcd.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: gcd)
        return gcd

    def test_first_launch_records_the_placement(self, tmp_path, monkeypatch):
        gcd = self._repo(tmp_path, monkeypatch)
        launcher._assert_placement_unchanged(self._svc(tmp_path), "host", tmp_path)
        assert json.loads((gcd / "harnessed-placement.json").read_text()) == {"beads-server": "host"}

    def test_the_same_placement_relaunches_cleanly(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        svc = self._svc(tmp_path)
        launcher._assert_placement_unchanged(svc, "in_repo", tmp_path)
        launcher._assert_placement_unchanged(svc, "in_repo", tmp_path)  # must not raise

    def test_switching_placement_aborts(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        svc = self._svc(tmp_path)
        launcher._assert_placement_unchanged(svc, "host", tmp_path)
        with pytest.raises(typer.Exit):  # team launch over a stealth workspace
            launcher._assert_placement_unchanged(svc, "in_repo", tmp_path)

    def test_the_record_lives_in_the_git_dir_so_git_never_sees_it(self, tmp_path, monkeypatch):
        # Stealth exists to be invisible; a marker in the working tree would defeat that.
        gcd = self._repo(tmp_path, monkeypatch)
        launcher._assert_placement_unchanged(self._svc(tmp_path), "host", tmp_path)
        assert (gcd / "harnessed-placement.json").is_file()
        assert not (tmp_path / "harnessed-placement.json").exists()

    def test_outside_a_git_checkout_it_is_a_no_op(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: None)
        launcher._assert_placement_unchanged(self._svc(tmp_path), "host", tmp_path)  # must not raise

    def test_a_corrupt_record_does_not_block_the_launch(self, tmp_path, monkeypatch):
        gcd = self._repo(tmp_path, monkeypatch)
        (gcd / "harnessed-placement.json").write_text("{ not json")
        launcher._assert_placement_unchanged(self._svc(tmp_path), "host", tmp_path)  # must not raise
        assert json.loads((gcd / "harnessed-placement.json").read_text()) == {"beads-server": "host"}




class TestDeadServiceFailsFast:
    """`podman run -d` returns 0 once the container is CREATED.

    A service whose process dies a moment later therefore leaves the launch believing it succeeded,
    and the user gets an agent wired to a backend that is not there (harnessed-709).
    """

    def _svc(self, tmp_path):
        return load_service(
            _svc_yaml(
                tmp_path,
                "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
                "data:\n  persist: .beads\n",
            ),
            "beads-server",
        )

    def test_running_container_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "running\n", ""),
        )
        launcher._assert_service_running("podman", "svc-x", self._svc(tmp_path))  # must not raise

    def test_exited_container_aborts_the_launch(self, tmp_path, monkeypatch):
        def fake_run(cmd, *a, **k):
            if "inspect" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "exited\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)
        with pytest.raises(typer.Exit):
            launcher._assert_service_running("podman", "svc-x", self._svc(tmp_path))

    def test_the_container_log_is_surfaced(self, tmp_path, monkeypatch, capsys):
        """The reason is already in the log — the user must not have to go find it."""
        reason = 'database "dolt" is locked by another dolt process'

        def fake_run(cmd, *a, **k):
            if "inspect" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "exited\n", "")
            return subprocess.CompletedProcess(cmd, 0, reason + "\n", "")

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)
        with pytest.raises(typer.Exit):
            launcher._assert_service_running("podman", "svc-x", self._svc(tmp_path))
        assert "locked by another dolt process" in capsys.readouterr().err


class TestServicesAreEnsuredOnEveryLaunchPath:
    """Sidecars must be revived on RE-ATTACH, not only when a pod is created (harnessed-aio).

    An agent container is long-lived; its sidecars are not. `_ensure_services` used to sit after the
    re-attach branch returned, so once an instance was running, every later launch attached and never
    looked at services again — a sidecar that died stayed dead for the life of the container, long
    after whatever killed it was gone. Observed 2026-07-21: a beads-server dead for 3h while every
    session's `bd` failed against a socket nothing was left to create.

    This is a STRUCTURAL guard, not a behavioural one: `launch()` takes an interactive path that
    ends in `os.execvp`, so the ordering cannot be exercised without a live runtime. Asserting the
    order in the source is the honest way to pin the invariant that actually regressed.
    """

    def _launch_source(self) -> str:
        import inspect

        return inspect.getsource(launcher.container_run)

    def test_services_are_ensured_before_any_attach_returns(self):
        # `wire_services` is the contract operation that ensures them (bd harnessed-0tk.1); the
        # ORDER against the re-attach branch is the sequencer's, which is what this pins.
        src = self._launch_source()
        ensure_at = src.find("backend.wire_services(")
        attach_at = src.find("_attach(")
        assert ensure_at != -1, "launch() no longer wires services at all"
        assert attach_at != -1, "launch() no longer has an attach path — revisit this guard"
        assert ensure_at < attach_at, (
            "_ensure_services must run BEFORE the re-attach branch, or a dead sidecar is never "
            "revived for an already-running instance"
        )

    def test_services_are_ensured_exactly_once(self):
        """Hoisting it above the attach branch must not leave the create-path call behind."""
        assert self._launch_source().count("backend.wire_services(") == 1
        import inspect

        wire = inspect.getsource(launcher.ContainerBackend.wire_services)
        assert wire.count("_ensure_services(") == 1
