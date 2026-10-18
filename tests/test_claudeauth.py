"""GH-597: one Claude login per machine, refreshed by the host alone.

The host store keeps the refresh token; every stack home and pod gets a view without it. These pin
what `sync`, the refresher pass and the refresher start do with real files under tmp dirs.
"""
import fcntl
import json
import os
import threading
import time

import pytest

from harnessed import claudeauth
from harnessed.claudeauth import start_refresher as _real_start_refresher  # before conftest stubs it


def _login(access: str, *, refresh: str | None = "r", expires_in: float = 8 * 3600, **extra) -> dict:
    oauth = {"accessToken": access, "expiresAt": int((time.time() + expires_in) * 1000), **extra}
    if refresh is not None:
        oauth["refreshToken"] = refresh
        oauth["refreshTokenExpiresAt"] = 1
    return {"claudeAiOauth": oauth}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A host store, one host stack home, one pod view and one isolated-auth store."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    store = tmp_path / "home" / ".claude" / ".credentials.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps(_login("host")))
    stack = tmp_path / "data" / "harnessed" / "home" / "s" / "claude" / ".credentials.json"
    stack.parent.mkdir(parents=True)
    stack.symlink_to(store)  # the pre-GH-597 layout
    pod = tmp_path / "state" / "harnessed" / "harnessed-claude-s-1" / "credentials.json"
    pod.parent.mkdir(parents=True)
    pod.write_text(json.dumps({**_login("pod", refresh="pod-r"), "mcpOAuth": {"srv": 1}}))
    isolated = tmp_path / "state" / "harnessed" / "harnessed-claude-c-2" / "isolated-auth" / "credentials.json"
    isolated.parent.mkdir(parents=True)
    isolated.write_text(json.dumps(_login("client")))
    return store, stack, pod, isolated


def _oauth(path):
    return json.loads(path.read_text())["claudeAiOauth"]


class TestSync:
    def test_every_view_gets_the_host_login_without_the_refresh_token(self, env):
        store, stack, pod, _ = env
        before = store.read_text()
        claudeauth.sync()
        for view in (stack, pod):
            assert _oauth(view)["accessToken"] == "host"
            assert "refreshToken" not in _oauth(view)
            assert "refreshTokenExpiresAt" not in _oauth(view)
        assert not stack.is_symlink(), "a symlinked view is replaced, never written through"
        assert store.read_text() == before, "sync wrote the host store"

    def test_a_pod_view_keeps_its_inode_and_its_mcp_logins(self, env):
        _, _, pod, _ = env
        inode = pod.stat().st_ino
        claudeauth.sync()
        assert pod.stat().st_ino == inode
        assert json.loads(pod.read_text())["mcpOAuth"] == {"srv": 1}

    def test_a_shorter_view_leaves_no_trailing_bytes(self, env):
        """The in-place write overwrites, then trims: a shorter body must not keep the old tail."""
        _, _, pod, _ = env
        pod.write_text(json.dumps({**_login("pod", refresh="pod-r"), "pad": "x" * 500}))
        inode = pod.stat().st_ino
        claudeauth.write_view(pod, {"accessToken": "a"}, in_place=True)
        assert pod.stat().st_ino == inode
        assert json.loads(pod.read_text())["claudeAiOauth"] == {"accessToken": "a"}

    def test_a_pod_view_write_waits_for_another_writer(self, env):
        """Two syncs (the refresher and a launch) must not interleave their in-place writes."""
        _, _, pod, _ = env
        before = pod.read_text()
        with pod.open("r") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            writer = threading.Thread(
                target=claudeauth.write_view, args=(pod, {"accessToken": "b"}), kwargs={"in_place": True}
            )
            writer.start()
            writer.join(0.3)
            assert writer.is_alive() and pod.read_text() == before
        writer.join(5)
        assert _oauth(pod) == {"accessToken": "b"}

    def test_the_merge_reads_what_the_previous_writer_stored(self, env):
        """The merge happens under the lock, so keys stored while this writer waited survive."""
        _, _, pod, _ = env
        with pod.open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            writer = threading.Thread(
                target=claudeauth.write_view, args=(pod, {"accessToken": "b"}), kwargs={"in_place": True}
            )
            writer.start()
            writer.join(0.3)
            # Another writer, holding the lock, stores a key before this one runs.
            held.seek(0)
            held.write(json.dumps({"claudeAiOauth": {"accessToken": "a"}, "mcpOAuth": {"new": 1}}))
            held.truncate()
            held.flush()
        writer.join(5)
        data = json.loads(pod.read_text())
        assert data == {"claudeAiOauth": {"accessToken": "b"}, "mcpOAuth": {"new": 1}}

    def test_a_configured_token_leaves_every_file_alone(self, env, monkeypatch):
        """Under `CLAUDE_CODE_OAUTH_TOKEN` nothing reads these files; the host side keeps none."""
        _, stack, pod, _ = env
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        before = pod.read_text()
        claudeauth.sync()
        assert pod.read_text() == before
        assert stack.is_symlink()

    def test_a_store_that_vanishes_after_the_check_gives_no_view(self, env, monkeypatch):
        """A logout between the usability check and the read must not fail a launch."""
        store, *_ = env
        monkeypatch.setattr(claudeauth, "_credentials_are_usable", lambda path: True)
        store.unlink()
        assert claudeauth.access_view(store) is None

    def test_an_isolated_auth_login_is_never_touched(self, env):
        *_, isolated = env
        before = isolated.read_text()
        claudeauth.sync()
        assert isolated.read_text() == before

    def test_a_newer_login_made_inside_a_stack_is_promoted_first(self, env):
        """A `/login` in a stack writes a full pair into its view. Overwriting it unpromoted would
        throw the new login away."""
        store, stack, pod, _ = env
        stack.unlink()
        stack.write_text(json.dumps(_login("stack-login", refresh="stack-r")))
        os.utime(stack, (time.time() + 60, time.time() + 60))
        claudeauth.sync()
        assert _oauth(store)["refreshToken"] == "stack-r"
        assert _oauth(stack)["accessToken"] == "stack-login"
        assert "refreshToken" not in _oauth(stack)
        assert _oauth(pod)["accessToken"] == "stack-login"

    def test_a_gutted_host_store_writes_no_view(self, env):
        store, _, pod, _ = env
        store.write_text(json.dumps(_login("", refresh="", expires_in=0)))
        before = pod.read_text()
        claudeauth.sync()
        assert pod.read_text() == before


    def test_a_store_with_top_level_tokens_writes_no_view(self, env):
        """`_credentials_are_usable` accepts a bare token object; a view needs `claudeAiOauth`."""
        store, _, pod, _ = env
        store.write_text(json.dumps(_login("bare")["claudeAiOauth"]))
        before = pod.read_text()
        claudeauth.sync()
        assert pod.read_text() == before


class TestTick:
    def test_refreshes_only_inside_the_lead(self, env, monkeypatch):
        store, *_ = env
        calls = []
        monkeypatch.setattr(claudeauth, "refresh_host", calls.append)
        monkeypatch.setattr(claudeauth, "_last_refresh", 0.0)
        claudeauth.tick()
        assert calls == []
        store.write_text(json.dumps(_login("host", expires_in=60)))
        claudeauth.tick()
        assert calls == [store]

    def test_a_failing_refresh_is_not_retried_every_tick(self, env, monkeypatch):
        store, *_ = env
        store.write_text(json.dumps(_login("host", expires_in=-60)))
        calls = []
        monkeypatch.setattr(claudeauth, "refresh_host", calls.append)
        monkeypatch.setattr(claudeauth, "_last_refresh", 0.0)
        claudeauth.tick()
        claudeauth.tick()
        assert len(calls) == 1


class TestRefreshHost:
    def test_runs_claude_against_the_host_store_with_nothing_else_loaded(self, env, monkeypatch):
        store, *_ = env
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
        seen = {}
        monkeypatch.setattr(claudeauth.shutil, "which", lambda name: "/bin/claude")

        def fake_run(argv, **kw):
            seen.update(argv=argv, env=kw["env"], cwd=kw["cwd"])
            return claudeauth.subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(claudeauth.subprocess, "run", fake_run)
        claudeauth.refresh_host(store)
        assert seen["argv"][:2] == ["/bin/claude", "-p"]
        assert "--no-session-persistence" in seen["argv"]
        assert seen["argv"][seen["argv"].index("--setting-sources") + 1] == "project"
        assert "CLAUDE_CONFIG_DIR" not in seen["env"], "setting it to ~/.claude moves .claude.json"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in seen["env"]

    def test_inside_a_stack_the_stack_config_dir_is_not_the_store(self, env, monkeypatch):
        """A launch from inside a host stack inherits that stack's CLAUDE_CONFIG_DIR."""
        store, stack, *_ = env
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(stack.parent))
        assert claudeauth.host_store() == store
        seen = {}
        monkeypatch.setattr(claudeauth.shutil, "which", lambda name: "/bin/claude")
        def fake_run(argv, **kw):
            seen.update(env=kw["env"])
            return claudeauth.subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(claudeauth.subprocess, "run", fake_run)
        claudeauth.refresh_host(store)
        assert "CLAUDE_CONFIG_DIR" not in seen["env"]

    def test_a_failing_claude_is_logged_as_a_failure(self, env, monkeypatch, capsys):
        store, *_ = env
        monkeypatch.setattr(claudeauth.shutil, "which", lambda name: "/bin/claude")
        monkeypatch.setattr(
            claudeauth.subprocess, "run", lambda argv, **kw: claudeauth.subprocess.CompletedProcess(argv, 3)
        )
        claudeauth.refresh_host(store)
        assert "claude exited 3" in capsys.readouterr().out


class TestStartRefresher:
    def test_spawns_when_none_runs(self, env, monkeypatch):
        spawned = []
        monkeypatch.setattr(claudeauth.subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
        _real_start_refresher()
        assert spawned[0][1:3] == ["-m", "harnessed.claudeauth"]

    def test_the_child_inherits_the_held_lock(self, env, monkeypatch):
        """No gap between the check and the child: while the parent spawns, the lock is held, and
        the child gets that same locked fd."""
        lock = claudeauth._lock_path()
        seen = {}

        def fake_popen(argv, **kw):
            seen.update(argv=argv, pass_fds=kw["pass_fds"])
            with lock.open("w") as probe:  # another launch, mid-spawn
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

        monkeypatch.setattr(claudeauth.subprocess, "Popen", fake_popen)
        _real_start_refresher()
        assert seen["pass_fds"] == (int(seen["argv"][3]),)

    def test_does_not_spawn_without_a_host_login(self, env, monkeypatch):
        store, *_ = env
        store.unlink()
        spawned = []
        monkeypatch.setattr(claudeauth.subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
        _real_start_refresher()
        assert spawned == []

    def test_does_not_spawn_while_one_holds_the_lock(self, env, monkeypatch):
        lock = claudeauth._lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            spawned = []
            monkeypatch.setattr(claudeauth.subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
            _real_start_refresher()
        assert spawned == []
