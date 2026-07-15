"""Tests for the content-only host-native launch backend (`launch --host`).

Covers the materialize + seed + plan seam WITHOUT the interactive exec: the launcher copies the
assembled profile's `.claude/*` content layer + settings floor into a host CLAUDE_CONFIG_DIR,
seeds claude's own auth from the host, and deliberately drops the container-only MCP artifacts.
"""

from pathlib import Path

from harnessed import launcher, paths


def _fake_profile(prof: Path) -> None:
    """A minimal assembled profile: content layer + container-only artifacts that must NOT leak."""
    claude = prof / ".claude"
    (claude / "skills" / "greet-helper").mkdir(parents=True)
    (claude / "skills" / "greet-helper" / "SKILL.md").write_text("# greet\n")
    (claude / "CLAUDE.md").write_text("stack identity\n")
    (prof / "settings.json").write_text('{"permissions":{"defaultMode":"acceptEdits"}}')
    # Container-only — the host backend must skip these (no hub host-side).
    (prof / ".mcp.json").write_text('{"mcpServers":{"hatago":{}}}')
    (prof / "hatago.config.json").write_text("{}")
    (prof / "Dockerfile.harnessed-x").write_text("FROM scratch\n")


class TestHostHomePaths:
    def test_host_home_uses_xdg_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") == tmp_path / "harnessed" / "home" / "s" / "claude"

    def test_host_home_distinct_from_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") != paths.profile_dir("s", "claude")


class TestMaterialize:
    def test_copies_content_and_drops_container_artifacts(self, tmp_path):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        launcher._materialize_host_home(prof, home)

        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()
        assert (home / "CLAUDE.md").is_file()
        assert (home / "settings.json").is_file()
        # Container-only artifacts must never reach the host config dir.
        assert not (home / ".mcp.json").exists()
        assert not (home / "hatago.config.json").exists()
        assert not (home / "Dockerfile.harnessed-x").exists()

    def test_rebuilds_home_from_scratch(self, tmp_path):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        home.mkdir()
        (home / "stale-skill.md").write_text("removed recipe residue")
        launcher._materialize_host_home(prof, home)
        assert not (home / "stale-skill.md").exists()


class TestSeedCredentials:
    def test_seeds_claude_auth_from_host(self, monkeypatch, tmp_path):
        host_src = tmp_path / "host-claude"
        host_src.mkdir()
        (host_src / ".credentials.json").write_text('{"token":"x"}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(host_src))
        home = tmp_path / "home"
        home.mkdir()
        launcher._seed_host_credentials(home)
        assert (home / ".credentials.json").read_text() == '{"token":"x"}'

    def test_missing_source_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "does-not-exist"))
        home = tmp_path / "home"
        home.mkdir()
        launcher._seed_host_credentials(home)  # must not raise
        assert not (home / ".credentials.json").exists()


class TestLaunchPlan:
    def test_plan_materializes_and_returns_argv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)

        home, argv, cwd = launcher._host_launch_plan("s", "claude", tmp_path)

        assert home == paths.host_home("s", "claude")
        assert argv == ["claude"]  # content-only: no --mcp-config
        assert cwd == tmp_path
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()
