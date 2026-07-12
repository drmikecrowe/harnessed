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

from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.schema import PersistEntry, PersistSpec, Recipe, SchemaError, load_service


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
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
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
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        host_dir, _, _ = launcher._service_data_dir(svc, "any", tmp_path / "checkout" / "main")
        assert host_dir == bare / ".beads"

    def test_host_recipe_puts_the_data_dir_outside_the_repo(self, tmp_path, monkeypatch):
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(paths, "persist_root", lambda: tmp_path / "persist")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: Path(p) / ".git")
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("host")])
        )
        project = tmp_path / "repo"
        host_dir, agent_dir, location = launcher._service_data_dir(svc, "any", project)
        assert location == "host"
        assert (tmp_path / "persist") in host_dir.parents
        assert agent_dir == "/home/harnessed/.beads"

    def test_missing_persist_entry_is_a_schema_error(self, tmp_path, monkeypatch):
        # A stack that attaches beads-server but has no beads recipe cannot say where the data lives.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda _r, _s: (None, []))
        with pytest.raises(SchemaError, match="data.persist"):
            launcher._service_data_dir(svc, "no-beads-stack", tmp_path)


class TestSocketEnvExport:
    def test_socket_path_is_exported_for_the_attach_shell(self, tmp_path, monkeypatch):
        # Recipes reference $HARNESSED_BEADS_SERVER_SOCKET in their `setup:` rather than recomputing
        # the launcher's path arithmetic.
        svc = load_service(_svc_yaml(tmp_path, PROJECT_SVC), "beads-server")
        project = tmp_path / "repo"
        monkeypatch.setattr(paths, "git_common_dir", lambda _p: project / ".git")
        monkeypatch.setattr(launcher, "load_service", lambda _r, _n: svc)
        monkeypatch.setattr(launcher, "_service_refs", lambda _s: ["beads-server"])
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        env = launcher.svc_socket_env("any", project)
        assert env == {"HARNESSED_BEADS_SERVER_SOCKET": f"{project}/.beads/run/mysql.sock"}

    def test_global_services_export_nothing(self, tmp_path, monkeypatch):
        root = _svc_yaml(tmp_path, "name: ping\nimage: harnessed-ping:latest\nport: 8080\n", name="ping")
        monkeypatch.setattr(launcher, "load_service", lambda _r, _n: load_service(root, "ping"))
        monkeypatch.setattr(launcher, "_service_refs", lambda _s: ["ping"])
        assert launcher.svc_socket_env("any", tmp_path) == {}
