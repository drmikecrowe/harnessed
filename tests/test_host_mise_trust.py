"""mise trust survives a host launch, and the suite writes no state into the developer's home.

Two regressions found together while debugging why every `--last` aoe row was failing. They are
independent, and both are about a directory harnessed redirects that it should not have.
"""
from __future__ import annotations

import os

from pathlib import Path

from harnessed import hostrun, paths


class TestHostLaunchKeepsTheUsersMiseTrustStore:
    """mise keeps `trusted-configs` in MISE_STATE_DIR, so redirecting that dir per stack throws the
    user's trust away.

    The symptom is not obviously about trust. mise reports an untrusted config as

        mise ERROR error parsing config file: <path>

    with the actual reason on the following line, so it reads as a TOML syntax error in a file that
    parses fine — and the config is then not loaded, which silently drops whatever `[env]` it
    carried. Verified against mise 2026.8.2.
    """

    def test_the_state_dir_is_not_redirected(self):
        assert "MISE_STATE_DIR" not in hostrun._host_mise_env("s"), (
            "MISE_STATE_DIR holds mise's trust store. Redirecting it per stack gives every stack an "
            "empty one, so every project mise.toml the user already trusted reads as untrusted "
            "inside every harnessed session — and each new stack re-breaks the one they just fixed."
        )

    def test_the_data_and_config_dirs_are_still_redirected(self):
        # The isolation that MUST survive the fix: shims resolve against the data dir, and the
        # stack's own tool list lives in the config dir. Dropping either is a different bug.
        env = hostrun._host_mise_env("s")
        assert set(env) == {"MISE_DATA_DIR", "MISE_CONFIG_DIR"}

    def test_an_inherited_state_dir_is_actively_removed(self):
        """Not setting it is not enough — a previous release DID set it.

        Launching a stack from inside another stack's host session is routine, and both consumers
        merge this over an inherited environment. Left in place, the outer session's redirect keeps
        the empty trust store alive in the inner one and the bug survives the release that fixed it.
        """
        env = {"MISE_STATE_DIR": "/some/stale/stack/mise/state", "PATH": "/usr/bin"}
        hostrun._apply_host_mise_env(env, "s")
        assert "MISE_STATE_DIR" not in env
        assert env["PATH"] == "/usr/bin", "unrelated variables must be left alone"
        assert env["MISE_DATA_DIR"] == hostrun._host_mise_env("s")["MISE_DATA_DIR"]


class TestTheSuiteWritesNoStateIntoTheDevelopersHome:
    """`conftest._isolated_user_state` is autouse, and this is what it is for.

    Everything durable harnessed records — `lastrun` replay records, project-env dotenvs holding
    live service passwords, per-instance dirs, `svc-secrets` — is keyed off `paths.xdg_state_home()`.
    Unset, that is the developer's real `~/.local/state`, and the launcher tests reach all of it.
    """

    def test_the_state_root_is_not_the_real_one(self):
        assert paths.xdg_state_home() != Path.home() / ".local" / "state", (
            "XDG_STATE_HOME is not isolated, so this test run is writing lastrun records and "
            "project-env dotenvs into the developer's own harnessed state"
        )

    def test_writing_a_lastrun_record_stays_inside_the_tmp_root(self, tmp_path):
        from harnessed import lastrun

        lastrun.record("host-run", "s", "claude", tmp_path)
        written = list((paths.xdg_state_home() / "harnessed" / "last-run").glob("*.json"))
        assert written, "the record went somewhere other than $XDG_STATE_HOME"
        assert all(str(p).startswith(os.environ["XDG_STATE_HOME"]) for p in written)
