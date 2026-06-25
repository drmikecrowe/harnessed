"""Tests for the token-free ~/.claude.json onboarding stub (design §4b auth seeding).

The real OAuth token is mounted separately (ro .credentials.json); this stub only carries
onboarding/identity fields so Claude Code skips its first-run login screen. It must NEVER contain
a token, and must be written per-instance (not into the host ~/.claude.json).
"""

import json
from pathlib import Path

from harnessed import launcher

CONTAINER_HOME = launcher._CONTAINER_HOME_STR


def _host(monkeypatch, tmp_path, claude_json: dict | None):
    home = tmp_path / "home"
    home.mkdir()
    if claude_json is not None:
        (home / ".claude.json").write_text(json.dumps(claude_json))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return home


def _stub_from_mount(mount: list[str]) -> dict:
    assert mount[0] == "-v"
    host_path = mount[1].split(":")[0]
    return json.loads(Path(host_path).read_text())


class TestSeedStub:
    def test_copies_identity_fields_sets_onboarding_no_token(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, {
            "oauthAccount": {"emailAddress": "x@example.com", "accountUuid": "abc"},
            "userID": "user-123",
            "projects": {"/secret/host/path": {}},   # host config that must NOT leak
            "mcpServers": {"leak": {}},
        })
        mount = launcher._claude_config_seed_mount("claude", "harnessed-claude_time-deadbeef")

        stub = _stub_from_mount(mount)
        assert stub["hasCompletedOnboarding"] is True
        assert stub["oauthAccount"] == {"emailAddress": "x@example.com", "accountUuid": "abc"}
        assert stub["userID"] == "user-123"
        # No host config bleed, no token.
        assert "projects" not in stub
        assert "mcpServers" not in stub
        assert not any("token" in k.lower() or "credential" in k.lower() for k in stub)
        # Mounted rw at the container home (so Claude can update it without touching the host).
        assert mount[1].endswith(f":{CONTAINER_HOME}/.claude.json:rw")

    def test_missing_host_config_still_seeds_onboarding(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, None)
        mount = launcher._claude_config_seed_mount("claude", "inst-x")
        stub = _stub_from_mount(mount)
        assert stub["hasCompletedOnboarding"] is True
        assert stub["oauthAccount"] == {}
        assert stub["userID"] == ""

    def test_per_instance_path_does_not_touch_host_claude_json(self, monkeypatch, tmp_path):
        home = _host(monkeypatch, tmp_path, {"oauthAccount": {}, "userID": "u", "numStartups": 99})
        before = (home / ".claude.json").read_text()
        launcher._claude_config_seed_mount("claude", "inst-y")
        # Host file untouched; stub lives under XDG_STATE_HOME/harnessed/<inst>/.
        assert (home / ".claude.json").read_text() == before
        assert (tmp_path / "state" / "harnessed" / "inst-y" / "claude.json").is_file()

    def test_non_claude_harness_gets_no_stub(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, {"oauthAccount": {}, "userID": "u"})
        assert launcher._claude_config_seed_mount("gemini", "inst-z") == []

    def test_omp_also_seeded(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, {"oauthAccount": {"x": 1}, "userID": "u"})
        assert launcher._claude_config_seed_mount("omp", "inst-omp") != []
