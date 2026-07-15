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

import subprocess
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
        monkeypatch.setattr(launcher, "load_service", lambda _r, _n: svc)
        monkeypatch.setattr(launcher, "_service_refs", lambda _s: ["beads-server"])
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        sock = launcher.svc_socket_env("any", project)["HARNESSED_BEADS_SERVER_SOCKET"]
        assert sock == f"{project}/.beads/run/mysql.sock"
        assert not sock.startswith("/data"), "clients must never be handed the service's own mount path"


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
        monkeypatch.setattr(launcher, "load_service", lambda _r, _n: svc)
        monkeypatch.setattr(
            launcher, "load_stack_with_recipes", lambda _r, _s: (None, [_beads_recipe("in_repo")])
        )
        monkeypatch.setattr(launcher, "_image_exists", lambda _rt, _img: True)
        monkeypatch.setattr(launcher, "_container_running", lambda _rt, _c: False)
        monkeypatch.setattr(launcher, "_install_corp_proxy_ca_in_container", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_wait_service_healthy", lambda *a, **k: None)
        monkeypatch.setattr(
            launcher.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        )
        captured: list[list[str]] = []
        monkeypatch.setattr(launcher, "_run", lambda cmd, **k: captured.append(cmd))
        launcher._ensure_service(
            "podman", "beads-server", stack="any", project_path=project, mount_path=project
        )
        return " ".join(captured[0])

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
