"""Tests for `harnessed install` shim generation.

The shim must bake in an ABSOLUTE path to the `harnessed` binary so it works even when
`harnessed` itself is not on PATH (e.g. a dev .venv) — the item-3 PATH-shim fix.
"""

import subprocess
import json
from pathlib import Path

import pytest
import typer

from harnessed import launcher, paths


def _stub_catalog(monkeypatch, tmp_path, *, exists: bool):
    """Point find_in_catalog at a tmp stacks dir; create stack.yaml iff exists."""
    stack_dir = tmp_path / "catalog" / "stacks" / "claude_time"
    if exists:
        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text(
            "name: claude_time\nrecipes: [time]\nservices: []\n"
        )
    monkeypatch.setattr(paths, "find_in_catalog", lambda kind, name: stack_dir)


def _home_in(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


class TestInstallShim:
    def test_bakes_absolute_harnessed_path_from_which(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=True)
        home = _home_in(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: "/opt/bin/harnessed")

        launcher.install_stack("claude_time")

        shim = home / ".local" / "bin" / "claude_time"
        content = shim.read_text()
        assert shim.exists()
        assert shim.stat().st_mode & 0o111  # executable
        # Absolute path baked in — NOT a bare `harnessed`.
        assert "exec /opt/bin/harnessed claude_time \"$@\"" in content
        assert "exec harnessed " not in content

    def test_falls_back_to_running_binary_when_not_on_path(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=True)
        home = _home_in(monkeypatch, tmp_path)
        monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
        monkeypatch.setattr(launcher.sys, "argv", ["/dev/venv/bin/harnessed", "install", "claude_time"])

        launcher.install_stack("claude_time")

        content = (home / ".local" / "bin" / "claude_time").read_text()
        assert "/dev/venv/bin/harnessed claude_time" in content

    def test_unknown_stack_exits_nonzero_and_writes_no_shim(self, monkeypatch, tmp_path):
        _stub_catalog(monkeypatch, tmp_path, exists=False)
        home = _home_in(monkeypatch, tmp_path)

        with pytest.raises(typer.Exit) as exc:
            launcher.install_stack("claude_time")

        assert exc.value.exit_code == 1
        assert not (home / ".local" / "bin" / "claude_time").exists()


class TestImageStaleness:
    """`_img_differs` decides whether a running container is on an older image build."""

    def test_different_ids_are_stale(self):
        assert launcher._img_differs("aaa111", "bbb222") is True

    def test_same_ids_not_stale(self):
        assert launcher._img_differs("aaa111", "aaa111") is False

    def test_sha256_prefix_normalized(self):
        # image inspect may yield a bare hash; container inspect a sha256:-prefixed one.
        assert launcher._img_differs("sha256:aaa111", "aaa111") is False

    def test_missing_id_is_not_stale(self):
        # inspect failure on either side → can't tell → don't nag / don't recreate.
        assert launcher._img_differs("", "aaa111") is False
        assert launcher._img_differs("aaa111", "") is False




class TestStoppedLeftover:
    """`_stopped_leftover` decides whether launch() must recreate a stopped instance before
    `pod create` (a same-name pod otherwise 125s "already in use")."""

    def _set(self, monkeypatch, *, running, exists, podman, pod_exists):
        monkeypatch.setattr(launcher, "_container_running", lambda rt, inst: running)
        monkeypatch.setattr(launcher, "_container_exists", lambda rt, inst: exists)
        monkeypatch.setattr(launcher, "_rt_uses_pods", lambda rt: podman)
        monkeypatch.setattr(launcher, "_pod_exists", lambda rt, pod: pod_exists)

    def test_running_instance_is_never_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=True, exists=True, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is False

    def test_stopped_container_is_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=False, exists=True, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is True

    def test_partial_create_pod_only_is_a_leftover(self, monkeypatch):
        # Pod created but harness container never started (crash between create + run).
        self._set(monkeypatch, running=False, exists=False, podman=True, pod_exists=True)
        assert launcher._stopped_leftover("podman", "inst", "inst") is True

    def test_nothing_present_is_not_a_leftover(self, monkeypatch):
        self._set(monkeypatch, running=False, exists=False, podman=True, pod_exists=False)
        assert launcher._stopped_leftover("podman", "inst", "inst") is False

    def test_docker_has_no_pod_concept(self, monkeypatch):
        # _rt_uses_pods False → pod check skipped; only the container check matters.
        self._set(monkeypatch, running=False, exists=False, podman=False, pod_exists=True)
        assert launcher._stopped_leftover("docker", "inst", "inst") is False


class TestSessionActive:
    """`_session_active` decides whether an interactive harness session is attached, which
    gates `harnessed prune`. After hatago-consolidation an idle instance also runs the
    in-container hatago hub (`node`) and its stdio children (`uvx mcp-server-time`), so the
    rule is positive: only the interactive attach owns a real pts; every infra process
    (sleep, hatago, stdio children) runs with no controlling terminal (`?` on podman,
    `-`/`` elsewhere)."""

    def _top(self, monkeypatch, stdout, *, rc=0):
        from types import SimpleNamespace
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=rc, stdout=stdout),
        )

    def test_idle_infra_only_is_inactive(self, monkeypatch):
        # header + sleep / hatago(node) / uvx child, all with no tty.
        self._top(monkeypatch, "TTY\n?\n?\n?\n")
        assert launcher._session_active("podman", "inst") is False

    def test_attached_pts_is_active(self, monkeypatch):
        # the interactive attach owns pts/0 alongside the no-tty infra rows.
        self._top(monkeypatch, "TTY\n?\n?\npts/0\n")
        assert launcher._session_active("podman", "inst") is True

    def test_nonzero_returncode_is_undetermined(self, monkeypatch):
        # `top` failed (transient runtime hiccup) → can't tell → None, NOT False. prune must not
        # read this as confirmed-idle and tear down a live session on a momentary error.
        self._top(monkeypatch, "", rc=1)
        assert launcher._session_active("podman", "inst") is None

    def test_header_only_is_inactive(self, monkeypatch):
        self._top(monkeypatch, "TTY\n")
        assert launcher._session_active("podman", "inst") is False

    @pytest.mark.parametrize("marker", ["-", ""])
    def test_other_runtime_no_tty_markers_are_inactive(self, monkeypatch, marker):
        # docker/other runtimes report no-tty as `-` or empty rather than `?`.
        self._top(monkeypatch, f"TTY\n{marker}\n{marker}\n")
        assert launcher._session_active("docker", "inst") is False


class TestPrune:
    """`harnessed prune` reaps idle instances. A running container is gated by `_session_active`
    (tty probe) so a live attached session is never torn down. A non-running container
    (exited/crashed) has no session, so it skips the probe and is reaped straight off the idle
    check — otherwise it lingers forever, since a plain `podman ps` never lists it."""

    def _setup(self, monkeypatch, tmp_path, ps_rows, *, session=None):
        # ps_rows: list of (name, state) the `podman ps -a` call reports. `session` is what the
        # (mocked) `_session_active` returns for any running container.
        from types import SimpleNamespace

        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_attach_marker", lambda inst: tmp_path / inst)

        ps_stdout = "".join(f"{n}\t{s}\n" for n, s in ps_rows)

        def fake_run(cmd, *a, **k):
            assert "ps" in cmd and "-a" in cmd  # prune must list ALL containers, not running-only
            return SimpleNamespace(returncode=0, stdout=ps_stdout, stderr="")

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)

        active_calls = []

        def fake_active(rt, inst):
            active_calls.append(inst)
            return session

        monkeypatch.setattr(launcher, "_session_active", fake_active)

        torn = []
        monkeypatch.setattr(launcher, "_pod_teardown", lambda rt, inst, pod: torn.append(inst))
        return torn, active_calls

    def _marker(self, tmp_path, name, *, age_min):
        import os
        import time

        m = tmp_path / name
        m.write_text("")
        t = time.time() - age_min * 60
        os.utime(m, (t, t))

    def test_exited_idle_is_reaped_without_session_probe(self, monkeypatch, tmp_path):
        torn, active_calls = self._setup(monkeypatch, tmp_path, [("harnessed-x-11111111", "exited")])
        self._marker(tmp_path, "harnessed-x-11111111", age_min=180)
        launcher.prune(idle=120, dry_run=False)
        assert torn == ["harnessed-x-11111111"]
        assert active_calls == []  # non-running: the running-only tty probe is skipped

    def test_exited_but_recently_attached_is_not_reaped(self, monkeypatch, tmp_path):
        torn, _ = self._setup(monkeypatch, tmp_path, [("harnessed-x-22222222", "exited")])
        self._marker(tmp_path, "harnessed-x-22222222", age_min=5)
        launcher.prune(idle=120, dry_run=False)
        assert torn == []

    def test_exited_never_attached_is_left_alone(self, monkeypatch, tmp_path):
        torn, _ = self._setup(monkeypatch, tmp_path, [("harnessed-x-33333333", "exited")])
        # no marker on disk → never interactively attached (headless / externally driven)
        launcher.prune(idle=120, dry_run=False)
        assert torn == []

    def test_running_idle_session_is_reaped(self, monkeypatch, tmp_path):
        torn, active_calls = self._setup(
            monkeypatch, tmp_path, [("harnessed-x-44444444", "running")], session=False)
        self._marker(tmp_path, "harnessed-x-44444444", age_min=180)
        launcher.prune(idle=120, dry_run=False)
        assert torn == ["harnessed-x-44444444"]
        assert active_calls == ["harnessed-x-44444444"]  # running: probed before reaping

    def test_running_attached_session_is_kept(self, monkeypatch, tmp_path):
        torn, _ = self._setup(
            monkeypatch, tmp_path, [("harnessed-x-55555555", "running")], session=True)
        self._marker(tmp_path, "harnessed-x-55555555", age_min=180)
        launcher.prune(idle=120, dry_run=False)
        assert torn == []

    def test_running_undetermined_session_is_kept(self, monkeypatch, tmp_path):
        # `_session_active` returns None on a transient `top` failure → must NOT be read as idle.
        torn, _ = self._setup(
            monkeypatch, tmp_path, [("harnessed-x-66666666", "running")], session=None)
        self._marker(tmp_path, "harnessed-x-66666666", age_min=180)
        launcher.prune(idle=120, dry_run=False)
        assert torn == []


class TestResolveStartDir:
    """`_resolve_start_dir` resolves the agent's working directory for --agent-start-folder."""

    def test_none_returns_project_root(self, tmp_path):
        assert launcher._resolve_start_dir(tmp_path, None) == tmp_path

    def test_relative_subfolder_resolves_under_project(self, tmp_path):
        sub = tmp_path / "packages" / "web"
        sub.mkdir(parents=True)
        assert launcher._resolve_start_dir(tmp_path, "packages/web") == sub

    def test_absolute_subfolder_under_project(self, tmp_path):
        sub = tmp_path / "svc"
        sub.mkdir()
        assert launcher._resolve_start_dir(tmp_path, str(sub)) == sub

    def test_nonexistent_folder_exits(self, tmp_path):
        with pytest.raises(typer.Exit):
            launcher._resolve_start_dir(tmp_path, "nope/missing")

    def test_file_not_directory_exits(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(typer.Exit):
            launcher._resolve_start_dir(tmp_path, "file.txt")

    def test_outside_project_exits(self, tmp_path):
        # A dir that exists on the host but is not under the mounted project tree.
        outside = tmp_path.parent / "elsewhere_check"
        outside.mkdir(exist_ok=True)
        try:
            with pytest.raises(typer.Exit):
                launcher._resolve_start_dir(tmp_path, str(outside))
        finally:
            outside.rmdir()


class TestResolveMountPath:
    """`_resolve_mount_path` widens the path-mirror mount via --mount-folder (must contain project)."""

    def test_none_returns_project(self, tmp_path):
        project = tmp_path / "harnessed" / "main"
        project.mkdir(parents=True)
        assert launcher._resolve_mount_path(project, None) == project

    def test_parent_folder_containing_project(self, tmp_path):
        parent = tmp_path / "harnessed"
        project = parent / "main"
        project.mkdir(parents=True)
        assert launcher._resolve_mount_path(project, str(parent)) == parent

    def test_project_itself_is_allowed(self, tmp_path):
        project = tmp_path / "p"
        project.mkdir()
        assert launcher._resolve_mount_path(project, str(project)) == project

    def test_nonexistent_mount_exits(self, tmp_path):
        project = tmp_path / "p"
        project.mkdir()
        with pytest.raises(typer.Exit):
            launcher._resolve_mount_path(project, str(tmp_path / "missing"))

    def test_mount_not_containing_project_exits(self, tmp_path):
        # A sibling dir that does NOT contain the project — invalid.
        project = tmp_path / "a" / "main"
        project.mkdir(parents=True)
        sibling = tmp_path / "b"
        sibling.mkdir()
        with pytest.raises(typer.Exit):
            launcher._resolve_mount_path(project, str(sibling))

    def test_none_auto_widens_for_bare_worktree_layout(self, tmp_path):
        # Bare repo + linked worktree, no --mount-folder given: default should auto-widen to the
        # dir containing the bare repo, not just the worktree itself.
        import subprocess

        def git(*args, cwd=None):
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        seed = tmp_path / "seed"
        git("init", "-q", str(seed))
        git("commit", "--allow-empty", "-m", "init", cwd=seed)
        default = subprocess.run(
            ["git", "-C", str(seed), "symbolic-ref", "--short", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        bare = tmp_path / "b.git"
        git("clone", "-q", "--bare", str(seed), str(bare))
        main_wt = tmp_path / "mainwt"
        git("--git-dir", str(bare), "worktree", "add", "-q", str(main_wt), default)

        assert launcher._resolve_mount_path(main_wt, None) == tmp_path

    def test_none_does_not_widen_for_ordinary_repo(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        assert launcher._resolve_mount_path(tmp_path, None) == tmp_path


class TestBuildMountArgs:
    """The path-mirror `-v` targets the mount root (project by default, a parent via --mount-folder)."""

    def test_mirrors_the_mount_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        parent = tmp_path / "harnessed"
        parent.mkdir()
        args = launcher._build_mount_args("claude", tmp_path / "prof", parent)
        assert "-v" in args and f"{parent}:{parent}" in args
        # The narrower project path is NOT mounted separately — it's covered by the parent mirror.
        assert not any(str(parent / "main") in a for a in args)

    def _prof_with_opencode_persona(self, tmp_path):
        prof = tmp_path / "prof"
        (prof / "opencode" / "prompts").mkdir(parents=True)
        (prof / "opencode" / "opencode.json").write_text("{}")
        (prof / "opencode" / "prompts" / "rel.md").write_text("persona")
        return prof

    def test_opencode_persona_mounts_config_and_prompts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = self._prof_with_opencode_persona(tmp_path)
        ctr = launcher._CONTAINER_HOME_STR
        args = launcher._build_mount_args("opencode", prof, tmp_path)
        cfg = prof / "opencode" / "opencode.json"
        prompts = prof / "opencode" / "prompts"
        assert f"{cfg}:{ctr}/.config/opencode/opencode.json:ro" in args
        assert f"{prompts}:{ctr}/.config/opencode/prompts:ro" in args

    def test_opencode_without_persona_no_config_mount(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = tmp_path / "prof"
        prof.mkdir()
        args = launcher._build_mount_args("opencode", prof, tmp_path)
        assert not any(".config/opencode" in a for a in args)

    def _prof_with_antigravity_identity(self, tmp_path):
        prof = tmp_path / "prof"
        (prof / ".gemini").mkdir(parents=True)
        (prof / ".gemini" / "settings.json").write_text("{}")
        (prof / ".gemini" / "GEMINI.md").write_text("identity")
        return prof

    def test_antigravity_identity_mounts_settings_and_gemini_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = self._prof_with_antigravity_identity(tmp_path)
        ctr = launcher._CONTAINER_HOME_STR
        args = launcher._build_mount_args("antigravity", prof, tmp_path)
        settings = prof / ".gemini" / "settings.json"
        identity = prof / ".gemini" / "GEMINI.md"
        assert f"{settings}:{ctr}/.gemini/settings.json:ro" in args
        assert f"{identity}:{ctr}/.gemini/GEMINI.md:ro" in args

    def test_antigravity_without_identity_no_gemini_mount(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = tmp_path / "prof"
        prof.mkdir()
        args = launcher._build_mount_args("antigravity", prof, tmp_path)
        assert not any(".gemini" in a for a in args)

    def test_codex_identity_mounts_agents_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = tmp_path / "prof"
        (prof / ".codex").mkdir(parents=True)
        (prof / ".codex" / "AGENTS.md").write_text("identity")
        ctr = launcher._CONTAINER_HOME_STR
        args = launcher._build_mount_args("codex", prof, tmp_path)
        agents = prof / ".codex" / "AGENTS.md"
        assert f"{agents}:{ctr}/.codex/AGENTS.md:ro" in args

    def test_codex_without_identity_no_agents_mount(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = tmp_path / "prof"
        prof.mkdir()
        args = launcher._build_mount_args("codex", prof, tmp_path)
        assert not any(".codex" in a for a in args)

    def test_claude_unaffected_by_identity_branches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher, "_catalog_base", lambda name: tmp_path / name)
        prof = self._prof_with_antigravity_identity(tmp_path)
        (prof / ".codex").mkdir(parents=True)
        (prof / ".codex" / "AGENTS.md").write_text("identity")
        args = launcher._build_mount_args("claude", prof, tmp_path)
        assert not any(".gemini" in a for a in args)
        assert not any(".codex" in a for a in args)


class TestHostClaudeSettingsMerge:
    def test_merges_host_settings_and_reapplies_required_grants(self, tmp_path, monkeypatch):
        home = _home_in(monkeypatch, tmp_path)
        prof = tmp_path / "prof"
        prof.mkdir()

        # Profile settings (image/profile defaults) include statusLine and a required hatago grant.
        (prof / "settings.json").write_text(
            json.dumps({
                "statusLine": {"type": "command", "command": "ccstatusline"},
                "permissions": {
                    "defaultMode": "acceptEdits",
                    "allow": ["mcp__hatago"],
                },
            })
        )

        # Host settings customize model + mode and deny hatago (which harnessed must re-enable).
        host_claude = home / ".claude"
        host_claude.mkdir(parents=True)
        (host_claude / "settings.json").write_text(
            json.dumps({
                "model": "sonnet",
                "permissions": {
                    "defaultMode": "default",
                    "allow": ["mcp__mytool"],
                    "deny": ["mcp__hatago"],
                },
            })
        )

        required = {
            "permissions": {
                "defaultMode": "acceptEdits",
                "allow": ["mcp__hatago"],
            }
        }
        launcher._merge_host_claude_settings(prof, required)
        out = json.loads((prof / "settings.json").read_text())

        # Host customizations are honored.
        assert out["model"] == "sonnet"
        assert out["permissions"]["defaultMode"] == "default"
        assert "mcp__mytool" in out["permissions"]["allow"]
        # Harnessed-required grant is always present and removed from deny.
        assert "mcp__hatago" in out["permissions"]["allow"]
        assert "mcp__hatago" not in out["permissions"].get("deny", [])
        # Profile-only keys survive when host does not override them.
        assert out["statusLine"]["command"] == "ccstatusline"

    def test_host_statusline_never_overrides_baked_container_path(self, tmp_path, monkeypatch):
        # The ccstatusline recipe bakes a container-absolute statusLine command
        # (/home/harnessed/...). The host's statusLine points at a host-absolute path that can never
        # resolve inside the container, so the host value must be dropped and the baked one kept.
        home = _home_in(monkeypatch, tmp_path)
        prof = tmp_path / "prof"
        prof.mkdir()
        (prof / "settings.json").write_text(
            json.dumps({
                "statusLine": {
                    "type": "command",
                    "command": "/home/harnessed/.local/share/mise/shims/ccstatusline",
                },
            })
        )
        host_claude = home / ".claude"
        host_claude.mkdir(parents=True)
        (host_claude / "settings.json").write_text(
            json.dumps({
                "statusLine": {
                    "type": "command",
                    "command": "/home/mcrowe/.local/share/mise/shims/ccstatusline",
                },
            })
        )

        launcher._merge_host_claude_settings(prof, {})
        out = json.loads((prof / "settings.json").read_text())
        assert out["statusLine"]["command"] == "/home/harnessed/.local/share/mise/shims/ccstatusline"

    def test_noop_when_host_settings_absent(self, tmp_path, monkeypatch):
        _home_in(monkeypatch, tmp_path)
        prof = tmp_path / "prof"
        prof.mkdir()
        baseline = {"permissions": {"defaultMode": "acceptEdits", "allow": ["mcp__hatago"]}}
        (prof / "settings.json").write_text(json.dumps(baseline))

        launcher._merge_host_claude_settings(prof, baseline)
        out = json.loads((prof / "settings.json").read_text())
        assert out == baseline


class TestOpencodeAttachCmd:
    """`_opencode_attach_cmd` is stack-conditional (bd main-rlw): a baked persona → `opencode
    --agent <name>`; no persona → the fixed `opencode` command."""

    def test_with_persona_uses_agent_flag(self, tmp_path):
        prof = tmp_path / "prof"
        (prof / "opencode").mkdir(parents=True)
        (prof / "opencode" / "opencode.json").write_text("{}")
        assert launcher._opencode_attach_cmd(prof, "opencode_bot") == "opencode --agent opencode-bot"

    def test_without_persona_keeps_fixed_command(self, tmp_path):
        prof = tmp_path / "prof"
        prof.mkdir()
        assert launcher._opencode_attach_cmd(prof, "opencode_bot") == "opencode"


class TestCredentialForwarding:
    """`_credential_forward_args` / `_ssh_agent_args` / `_yubikey_device_args` forward the host's
    git signing + push surface (1Password/GPG/YubiKey agent, git config, ~/.ssh) into the harness
    container, conditioned on host-side existence. Ports container.sh's optional_args block."""

    CTR = launcher._CONTAINER_HOME_STR

    @pytest.fixture
    def cred_home(self):
        # AF_UNIX socket paths cap at ~108 chars, so use a SHORT /tmp home, not pytest's long tmp_path.
        import shutil
        import tempfile
        home = Path(tempfile.mkdtemp(prefix="hshome"))
        socks: list = []
        yield home, socks
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        shutil.rmtree(home, ignore_errors=True)

    @staticmethod
    def _mksock(p: Path, keep: list):
        import socket
        p.parent.mkdir(parents=True, exist_ok=True)
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(p))
        keep.append(s)

    # --- _ssh_agent_args: 1Password primary, gpg-agent (YubiKey) fallback ---

    def test_no_agents_is_empty(self, cred_home):
        home, _ = cred_home
        assert launcher._ssh_agent_args(home, home / "nope.sock") == []

    def test_1password_socket_sets_auth_sock(self, cred_home, monkeypatch):
        home, socks = cred_home
        # Force the host-os branch to linux so _op_agent_socket resolves ~/.1password/agent.sock,
        # matching the test socket we create here. CI runs on Linux; this makes the test portable
        # to macOS where the default path is the Group Containers dir.
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        self._mksock(home / ".1password" / "agent.sock", socks)
        args = launcher._ssh_agent_args(home, home / "nogpg.sock")
        ctr_sock = f"{self.CTR}/.1password/agent.sock"
        assert f"{home / '.1password' / 'agent.sock'}:{ctr_sock}" in args
        assert f"SSH_AUTH_SOCK={ctr_sock}" in args

    def test_1password_wins_over_gpg(self, cred_home, monkeypatch):
        home, socks = cred_home
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        self._mksock(home / ".1password" / "agent.sock", socks)
        gpg = home / "gpg.sock"
        self._mksock(gpg, socks)
        args = launcher._ssh_agent_args(home, gpg)
        # Both sockets mounted, but SSH_AUTH_SOCK stays 1Password (the active signer).
        assert f"SSH_AUTH_SOCK={self.CTR}/.1password/agent.sock" in args
        assert f"SSH_AUTH_SOCK={self.CTR}/.gnupg-sockets/S.gpg-agent.ssh" not in args
        assert any("S.gpg-agent.ssh" in a for a in args)  # gpg socket still bind-mounted

    def test_gpg_fallback_when_no_1password(self, cred_home, monkeypatch):
        home, socks = cred_home
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        gpg = home / "gpg.sock"
        self._mksock(gpg, socks)
        args = launcher._ssh_agent_args(home, gpg)
        assert f"SSH_AUTH_SOCK={self.CTR}/.gnupg-sockets/S.gpg-agent.ssh" in args

    # --- _ssh_agent_auto_forward_args: presence-driven, no forward_git_credentials opt-in ---

    def test_auto_forward_noop_without_agent(self, cred_home, monkeypatch):
        # No agent socket on the host → nothing forwarded, even though a git config exists.
        home, _ = cred_home
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(launcher, "_gpg_ssh_socket", lambda: None)
        (home / ".gitconfig").write_text("[user]\n  name = t\n")
        assert launcher._ssh_agent_auto_forward_args(home) == []

    def test_auto_forward_mounts_agent_and_gitconfig(self, cred_home, monkeypatch):
        # 1Password socket live → agent + ro git identity config forwarded with no opt-in flag.
        home, socks = cred_home
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(launcher, "_gpg_ssh_socket", lambda: None)
        self._mksock(home / ".1password" / "agent.sock", socks)
        (home / ".gitconfig").write_text("[commit]\n  gpgsign = true\n")
        args = launcher._ssh_agent_auto_forward_args(home)
        assert f"SSH_AUTH_SOCK={self.CTR}/.1password/agent.sock" in args
        assert f"{home / '.gitconfig'}:{self.CTR}/.gitconfig:ro" in args

    def test_auto_forward_omits_gh_token_and_private_keys(self, cred_home, monkeypatch):
        # The secret-bearing surface (gh oauth token, ~/.ssh) stays behind forward_git_credentials.
        home, socks = cred_home
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(launcher, "_gpg_ssh_socket", lambda: None)
        self._mksock(home / ".1password" / "agent.sock", socks)
        gh_hosts = home / ".config" / "gh" / "hosts.yml"
        gh_hosts.parent.mkdir(parents=True)
        gh_hosts.write_text("github.com:\n  oauth_token: SECRET\n")
        (home / ".ssh").mkdir()
        (home / ".ssh" / "id_ed25519").write_text("PRIVATE")
        args = launcher._ssh_agent_auto_forward_args(home)
        assert not any("hosts.yml" in a for a in args)
        assert not any(".ssh" in a for a in args)

    # --- _yubikey_device_args: USB passthrough via lsusb ---

    def test_yubikey_present_adds_device(self, monkeypatch):
        from types import SimpleNamespace
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="Bus 003 Device 004: ID 1050:0407 Yubico.com\n"),
        )
        real_exists = Path.exists
        monkeypatch.setattr(
            launcher.Path, "exists",
            lambda self: True if str(self) == "/dev/bus/usb/003/004" else real_exists(self),
        )
        assert launcher._yubikey_device_args() == ["--device", "/dev/bus/usb/003/004"]

    def test_yubikey_absent_returns_empty(self, monkeypatch):
        from types import SimpleNamespace
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="Bus 001 Device 002: ID 8087:0029 Intel Corp.\n"),
        )
        assert launcher._yubikey_device_args() == []

    # --- _aws_sso_ecs_forward_args: opt-in AWS creds via the host aws-sso ECS server ---

    def test_aws_sso_noop_without_token_file(self, tmp_path):
        # No bearer token file on the host → nothing injected (server never set up).
        assert launcher._aws_sso_ecs_forward_args(token_file=tmp_path / "absent.token") == []

    def test_aws_sso_noop_with_empty_token(self, tmp_path):
        # Present-but-empty token file is treated as unconfigured.
        tf = tmp_path / "aws-sso-ecs.token"
        tf.write_text("   \n")
        assert launcher._aws_sso_ecs_forward_args(token_file=tf) == []

    def test_aws_sso_injects_uri_and_bearer_token(self, tmp_path):
        # Token present → the ECS endpoint URI (host.containers.internal) + Bearer token env are
        # injected, honoring a custom port. Token is stripped of surrounding whitespace.
        tf = tmp_path / "aws-sso-ecs.token"
        tf.write_text("deadbeef\n")
        args = launcher._aws_sso_ecs_forward_args(port=9999, token_file=tf)
        assert "AWS_CONTAINER_CREDENTIALS_FULL_URI=http://host.containers.internal:9999/" in args
        assert "AWS_CONTAINER_AUTHORIZATION_TOKEN=Bearer deadbeef" in args

    # --- _apply_firewall: recipe-declared egress domains appended to the allowlist ---

    def test_firewall_appends_egress_domains(self, monkeypatch):
        # Extra domains are passed to the egress-firewall script as positional args.
        captured = {}
        monkeypatch.setattr(launcher.os.environ, "get", lambda k, d=None: "false" if k == "NO_FIREWALL" else d)
        monkeypatch.setattr(launcher.subprocess, "run", lambda cmd, **k: captured.setdefault("cmd", cmd))
        launcher._apply_firewall("podman", "inst", ["api.pulumi.com", "get.pulumi.com"])
        assert captured["cmd"][-2:] == ["api.pulumi.com", "get.pulumi.com"]
        assert captured["cmd"][:5] == ["podman", "exec", "inst", "bash", "/usr/local/sbin/egress-firewall"]

    def test_firewall_skipped_when_disabled(self, monkeypatch):
        called = {"ran": False}
        monkeypatch.setattr(launcher.os.environ, "get", lambda k, d=None: "true" if k == "NO_FIREWALL" else d)
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: called.__setitem__("ran", True))
        launcher._apply_firewall("podman", "inst", ["api.pulumi.com"])
        assert called["ran"] is False

    def test_yubikey_no_lsusb_is_clean(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("lsusb")
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(launcher.subprocess, "run", boom)
        assert launcher._yubikey_device_args() == []

    def test_yubikey_vendor_id_not_device_number(self, monkeypatch):
        # LOW-1: "1050" must match the Yubico VENDOR id (ID 1050:), not a high device number — a
        # line like "Device 1050: ID 1234:5678 Acme" must NOT be selected for --device passthrough.
        from types import SimpleNamespace
        real_exists = Path.exists
        monkeypatch.setattr(launcher, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            launcher.Path, "exists",
            lambda self: True if str(self) == "/dev/bus/usb/005/1050" else real_exists(self),
        )
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="Bus 005 Device 1050: ID 1234:5678 Acme Widget\n"),
        )
        assert launcher._yubikey_device_args() == []

    # --- _credential_forward_args: git config + ~/.ssh + ~/.gnupg (agent/yubikey isolated) ---

    def _isolate(self, monkeypatch):
        # The SSH-agent + YubiKey pieces are tested above; isolate them so these assert the mounts.
        monkeypatch.setattr(launcher, "_ssh_agent_args", lambda *a, **k: [])
        monkeypatch.setattr(launcher, "_yubikey_device_args", lambda: [])

    def test_empty_home_is_noop(self, tmp_path, monkeypatch):
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        home.mkdir()
        assert launcher._credential_forward_args(home) == []

    def test_legacy_gitconfig_mounted_ro(self, tmp_path, monkeypatch):
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        home.mkdir()
        (home / ".gitconfig").write_text("[user]\n  name = x\n")
        args = launcher._credential_forward_args(home)
        assert f"{home / '.gitconfig'}:{self.CTR}/.gitconfig:ro" in args

    def test_xdg_gitconfig_wins_over_legacy(self, tmp_path, monkeypatch):
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".gitconfig").write_text("x")
        args = launcher._credential_forward_args(home)
        assert f"{home / '.config' / 'git'}:{self.CTR}/.config/git:ro" in args
        assert not any(a.endswith(".gitconfig:ro") or "/.gitconfig:" in a for a in args)

    def test_gh_hosts_yml_mounted_ro(self, tmp_path, monkeypatch, capsys):
        # gh's oauth token lives in ~/.config/gh/hosts.yml — forward just that file, ro, so `gh` in
        # the container authenticates as the host user. No wider gh config, no token in env.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        (home / ".config" / "gh").mkdir(parents=True)
        (home / ".config" / "gh" / "hosts.yml").write_text("github.com:\n  oauth_token: x\n")
        args = launcher._credential_forward_args(home)
        assert f"{home / '.config' / 'gh' / 'hosts.yml'}:{self.CTR}/.config/gh/hosts.yml:ro" in args
        # A real plaintext token is present — no keychain-storage warning should fire.
        assert "insecure-storage" not in capsys.readouterr().err

    def test_gh_hosts_keychain_backed_warns(self, tmp_path, monkeypatch, capsys):
        # Modern `gh` stores the token in the OS credential store (macOS Keychain, etc.) by default,
        # leaving hosts.yml with real entries but no `oauth_token` field. The container can't reach
        # the host keychain, so `gh` inside it has no usable token — warn and point at the fix.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        (home / ".config" / "gh").mkdir(parents=True)
        (home / ".config" / "gh" / "hosts.yml").write_text(
            "github.com:\n    git_protocol: https\n    users:\n        someuser:\n    user: someuser\n"
        )
        args = launcher._credential_forward_args(home)
        # Still mounted — the file may become useful after the user fixes storage on the host.
        assert f"{home / '.config' / 'gh' / 'hosts.yml'}:{self.CTR}/.config/gh/hosts.yml:ro" in args
        assert "insecure-storage" in capsys.readouterr().err

    def test_gh_hosts_missing_plaintext_token_helper(self, tmp_path):
        keychain_backed = tmp_path / "keychain.yml"
        keychain_backed.write_text("github.com:\n    users:\n        someuser:\n")
        assert launcher._gh_hosts_missing_plaintext_token(keychain_backed) is True

        plaintext = tmp_path / "plaintext.yml"
        plaintext.write_text("github.com:\n    oauth_token: x\n")
        assert launcher._gh_hosts_missing_plaintext_token(plaintext) is False

        unparseable = tmp_path / "bad.yml"
        unparseable.write_text("key: [1, 2\n")  # unclosed flow sequence -> ParserError
        assert launcher._gh_hosts_missing_plaintext_token(unparseable) is False

    def test_gnupg_nonsecret_files_mounted_but_not_keyring(self, tmp_path, monkeypatch):
        # Security regression guard (review Finding 2): the whole ~/.gnupg mount leaked
        # private-keys-v1.d/*.key. Only the non-secret files may be forwarded; the private keyring
        # must NEVER be mounted.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        gnupg = home / ".gnupg"
        (gnupg / "private-keys-v1.d").mkdir(parents=True)
        (gnupg / "private-keys-v1.d" / "DEADBEEF.key").write_text("SECRET-KEY-MATERIAL")
        (gnupg / "pubring.kbx").write_text("pub")
        (gnupg / "trustdb.gpg").write_text("trust")
        args = launcher._credential_forward_args(home)
        assert f"{gnupg / 'pubring.kbx'}:{self.CTR}/.gnupg/pubring.kbx:ro" in args
        # The whole-dir mount and the private keyring must both be absent.
        assert f"{gnupg}:{self.CTR}/.gnupg:ro" not in args
        assert not any("private-keys-v1.d" in a for a in args)

    def test_gnupg_sshcontrol_mounted(self, tmp_path, monkeypatch):
        # LOW-4: gpg-agent's sshcontrol (keygrips authorized for SSH) is non-secret and needed for the
        # YubiKey-via-gpg-agent SSH path — include it in the non-secret allowlist.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        gnupg = home / ".gnupg"
        gnupg.mkdir(parents=True)
        (gnupg / "sshcontrol").write_text("ABCDEFGH 0\n")
        args = launcher._credential_forward_args(home)
        assert f"{gnupg / 'sshcontrol'}:{self.CTR}/.gnupg/sshcontrol:ro" in args

    def test_pubkey_with_colon_in_name_is_skipped(self, tmp_path, monkeypatch):
        # Review Finding 5: a ~/.ssh/*.pub filename containing ':' would reparse the -v mount spec.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        ssh = home / ".ssh"
        ssh.mkdir(parents=True)
        (ssh / "normal.pub").write_text("pub")
        (ssh / "evil:x:ro.pub").write_text("pub")  # ':' reparses the -v spec; must be skipped
        args = launcher._credential_forward_args(home)
        assert any("normal.pub" in a for a in args)
        assert not any("evil" in a for a in args)

    def test_whole_ssh_dir_is_never_mounted(self, tmp_path, monkeypatch):
        # Regression guard: the blunt `-v ~/.ssh:/.ssh` mount (which dropped ALL private keys into
        # the container) must NOT come back. ~/.ssh is forwarded file-by-file via _ssh_dir_mounts.
        self._isolate(monkeypatch)
        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_secret").write_text("PRIVATE")  # not opted in
        args = launcher._credential_forward_args(home)
        assert f"{home / '.ssh'}:{self.CTR}/.ssh:ro" not in args
        assert not any("id_secret" in a for a in args)  # un-declared private key never mounted


class TestSshDirMounts:
    """`_ssh_dir_mounts` forwards the non-secret SSH surface (config, known_hosts, *.pub) always, and
    private keys ONLY when the stack's ssh_keys opts them in by basename — never the whole dir."""

    CTR = launcher._CONTAINER_HOME_STR

    def test_public_surface_mounted_ro(self, tmp_path):
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        (ssh / "config").write_text("Host *\n")
        (ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
        (ssh / "id_ed25519.pub").write_text("ssh-ed25519 AAAA pub\n")
        (ssh / "id_ed25519").write_text("PRIVATE")  # present but NOT opted-in
        args = launcher._ssh_dir_mounts(tmp_path, [])
        assert f"{ssh / 'config'}:{self.CTR}/.ssh/config:ro" in args
        assert f"{ssh / 'known_hosts'}:{self.CTR}/.ssh/known_hosts:ro" in args
        assert f"{ssh / 'id_ed25519.pub'}:{self.CTR}/.ssh/id_ed25519.pub:ro" in args
        # The private key is present but not declared → must NOT be mounted.
        assert not any(a == f"{ssh / 'id_ed25519'}:{self.CTR}/.ssh/id_ed25519:ro" for a in args)

    def test_declared_private_key_mounted_ro(self, tmp_path):
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        (ssh / "id_work").write_text("PRIVATE")
        args = launcher._ssh_dir_mounts(tmp_path, ["id_work"])
        assert f"{ssh / 'id_work'}:{self.CTR}/.ssh/id_work:ro" in args

    def test_declared_but_missing_key_is_skipped(self, tmp_path):
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        args = launcher._ssh_dir_mounts(tmp_path, ["nope"])
        assert not any("nope" in a for a in args)

    def test_no_ssh_dir_is_noop(self, tmp_path):
        assert launcher._ssh_dir_mounts(tmp_path, ["id_work"]) == []

    def test_symlink_escaping_ssh_is_refused(self, tmp_path):
        # A symlink in ~/.ssh pointing at a secret OUTSIDE ~/.ssh must not be followed out.
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        outside = tmp_path / "elsewhere_key"
        outside.write_text("PRIVATE")
        (ssh / "evil").symlink_to(outside)
        args = launcher._ssh_dir_mounts(tmp_path, ["evil"])
        assert not any("elsewhere_key" in a or "/evil:" in a for a in args)

    def test_symlinked_public_surface_escaping_ssh_is_refused(self, tmp_path):
        # MED-3: the always-on surface (config / known_hosts / *.pub) must NOT follow a symlink whose
        # target escapes ~/.ssh — same containment as the opt-in ssh_keys path. A symlinked
        # ~/.ssh/config -> <secret> must not mount the secret read-only into the container.
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        secret = tmp_path / "aws-credentials"
        secret.write_text("[default]\naws_secret = x")
        (ssh / "config").symlink_to(secret)      # escaping symlink, always-on mount
        (ssh / "leak.pub").symlink_to(secret)    # escaping symlink, *.pub mount
        args = launcher._ssh_dir_mounts(tmp_path, [])
        assert not any("aws-credentials" in a for a in args)
        assert not any(a.endswith("/.ssh/config:ro") for a in args)
        assert not any("leak.pub" in a for a in args)


class TestTrustedSshKeys:
    """Review Finding 1: private-key `ssh_keys` mounts are honored ONLY from the user overlay — a
    shared repo-catalog stack must never mount the user's private key without the owner's consent."""

    def test_overlay_stack_keys_honored(self):
        assert launcher._trusted_ssh_keys(["id_ed25519"], True, "mystack") == ["id_ed25519"]

    def test_repo_catalog_keys_dropped(self):
        assert launcher._trusted_ssh_keys(["id_ed25519"], False, "shared") == []

    def test_no_keys_is_noop_either_way(self):
        assert launcher._trusted_ssh_keys([], False, "s") == []
        assert launcher._trusted_ssh_keys([], True, "s") == []


class TestHostOsPaths:
    """OS-aware agent socket + gpg socket detection (macOS vs Linux)."""

    def test_op_socket_linux(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert launcher._op_agent_socket(tmp_path) == tmp_path / ".1password" / "agent.sock"

    def test_op_socket_macos(self, tmp_path, monkeypatch):
        monkeypatch.setattr(launcher.sys, "platform", "darwin")
        got = launcher._op_agent_socket(tmp_path)
        assert got == tmp_path / "Library" / "Group Containers" / "2BUA8C4S2C.com.1password" / "t" / "agent.sock"

    def test_gpg_socket_prefers_gpgconf(self, monkeypatch):
        from types import SimpleNamespace
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="/run/user/1000/gnupg/S.gpg-agent.ssh\n"),
        )
        assert launcher._gpg_ssh_socket() == Path("/run/user/1000/gnupg/S.gpg-agent.ssh")

    def test_gpg_socket_linux_fallback_when_no_gpgconf(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("gpgconf")
        monkeypatch.setattr(launcher.subprocess, "run", boom)
        monkeypatch.setattr(launcher.sys, "platform", "linux")
        assert str(launcher._gpg_ssh_socket()).endswith("/gnupg/S.gpg-agent.ssh")

    def test_gpg_socket_with_colon_skips_mount(self, tmp_path, monkeypatch):
        # LOW-2: a ':' in the gpg-agent socket path would reparse the `-v src:dst` spec → skip mount.
        monkeypatch.setattr(launcher.Path, "is_socket", lambda self: True)
        args = launcher._ssh_agent_args(tmp_path, Path("/run/gnupg:weird/S.gpg-agent.ssh"))
        assert not any("S.gpg-agent.ssh" in a for a in args)

    def test_yubikey_skipped_off_linux(self, monkeypatch):
        monkeypatch.setattr(launcher.sys, "platform", "darwin")
        # Even if lsusb would match, the non-Linux guard returns [] before shelling out.
        assert launcher._yubikey_device_args() == []

    def test_macos_relay_returns_none_on_failed_forward(self, monkeypatch):
        # Review Finding 4: a failed reverse-forward must NOT return a path (which would point
        # SSH_AUTH_SOCK at a dead socket) — return None so the caller falls back to the note.
        from types import SimpleNamespace
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=255, stdout="", stderr="forward failed"),
        )
        assert launcher._macos_op_socket_mount_source("podman", Path("/host/agent.sock")) is None

    def test_macos_relay_returns_vm_sock_on_success(self, monkeypatch):
        from types import SimpleNamespace
        monkeypatch.setattr(
            launcher.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        assert launcher._macos_op_socket_mount_source("podman", Path("/host/agent.sock")) == Path(
            "/tmp/harnessed-op-agent.sock"
        )

    def test_macos_relay_skips_non_podman(self, monkeypatch):
        assert launcher._macos_op_socket_mount_source("docker", Path("/host/agent.sock")) is None


class TestBuildDerivedImageNeverTouchesSecrets:
    """`harnessed build` must never invoke varlock or touch secrets, even when
    ~/.config/harnessed/.env.schema exists — a credentialed scan is a deliberately separate,
    explicit step (`harnessed rescan`), not something the build does on your behalf."""

    def test_build_never_invokes_varlock_even_with_schema_present(self, monkeypatch, tmp_path):
        # Schema present + varlock on PATH — the exact condition that used to trigger a varlock
        # invocation (and an interactive 1Password prompt in a real environment). Confirm neither
        # is even consulted: no Path.home() lookup for a schema, no "varlock" in any command run.
        home = tmp_path / "home"
        schema_dir = home / ".config" / "harnessed"
        schema_dir.mkdir(parents=True)
        (schema_dir / ".env.schema").write_text("SNYK_TOKEN=op(op://x/y/z)\n")
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/varlock" if name == "varlock" else None)

        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)
        launcher._build_derived_image("podman", "harnessed-x:latest", tmp_path / "Dockerfile", tmp_path, "deadbeef")

        assert len(calls) == 1, "build must issue exactly one command: the plain podman build"
        assert calls[0][:2] == ["podman", "build"]
        assert "varlock" not in calls[0]
        assert "--secret" not in calls[0], "the build must never claim a secret it doesn't resolve"
