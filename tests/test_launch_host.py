"""Tests for the content-only host-native launch backend (`launch --host`).

Covers the materialize + seed + plan seam WITHOUT the interactive exec: the launcher copies the
assembled profile's `.claude/*` content layer + settings floor into a host CLAUDE_CONFIG_DIR,
seeds claude's own auth from the host, and deliberately drops the container-only MCP artifacts.
"""

import inspect
import json
import os
from pathlib import Path

import pytest
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
    def test_host_home_is_keyed_by_stack_and_harness_only(self, monkeypatch, tmp_path):
        """bd harnessed-8px.12: --host isolates CONFIGURATION and the STACK defines it, so the
        config dir is the stack identity. Nothing project-specific lives in there."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") == tmp_path / "harnessed" / "home" / "s" / "claude"

    def test_host_home_differs_per_harness(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") != paths.host_home("s", "omp")

    def test_host_home_distinct_from_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.host_home("s", "claude") != paths.profile_dir("s", "claude")

    def test_shim_is_a_sibling_not_a_child(self, monkeypatch, tmp_path):
        """The shim must survive the rebuild that rmtree's the config dir, so it cannot live inside
        it — and host-gc must not mistake it for a config dir."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        home = paths.host_home("s", "claude")
        assert paths.host_home_shim(home).parent == home.parent


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

    def _shared(self, monkeypatch, tmp_path, body=None, mtime=None):
        """Point HOME at a fake home and optionally seed the SHARED ~/.claude credential."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        real = fake_home / ".claude" / ".credentials.json"
        if body is not None:
            real.write_text(body)
            os.utime(real, (mtime, mtime))
        return real

    def _stack_cred(self, stack, project, body, mtime, *, symlink_to=None):
        """A per-(stack, harness, project) config dir holding a credential file. A REGULAR file is
        what a token refresh leaves behind, having replaced the symlink we created."""
        home = paths.host_homes_root() / stack / "claude" / project
        home.mkdir(parents=True, exist_ok=True)
        cred = home / ".credentials.json"
        if symlink_to is not None:
            cred.symlink_to(symlink_to)
            return home
        cred.write_text(body)
        os.utime(cred, (mtime, mtime))
        return home

    def test_refreshed_token_is_promoted_before_the_wipe(self, monkeypatch, tmp_path):
        """bd harnessed-8px.10: Claude rewrites .credentials.json on refresh, and the rewrite
        REPLACES our symlink with a regular file — so the fresh token sits in the stack config dir
        while the shared ~/.claude copy goes stale. _materialize_host_home then rmtree's the config
        dir and we re-link to the stale copy, logging the user out every token lifetime."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"stale"}', 100_000)
        self._stack_cred("s", "proj1", '{"token":"fresh"}', 200_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == '{"token":"fresh"}'
        assert oct(real.stat().st_mode)[-3:] == "600"  # never widen a credential file

    def test_rescues_across_stacks_and_projects_not_just_the_launching_one(
        self, monkeypatch, tmp_path
    ):
        """A config dir is keyed <stack>/<harness>/<project>, so one stack open in three projects has
        three. Rescuing only the launching home would converge lazily: a token refreshed in project A
        would not reach the shared copy until project A relaunched, so launching project B first
        would still restore a stale token and force a login."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"stale"}', 100_000)
        self._stack_cred("stack-a", "proj1", '{"token":"older"}', 150_000)
        self._stack_cred("stack-b", "proj2", '{"token":"newest"}', 300_000)
        self._stack_cred("stack-b", "proj3", '{"token":"middle"}', 200_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == '{"token":"newest"}'

    def test_older_stack_token_never_overwrites_a_newer_shared_one(self, monkeypatch, tmp_path):
        """A stack home left over from days ago must not drag the shared token backwards."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"current"}', 200_000)
        self._stack_cred("s", "proj1", '{"token":"ancient"}', 100_000)
        launcher._rescue_host_credentials()
        assert real.read_text() == '{"token":"current"}'

    def test_intact_symlink_is_not_a_rescue_candidate(self, monkeypatch, tmp_path):
        """A surviving symlink means that home's refresh propagated live — it already IS the shared
        copy, so treating it as a candidate would be a self-copy."""
        real = self._shared(monkeypatch, tmp_path, '{"token":"shared"}', 100_000)
        self._stack_cred("s", "proj1", None, None, symlink_to=real)
        launcher._rescue_host_credentials()  # must not raise
        assert real.read_text() == '{"token":"shared"}'

    def test_first_ever_launch_has_nothing_to_rescue(self, monkeypatch, tmp_path):
        real = self._shared(monkeypatch, tmp_path)
        launcher._rescue_host_credentials()  # no homes on disk at all — must not raise
        assert not real.exists()

    def test_plan_rescues_before_materialize_wipes_the_home(self, monkeypatch, tmp_path):
        """The ordering IS the fix: run the rescue after the rmtree and the fresh token is gone."""
        src = inspect.getsource(launcher._host_launch_plan)
        assert src.index("_rescue_host_credentials") < src.index("_materialize_host_home")

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

        home, argv, cwd, _rebuilt = launcher._host_launch_plan("s", "claude", tmp_path)

        assert home == paths.host_home("s", "claude")
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
        home, argv, cwd, _rebuilt = launcher._host_launch_plan("hostspike", "claude", tmp_path)

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
        assert captured["ccd"] == str(paths.host_home("hostspike", "claude"))
        assert paths.is_built("hostspike", "claude")  # profile assembled during the launch itself

    def test_host_settings_inherit_the_host_claude_default_mode(self, monkeypatch, tmp_path):
        """bd harnessed-8px.8, found by a REAL --host launch: the session came up in acceptEdits
        even though the host ~/.claude declared `auto`.

        `launch` diverted to _launch_host and returned BEFORE the container path's
        _merge_host_claude_settings call, so _materialize_host_home copied the bare assemble-time
        FLOOR into the config dir and the host's own mode never crossed over. Container mode was
        unaffected, which is why unit tests on the container path stayed green.
        """
        fake_home = tmp_path / "fakehome"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "settings.json").write_text(
            json.dumps({"permissions": {"defaultMode": "auto", "mode": "auto"}})
        )
        monkeypatch.setenv("HOME", str(fake_home))  # _merge_host_claude_settings reads Path.home()
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)

        result = runner.invoke(
            launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"]
        )

        assert result.exit_code == 0, result.output
        home = paths.host_home("hostspike", "claude")
        settings = json.loads((home / "settings.json").read_text())
        # The host's mode wins: merge_settings applies required.defaultMode with setdefault, so the
        # harnessed floor is a floor, not an override.
        assert settings["permissions"]["defaultMode"] == "auto"

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




class TestStackFingerprintGate:
    """bd harnessed-8px.12. The materialize used to rmtree the config dir on EVERY launch. That one
    behaviour caused three separate problems: it forced the project into the config-dir key (so a
    second launch could not wipe a live one), it made every install script re-run per project per
    launch, and it reset `.claude.json` so approvals never persisted.

    The rebuild is still WHOLESALE — the dir stays a pure function of (profile + installs), so a
    recipe dropped from the stack still cannot leave files behind — it just happens only when the
    stack actually changed.
    """

    def _prof(self, tmp_path):
        prof = tmp_path / "prof"
        prof.mkdir()
        _fake_profile(prof)
        return prof

    def test_unchanged_fingerprint_leaves_the_home_untouched(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is True
        launcher._stamp_host_home(home, "fp-1")  # the caller stamps, AFTER installs succeed
        # Something the AGENT wrote after the build — it must survive an unchanged relaunch.
        (home / "runtime-state.json").write_text("session data")
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is False
        assert (home / "runtime-state.json").is_file()

    def test_changed_fingerprint_rebuilds_wholesale(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        launcher._stamp_host_home(home, "fp-1")
        (home / "stale-recipe-leftover.md").write_text("from a recipe no longer in the stack")
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-2") is True
        # The whole point of keeping a wholesale wipe: a departed recipe leaves nothing behind.
        assert not (home / "stale-recipe-leftover.md").exists()
        assert (home / "skills" / "greet-helper" / "SKILL.md").is_file()

    def test_missing_stamp_rebuilds(self, tmp_path):
        """A hand-deleted or half-written dir must not be trusted."""
        prof, home = self._prof(tmp_path), tmp_path / "home"
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        launcher._stamp_host_home(home, "fp-1")
        (home / launcher._HOST_STACK_FINGERPRINT).unlink()
        assert launcher._materialize_host_home(prof, home, fingerprint="fp-1") is True

    def test_stamp_is_written_after_the_installs(self, tmp_path):
        """The stamp certifies content that is not complete until every install.script has run."""
        src = inspect.getsource(launcher._launch_host)
        assert src.index("_host_run_installs(") < src.index("_stamp_host_home(")

    def test_no_fingerprint_keeps_unconditional_rebuild(self, tmp_path):
        prof, home = self._prof(tmp_path), tmp_path / "home"
        assert launcher._materialize_host_home(prof, home) is True
        assert launcher._materialize_host_home(prof, home) is True

    def test_fingerprint_includes_the_harnessed_version(self):
        """A host launch has no image build to force a refresh, so a change to what emit writes —
        with a byte-identical recipe closure — would otherwise serve stale content forever."""
        from harnessed import __version__
        src = inspect.getsource(launcher._host_stack_fingerprint)
        assert "__version__" in src and __version__


class TestLegacyPerProjectMigration:
    """The old key was <stack>/<harness>/<project_hash>; the new config dir IS <stack>/<harness>, so
    every old per-project dir is now a child of it. They hold real tokens (bd harnessed-8px.10), so
    the rmtree must not be what removes them."""

    def _legacy(self, home, name, cred_body="tok"):
        d = home / name
        d.mkdir(parents=True)
        (d / "settings.json").write_text("{}")
        (d / ".credentials.json").write_text(cred_body)
        return d

    def test_legacy_dir_is_scrubbed_not_just_wiped(self, tmp_path, monkeypatch):
        prof, home = tmp_path / "prof", tmp_path / "home"
        prof.mkdir()
        _fake_profile(prof)
        legacy = self._legacy(home, "a1b2c3d4")
        scrubbed = []
        real_scrub = launcher._scrub_host_home
        monkeypatch.setattr(
            launcher, "_scrub_host_home",
            lambda p: (scrubbed.append(p.name), real_scrub(p))[1],
        )
        launcher._materialize_host_home(prof, home, fingerprint="fp-1")
        assert scrubbed == ["a1b2c3d4"], "legacy dir must go through the scrub path, not the rmtree"
        assert not legacy.exists()

    def test_non_config_eight_hex_dir_is_left_alone(self, tmp_path):
        """Matched narrowly: an 8-hex name alone is not enough to delete something."""
        home = tmp_path / "home"
        d = home / "deadbeef"
        d.mkdir(parents=True)
        (d / "notes.md").write_text("a recipe's own data")
        launcher._migrate_legacy_host_homes(home)
        assert d.exists()


class TestHostGC:
    """host-gc under the per-stack layout: an orphan is a config dir whose STACK is gone from the
    catalog — a far better signal than the old one-way project_hash, which could not be resolved
    back to anything."""

    def _home(self, stack, harness="claude", *, cred=None, legacy=None):
        home = paths.host_homes_root() / stack / harness
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text("{}")
        if cred is not None:
            (home / ".credentials.json").write_text(cred)
        if legacy:
            d = home / legacy
            d.mkdir(exist_ok=True)
            (d / "settings.json").write_text("{}")
        return home

    def _run(self, monkeypatch, tmp_path, *args):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        return runner.invoke(launcher.app, ["host-gc", *args])

    def test_lists_real_stack_as_ok_and_unknown_stack_as_orphan(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike")          # a real catalog stack
        self._home("deleted-stack-xyz")  # not in any catalog root
        r = self._run(monkeypatch, tmp_path)
        assert r.exit_code == 0, r.output
        assert "hostspike/claude" in r.output and "deleted-stack-xyz/claude" in r.output
        assert "ORPHAN" in r.output

    def test_shim_sibling_is_not_listed_as_a_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        home = self._home("hostspike")
        paths.host_home_shim(home).mkdir(parents=True, exist_ok=True)
        r = self._run(monkeypatch, tmp_path)
        assert "claude.home" not in r.output

    def test_flags_a_real_credential_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike", cred="tok")
        assert "REAL-FILE" in self._run(monkeypatch, tmp_path).output

    def test_surfaces_legacy_per_project_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("hostspike", legacy="a1b2c3d4")
        assert "legacy" in self._run(monkeypatch, tmp_path).output

    def test_prune_removes_only_the_orphan(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        live = self._home("hostspike")
        gone = self._home("deleted-stack-xyz")
        r = self._run(monkeypatch, tmp_path, "--prune")
        assert r.exit_code == 0, r.output
        assert live.exists(), "a stack still in the catalog must never be removed"
        assert not gone.exists()

    def test_dry_run_deletes_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        gone = self._home("deleted-stack-xyz")
        r = self._run(monkeypatch, tmp_path, "--prune", "--dry-run")
        assert "would remove" in r.output
        assert gone.exists()

    def test_prune_scrubs_the_credential_before_deleting(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        self._home("deleted-stack-xyz", cred="a-real-token")
        scrubbed = []
        monkeypatch.setattr(launcher, "_scrub_host_home", lambda p: scrubbed.append(p))
        self._run(monkeypatch, tmp_path, "--prune")
        assert len(scrubbed) == 1, "removal must go through the scrub path, never a bare rmtree"


class TestSecondLaunchSkipsInstalls:
    """bd harnessed-8px.12 acceptance: an install is logically once per STACK. It only ever ran on
    every launch because the materialize wiped its output on every launch."""

    def _launch(self, tmp_path, monkeypatch, calls):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        monkeypatch.setattr(
            launcher, "_host_run_installs",
            lambda stack, project_path, *, harness, home: calls.append(stack),
        )
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        return runner.invoke(
            launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"]
        )

    def test_installs_run_on_first_launch_and_are_skipped_on_the_second(
        self, monkeypatch, tmp_path
    ):
        calls: list[str] = []
        first = self._launch(tmp_path, monkeypatch, calls)
        assert first.exit_code == 0, first.output
        assert calls == ["hostspike"], "first launch must build the home and run installs"

        second = self._launch(tmp_path, monkeypatch, calls)
        assert second.exit_code == 0, second.output
        assert calls == ["hostspike"], "unchanged stack must not re-run installs"
        assert "installs skipped" in second.output

    def test_a_changed_stack_fingerprint_reruns_installs(self, monkeypatch, tmp_path):
        calls: list[str] = []
        self._launch(tmp_path, monkeypatch, calls)
        assert calls == ["hostspike"]
        # Simulate a recipe edit: the stamp no longer matches the stack's recipe closure.
        home = paths.host_home("hostspike", "claude")
        (home / launcher._HOST_STACK_FINGERPRINT).write_text("something-else\n")
        self._launch(tmp_path, monkeypatch, calls)
        assert calls == ["hostspike", "hostspike"], "a changed stack must rebuild and re-install"


class TestHostHomeLock:
    """bd harnessed-8px.12 criterion 4. The gate makes contention rare — an unchanged stack never
    rebuilds — but two launches that both see a CHANGED fingerprint must not rebuild concurrently."""

    def test_lock_actually_excludes_a_second_holder(self, tmp_path):
        import fcntl as _f
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            other = open(home.parent / f"{home.name}.lock", "w")
            try:
                with pytest.raises(BlockingIOError):
                    _f.flock(other.fileno(), _f.LOCK_EX | _f.LOCK_NB)
            finally:
                other.close()

    def test_lock_is_released_on_exit(self, tmp_path):
        import fcntl as _f
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            pass
        other = open(home.parent / f"{home.name}.lock", "w")
        try:
            _f.flock(other.fileno(), _f.LOCK_EX | _f.LOCK_NB)  # must not raise
        finally:
            other.close()

    def test_lock_file_is_a_sibling_so_the_rebuild_cannot_delete_it(self, tmp_path):
        home = tmp_path / "data" / "harnessed" / "home" / "s" / "claude"
        with launcher._host_home_lock(home):
            pass
        assert (home.parent / "claude.lock").is_file()
        assert not home.exists(), "the lock must not create the config dir it guards"

    def test_lock_spans_the_installs_not_just_the_rebuild(self):
        """Releasing after the rebuild would let a second launch see a matching stamp, skip
        installs, and exec the agent while the first launch's scripts were still writing."""
        src = inspect.getsource(launcher._launch_host)
        # Match the CALL sites, not the prose — an earlier comment names _host_launch_plan too.
        lock_at = src.index("with _host_home_lock(")
        assert lock_at < src.index("_host_launch_plan(")
        assert lock_at < src.index("_host_run_installs(")


class TestFailedInstallDoesNotStamp:
    """bd harnessed-8px.15, found by a REAL host launch. The stamp was written at the end of the
    content copy, but installs run AFTER that — so an install that failed left a matching stamp on
    disk. The next launch then saw "unchanged", skipped the rebuild AND the installs, and started
    the agent against a permanently half-installed stack. Silently: the exact failure mode this
    whole epic exists to remove, reintroduced by its own optimisation."""

    def _launch(self, tmp_path, monkeypatch, *, install_fails):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))

        def _installs(stack, project_path, *, harness, home):
            if install_fails:
                raise SystemExit(1)  # what _host_run_installs does on a failed script

        monkeypatch.setattr(launcher, "_host_run_installs", _installs)
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        return runner.invoke(launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"])

    def test_a_failed_install_leaves_no_stamp(self, monkeypatch, tmp_path):
        self._launch(tmp_path, monkeypatch, install_fails=True)
        home = paths.host_home("hostspike", "claude")
        assert not (home / launcher._HOST_STACK_FINGERPRINT).exists(), (
            "a stamp after a failed install makes the next launch skip the retry"
        )

    def test_the_next_launch_retries_after_a_failure(self, monkeypatch, tmp_path):
        self._launch(tmp_path, monkeypatch, install_fails=True)
        calls: list[str] = []
        monkeypatch.setattr(
            launcher, "_host_run_installs",
            lambda stack, project_path, *, harness, home: calls.append(stack),
        )
        monkeypatch.setattr(launcher.os, "execvpe", lambda *_a: (_ for _ in ()).throw(SystemExit(0)))
        monkeypatch.setattr(launcher.os, "chdir", lambda *_a: None)
        r = runner.invoke(launcher.app, ["launch", "hostspike", "claude", str(tmp_path), "--host"])
        assert r.exit_code == 0, r.output
        assert calls == ["hostspike"], "the retry must actually re-run the installs"


class TestSettingsPropagateWithoutARebuild:
    """bd harnessed-8px.18. The 8px.12 fingerprint gate skips _materialize_host_home when the stack
    is unchanged — but that is what copies settings.json into the config dir. settings.json is NOT a
    pure function of the recipe closure the fingerprint covers: _merge_host_claude_settings folds in
    the host's live ~/.claude preferences and re-applies harnessed's required grants every launch.

    Caught on a real third launch: the 8px.17 duplicate-hook fix reached the profile and the live
    config dir kept running the doubled hooks, because nothing had changed the stack.
    """

    def test_settings_reach_the_home_even_when_the_stack_is_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        monkeypatch.setattr(launcher, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")

        home, _a, _c, rebuilt = launcher._host_launch_plan("s", "claude", tmp_path, recipes=[])
        assert rebuilt is True
        # _host_launch_plan deliberately does NOT stamp — _launch_host does, only after the installs
        # succeed, so a failed install can never leave a matching stamp behind (70fb163).
        launcher._stamp_host_home(home, "fp-1")

        # A launch-time settings change: host prefs merged, or harnessed fixing what it emits.
        (prof / "settings.json").write_text('{"permissions":{"defaultMode":"auto"}}')

        home, _a, _c, rebuilt = launcher._host_launch_plan("s", "claude", tmp_path, recipes=[])
        assert rebuilt is False, "unchanged stack must not rebuild"
        assert json.loads((home / "settings.json").read_text())["permissions"]["defaultMode"] == "auto"

    def test_content_is_still_gated(self, tmp_path, monkeypatch):
        """Only settings.json is exempt — skills/rules ARE a function of the recipe closure, so a
        skipped rebuild must not resurrect them (that would defeat the gate entirely)."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-host-src"))
        prof = paths.profile_dir("s2", "claude")
        prof.mkdir(parents=True)
        _fake_profile(prof)
        monkeypatch.setattr(launcher, "_host_stack_fingerprint", lambda stack, recipes: "fp-1")
        home, *_ = launcher._host_launch_plan("s2", "claude", tmp_path, recipes=[])
        launcher._stamp_host_home(home, "fp-1")
        (prof / ".claude" / "skills" / "late-skill").mkdir(parents=True)
        (prof / ".claude" / "skills" / "late-skill" / "SKILL.md").write_text("# late\n")
        launcher._host_launch_plan("s2", "claude", tmp_path, recipes=[])
        assert not (home / "skills" / "late-skill").exists()
