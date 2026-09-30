"""The pod's env comes from the broker, not from `varlock load` — issue #439.

Before this, a schema with `@proxy` items still had `varlock load` resolve every value on the host
and hand podman a 0600 --env-file of REAL values. The broker only ever saw traffic from a pod that
already held the secret. Topology B replaces the source, not the mechanism:

    varlock proxy env --full --proxy-url <door> --cert-dir <mount> --format json

prints exactly the env a guest should run with: placeholders for `@proxy` items, real values for
passthrough items and non-secrets, the proxy vars and the seven CA-path vars. Same temp file, same
0600, same unlink.

The proxied schema dirs are never `varlock load`ed at all when a broker will run, so no real value
for them is written to disk even briefly. That is safe because a broker that fails to start, or a
door the probe cannot reach, already refuses the launch. `--no-secrets` keeps today's behaviour.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import broker, launchenv, launcher, paths

PORT = 39443
SESSION = "s1"


def _broker() -> broker.Broker:
    return broker.Broker(instance="inst", pod="pod", session=SESSION, port=PORT,
                         cert_dir="/state/inst-certs")


class TestTheProxiedDirsAreNotLoaded:
    def _schemas(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".config" / "harnessed").mkdir(parents=True)
        (home / ".config" / "harnessed" / ".env.schema").write_text("G=1\n")
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".env.schema").write_text("P=1\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launchenv.shutil, "which", lambda name: "/bin/varlock")
        monkeypatch.setattr(launchenv, "_warn_unproxied_secrets", lambda d: None)
        loaded: list[Path] = []

        def resolve(d):
            loaded.append(d)
            f = tmp_path / f"env-{len(loaded)}"
            f.write_text("")
            return f

        monkeypatch.setattr(launchenv, "_varlock_resolve_env_file", resolve)
        return home / ".config" / "harnessed", proj, loaded

    def test_a_skipped_dir_is_never_resolved(self, tmp_path, monkeypatch):
        global_dir, proj, loaded = self._schemas(tmp_path, monkeypatch)
        files, temps = launchenv._resolve_launch_secrets(proj, skip=[proj])
        assert loaded == [global_dir]
        assert files == temps and len(files) == 1

    def test_nothing_skipped_is_todays_behaviour(self, tmp_path, monkeypatch):
        global_dir, proj, loaded = self._schemas(tmp_path, monkeypatch)
        launchenv._resolve_launch_secrets(proj)
        assert loaded == [global_dir, proj]


class TestTheProxyEnvFile:
    def _run(self, monkeypatch, *, rc=0, stdout='{"A": "ph_1", "B": "real-b"}'):
        seen: dict = {}

        def run(argv, **kw):
            seen["argv"], seen["kw"] = argv, kw
            return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="err-with-value")

        monkeypatch.setattr(launchenv.subprocess, "run", run)
        path = launchenv._varlock_proxy_env_file(
            SESSION, "http://varlock:tok@door:1", paths.BROKER_GUEST_CERT_DIR,
        )
        return path, seen

    def _ok(self, monkeypatch, **kw) -> tuple[Path, dict]:
        path, seen = self._run(monkeypatch, **kw)
        assert path is not None
        return path, seen

    def test_it_asks_this_session_for_the_full_repointed_env(self, monkeypatch):
        path, seen = self._ok(monkeypatch)
        try:
            argv = seen["argv"]
            assert argv[:3] == ["varlock", "proxy", "env"]
            assert argv[argv.index("--session") + 1] == SESSION
            assert "--full" in argv
            assert argv[argv.index("--format") + 1] == "json"
            assert argv[argv.index("--proxy-url") + 1] == "http://varlock:tok@door:1"
            assert argv[argv.index("--cert-dir") + 1] == paths.BROKER_GUEST_CERT_DIR
            # #462: varlock colours output under CI; JSON is safe, but pin the same override.
            assert seen["kw"]["env"]["FORCE_COLOR"] == "0"
            assert seen["kw"].get("timeout")
        finally:
            path.unlink()

    def test_it_writes_a_0600_env_file_of_the_values(self, monkeypatch):
        path, _ = self._ok(monkeypatch)
        try:
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
            assert path.read_text() == "A=ph_1\nB=real-b\n"
        finally:
            path.unlink()

    def test_a_multiline_value_is_skipped_not_truncated(self, monkeypatch, capsys):
        path, _ = self._ok(monkeypatch, stdout='{"PEM": "a\\nb", "A": "x"}')
        try:
            assert path.read_text() == "A=x\n"
            assert "PEM" in capsys.readouterr().err
        finally:
            path.unlink()

    @pytest.mark.parametrize("rc,stdout", [(1, ""), (0, "not json"), (0, "[1, 2]")])
    def test_a_failure_returns_none_and_prints_no_output(self, monkeypatch, capsys, rc, stdout):
        path, _ = self._run(monkeypatch, rc=rc, stdout=stdout)
        assert path is None
        assert "err-with-value" not in capsys.readouterr().err


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    """BOUNDARY with a reachable broker; returns (run, calls)."""
    calls: dict = {"runs": [], "teardown": [], "proxy_env": [], "env_at_run": {}}

    def fake_run(cmd, **kw):
        calls["runs"].append(list(cmd))
        if cmd[1:3] == ["run", "-d"]:
            # Snapshot what podman would ingest; the files are unlinked right after.
            calls["env_at_run"] = {
                a: Path(a).read_text() for i, a in enumerate(cmd) if cmd[i - 1] == "--env-file"
            }

    monkeypatch.setattr(launcher, "_run", fake_run)
    for name, value in (
        ("harnessed_env", {}), ("_pending_setup_scripts", []), ("_container_setup_env", {}),
        ("_recipe_env", {}), ("_claude_oauth_token_args", []), ("_agent_placement_args", []),
    ):
        monkeypatch.setattr(launcher, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(launcher, "_broker_gateway", lambda *a, **k: "172.17.0.1")
    monkeypatch.setattr(launcher.broker, "token", lambda brk: "tok-xyz")
    monkeypatch.setattr(
        launcher, "_pod_teardown", lambda rt, inst, pod: calls["teardown"].append(inst),
    )
    monkeypatch.delenv("HARNESSED_NET", raising=False)

    def run(rt, brk, *, env_file_ok=True, existing=(), isolated=False, project_proxied=True):
        monkeypatch.setattr(launcher, "_broker_start_for", lambda *a, **k: brk)
        monkeypatch.setattr(
            launcher, "proxy_schema_dirs", lambda p: [p] if project_proxied else [Path("/global")],
        )
        proxy_file = tmp_path / "proxy.env"

        def build(session, proxy_url, cert_dir):
            assert cert_dir == paths.BROKER_GUEST_CERT_DIR, "the CA vars must point at the mount"
            calls["proxy_env"].append((session, proxy_url))
            if not env_file_ok:
                return None
            proxy_file.write_text("A=ph\nCLAUDE_CODE_OAUTH_TOKEN=x\n")
            return proxy_file

        monkeypatch.setattr(launcher, "_varlock_proxy_env_file", build)
        b = launcher.ContainerBackend.__new__(launcher.ContainerBackend)
        b.rt, b.inst, b.pod, b.recipes, b.servers = rt, "inst", "pod", [], []
        b.harness_image, b.mount_path, b.broker = "img", Path("/workspace"), None
        b.broker_gateway = None
        b.member_mounts = []
        b.secrets_env_files, b.secrets_temp_files = list(existing), list(existing)
        b.stk = type("Stk", (), {"isolated_auth": isolated, "hub_transport": "stdio"})()
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=tmp_path)
        b.apply_isolation(spec, launcher.BOUNDARY)
        return b, proxy_file

    return run, calls


def _member(calls) -> list[str]:
    (member,) = [c for c in calls["runs"] if c[1:3] == ["run", "-d"]]
    return member


class TestTheLaunchUsesTheBrokersEnv:
    @pytest.mark.parametrize("rt,door", [("podman", "host.containers.internal"),
                                         ("docker", "host.docker.internal")])
    def test_the_proxy_url_carries_the_token_to_this_runtimes_door(self, boundary, rt, door):
        run, calls = boundary
        run(rt, _broker())
        assert calls["proxy_env"] == [(SESSION, f"http://varlock:tok-xyz@{door}:{PORT}")]

    def test_the_file_reaches_the_member_and_is_unlinked_after(self, boundary):
        run, calls = boundary
        _, proxy_file = run("podman", _broker())
        argv = _member(calls)
        assert argv[argv.index(str(proxy_file)) - 1] == "--env-file"
        assert not proxy_file.exists(), "resolved env must not linger on disk"

    def test_it_comes_after_the_non_proxied_files(self, boundary, tmp_path):
        """--env-file is last-wins; a proxied project overrides a plain global, as before."""
        plain = tmp_path / "global.env"
        plain.write_text("G=1\n")
        run, calls = boundary
        _, proxy_file = run("podman", _broker(), existing=[plain])
        argv = _member(calls)
        assert argv.index(str(plain)) < argv.index(str(proxy_file))

    def test_a_proxied_global_does_not_override_a_plain_project(self, boundary, tmp_path):
        """Only the global schema opted in: its file takes the global slot, first."""
        plain = tmp_path / "project.env"
        plain.write_text("P=1\n")
        run, calls = boundary
        _, proxy_file = run("podman", _broker(), existing=[plain], project_proxied=False)
        argv = _member(calls)
        assert argv.index(str(proxy_file)) < argv.index(str(plain))

    def test_no_broker_builds_no_proxy_env(self, boundary):
        run, calls = boundary
        run("podman", None)
        assert calls["proxy_env"] == []

    def test_an_isolated_claude_stack_still_loses_the_host_token(self, boundary):
        """seed_auth strips it from every env-file; this one is built later and must match."""
        run, calls = boundary
        _, proxy_file = run("podman", _broker(), isolated=True)
        ingested = calls["env_at_run"][str(proxy_file)]
        assert "A=ph" in ingested
        assert launcher._OAUTH_TOKEN_VAR not in ingested

    def test_a_non_isolated_stack_keeps_it(self, boundary):
        """The negative control: the strip above is conditional, not a blanket filter."""
        run, calls = boundary
        _, proxy_file = run("podman", _broker())
        assert launcher._OAUTH_TOKEN_VAR in calls["env_at_run"][str(proxy_file)]

    def test_a_failed_proxy_env_refuses_the_launch(self, boundary, capsys):
        run, calls = boundary
        with pytest.raises(typer.Exit):
            run("podman", _broker(), env_file_ok=False)
        assert calls["teardown"] == ["inst"]
        assert not [c for c in calls["runs"] if c[1:3] == ["run", "-d"]]
        assert "--no-secrets" in capsys.readouterr().err


class TestSeedAuthSkipsTheProxiedDirs:
    def _seed(self, monkeypatch, tmp_path, *, no_secrets: bool):
        seen: dict = {}
        monkeypatch.setattr(launcher, "proxy_schema_dirs", lambda p: [tmp_path])
        monkeypatch.setattr(launcher, "_secrets_disabled", lambda: no_secrets)

        def resolve(project_path, *, skip=()):
            seen["skip"] = list(skip)
            return [], []

        monkeypatch.setattr(launcher, "_resolve_launch_secrets", resolve)
        monkeypatch.setattr(launcher, "_claude_creds_seed_mount", lambda *a, **k: [])
        monkeypatch.setattr(launcher, "_claude_oauth_token_configured", lambda *a, **k: True)
        b = launcher.ContainerBackend.__new__(launcher.ContainerBackend)
        b.inst, b.mount_args = "inst", []
        b.stk = type("Stk", (), {"isolated_auth": False})()
        spec = launcher.LaunchSpec(stack="s", harness="claude", project_path=tmp_path)
        b.seed_auth(spec)
        return seen["skip"]

    def test_a_broker_launch_skips_them(self, monkeypatch, tmp_path):
        assert self._seed(monkeypatch, tmp_path, no_secrets=False) == [tmp_path]

    def test_no_secrets_loads_everything_as_before(self, monkeypatch, tmp_path):
        assert self._seed(monkeypatch, tmp_path, no_secrets=True) == []
