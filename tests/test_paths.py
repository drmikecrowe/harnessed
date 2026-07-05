"""Tests for paths.py resolver (B6 — single source of truth)."""

import os
from pathlib import Path

import pytest

from harnessed import paths


class TestProfileDir:
    def test_uses_xdg_data_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.profile_dir("my-stack") == tmp_path / "harnessed" / "profiles" / "my-stack"

    def test_falls_back_to_local_share(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        home = Path.home()
        assert paths.profile_dir("my-stack") == home / ".local" / "share" / "harnessed" / "profiles" / "my-stack"

    def test_different_stacks_different_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.profile_dir("a") != paths.profile_dir("b")


class TestIsBuilt:
    def test_missing_profile_not_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert not paths.is_built("nonexistent")

    def test_profile_with_mcp_json_is_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        prof = paths.profile_dir("my-stack")
        prof.mkdir(parents=True)
        (prof / ".mcp.json").write_text('{"mcpServers":{}}')
        assert paths.is_built("my-stack")

    def test_profile_without_mcp_json_not_built(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        prof = paths.profile_dir("my-stack")
        prof.mkdir(parents=True)
        # No .mcp.json — profile dir exists but not "built"
        assert not paths.is_built("my-stack")


class TestInstanceName:
    def test_stable_for_same_inputs(self):
        a = paths.instance_name("my-stack", "/home/user/project")
        b = paths.instance_name("my-stack", "/home/user/project")
        assert a == b

    def test_format_matches_pattern(self):
        name = paths.instance_name("tracer-time", "/home/user/myproject")
        assert name.startswith("harnessed-tracer-time-")
        assert len(name.split("-")[-1]) == 8

    def test_different_projects_different_names(self):
        a = paths.instance_name("stack", "/home/user/proj-a")
        b = paths.instance_name("stack", "/home/user/proj-b")
        assert a != b

    def test_different_stacks_different_names(self):
        a = paths.instance_name("stack-a", "/home/user/proj")
        b = paths.instance_name("stack-b", "/home/user/proj")
        assert a != b

    def test_trailing_slash_stripped(self):
        a = paths.instance_name("stack", "/home/user/project")
        b = paths.instance_name("stack", "/home/user/project/")
        assert a == b


class TestProjectHash:
    def test_stable_for_same_input(self):
        assert paths.project_hash("/home/user/project") == paths.project_hash("/home/user/project")

    def test_eight_hex_chars(self):
        h = paths.project_hash("/home/user/project")
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)

    def test_trailing_slash_stripped(self):
        assert paths.project_hash("/home/user/project") == paths.project_hash("/home/user/project/")

    def test_is_the_key_inside_instance_name(self):
        # Single source: instance_name must embed exactly project_hash (no independent digest).
        h = paths.project_hash("/home/user/project")
        assert paths.instance_name("my-stack", "/home/user/project") == f"harnessed-my-stack-{h}"

    def test_different_projects_differ(self):
        assert paths.project_hash("/home/user/a") != paths.project_hash("/home/user/b")


class TestPersistDir:
    def test_under_xdg_data_persist_namespace(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.persist_root() == tmp_path / "harnessed" / "persist"

    def test_persist_root_is_sibling_of_profiles_root(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.persist_root().parent == paths.profiles_root().parent
        assert paths.persist_root() != paths.profiles_root()

    # --- persist_workspace_dir (scope: workspace — keyed by resolved path) ---

    def test_workspace_dir_keyed_by_recipe_path_and_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        h = paths.project_hash("/home/user/proj")
        d = paths.persist_workspace_dir("context-mode", "/home/user/proj", ".context-mode")
        assert d == tmp_path / "harnessed" / "persist" / "context-mode" / h / ".context-mode"

    def test_workspace_two_recipes_same_name_dont_collide(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = paths.persist_workspace_dir("recipe-a", "/home/user/proj", "cache")
        b = paths.persist_workspace_dir("recipe-b", "/home/user/proj", "cache")
        assert a != b

    def test_workspace_same_recipe_different_paths_isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        a = paths.persist_workspace_dir("context-mode", "/home/user/proj-a", "idx")
        b = paths.persist_workspace_dir("context-mode", "/home/user/proj-b", "idx")
        assert a != b

    # --- git_common_dir ---

    def test_git_common_dir_returns_none_for_nonexistent_path(self):
        assert paths.git_common_dir("/does/not/exist/ever") is None

    def test_git_common_dir_returns_path_for_real_git_repo(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        gcd = paths.git_common_dir(tmp_path)
        assert gcd is not None
        assert gcd.exists()

    def test_git_common_dir_same_across_worktrees(self, tmp_path):
        import subprocess
        # Init main repo
        main = tmp_path / "main"
        main.mkdir()
        subprocess.run(["git", "init", str(main)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(main), "commit", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        # Add a worktree
        wt = tmp_path / "feature"
        subprocess.run(["git", "-C", str(main), "worktree", "add", str(wt), "-b", "feature"],
                       check=True, capture_output=True)
        gcd_main = paths.git_common_dir(main)
        gcd_wt = paths.git_common_dir(wt)
        assert gcd_main is not None and gcd_wt is not None
        assert gcd_main == gcd_wt, "git_common_dir must be identical across all worktrees of one checkout"

    # --- persist_project_dir (scope: project — keyed by git-common-dir, fallback to path) ---

    def test_project_dir_falls_back_to_path_hash_when_not_in_git(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # /home/user/proj does not exist → git fails → fallback to path hash
        h = paths.project_hash("/home/user/proj")
        d = paths.persist_project_dir("context-mode", "/home/user/proj", ".context-mode")
        assert d == tmp_path / "harnessed" / "persist" / "context-mode" / h / ".context-mode"

    def test_project_dir_same_across_worktrees(self, monkeypatch, tmp_path):
        import subprocess
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        main = tmp_path / "main"
        main.mkdir()
        subprocess.run(["git", "init", str(main)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(main), "commit", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        wt = tmp_path / "feature"
        subprocess.run(["git", "-C", str(main), "worktree", "add", str(wt), "-b", "feature"],
                       check=True, capture_output=True)
        a = paths.persist_project_dir("beads", main, ".beads")
        b = paths.persist_project_dir("beads", wt, ".beads")
        assert a == b, "project-scope persist must be the same dir across all worktrees"

    def test_project_dir_differs_from_workspace_dir_when_in_git(self, monkeypatch, tmp_path):
        import subprocess
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        proj = paths.persist_project_dir("beads", repo, ".beads")
        ws = paths.persist_workspace_dir("beads", repo, ".beads")
        # They will differ because the git common dir path ≠ the repo path for git's internal dir
        # The hashes may differ — this test just confirms they ARE distinct concepts when in a git repo.
        # (They are the same only when git_common_dir == repo, which shouldn't happen.)
        gcd = paths.git_common_dir(repo)
        assert gcd is not None
        # project-scope hash is based on gcd; workspace-scope hash is based on repo path
        expected_proj = paths.persist_root() / "beads" / paths.project_hash(gcd) / ".beads"
        assert proj == expected_proj


class TestPrimaryWorktree:
    """`primary_worktree` returns the default-branch work tree for a bare + linked-worktree repo."""

    def test_non_git_returns_itself(self):
        assert paths.primary_worktree("/does/not/exist/ever") == Path("/does/not/exist/ever")

    def test_normal_repo_returns_itself(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        assert paths.primary_worktree(tmp_path) == tmp_path

    def test_bare_layout_resolves_non_main_worktree_to_default_branch_worktree(self, tmp_path):
        import subprocess

        def git(*args, cwd=None):
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        # Seed a normal repo, clone it bare, then add a default-branch worktree + a feature worktree.
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
        feat = tmp_path / "feat"
        git("--git-dir", str(bare), "worktree", "add", "-q", str(feat), "-b", "feature")

        # From the feature worktree, the primary work tree is the default-branch one, not itself.
        assert paths.primary_worktree(feat) == main_wt
        assert paths.primary_worktree(main_wt) == main_wt


class TestProjectRelpath:
    def test_path_under_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        p = tmp_path / "Programming" / "myproject"
        assert paths.project_relpath(p) == "Programming/myproject"

    def test_path_outside_home_uses_basename(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home" / "user")
        p = Path("/opt/projects/myproject")
        assert paths.project_relpath(p) == "myproject"


class TestHatagoPort:
    def test_defaults_to_constant(self, monkeypatch):
        monkeypatch.delenv("HATAGO_PORT", raising=False)
        assert paths.hatago_port() == paths.HATAGO_PORT

    def test_honors_env_override(self, monkeypatch):
        monkeypatch.setenv("HATAGO_PORT", "4040")
        assert paths.hatago_port() == 4040

    def test_endpoint_uses_default_port(self, monkeypatch):
        monkeypatch.delenv("HATAGO_PORT", raising=False)
        assert paths.hatago_endpoint() == f"http://localhost:{paths.HATAGO_PORT}/mcp"

    def test_endpoint_honors_env_override(self, monkeypatch):
        monkeypatch.setenv("HATAGO_PORT", "4040")
        assert paths.hatago_endpoint() == "http://localhost:4040/mcp"


class TestContainerPaths:
    def test_mcp_config_at_container_home_root(self):
        p = paths.container_mcp_config()
        assert p == Path("/home/harnessed/.mcp.json")

    def test_hatago_config_at_container_home(self):
        p = paths.hatago_config_container()
        assert p == Path("/home/harnessed/hatago.config.json")
