"""The beads `bd` shim: per-invocation workspace resolution.

Regression cover for the 2026-07-26 report. `harnessed host-run <stack>` in project A, then a second
session opened in project B from Claude Code's session switcher: `bd list` in B listed A's issues.
Both sessions are children of one harness process, and that process carries A's `BEADS_DIR` plus A's
beads-server connection vars — resolved once, at launch, and read by `bd` on every invocation.

The fix keeps those exports (they are what makes bd CWD-independent for a harness that starts the
agent in $HOME — harnessed-b0s) and demotes them to a FALLBACK: a `bd` wrapper ahead of mise's shim
re-resolves from $PWD per call. What it must NOT do is retarget halfway — BEADS_DIR pointing at B
while the connection still points at A's dolt server is how issues get written into the wrong
database (BEADS.md §10). So a foreign project is either fully resolved or refused.

The shim reimplements three pieces of the launcher's path arithmetic in shell; the tests below pin
each one against the Python it mirrors rather than against a hard-coded string.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from harnessed import emit, launcher, paths
from harnessed.schema import load_recipe

REPO = Path(__file__).resolve().parents[1]
TEAM = REPO / "catalog" / "recipes" / "beads" / "team"
STEALTH = REPO / "catalog" / "recipes" / "beads" / "stealth"
SHIM_SRC = TEAM / "bd-shim.sh"

_STUB_BD = """#!/usr/bin/env bash
python3 -c '
import json, os, sys
print(json.dumps({
    "args": sys.argv[1:],
    "env": {k: os.environ.get(k, "") for k in (
        "BEADS_DIR", "BEADS_DOLT_SERVER_HOST", "BEADS_DOLT_SERVER_PORT",
        "BEADS_DOLT_PASSWORD", "BEADS_DOLT_AUTO_START", "BEADS_DOLT_SERVER_SOCKET",
    )},
}))' "$@"
"""


def _git_repo(root: Path) -> Path:
    """Init a repo and return its git common dir (`<root>/.git`)."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root / ".git"


@pytest.fixture
def env(tmp_path: Path):
    """A launch project, a shim on PATH ahead of a stub `bd`, and knobs for the rest."""
    bin_dir = tmp_path / "bin"
    (bin_dir / "bd-shim").mkdir(parents=True)
    shim = bin_dir / "bd-shim" / "bd"
    shim.write_bytes(SHIM_SRC.read_bytes())
    shim.chmod(0o755)

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "bd").write_text(_STUB_BD)
    (stub_dir / "bd").chmod(0o755)

    launch = tmp_path / "launch"
    launch_gcd = _git_repo(launch)

    state = tmp_path / "state"
    data = tmp_path / "data"

    class Env:
        shim_dir = bin_dir / "bd-shim"
        stub = stub_dir
        launch_dir = launch
        gcd = launch_gcd
        podman_log = tmp_path / "podman.log"
        # A socket-era launch carries this. Opt-in per test: the current transport is TCP, and
        # whether the socket is LIVE is now behaviour under test rather than fixture noise.
        socket_path: str | None = None

        def with_podman(self, port: str | None = "49183") -> None:
            """A stub `podman port` — `None` means the sidecar is not running."""
            body = f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{self.podman_log}"\n'
            body += f'printf "127.0.0.1:{port}\\n"\n' if port else "exit 125\n"
            (stub_dir / "podman").write_text(body)
            (stub_dir / "podman").chmod(0o755)

        def secret(self, gcd: Path, value: str = "s3cret") -> Path:
            store = state / "harnessed" / "svc-secrets"
            store.mkdir(parents=True, exist_ok=True)
            f = store / f"beads-server-{paths.project_hash(gcd)}"
            f.write_text(value)
            return f

        def run(self, cwd: Path, *args: str, beads_dir: Path | None = None):
            import os

            e = dict(os.environ)
            e["PATH"] = f"{self.shim_dir}:{stub_dir}:{e['PATH']}"
            e["BEADS_DIR"] = str(beads_dir or (launch / ".beads"))
            e["HARNESSED_GIT_COMMON_DIR"] = str(launch_gcd)
            # Explicit both ways. The developer running these tests is very likely inside a
            # harnessed session whose own BEADS_DOLT_SERVER_SOCKET is set — and, post-reversal,
            # points at a socket nothing serves. Inheriting that silently turns every passthrough
            # case into a stale-socket case.
            e.pop("BEADS_DOLT_SERVER_SOCKET", None)
            e.pop("HARNESSED_BEADS_SERVER_SOCKET", None)
            if self.socket_path:
                e["BEADS_DOLT_SERVER_SOCKET"] = self.socket_path
            e["XDG_STATE_HOME"] = str(state)
            e["XDG_DATA_HOME"] = str(data)
            e.pop("HARNESSED_BD_SHIM", None)
            return subprocess.run(
                ["bd", *args], cwd=cwd, env=e, capture_output=True, text=True
            )

    return Env()


def _payload(proc) -> dict:
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestPassthrough:
    """Everything that is not a foreign project must reach bd untouched — the b0s guarantee."""

    def test_outside_any_repo_keeps_the_launch_env(self, env, tmp_path):
        """The case the exports exist for: omp starts the agent in $HOME, where no git walk can
        find a workspace. The shim must not turn that into an error."""
        elsewhere = tmp_path / "not-a-repo"
        elsewhere.mkdir()
        out = _payload(env.run(elsewhere, "list"))
        assert out["env"]["BEADS_DIR"] == str(env.launch_dir / ".beads")
        assert out["args"] == ["list"]

    def test_inside_the_launch_project_keeps_the_launch_env(self, env):
        out = _payload(env.run(env.launch_dir, "list"))
        assert out["env"]["BEADS_DIR"] == str(env.launch_dir / ".beads")

    def test_a_worktree_of_the_launch_project_is_the_same_project(self, env, tmp_path):
        """git-common-dir keyed, like every other per-project key in the launcher: a linked
        worktree shares the launch project's beads and must not be treated as foreign."""
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "root"],
            cwd=env.launch_dir, check=True,
        )
        wt = tmp_path / "wt"
        subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "feat", str(wt)],
            cwd=env.launch_dir, check=True,
        )
        out = _payload(env.run(wt, "list"))
        assert out["env"]["BEADS_DIR"] == str(env.launch_dir / ".beads")

    def test_the_escape_hatch_skips_resolution_entirely(self, env, tmp_path):
        import os

        foreign = tmp_path / "foreign"
        _git_repo(foreign)
        (foreign / ".beads").mkdir()
        e = dict(os.environ)
        e["PATH"] = f"{env.shim_dir}:{env.stub}:{e['PATH']}"
        e["BEADS_DIR"] = str(env.launch_dir / ".beads")
        e["HARNESSED_GIT_COMMON_DIR"] = str(env.gcd)
        e["HARNESSED_BD_SHIM"] = "off"
        proc = subprocess.run(
            ["bd", "list"], cwd=foreign, env=e, capture_output=True, text=True
        )
        assert _payload(proc)["env"]["BEADS_DIR"] == str(env.launch_dir / ".beads")


class TestStaleLaunchEnv:
    """The launch project is re-resolved too — but only when its inherited socket is gone.

    A daemon can hold a launch env for days while the sidecar underneath it is rebuilt by a
    harnessed that has since changed transport. bd then selects socket mode because the variable
    exists, and reports "Dolt server unreachable … Auto-start is not supported in socket mode" about
    a database whose server is healthy on a port. Passing that through unvalidated is how the launch
    project became the one case the shim could not help.
    """

    def test_a_live_socket_is_still_trusted(self, env):
        """The check is `-S`, not "is a socket variable set" — a working socket must pass through
        untouched, or every socket-era launch breaks."""
        sock = env.launch_dir / ".beads" / "run" / "mysql.sock"
        sock.parent.mkdir(parents=True, exist_ok=True)
        env.socket_path = str(sock)
        import socket as _s
        srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        srv.bind(str(sock))
        try:
            out = _payload(env.run(env.launch_dir, "list"))
            assert out["env"]["BEADS_DOLT_SERVER_SOCKET"] == str(sock)
        finally:
            srv.close()

    def test_a_vanished_socket_is_re_resolved(self, env, tmp_path):
        """The launch project, whose socket no longer exists: discover the sidecar instead."""
        env.socket_path = str(env.launch_dir / ".beads" / "run" / "gone.sock")
        env.with_podman("49183")
        env.secret(env.gcd, "pw-launch")
        (env.launch_dir / ".beads").mkdir(parents=True, exist_ok=True)
        out = _payload(env.run(env.launch_dir, "list"))
        assert out["env"]["BEADS_DOLT_SERVER_SOCKET"] == ""
        assert out["env"]["BEADS_DOLT_SERVER_PORT"] == "49183"
        assert out["env"]["BEADS_DOLT_PASSWORD"] == "pw-launch"

    def test_it_says_relaunch_not_cd_back(self, env):
        """Telling someone standing in the right repo to `cd back` is nonsense."""
        env.socket_path = str(env.launch_dir / ".beads" / "run" / "gone.sock")
        env.with_podman(None)
        (env.launch_dir / ".beads").mkdir(parents=True, exist_ok=True)
        proc = env.run(env.launch_dir, "list")
        assert proc.returncode != 0
        assert "relaunch harnessed here" in proc.stderr
        assert "cd back" not in proc.stderr

    def test_no_repo_still_passes_through_with_a_dead_socket(self, env, tmp_path):
        """b0s: an agent started in $HOME has nothing to re-resolve FROM, so the launch env is all
        there is — even a stale one. Never turn that into an error."""
        env.socket_path = str(env.launch_dir / ".beads" / "run" / "gone.sock")
        elsewhere = tmp_path / "not-a-repo"
        elsewhere.mkdir()
        out = _payload(env.run(elsewhere, "list"))
        assert out["env"]["BEADS_DIR"] == str(env.launch_dir / ".beads")


class TestForeignProject:
    """A different repository under $PWD — resolve it completely or refuse."""

    def test_resolved_when_workspace_port_and_password_all_exist(self, env, tmp_path):
        foreign = tmp_path / "foreign"
        fgcd = _git_repo(foreign)
        (foreign / ".beads").mkdir()
        env.with_podman("49183")
        env.secret(fgcd, "pw-for-b")

        out = _payload(env.run(foreign, "list"))
        assert out["env"]["BEADS_DIR"] == str(foreign / ".beads")
        assert out["env"]["BEADS_DOLT_SERVER_PORT"] == "49183"
        assert out["env"]["BEADS_DOLT_PASSWORD"] == "pw-for-b"
        # Auto-start is what turned a reachability problem into five days of data loss in §10; the
        # shim must carry the interlock into the retargeted env, not just the connection.
        assert out["env"]["BEADS_DOLT_AUTO_START"] == "false"
        assert out["env"]["BEADS_DOLT_SERVER_HOST"] == "127.0.0.1"

    def test_the_sidecar_is_looked_up_under_the_launchers_container_name(self, env, tmp_path):
        """The shim recomputes `harnessed-svc-beads-server-<project_hash(gcd)>` in shell. Pin it to
        the Python that names the container, or the two drift on the next hash change."""
        foreign = tmp_path / "foreign"
        fgcd = _git_repo(foreign)
        (foreign / ".beads").mkdir()
        env.with_podman("49183")
        env.secret(fgcd)
        env.run(foreign, "list")
        expected = launcher._svc_container("beads-server", paths.project_hash(fgcd))
        assert env.podman_log.read_text().split() [:3] == ["port", expected, "3307"]

    def test_stealth_placement_is_found_under_the_persist_root(self, env, tmp_path):
        """The foreign project's placement is its own business: no in-repo .beads means look where
        `beads/stealth` puts it — paths.persist_project_dir, reimplemented in the shim."""
        foreign = tmp_path / "foreign"
        fgcd = _git_repo(foreign)
        stealth_dir = (
            tmp_path / "data" / "harnessed" / "persist" / "beads-stealth"
            / paths.project_hash(fgcd) / ".beads"
        )
        stealth_dir.mkdir(parents=True)
        env.with_podman("49183")
        env.secret(fgcd)

        out = _payload(env.run(foreign, "list"))
        assert out["env"]["BEADS_DIR"] == str(stealth_dir)


    def test_the_launch_projects_socket_is_cleared(self, env, tmp_path):
        """Setting the new connection is not enough. bd picks socket mode whenever
        BEADS_DOLT_SERVER_SOCKET is set, so a launch-era socket outranks every port variable and bd
        dials the LAUNCH project's database while believing it is talking to this one — observed
        2026-07-27 as "Dolt server unreachable at <launch project>/.beads/run/mysql.sock" from a
        session whose BEADS_DIR had been retargeted correctly. Whether TCP or the socket wins is a
        coin flip, which is exactly what the honesty rule exists to prevent."""
        foreign = tmp_path / "foreign"
        fgcd = _git_repo(foreign)
        (foreign / ".beads").mkdir()
        env.socket_path = str(env.launch_dir / ".beads" / "run" / "mysql.sock")
        env.with_podman("49183")
        env.secret(fgcd)
        out = _payload(env.run(foreign, "list"))
        assert out["env"]["BEADS_DOLT_SERVER_SOCKET"] == ""
        assert out["env"]["BEADS_DOLT_SERVER_PORT"] == "49183"

    def test_no_workspace_refuses_instead_of_falling_back(self, env, tmp_path):
        foreign = tmp_path / "foreign"
        _git_repo(foreign)
        env.with_podman("49183")
        proc = env.run(foreign, "list")
        assert proc.returncode != 0
        assert "no beads workspace" in proc.stderr
        assert str(foreign) in proc.stderr

    def test_a_workspace_with_no_reachable_server_refuses(self, env, tmp_path):
        """The half-retarget this whole design exists to prevent: B's metadata over A's server."""
        foreign = tmp_path / "foreign"
        fgcd = _git_repo(foreign)
        (foreign / ".beads").mkdir()
        env.with_podman(None)  # sidecar not running
        env.secret(fgcd)
        proc = env.run(foreign, "list")
        assert proc.returncode != 0
        assert "no reachable beads-server" in proc.stderr
        assert "Launch harnessed in" in proc.stderr

    def test_a_missing_password_refuses_too(self, env, tmp_path):
        foreign = tmp_path / "foreign"
        _git_repo(foreign)
        (foreign / ".beads").mkdir()
        env.with_podman("49183")  # port answers, but no secret was ever minted
        proc = env.run(foreign, "list")
        assert proc.returncode != 0
        assert "no reachable beads-server" in proc.stderr


class TestWiring:
    """The shim only helps if it is actually installed and actually first on PATH."""

    def test_both_placements_ship_the_same_shim(self):
        """team and stealth are separate recipe dirs (the container build COPYs one of them), so the
        file is duplicated. Byte-identical, or the two placements diverge silently."""
        assert (STEALTH / "bd-shim.sh").read_bytes() == SHIM_SRC.read_bytes()

    @pytest.mark.parametrize("recipe_dir", [TEAM, STEALTH], ids=["team", "stealth"])
    def test_install_puts_the_shim_in_its_own_dir_under_the_bin_dir(self, recipe_dir):
        body = (recipe_dir / "install.sh").read_text()
        assert '"${HARNESSED_BIN_DIR:?}/bd-shim"' in body
        assert 'install -m 0755 "${HARNESSED_RECIPE_DIR:?}/bd-shim.sh" "$shim_dir/bd"' in body
        # Before the "bd is already the pinned version" early exit, which would otherwise skip it.
        assert body.index("bd-shim.sh") < body.index("nothing to do")

    @pytest.mark.parametrize("recipe_dir", [TEAM, STEALTH], ids=["team", "stealth"])
    def test_init_prepends_the_shim_dir_to_path(self, recipe_dir):
        """mise's shims lead PATH in the base image, so `bd` resolves to mise's unless the shim dir
        is prepended at attach time. A plain export — Model A runs init on every attach."""
        recipe = load_recipe(recipe_dir)
        assert recipe.init is not None
        assert 'export PATH="${HARNESSED_BIN_DIR:?}/bd-shim:$PATH"' in recipe.init.run


class TestBinDirContract:
    """`init:` can only reference $HARNESSED_BIN_DIR if the attach shell exports it."""

    def _env(self, mode: str, tmp_path: Path) -> dict[str, str]:
        return launcher.harnessed_env(
            "any-stack", tmp_path, harness="claude", mode=mode, sockets=False
        )

    def test_container_mode_names_the_image_bin_dir(self, tmp_path):
        assert self._env("container", tmp_path)["HARNESSED_BIN_DIR"] == "/home/harnessed/.local/bin"

    def test_host_mode_names_the_stacks_own_tools_bin(self, tmp_path):
        expected = launcher._stack_tools_dirs("any-stack")[1]
        assert self._env("host", tmp_path)["HARNESSED_BIN_DIR"] == str(expected)

    def test_it_is_the_same_dir_the_install_contract_hands_the_script(self, tmp_path):
        """One name, one dir: an install lands the wrapper here, the attach shell puts THIS on
        PATH. If the two ever disagree the shim is installed somewhere nothing looks."""
        recipe = type("R", (), {"install": None, "name": "beads-team", "root": tmp_path})()
        install = emit.install_env(
            recipe, mode="container", harness="claude", config_dir="/home/harnessed/.claude",
            cache_dir="", bin_dir="/home/harnessed/.local/bin", home_shim="/home/harnessed",
        )
        assert install["HARNESSED_BIN_DIR"] == self._env("container", tmp_path)["HARNESSED_BIN_DIR"]
