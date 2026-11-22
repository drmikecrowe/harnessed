"""The private-key gate and the storage name of a scoped stack.

HF-20261122-private-catalogs-add-two, AC-8 and AC-9.
"""

from __future__ import annotations

import inspect

import pytest
from catalog_env import entry, install, project

from harnessed import catalogsources, credmounts, launcher, launchscript, layout, paths, setupenv, volumes

_REPO_HOME = paths.harnessed_home()


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    yield e
    catalogsources.reset()


def _keyed(root):
    return entry(root, "stacks", "keyed", "name: keyed\nrecipes: []\nssh_keys: [id_ed25519]\n")


class TestPrivateKeyGate:
    @pytest.mark.parametrize("source", ["flag", "project", "git"])
    def test_s8_1_new_sources_drop_ssh_keys(self, env, tmp_path, capsys, source):
        if source == "flag":
            _keyed(tmp_path / "cat")
            catalogsources.set_flag_sources([tmp_path / "cat"])
        elif source == "project":
            proj = project(tmp_path)
            _keyed(proj / ".harnessed" / "catalog")
            catalogsources.trust(proj)
            catalogsources.set_project_dir(proj)
        else:
            catalogsources._write_registry([{"name": "g", "url": "u", "ref": "main", "sha": "a" * 40}])
            _keyed(env.clones / "g")
        assert credmounts._stack_from_overlay("keyed") is False
        assert credmounts._trusted_ssh_keys(["id_ed25519"], False, "keyed") == []
        cap = capsys.readouterr()
        assert "ignoring ssh_keys from shared-catalog stack 'keyed'" in cap.out + cap.err

    def test_s8_2_the_overlay_keeps_them(self, env):
        _keyed(env.overlay)
        assert credmounts._stack_from_overlay("keyed") is True

    def test_s8_3_a_flag_symlinked_into_the_overlay_is_not_the_overlay(self, env, tmp_path):
        inside = env.overlay / "sub"
        _keyed(inside)
        link = tmp_path / "link"
        link.symlink_to(inside)
        catalogsources.set_flag_sources([link])
        assert credmounts._stack_from_overlay("keyed") is False

    def test_s8_4_a_project_stack_is_not_the_overlay_for_services(self, env, tmp_path):
        proj = project(tmp_path)
        _keyed(proj / ".harnessed" / "catalog")
        _keyed(env.overlay)
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        assert credmounts._stack_from_overlay("keyed") is False

    def test_container_run_uses_the_source_kind_gate(self):
        src = inspect.getsource(launcher.container_run)
        assert 'stack_from_overlay = paths.catalog_source_kind("stacks", stack) == "overlay"' in src
        assert "is_relative_to(paths.user_catalog()" not in src


class TestStorageName:
    def _scoped_default(self, tmp_path, rel="a"):
        proj = project(tmp_path, rel)
        entry(proj / ".harnessed" / "catalog", "stacks", "default")
        catalogsources.trust(proj)
        return proj

    def test_s9_1_assemble_writes_a_scoped_profile(self, env, tmp_path, monkeypatch):
        from harnessed import assemble

        monkeypatch.setenv("HARNESSED_DIR", str(_REPO_HOME))
        plain = paths.profile_dir("default", "claude")
        plain.mkdir(parents=True)
        (plain / ".mcp.json").write_text("{}\n")
        proj = self._scoped_default(tmp_path)
        catalogsources.set_project_dir(proj)
        suffix = catalogsources.scope_suffix()
        result = assemble.assemble(None, "default", paths.xdg_data_home() / "harnessed", "claude")
        assert result.profile_dir == paths.profiles_root() / f"default{suffix}" / "claude"
        assert (plain / ".mcp.json").read_text() == "{}\n"
        assert sorted(p.name for p in plain.iterdir()) == [".mcp.json"]

    def test_s9_2_two_projects_get_separate_state(self, env, tmp_path):
        names = []
        for rel in ("a", "b"):
            catalogsources.reset()
            catalogsources.set_project_dir(self._scoped_default(tmp_path, rel))
            names.append((
                paths.profile_dir("default", "claude"),
                paths.host_home("default", "claude"),
                layout._derived_image("default", "claude"),
                setupenv._stack_tools_dirs("default")[0],
                volumes._stack_config_volume("default", "claude"),
                volumes._stack_tools_volume("default", "claude"),
                paths.instance_name("default", "claude", tmp_path),
                paths.claude_imports_dir("default"),
                paths.claude_imports_answer_file("default"),
            ))
        for a, b in zip(*names, strict=True):
            assert a != b
        assert all("default-" in str(v) for v in names[0])

    def test_s9_3_an_unrelated_project_recipe_does_not_scope(self, env, tmp_path):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "recipes", "extra")
        entry(env.shipped, "stacks", "default")
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        assert paths.storage_name("default") == "default"
        assert paths.profile_dir("default", "claude") == paths.profiles_root() / "default" / "claude"

    def test_s9_4_a_project_recipe_the_stack_loads_scopes_it(self, env, tmp_path):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "recipes", "time")
        entry(env.shipped, "recipes", "time")
        entry(env.shipped, "stacks", "default", "name: default\nrecipes: [time]\n")
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        assert paths.storage_name("default") == f"default{catalogsources.scope_suffix()}"

    def test_a_project_parent_scopes_the_child(self, env, tmp_path):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "stacks", "base")
        entry(env.shipped, "stacks", "child", "name: child\nextends: base\nrecipes: []\n")
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        assert paths.storage_name("child") != "child"

    def test_a_project_service_scopes_the_stack(self, env, tmp_path):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "services", "svc", "name: svc\n")
        entry(env.shipped, "stacks", "s", "name: s\nrecipes: []\nservices: [svc]\n")
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        assert paths.storage_name("s") != "s"

    def test_s9_5_another_project_reads_the_plain_profile(self, env, tmp_path):
        self._scoped_default(tmp_path)
        b = tmp_path / "b"
        (b / ".git").mkdir(parents=True)
        catalogsources.set_project_dir(b)
        assert paths.profile_dir("default", "claude") == paths.profiles_root() / "default" / "claude"

    def test_s9_6_launcher_names_keep_the_plain_name(self, env, tmp_path):
        catalogsources.set_project_dir(self._scoped_default(tmp_path))
        suffix = catalogsources.scope_suffix()
        assert paths.storage_name("default") == f"default{suffix}"
        name = launchscript.script_name("container-run", "default", "claude")
        body = launchscript._global_body("container-run", "default", "claude", tmp_path)
        assert suffix not in name and suffix not in body
        assert "--stack default " in body

    def test_the_suffix_is_eight_hex_of_the_folder_sources(self, env, tmp_path):
        import hashlib

        proj = self._scoped_default(tmp_path)
        cat = tmp_path / "cat"
        cat.mkdir()
        catalogsources.set_flag_sources([cat])
        catalogsources.set_project_dir(proj)
        joined = "\n".join([str(cat.resolve()), str((proj / ".harnessed" / "catalog").resolve())])
        assert catalogsources.scope_suffix() == "-" + hashlib.sha256(joined.encode()).hexdigest()[:8]

    def test_two_stacks_in_one_process_keep_their_own_names(self, env, tmp_path):
        """mutmut survivor `x_storage_name__mutmut_3`: the cache key holds the stack name."""
        proj = self._scoped_default(tmp_path)
        entry(env.shipped, "stacks", "other")
        catalogsources.set_project_dir(proj)
        assert paths.storage_name("default") == f"default{catalogsources.scope_suffix()}"
        assert paths.storage_name("other") == "other"

    def test_an_unknown_stack_keeps_its_name(self, env, tmp_path):
        catalogsources.set_project_dir(self._scoped_default(tmp_path))
        assert paths.storage_name("nope") == "nope"
