"""Tests for the content-only host-native launch backend (`launch --host`).

Covers the materialize + seed + plan seam WITHOUT the interactive exec: the launcher copies the
assembled profile's `.claude/*` content layer + settings floor into a host CLAUDE_CONFIG_DIR,
seeds claude's own auth from the host, and deliberately drops the container-only MCP artifacts.
"""

from pathlib import Path

from typer.testing import CliRunner

from harnessed import launcher, paths
from harnessed.assemble import assemble

runner = CliRunner()


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
    def test_host_home_uses_xdg_data_home_and_is_project_keyed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        proj = tmp_path / "proj"
        assert paths.host_home("s", "claude", proj) == (
            tmp_path / "harnessed" / "home" / "s" / "claude" / paths.project_hash(proj)
        )

    def test_host_home_differs_per_project(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # Same stack, different projects → different config dirs (no cross-project clobber).
        assert paths.host_home("s", "claude", tmp_path / "a") != paths.host_home("s", "claude", tmp_path / "b")

    def test_host_home_distinct_from_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude", tmp_path) != paths.profile_dir("s", "claude")


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


class TestShareClaudeState:
    def test_symlinks_session_state_and_live_auth(self, monkeypatch, tmp_path):
        real = tmp_path / "host-claude"
        real.mkdir()
        (real / ".credentials.json").write_text('{"token":"x"}')
        (real / ".claude.json").write_text('{"account":"a"}')
        (real / "projects").mkdir()
        (real / "projects" / "p.jsonl").write_text("transcript")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real))
        home = tmp_path / "home"
        home.mkdir()

        launcher._share_host_claude_state(home)

        # session state: symlinked to the real ~/.claude (shared, resumable)
        assert (home / "projects").is_symlink()
        assert (home / "projects" / "p.jsonl").read_text() == "transcript"
        for name in ("file-history", "todos", "tasks", "session-env", "shell-snapshots"):
            assert (home / name).is_symlink()
        # auth token: symlinked (live refresh propagates)
        assert (home / ".credentials.json").is_symlink()
        assert (home / ".credentials.json").read_text() == '{"token":"x"}'
        # account: COPIED (isolated writes), not a symlink
        assert (home / ".claude.json").is_file()
        assert not (home / ".claude.json").is_symlink()

    def test_claude_json_seeded_from_home_level_not_config_dir(self, monkeypatch, tmp_path):
        # The account file is $HOME/.claude.json — NOT ~/.claude/.claude.json. Seed from the right one.
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude.json").write_text('{"account":"real"}')            # HOME-level (correct)
        (fake_home / ".claude" / ".claude.json").write_text('{"account":"WRONG"}')  # decoy inside dir
        (fake_home / ".claude" / ".credentials.json").write_text('{"t":"x"}')
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(fake_home))
        home = tmp_path / "stackhome"
        home.mkdir()
        launcher._share_host_claude_state(home)
        assert (home / ".claude.json").read_text() == '{"account":"real"}'

    def test_missing_source_creates_dirs_no_crash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fresh"))
        home = tmp_path / "home"
        home.mkdir()
        launcher._share_host_claude_state(home)  # must not raise
        assert (home / "projects").is_symlink()          # created + linked
        assert not (home / ".credentials.json").exists()  # no token to share


class TestLaunchPlan:
    def test_plan_materializes_and_returns_argv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)

        home, argv, cwd = launcher._host_launch_plan("s", "claude", tmp_path)

        assert home == paths.host_home("s", "claude", tmp_path)
        assert argv == ["claude"]  # content-only: no --mcp-config
        assert cwd == tmp_path
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()


class TestHostAssembleIntegration:
    """The bug that shipped in the first spike: `--host` required `harnessed build` (a full container
    image build). Host mode must assemble the real catalog stack IN-PROCESS with no pre-build and no
    podman — this guards that the greet skill lands from a cold start."""

    def test_hostspike_assembles_and_plans_without_prebuild(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        assert not paths.is_built("hostspike", "claude")  # cold: nothing pre-built

        assemble(None, "hostspike", paths.profiles_root().parent, "claude", strict=True)
        home, argv, cwd = launcher._host_launch_plan("hostspike", "claude", tmp_path)

        assert cwd == tmp_path
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()
        assert (home / "CLAUDE.md").is_file()
        assert argv == ["claude"]
        # No container/MCP artifacts leak from a real assemble either.
        assert not (home / ".mcp.json").exists()


class TestHostCliRouting:
    def test_launch_host_flag_assembles_and_execs_claude(self, monkeypatch, tmp_path):
        """End-to-end CLI path: `launch <stack> claude --host` must assemble in-process (no
        pre-build, no podman) and hand off to claude with CLAUDE_CONFIG_DIR — captured here instead
        of actually exec'ing."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(file=file, argv=argv, ccd=env.get("CLAUDE_CONFIG_DIR"))
            raise SystemExit(0)  # execvpe would replace the process; halt cleanly instead

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"]
        )

        assert result.exit_code == 0, result.output
        assert captured["file"] == "claude"
        # Always --strict-mcp-config (even content-only) so global .claude.json servers never leak.
        assert captured["argv"][0] == "claude"
        assert "--strict-mcp-config" in captured["argv"]
        assert captured["ccd"] == str(paths.host_home("hostspike", "claude", tmp_path.resolve()))
        assert paths.is_built("hostspike", "claude")  # profile assembled during the launch itself

    def test_agent_process_inherits_the_folder_env_contract(self, monkeypatch, tmp_path):
        """bd harnessed-0tk.7: a container launch sets the contract box-wide (`podman run -e`), so
        every process in it agrees. The host has no box — os.environ IS the box. Before the fix
        _host_run_setups built a private env copy and the exec'd agent saw none of it."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        captured: dict = {}

        def fake_execvpe(file, argv, env):
            captured.update(env=env)
            raise SystemExit(0)

        monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"]
        )

        assert result.exit_code == 0, result.output
        env = captured["env"]
        assert env["HARNESS"] == "claude"
        assert env["PROJECT_DIR"] == str(tmp_path.resolve())
        for var in ("MAIN_REPO_DIR", "HARNESSED_GIT_COMMON_DIR", "HOST_WORKSPACE_DIR",
                    "CONTAINER_WORKSPACE_DIR", "HOST_HOME"):
            assert env[var]
        # git consumes GIT_COMMON_DIR itself — exporting it would hijack common-dir resolution.
        assert "GIT_COMMON_DIR" not in env
