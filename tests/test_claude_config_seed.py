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
        _host(
            monkeypatch,
            tmp_path,
            {
                "oauthAccount": {"emailAddress": "x@example.com", "accountUuid": "abc"},
                "userID": "user-123",
                "projects": {"/secret/host/path": {}},  # host config that must NOT leak
                "mcpServers": {"leak": {}},
            },
        )
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
        assert launcher._claude_config_seed_mount("antigravity", "inst-z") == []

    def test_omp_gets_no_stub(self, monkeypatch, tmp_path):
        """omp reads ~/.claude.json only to discover MCP servers, which harnessed supplies through
        `_omp_mcp_seed_mount`. Seeding an onboarding stub there mounts a file omp never uses and
        shadows nothing it wants (#314)."""
        _host(monkeypatch, tmp_path, {"oauthAccount": {"x": 1}, "userID": "u"})
        assert launcher._claude_config_seed_mount("omp", "inst-omp") == []


class TestStubMergesOverTheLiveFile:
    """GH-594 S2. The stub path is per instance (stack, harness, project), but it was rewritten on
    every launch, so every answer given inside the stack was lost on the next one."""

    P = "/work/proj"
    TRUST = (
        "hasTrustDialogAccepted",
        "hasClaudeMdExternalIncludesApproved",
        "hasClaudeMdExternalIncludesWarningShown",
    )

    def _stub_path(self, tmp_path, inst):
        return tmp_path / "state" / "harnessed" / inst / "claude.json"

    def test_s2_1_first_launch_seeds_trust_for_the_project(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, None)
        mount = launcher._claude_config_seed_mount("claude", "inst-a", project_path=self.P)
        stub = _stub_from_mount(mount)
        assert stub["projects"] == {self.P: dict.fromkeys(self.TRUST, True)}
        assert stub["hasCompletedOnboarding"] is True
        assert mount[1].endswith(f":{CONTAINER_HOME}/.claude.json:rw")

    def test_s2_2_answers_in_the_stub_survive_a_relaunch(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, None)
        stub_path = self._stub_path(tmp_path, "inst-b")
        stub_path.parent.mkdir(parents=True)
        stub_path.write_text(json.dumps({
            "customApiKeyResponses": {"approved": [], "rejected": ["def"]},
            "projects": {self.P: {"enabledMcpjsonServers": ["srv"]}},
        }))
        stub = _stub_from_mount(
            launcher._claude_config_seed_mount("claude", "inst-b", project_path=self.P)
        )
        assert stub["customApiKeyResponses"] == {"approved": [], "rejected": ["def"]}
        assert stub["projects"][self.P]["enabledMcpjsonServers"] == ["srv"]
        assert stub["projects"][self.P]["hasTrustDialogAccepted"] is True

    def test_s2_3_an_unreadable_stub_is_rebuilt(self, monkeypatch, tmp_path):
        _host(monkeypatch, tmp_path, None)
        stub_path = self._stub_path(tmp_path, "inst-c")
        stub_path.parent.mkdir(parents=True)
        stub_path.write_text("{not json")
        stub = _stub_from_mount(
            launcher._claude_config_seed_mount("claude", "inst-c", project_path=self.P)
        )
        assert stub["hasCompletedOnboarding"] is True
        assert stub["projects"][self.P]["hasTrustDialogAccepted"] is True

    def test_s2_4_the_container_backend_passes_the_project(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from harnessed.backend import LaunchSpec

        seen = {}

        class _Stop(Exception):
            pass

        def _capture(harness, inst, *, isolated_auth=False, project_path=None):
            seen.update(harness=harness, inst=inst, isolated_auth=isolated_auth, project=project_path)
            raise _Stop

        monkeypatch.setattr(launcher, "_build_mount_args", lambda *a, **k: [])
        monkeypatch.setattr(launcher, "_claude_config_seed_mount", _capture)
        b = launcher.ContainerBackend(
            "podman", "inst-d", "pod-d", tmp_path, "img", tmp_path, [], [],
            SimpleNamespace(isolated_auth=True), stack_from_overlay=False, headless=True,
        )
        b.config_volume, b.tools_volume = "cfg", "tools"
        project = tmp_path / "proj"
        try:
            b.materialize_config(LaunchSpec(stack="s", harness="claude", project_path=project))
        except _Stop:
            pass
        assert seen == {"harness": "claude", "inst": "inst-d", "isolated_auth": True, "project": str(project)}
