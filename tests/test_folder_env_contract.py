"""The folder-env contract (`launcher.harnessed_env`) — bd harnessed-0tk.7.

One definition of PROJECT_DIR / MAIN_REPO_DIR / …, injected at every surface where a
catalog-authored string or file runs. The regression these tests lock down: a `setup.condition`
used to be evaluated by a bare `bash -lc` with NO env, so `[ ! -f "${MAIN_REPO_DIR}/.beads/…" ]`
expanded MAIN_REPO_DIR to the empty string and the test passed *falsely* on an already-set-up repo.
"""

from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.schema import load_recipe


CONTRACT_KEYS = {
    "HARNESS",
    "PROJECT_DIR",
    "MAIN_REPO_DIR",
    "HARNESSED_GIT_COMMON_DIR",
    "CONTAINER_WORKSPACE_DIR",
    "HOST_WORKSPACE_DIR",
    "HOST_HOME",
}


def _recipe(tmp_path, name, *, condition=None, run=None):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    body = f"name: {name}\nsetup:\n  summary: s\n  reference: http://x\n"
    if condition:
        body += f"  condition: {condition!r}\n"
    if run:
        body += f"  run: {run!r}\n"
    (d / "recipe.yaml").write_text(body)
    return load_recipe(d, strict=True)


class TestHarnessedEnv:
    def test_every_documented_var_is_present_in_both_modes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        host = launcher.harnessed_env("s", tmp_path, harness="claude", mode="host")
        ctr = launcher.harnessed_env("s", tmp_path, harness="claude", mode="container",
                                     mount_path=tmp_path, sockets=False)
        assert CONTRACT_KEYS <= set(host)
        assert CONTRACT_KEYS <= set(ctr)

    def test_harness_is_unprefixed_so_a_script_matches_a_dockerfile_arg(self, tmp_path, monkeypatch):
        """`ARG HARNESS` in a recipe Dockerfile and `$HARNESS` in a setup script must be one token."""
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        env = launcher.harnessed_env("s", tmp_path, harness="opencode", mode="host")
        assert env["HARNESS"] == "opencode"

    def test_main_repo_dir_is_the_git_common_dir(self, tmp_path, monkeypatch):
        common = tmp_path / "bare"
        monkeypatch.setattr(paths, "git_common_dir", lambda p: common)
        env = launcher.harnessed_env("s", tmp_path / "main", harness="claude", mode="host")
        assert env["MAIN_REPO_DIR"] == str(common)
        assert env["HARNESSED_GIT_COMMON_DIR"] == str(common)

    def test_never_exports_bare_git_common_dir(self, tmp_path, monkeypatch):
        """git itself consumes GIT_COMMON_DIR — exporting it would hijack common-dir resolution the
        moment the agent cd's into a different repository."""
        monkeypatch.setattr(paths, "git_common_dir", lambda p: tmp_path / "bare")
        assert "GIT_COMMON_DIR" not in launcher.harnessed_env(
            "s", tmp_path, harness="claude", mode="host"
        )

    def test_recipe_dir_is_the_catalog_dir_on_host_and_the_mount_in_container(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        r = _recipe(tmp_path / "cat", "rr")
        host = launcher.harnessed_env("s", tmp_path, harness="claude", mode="host", recipe=r)
        ctr = launcher.harnessed_env("s", tmp_path, harness="claude", mode="container",
                                     recipe=r, sockets=False)
        assert host["HARNESSED_RECIPE_DIR"] == str(r.root)
        assert ctr["HARNESSED_RECIPE_DIR"] == f"{launcher._CTR_RECIPE_DIR}/rr"

    def test_recipe_dir_absent_when_not_recipe_scoped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "git_common_dir", lambda p: None)
        env = launcher.harnessed_env("s", tmp_path, harness="claude", mode="host")
        assert "HARNESSED_RECIPE_DIR" not in env

    def test_container_recipe_dir_is_actually_mounted(self, tmp_path):
        """$HARNESSED_RECIPE_DIR is only usable in-container if the dir is bind-mounted there."""
        d = tmp_path / "rr"
        d.mkdir()
        (d / "recipe.yaml").write_text(
            "name: rr\nsetup:\n  summary: s\n  reference: http://x\n  script: setup.sh\n"
        )
        (d / "setup.sh").write_text("#!/usr/bin/env bash\ntrue\n")
        r = load_recipe(d, strict=True)
        args = launcher._setup_script_mounts([r])
        assert f"{r.root}:{launcher._CTR_RECIPE_DIR}/rr:ro" in args


class TestConditionEvalSeesTheContract:
    """The acceptance criterion: a condition referencing ${MAIN_REPO_DIR} resolves to the real path
    at BOTH eval sites."""

    def _repo(self, tmp_path, monkeypatch, *, marker: bool):
        common = tmp_path / "bare"
        (common / ".beads").mkdir(parents=True)
        if marker:
            (common / ".beads" / "metadata.json").write_text("{}")
        monkeypatch.setattr(paths, "git_common_dir", lambda p: common)
        proj = tmp_path / "main"
        proj.mkdir()
        return proj

    COND = '[ ! -f "${MAIN_REPO_DIR}/.beads/metadata.json" ]'

    @pytest.mark.parametrize("marker,expected", [(False, ["r"]), (True, [])])
    def test_notice_site(self, tmp_path, monkeypatch, marker, expected):
        proj = self._repo(tmp_path, monkeypatch, marker=marker)
        r = _recipe(tmp_path / "cat", "r", condition=self.COND)
        got = launcher._collect_setup_notices([r], proj, "s", "claude")
        assert [x.name for x in got] == expected

    @pytest.mark.parametrize("marker,ran", [(False, True), (True, False)])
    def test_host_run_site(self, tmp_path, monkeypatch, marker, ran):
        proj = self._repo(tmp_path, monkeypatch, marker=marker)
        stamp = tmp_path / "ran"
        r = _recipe(tmp_path / "cat", "r", condition=self.COND, run=f"touch {stamp}")
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda _c, _s: (None, [r]))
        monkeypatch.setattr(paths, "xdg_data_home", lambda: tmp_path / "xdg")
        launcher._host_run_setups("s", proj, harness="claude")
        assert stamp.exists() is ran

    def test_env_less_eval_would_have_passed_falsely(self, tmp_path, monkeypatch):
        """Documents the bug: with no env, ${MAIN_REPO_DIR} is empty, `-f /.beads/metadata.json` is
        false, so the condition exits 0 ("still needed") on an already-set-up repo."""
        import subprocess

        proj = self._repo(tmp_path, monkeypatch, marker=True)
        bare = subprocess.run(["bash", "-lc", self.COND], cwd=str(proj), env={})
        assert bare.returncode == 0  # wrong answer — which is why the contract must be injected
        assert launcher._collect_setup_notices(
            [_recipe(tmp_path / "cat", "r", condition=self.COND)], proj, "s", "claude"
        ) == []  # right answer, with the contract
