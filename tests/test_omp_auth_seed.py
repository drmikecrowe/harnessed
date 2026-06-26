"""Tests for omp credential seeding (Oh My Pi keeps auth in its own SQLite store).

omp authenticates from ~/.omp/agent/agent.db (table auth_credentials), not ~/.claude. The launcher
must snapshot that store per-instance, carry the credentials, and strip host history.
"""

import sqlite3
from pathlib import Path

from harnessed import launcher

CONTAINER_HOME = launcher._CONTAINER_HOME_STR


def _fake_host_omp_db(home: Path):
    """Create a minimal ~/.omp/agent/agent.db with an auth cred + some host history."""
    agent = home / ".omp" / "agent"
    agent.mkdir(parents=True)
    db = sqlite3.connect(str(agent / "agent.db"))
    db.execute("CREATE TABLE auth_credentials (id INTEGER PRIMARY KEY, provider TEXT, data TEXT)")
    db.execute("INSERT INTO auth_credentials (provider, data) VALUES ('anthropic', 'oauth-token')")
    db.execute("CREATE TABLE threads (id INTEGER PRIMARY KEY, body TEXT)")
    db.execute("INSERT INTO threads (body) VALUES ('host session — must NOT leak')")
    db.execute("CREATE TABLE cache (k TEXT)")
    db.execute("INSERT INTO cache (k) VALUES ('host')")
    db.commit()
    db.close()


def _home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return home


def _seeded_db(mount: list[str]) -> Path:
    assert mount[0] == "-v"
    return Path(mount[1].split(":")[0]) / "agent.db"


class TestOmpAuthSeed:
    def test_carries_credentials_strips_history(self, monkeypatch, tmp_path):
        _home(monkeypatch, tmp_path)
        _fake_host_omp_db(Path.home())

        mount = launcher._omp_auth_seed_mount("omp", "harnessed-omp_x-deadbeef")

        # Mounted rw at the container's ~/.omp/agent.
        assert mount[1].endswith(f":{CONTAINER_HOME}/.omp/agent:rw")
        db = sqlite3.connect(str(_seeded_db(mount)))
        # Credentials carried over.
        assert db.execute("SELECT data FROM auth_credentials WHERE provider='anthropic'").fetchone()[0] == "oauth-token"
        # Host history stripped — table kept (schema), rows gone.
        assert db.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
        db.close()

    def test_no_host_store_returns_empty(self, monkeypatch, tmp_path):
        _home(monkeypatch, tmp_path)  # no ~/.omp/agent/agent.db created
        assert launcher._omp_auth_seed_mount("omp", "inst-x") == []

    def test_non_omp_harness_noop(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        _fake_host_omp_db(home)
        assert launcher._omp_auth_seed_mount("claude", "inst-x") == []

    def test_reseed_overwrites_with_current_host_creds(self, monkeypatch, tmp_path):
        home = _home(monkeypatch, tmp_path)
        _fake_host_omp_db(home)
        m1 = launcher._omp_auth_seed_mount("omp", "inst-y")
        # Host rotates the credential; re-seed must pick it up.
        hdb = sqlite3.connect(str(home / ".omp" / "agent" / "agent.db"))
        hdb.execute("UPDATE auth_credentials SET data='rotated' WHERE provider='anthropic'")
        hdb.commit(); hdb.close()
        launcher._omp_auth_seed_mount("omp", "inst-y")
        db = sqlite3.connect(str(_seeded_db(m1)))
        assert db.execute("SELECT data FROM auth_credentials WHERE provider='anthropic'").fetchone()[0] == "rotated"
        db.close()
