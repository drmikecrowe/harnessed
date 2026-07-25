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
import subprocess
from pathlib import Path

import pytest
import typer

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
        # `_run` is stubbed, so no container is ever created — liveness is not what this asserts.
        monkeypatch.setattr(launcher, "_assert_service_running", lambda *a, **k: None)
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
            found = launcher._host_process_in_dir("sleep", tmp_path.resolve())
            assert found is not None, "host process in the data dir was not detected"
            assert found[0] == proc.pid
        finally:
            proc.kill()
            proc.wait()

    def test_ignores_a_process_of_another_name(self, tmp_path):
        proc = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
        try:
            assert launcher._host_process_in_dir("dolt", tmp_path.resolve()) is None
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
            assert launcher._host_process_in_dir("sleep", data_dir.resolve()) is None
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


class TestNamedDatabaseMustBePresent:
    """`metadata.json` names the database; the sidecar serves `<data>/dolt/`.

    If the named database is not a child of that data dir the sidecar starts fine and every client
    fails with errno 1049 instead — the state harnessed's own checkout sat in from 2026-07-19, where
    the bytes were in bd's `~/.beads/shared-server` and nothing on the client side said so.
    """

    def _svc(self, tmp_path, lock="dolt"):
        return load_service(
            _svc_yaml(
                tmp_path,
                "name: beads-server\nimage: x:latest\nscope: project\nsocket: run/mysql.sock\n"
                f"data:\n  persist: .beads\nexclusive_lock: {lock}\n",
            ),
            "beads-server",
        )

    def _meta(self, tmp_path, **keys):
        (tmp_path / "metadata.json").write_text(json.dumps({"backend": "dolt", **keys}))

    def test_aborts_when_the_named_database_is_absent(self, tmp_path):
        self._meta(tmp_path, dolt_database="programming_personal_harnessed")
        with pytest.raises(typer.Exit):
            launcher._assert_named_database_present(self._svc(tmp_path), tmp_path)

    def test_passes_when_the_named_database_is_present(self, tmp_path):
        self._meta(tmp_path, dolt_database="myproject")
        (tmp_path / "dolt" / "myproject").mkdir(parents=True)
        launcher._assert_named_database_present(self._svc(tmp_path), tmp_path)  # must not raise

    def test_a_workspace_that_does_not_exist_yet_is_left_to_first_run_init(self, tmp_path):
        launcher._assert_named_database_present(self._svc(tmp_path), tmp_path)  # must not raise

    def test_unreadable_metadata_is_not_this_guards_problem(self, tmp_path):
        (tmp_path / "metadata.json").write_text("{ not json")
        launcher._assert_named_database_present(self._svc(tmp_path), tmp_path)  # must not raise

    def test_another_engine_is_never_checked(self, tmp_path):
        self._meta(tmp_path, dolt_database="absent")
        launcher._assert_named_database_present(self._svc(tmp_path, lock="sleep"), tmp_path)


class TestPlacementMismatchIsRejected:
    """team (`in_repo`) and stealth (`host`) placement are invisible to each other.

    A stealth launch over a checkout that already carries a team workspace starts a second, EMPTY
    workspace: no error, no issues, and "my data is gone" is the natural — and wrong — reading.
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

    def test_stealth_aborts_over_an_existing_in_repo_workspace(self, tmp_path):
        team = launcher.paths.persist_in_repo_dir(tmp_path, ".beads")
        team.mkdir(parents=True, exist_ok=True)
        (team / "metadata.json").write_text(json.dumps({"dolt_database": "x"}))
        with pytest.raises(typer.Exit):
            launcher._assert_placement_matches(self._svc(tmp_path), "host", tmp_path)

    def test_stealth_passes_when_the_checkout_has_no_in_repo_workspace(self, tmp_path):
        launcher._assert_placement_matches(self._svc(tmp_path), "host", tmp_path)  # must not raise

    def test_in_repo_placement_is_never_checked(self, tmp_path):
        team = launcher.paths.persist_in_repo_dir(tmp_path, ".beads")
        team.mkdir(parents=True, exist_ok=True)
        (team / "metadata.json").write_text(json.dumps({"dolt_database": "x"}))
        launcher._assert_placement_matches(self._svc(tmp_path), "in_repo", tmp_path)


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

        return inspect.getsource(launcher.launch)

    def test_services_are_ensured_before_any_attach_returns(self):
        src = self._launch_source()
        ensure_at = src.find("_ensure_services(")
        attach_at = src.find("_attach(")
        assert ensure_at != -1, "launch() no longer calls _ensure_services at all"
        assert attach_at != -1, "launch() no longer has an attach path — revisit this guard"
        assert ensure_at < attach_at, (
            "_ensure_services must run BEFORE the re-attach branch, or a dead sidecar is never "
            "revived for an already-running instance"
        )

    def test_services_are_ensured_exactly_once(self):
        """Hoisting it above the attach branch must not leave the create-path call behind."""
        assert self._launch_source().count("_ensure_services(") == 1
