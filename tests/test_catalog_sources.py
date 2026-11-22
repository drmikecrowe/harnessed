"""Catalog source order, `--catalog`, project discovery, and the shadow warning.

HF-20261122-private-catalogs-add-two, AC-1, AC-2, AC-7 and AC-10.
"""

from __future__ import annotations

import sys

import pytest
from catalog_env import entry, install, project
from typer.testing import CliRunner

from harnessed import catalogsources, launcher, paths

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    yield e
    catalogsources.reset()


def _run_main(monkeypatch, argv):
    """Run `launcher.main()` with `argv`; return the exit code."""
    monkeypatch.setattr(sys, "argv", ["harnessed", *argv])
    with pytest.raises(SystemExit) as caught:
        launcher.main()
    return caught.value.code


class TestFlagSource:
    def test_s1_1_flag_before_the_command(self, env, tmp_path, monkeypatch, capsys):
        cat = tmp_path / "cat"
        hello = entry(cat, "recipes", "hello")
        entry(cat, "stacks", "hi")
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: type("R", (), {"returncode": 1})())
        code = _run_main(monkeypatch, ["--catalog", str(cat), "list"])
        assert code in (0, None)
        assert "  hi  (" in capsys.readouterr().out
        assert paths.find_in_catalog("recipes", "hello") == hello

    def test_s1_2_flag_after_the_command(self, env, tmp_path, monkeypatch, capsys):
        cat = tmp_path / "cat"
        entry(cat, "stacks", "hi")
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: type("R", (), {"returncode": 1})())
        _run_main(monkeypatch, ["list", f"--catalog={cat}"])
        assert "  hi  (" in capsys.readouterr().out

    def test_s1_3_first_flag_wins(self, env, tmp_path):
        one = entry(tmp_path / "one", "recipes", "time")
        entry(tmp_path / "two", "recipes", "time")
        catalogsources.set_flag_sources([tmp_path / "one", tmp_path / "two"])
        assert paths.find_in_catalog("recipes", "time") == one

    def test_s1_4_missing_dir_stops_before_any_build(self, env, tmp_path, monkeypatch, capsys):
        called = []
        monkeypatch.setattr(launcher, "app", lambda: called.append(1))
        code = _run_main(monkeypatch, ["--catalog", str(tmp_path / "none"), "build", "default", "claude"])
        assert code not in (0, None)
        assert str(tmp_path / "none") in capsys.readouterr().err
        assert called == []
        assert not paths.profiles_root().exists()

    def test_flag_reaches_a_child_process_through_the_environment(self, env, tmp_path, monkeypatch):
        cat = tmp_path / "cat"
        cat.mkdir()
        monkeypatch.setattr(launcher, "app", lambda: None)
        monkeypatch.setattr(sys, "argv", ["harnessed", "--catalog", str(cat), "list"])
        launcher.main()
        assert catalogsources.ENV_FLAG in __import__("os").environ
        catalogsources.reset()
        assert catalogsources.flag_sources() == [cat.resolve()]

    def test_flag_after_double_dash_is_passthrough(self, env, tmp_path):
        argv, dirs = launcher._extract_catalog_flags(["host-run", "claude", "--", "--catalog", "x"])
        assert dirs == [] and argv == ["host-run", "claude", "--", "--catalog", "x"]

    def test_two_exported_folders_both_reach_a_child(self, env, tmp_path):
        """mutmut survivor `x_flag_sources__mutmut_10`: the variable splits on os.pathsep."""
        one, two = tmp_path / "one", tmp_path / "two"
        catalogsources.set_flag_sources([one, two])
        catalogsources.reset()
        assert catalogsources.flag_sources() == [one.resolve(), two.resolve()]

    def test_flag_after_cli_belongs_to_the_harness(self, env, tmp_path):
        """Adversary round 1: `--cli` hands the rest of argv to the harness, as `--` does."""
        cat = tmp_path / "cat"
        cat.mkdir()
        argv = ["--catalog", str(cat), "host-acp", "claude", "--stack", "s", "--cli", "--catalog", "y"]
        rest, dirs = launcher._extract_catalog_flags(argv)
        assert dirs == [cat.resolve()]
        assert rest == ["host-acp", "claude", "--stack", "s", "--cli", "--catalog", "y"]

    def test_host_acp_sets_the_project_before_it_checks_the_build(self, env, monkeypatch):
        """Adversary round 1, blocking: host-acp read `is_built` with no project directory set."""
        order = []
        monkeypatch.setattr(launcher, "_set_catalog_project", lambda p: order.append(("project", p)))

        def built(*a):
            order.append(("is_built", a))
            raise SystemExit(0)

        monkeypatch.setattr(launcher.paths, "is_built", built)
        monkeypatch.setattr(launcher, "set_acp_mode", lambda *_: None)
        runner.invoke(launcher.app, ["host-acp", "claude", "--stack", "s"])
        assert order[0] == ("project", None) and order[1][0] == "is_built"

    def test_a_corrupt_trust_record_is_an_error_not_a_traceback(self, env, tmp_path, monkeypatch, capsys):
        """Adversary round 1: an unreadable trust record or registry must name the file."""
        catalogsources.trust_file().parent.mkdir(parents=True)
        catalogsources.trust_file().write_text("{not json")
        project(tmp_path)
        monkeypatch.chdir(tmp_path / "proj")

        def boom():
            catalogsources.set_project_dir(tmp_path / "proj")
            paths.catalog_roots()

        monkeypatch.setattr(launcher, "app", boom)
        code = _run_main(monkeypatch, ["list"])
        assert code not in (0, None)
        assert str(catalogsources.trust_file()) in capsys.readouterr().err

    @pytest.mark.parametrize("body", ["catalogs: [{name: x}]\n", "catalogs: 3\n", "[: bad\n"])
    def test_a_corrupt_registry_is_an_error_not_a_traceback(self, env, body, monkeypatch, capsys):
        catalogsources.registry_file().parent.mkdir(parents=True)
        catalogsources.registry_file().write_text(body)
        code = _run_main(monkeypatch, ["list"])
        assert code not in (0, None)
        assert str(catalogsources.registry_file()) in capsys.readouterr().err


class TestProjectDiscovery:
    def test_s2_1_found_from_a_subfolder(self, env, tmp_path, monkeypatch, capsys):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "stacks", "mine")
        catalogsources.trust(proj)
        (proj / "src" / "app").mkdir(parents=True)
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: type("R", (), {"returncode": 1})())
        result = runner.invoke(launcher.app, ["list", "--project", str(proj / "src" / "app")])
        assert "  mine  (" in result.output

    def test_s2_2_nearest_wins(self, env, tmp_path):
        proj = project(tmp_path)
        sub = tmp_path / "proj" / "sub"
        (sub / ".harnessed" / "catalog").mkdir(parents=True)
        catalogsources.trust(proj)
        catalogsources.trust(sub)
        catalogsources.set_project_dir(sub)
        roots = paths.catalog_roots()
        assert (sub / ".harnessed" / "catalog").resolve() in roots
        assert (proj / ".harnessed" / "catalog").resolve() not in roots

    def test_s2_3_stops_at_the_git_top_level(self, env, tmp_path):
        (tmp_path / ".harnessed" / "catalog").mkdir(parents=True)
        catalogsources._record_trust((tmp_path / ".harnessed" / "catalog").resolve())
        (tmp_path / "proj" / ".git").mkdir(parents=True)
        catalogsources.set_project_dir(tmp_path / "proj")
        assert (tmp_path / ".harnessed" / "catalog").resolve() not in paths.catalog_roots()

    def test_s2_4_no_git_top_level_checks_only_the_project_dir(self, env, tmp_path):
        (tmp_path / ".harnessed" / "catalog").mkdir(parents=True)
        catalogsources._record_trust((tmp_path / ".harnessed" / "catalog").resolve())
        (tmp_path / "plain").mkdir()
        assert catalogsources.discover_project_catalog(tmp_path / "plain") is None

    def test_s2_5_untrusted_is_ignored_with_one_warning(self, env, tmp_path, monkeypatch, capsys):
        proj = project(tmp_path)
        catalogsources.set_project_dir(proj)
        paths.catalog_roots()
        paths.catalog_roots()
        cat = proj / ".harnessed" / "catalog"
        assert cat.resolve() not in paths.catalog_roots()
        err = capsys.readouterr().err
        assert err.count("warning") == 1
        assert str(cat.resolve()) in err and "harnessed catalog trust" in err

    def test_s2_5_list_exits_zero(self, env, tmp_path, monkeypatch):
        proj = project(tmp_path)
        monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
        monkeypatch.setattr(launcher, "_bounded", lambda *a, **k: type("R", (), {"returncode": 0})())
        monkeypatch.setattr(launcher, "_broker_report", lambda *_: None)
        result = runner.invoke(launcher.app, ["list", "--project", str(proj)])
        assert result.exit_code == 0
        assert "harnessed catalog trust" in result.output

    def test_s2_6_untrusted_integrations_are_not_listed(self, env, tmp_path):
        proj = project(tmp_path)
        reg = proj / ".harnessed" / "catalog" / "integrations" / "evil"
        reg.mkdir(parents=True)
        (reg / "register").write_text("#!/bin/sh\n")
        catalogsources.set_project_dir(proj)
        assert "evil" not in paths.list_catalog("integrations")

    def test_s2_7_launch_anchors_on_the_path_argument(self, env, tmp_path, monkeypatch):
        proj = project(tmp_path)
        mine = entry(proj / ".harnessed" / "catalog", "stacks", "mine")
        catalogsources.trust(proj)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        launcher._set_catalog_project(str(proj))
        assert paths.find_in_catalog("stacks", "mine") == mine.resolve()

    def test_s2_8_the_cwd_does_not_count_when_a_path_is_given(self, env, tmp_path, monkeypatch):
        proj = project(tmp_path)
        entry(proj / ".harnessed" / "catalog", "stacks", "mine")
        catalogsources.trust(proj)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(proj)
        launcher._set_catalog_project(str(elsewhere))
        assert not (paths.find_in_catalog("stacks", "mine") / "stack.yaml").is_file()

    @pytest.mark.parametrize("verb", ["container-run", "host-run", "use"])
    def test_each_launch_verb_sets_the_project_from_its_path(self, env, tmp_path, monkeypatch, verb):
        seen = []

        def stop(path):
            seen.append(path)
            raise SystemExit(0)

        monkeypatch.setattr(launcher, "_set_catalog_project", stop)
        runner.invoke(launcher.app, [verb, "claude", str(tmp_path), "--stack", "x"])
        assert seen == [str(tmp_path)]

    def test_no_project_dir_set_gives_no_project_source(self, env, tmp_path, monkeypatch):
        proj = project(tmp_path)
        catalogsources.trust(proj)
        monkeypatch.chdir(proj)
        assert [k for k, _ in paths.catalog_sources()] == ["shipped"]


class TestSourceOrder:
    def _six(self, env, tmp_path):
        flag = tmp_path / "flag"
        proj = project(tmp_path)
        pcat = proj / ".harnessed" / "catalog"
        catalogsources.trust(proj)
        first = env.clones / "first"
        second = env.clones / "second"
        catalogsources._write_registry([
            {"name": "first", "url": "u1", "ref": "main", "sha": "a" * 40},
            {"name": "second", "url": "u2", "ref": "main", "sha": "b" * 40},
        ])
        copies = [entry(r, "recipes", "time") for r in (flag, pcat, env.overlay, first, second, env.shipped)]
        catalogsources.set_flag_sources([flag])
        catalogsources.set_project_dir(proj)
        return copies

    def test_s7_1_each_source_in_turn(self, env, tmp_path):
        import shutil

        copies = self._six(env, tmp_path)
        for i, copy in enumerate(copies):
            assert paths.find_in_catalog("recipes", "time") == copy.resolve(), i
            shutil.rmtree(copy)

    def test_kinds_in_source_order(self, env, tmp_path):
        self._six(env, tmp_path)
        env.generated.mkdir(parents=True)
        assert [k for k, _ in paths.catalog_sources()] == [
            "flag", "project", "overlay", "git", "git", "shipped", "generated",
        ]

    def test_s7_2_first_registered_git_catalog_wins(self, env, tmp_path):
        catalogsources._write_registry([
            {"name": "first", "url": "u1", "ref": "main", "sha": "a" * 40},
            {"name": "second", "url": "u2", "ref": "main", "sha": "b" * 40},
        ])
        a = entry(env.clones / "first", "recipes", "time")
        entry(env.clones / "second", "recipes", "time")
        assert paths.find_in_catalog("recipes", "time") == a

    def test_s7_3_generated_never_wins(self, env, tmp_path):
        catalogsources._write_registry([{"name": "g", "url": "u", "ref": "main", "sha": "a" * 40}])
        g = entry(env.clones / "g", "stacks", "adhoc")
        entry(env.generated, "stacks", "adhoc")
        assert paths.find_in_catalog("stacks", "adhoc") == g
        assert paths.catalog_roots()[-1] == env.generated

    def test_s7_4_extends_parent_from_the_project_source(self, env, tmp_path):
        from harnessed import schema

        proj = project(tmp_path)
        pcat = proj / ".harnessed" / "catalog"
        entry(pcat, "stacks", "mine", "name: mine\nextends: default\nrecipes: []\n")
        entry(pcat, "stacks", "default", "name: default\nrecipes: [from-project]\n")
        entry(pcat, "recipes", "from-project")
        entry(env.overlay, "stacks", "default", "name: default\nrecipes: [from-overlay]\n")
        entry(env.overlay, "recipes", "from-overlay")
        entry(env.shipped, "stacks", "default", "name: default\nrecipes: []\n")
        catalogsources.trust(proj)
        catalogsources.set_project_dir(proj)
        stack = schema.load_stack(paths.find_in_catalog("stacks", "mine"))
        assert stack.recipes == ["from-project"]

    def test_s7_5_one_directory_counts_once(self, env, tmp_path):
        cat = tmp_path / "cat"
        cat.mkdir()
        proj = tmp_path / "proj"
        (proj / ".harnessed").mkdir(parents=True)
        (proj / ".git").mkdir()
        (proj / ".harnessed" / "catalog").symlink_to(cat)
        catalogsources.trust(proj)
        catalogsources.set_flag_sources([cat])
        catalogsources.set_project_dir(proj)
        sources = paths.catalog_sources()
        assert [p for _, p in sources].count(cat.resolve()) == 1
        assert sources[0] == ("flag", cat.resolve())

    def test_must_not_unchanged_list_with_no_new_source(self, env, tmp_path):
        env.overlay.mkdir(parents=True)
        env.generated.mkdir(parents=True)
        assert paths.catalog_roots() == [paths.user_catalog(), env.shipped, env.generated]


class TestShadowWarning:
    @pytest.fixture(autouse=True)
    def _wide(self, monkeypatch):
        from harnessed import schema

        monkeypatch.setattr(schema._err, "width", 400)

    def test_s10_1_one_warning_names_both_paths(self, env, tmp_path, capsys):
        from harnessed import schema

        cat = tmp_path / "cat"
        mine = entry(cat, "recipes", "time")
        shipped = entry(env.shipped, "recipes", "time")
        entry(env.shipped, "stacks", "s", "name: s\nrecipes: [time]\n")
        catalogsources.set_flag_sources([cat])
        schema.load_stack_with_recipes(None, "s")
        schema.load_stack_with_recipes(None, "s")
        err = capsys.readouterr().err
        assert err.count("recipe 'time'") == 1
        assert str(mine.resolve()) in err and str(shipped) in err

    def test_s10_2_stacks_warn_too(self, env, tmp_path, capsys):
        catalogsources._write_registry([{"name": "g", "url": "u", "ref": "main", "sha": "a" * 40}])
        mine = entry(env.clones / "g", "stacks", "team")
        shipped = entry(env.shipped, "stacks", "team")
        paths.find_in_catalog("stacks", "team")
        err = capsys.readouterr().err
        assert err.count("stack 'team'") == 1 and str(mine) in err and str(shipped) in err

    def test_s10_3_no_warning_when_nothing_is_hidden(self, env, tmp_path, capsys):
        from harnessed import schema

        cat = tmp_path / "cat"
        entry(cat, "recipes", "hello")
        entry(cat, "stacks", "s", "name: s\nrecipes: [hello]\n")
        catalogsources.set_flag_sources([cat])
        schema.load_stack_with_recipes(None, "s")
        assert "warning" not in capsys.readouterr().err

    def test_s10_4_overlay_only_keeps_todays_warning(self, env, tmp_path, capsys):
        from harnessed import schema

        entry(env.overlay, "recipes", "time")
        entry(env.shipped, "recipes", "time")
        entry(env.shipped, "stacks", "s", "name: s\nrecipes: [time]\n")
        schema.load_stack_with_recipes(None, "s")
        err = capsys.readouterr().err
        assert err.count("warning") == 1
        assert "comes from your user overlay" in err

    def test_s10_5_the_warning_never_stops_the_load(self, env, tmp_path):
        from harnessed import schema

        cat = tmp_path / "cat"
        entry(cat, "recipes", "time")
        entry(env.shipped, "recipes", "time")
        entry(env.shipped, "stacks", "s", "name: s\nrecipes: [time]\n")
        catalogsources.set_flag_sources([cat])
        _, recipes = schema.load_stack_with_recipes(None, "s")
        assert [r.ref for r in recipes] == ["time"]
