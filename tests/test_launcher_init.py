"""Tests for Model A recipe init: `init.run` sourced in the attach shell.

The transient `podman run --rm` init container is gone; init now runs inline in the same shell that
starts the harness (`_init_shell_prologue`, wired into `_attach`), so init-derived env reaches the
agent. No real podman; `load_stack_with_recipes`, `paths.git_common_dir`, and `os.execvp` are
monkeypatched.
"""

import os
import shlex

import pytest
import typer

from harnessed import launcher, paths
from harnessed.schema import InitSpec, PersistSpec, Recipe, Stack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recipe(name: str, run: "str | None" = None) -> Recipe:
    return Recipe(name=name, init=InitSpec(run=run) if run else None, persist=PersistSpec())


def _stub_recipes(monkeypatch, recipes: list[Recipe]) -> None:
    stk = Stack(name="s", recipes=[r.name for r in recipes])
    monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, stack: (stk, recipes))


# ---------------------------------------------------------------------------
# TestInitShellPrologue
# ---------------------------------------------------------------------------


class TestInitShellPrologue:
    """`_init_shell_prologue` builds the exports + per-recipe fail-fast init runs."""

    def test_no_init_recipes_returns_only_exports(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("ping")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        proj = tmp_path / "proj"
        out = launcher._init_shell_prologue("s", proj, tmp_path, harness="claude")
        assert out.startswith("export ")
        # No init recipe → no run wrappers appended, so no `&&` join.
        assert "&&" not in out
        assert "|| " not in out

    def test_exports_all_four_contract_vars(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("ping")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        proj = tmp_path / "proj"
        out = launcher._init_shell_prologue("s", proj, tmp_path, harness="claude")
        assert f"PROJECT_DIR={shlex.quote(str(proj))}" in out
        assert f"MAIN_REPO_DIR={shlex.quote(str(proj))}" in out  # falls back to project
        assert f"CONTAINER_WORKSPACE_DIR={shlex.quote(str(tmp_path))}" in out
        assert f"HOST_WORKSPACE_DIR={shlex.quote(str(tmp_path))}" in out

    def test_exports_host_home(self, tmp_path, monkeypatch):
        """HOST_HOME is the host's $HOME — the pod's is /home/harnessed, so a recipe whose tool
        reads a path-mirrored `scope: global` persist dir (e.g. pulumi's ~/.pulumi) needs it."""
        _stub_recipes(monkeypatch, [_recipe("ping")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: tmp_path / "hosthome"))
        out = launcher._init_shell_prologue("s", tmp_path / "proj", tmp_path, harness="claude")
        assert f"HOST_HOME={shlex.quote(str(tmp_path / 'hosthome'))}" in out

    def test_main_repo_dir_uses_git_common_dir(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("ping")])
        common = tmp_path / "bare"
        monkeypatch.setattr(paths, "git_common_dir", lambda p: common)
        proj = tmp_path / "main"
        out = launcher._init_shell_prologue("s", proj, tmp_path, harness="claude")
        assert f"MAIN_REPO_DIR={shlex.quote(str(common))}" in out
        assert f"PROJECT_DIR={shlex.quote(str(proj))}" in out

    def test_single_init_recipe_wrapped_fail_fast(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("beads", run="bd list || bd init")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        out = launcher._init_shell_prologue("s", tmp_path / "proj", tmp_path, harness="claude")
        assert "{ bd list || bd init; } ||" in out
        assert "init failed for recipe beads" in out
        assert "exit 1" in out
        # Exactly one run wrapper, joined to the exports with &&.
        assert out.count("init failed for recipe") == 1
        assert " && { bd list || bd init; }" in out

    def test_multiple_init_recipes_each_wrapped_and_joined(self, tmp_path, monkeypatch):
        recipes = [_recipe("a", "cmd-a"), _recipe("noinit"), _recipe("b", "cmd-b")]
        _stub_recipes(monkeypatch, recipes)
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        out = launcher._init_shell_prologue("s", tmp_path / "proj", tmp_path, harness="claude")
        assert "{ cmd-a; }" in out
        assert "{ cmd-b; }" in out
        assert "init failed for recipe a" in out
        assert "init failed for recipe b" in out
        # A recipe with no init: contributes nothing.
        assert "noinit" not in out
        assert out.count("init failed for recipe") == 2


# ---------------------------------------------------------------------------
# TestAttachRunsInit
# ---------------------------------------------------------------------------


class TestAttachRunsInit:
    """`_attach` folds the init prologue into the attach shell BEFORE the harness starts."""

    def _capture_argv(self, monkeypatch) -> dict:
        captured: dict = {}

        def fake_execvp(rt, argv):
            captured["argv"] = argv
            raise SystemExit(0)  # stop after building the exec argv

        monkeypatch.setattr(launcher.os, "execvp", fake_execvp)
        monkeypatch.setattr(launcher, "_touch_attach_marker", lambda inst: None)
        return captured

    def test_shell_mode_runs_init_before_exec_bash(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("beads", "bd init")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        captured = self._capture_argv(monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()
        with pytest.raises(SystemExit):
            launcher._attach("podman", "claude", "inst", proj,
                             stack="s", mount_path=tmp_path, shell=True)
        shell_cmd = captured["argv"][-1]
        assert "source ~/.bashrc" in shell_cmd
        assert "export PROJECT_DIR=" in shell_cmd
        assert "{ bd init; }" in shell_cmd
        # init runs BEFORE the interactive shell.
        assert shell_cmd.index("bd init") < shell_cmd.index("exec bash -l")
        assert shell_cmd.rstrip().endswith("exec bash -l")

    def test_harness_mode_runs_init_before_harness(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("beads", "bd init")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        captured = self._capture_argv(monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()
        with pytest.raises(SystemExit):
            launcher._attach("podman", "claude", "inst", proj,
                             stack="s", mount_path=tmp_path, shell=False)
        shell_cmd = captured["argv"][-1]
        assert "export PROJECT_DIR=" in shell_cmd
        assert "claude" in shell_cmd
        # The literal "claude" also appears as the HARNESS export value, so anchor on the tail
        # command (`&& claude …`) rather than the bare word.
        harness_at = shell_cmd.index("&& claude ")
        assert shell_cmd.index("export PROJECT_DIR=") < harness_at
        assert shell_cmd.index("bd init") < harness_at

    def test_no_secrets_in_shell_cmd(self, tmp_path, monkeypatch):
        _stub_recipes(monkeypatch, [_recipe("beads", "bd init")])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        captured = self._capture_argv(monkeypatch)
        proj = tmp_path / "proj"
        proj.mkdir()
        with pytest.raises(SystemExit):
            launcher._attach("podman", "claude", "inst", proj,
                             stack="s", mount_path=tmp_path, shell=False)
        shell_cmd = captured["argv"][-1]
        assert "varlock" not in shell_cmd
        assert "--secret" not in shell_cmd


# ---------------------------------------------------------------------------
# TestHostInitEnvPropagation
# ---------------------------------------------------------------------------


class TestHostInitEnvPropagation:
    """`init.run`'s exports must reach the HOST agent, not die with a subprocess.

    Model A's guarantee is that init runs in the shell that then starts the harness. The container
    path gets that from `_init_shell_prologue`'s brace group; host-side the agent is exec'd from
    `os.environ`, so `_host_run_inits` has to carry the delta back. Until it did, every host `init:`
    that was a plain `export` was a silent no-op — beads' `bd-shim` PATH line (the shim was
    installed and never on PATH, observed 2026-07-26) and pulumi's `PULUMI_HOME`.
    """

    @pytest.fixture(autouse=True)
    def _isolated_environ(self, monkeypatch):
        """Real bash runs here, and the function under test writes to os.environ by design."""
        monkeypatch.setattr(os, "environ", dict(os.environ))

    def _run(self, monkeypatch, tmp_path, run: str) -> None:
        _stub_recipes(monkeypatch, [_recipe("r", run)])
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        proj = tmp_path / "proj"
        proj.mkdir(exist_ok=True)
        launcher._host_run_inits("s", proj, harness="claude")

    def test_an_exported_var_reaches_the_agent_env(self, tmp_path, monkeypatch):
        self._run(monkeypatch, tmp_path, 'export HARNESSED_TEST_VAR="hello world"')
        assert os.environ["HARNESSED_TEST_VAR"] == "hello world"

    def test_path_additions_are_prepended_not_replaced(self, tmp_path, monkeypatch):
        """The launcher composed the agent's PATH (stack tools dir first). A `bash -lc` login shell
        also re-runs the user's profile, so assigning its PATH wholesale would hand the agent a
        different toolchain. Only what init ADDED is taken."""
        os.environ["PATH"] = f"/stack/tools/bin{os.pathsep}/usr/bin"
        self._run(monkeypatch, tmp_path, 'export PATH="/shim/dir:$PATH"')
        entries = os.environ["PATH"].split(os.pathsep)
        assert entries[0] == "/shim/dir"
        assert "/stack/tools/bin" in entries and "/usr/bin" in entries

    def test_a_no_op_init_changes_nothing(self, tmp_path, monkeypatch):
        """The delta is captured inside the init shell, so profile-sourced variables — which are
        not something a recipe asked to export — must not ride along."""
        before = dict(os.environ)
        self._run(monkeypatch, tmp_path, "true")
        assert dict(os.environ) == before

    def test_a_failing_init_aborts_and_propagates_nothing(self, tmp_path, monkeypatch):
        with pytest.raises(typer.Exit):
            self._run(monkeypatch, tmp_path, 'export HARNESSED_TEST_VAR=set; exit 3')
        assert "HARNESSED_TEST_VAR" not in os.environ

    def test_shell_bookkeeping_is_not_propagated(self, tmp_path, monkeypatch):
        """PWD is the init shell's cwd (the project); adopting it would relocate the agent."""
        os.environ["PWD"] = "/somewhere/else"
        self._run(monkeypatch, tmp_path, "true")
        assert os.environ["PWD"] == "/somewhere/else"
