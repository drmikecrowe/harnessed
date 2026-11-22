"""Git catalogs: add, update, list, remove, and the no-network build rule.

HF-20261122-private-catalogs-add-two, AC-4, AC-5, AC-6, AC-11 and AC-12. Every URL is a local bare
repository under `tmp_path`, so no test reaches a network.
"""

from __future__ import annotations

import shutil
import sys

import pytest
from catalog_env import commit, entry, git, install, project, push, remote
from typer.testing import CliRunner

from harnessed import catalogsources, launcher, paths

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = install(monkeypatch, tmp_path)
    yield e
    catalogsources.reset()


def _head(d) -> str:
    return git("rev-parse", "HEAD", cwd=d)


def _reg_bytes() -> bytes | None:
    f = catalogsources.registry_file()
    return f.read_bytes() if f.exists() else None


def _no_git(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"git ran: {a}")

    monkeypatch.setattr(catalogsources, "_git", refuse)


class TestAdd:
    def test_s4_1_clones_and_locks(self, env, tmp_path):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        result = runner.invoke(launcher.app, ["catalog", "add", str(bare), "--ref", "main"])
        assert result.exit_code == 0, result.output
        clone = env.clones / "harnessed-catalog"
        assert _head(clone) == c1
        assert catalogsources.load_registry() == [
            {"name": "harnessed-catalog", "url": str(bare), "ref": "main", "sha": c1}
        ]

    @pytest.mark.parametrize(
        ("url", "name"),
        [
            ("git@github.com:drmikecrowe/harnessed-catalog.git", "harnessed-catalog"),
            ("https://example.invalid/a/b/team-cat", "team-cat"),
            ("git@host:solo.git", "solo"),
            ("/srv/repos/x.git/", "x"),
        ],
    )
    def test_name_from_url(self, url, name):
        assert catalogsources.name_from_url(url) == name

    def test_s4_2_no_ref_locks_the_default_branch(self, env, tmp_path):
        bare, work = remote(tmp_path, branch="trunk")
        c2 = _head(work)
        assert runner.invoke(launcher.app, ["catalog", "add", str(bare)]).exit_code == 0
        (item,) = catalogsources.load_registry()
        assert (item["ref"], item["sha"]) == ("trunk", c2)

    def test_s4_3_a_taken_name_needs_name(self, env, tmp_path):
        bare, _ = remote(tmp_path)
        other, _ = remote(tmp_path / "o")
        catalogsources.add(str(bare), "main")
        before = _reg_bytes()
        result = runner.invoke(launcher.app, ["catalog", "add", str(other)])
        assert result.exit_code != 0 and "--name" in result.output
        assert _reg_bytes() == before
        result = runner.invoke(launcher.app, ["catalog", "add", str(other), "--name", "second"])
        assert result.exit_code == 0, result.output
        assert (env.clones / "second" / "stacks" / "team").is_dir()
        assert [i["name"] for i in catalogsources.load_registry()] == ["harnessed-catalog", "second"]

    def test_s4_4_a_failed_clone_leaves_nothing(self, env, tmp_path):
        result = runner.invoke(launcher.app, ["catalog", "add", str(tmp_path / "no-such-repo.git")])
        assert result.exit_code != 0
        assert _reg_bytes() is None
        assert not (env.clones / "no-such-repo").exists()
        assert not env.clones.exists() or list(env.clones.iterdir()) == []

    def test_s4_4_a_bad_ref_leaves_nothing(self, env, tmp_path):
        bare, _ = remote(tmp_path)
        result = runner.invoke(launcher.app, ["catalog", "add", str(bare), "--ref", "nope"])
        assert result.exit_code != 0
        assert _reg_bytes() is None
        assert not env.clones.exists() or list(env.clones.iterdir()) == []

    @pytest.mark.parametrize(
        ("url", "ref"),
        [("--upload-pack=touch /tmp/pwned", None), ("{bare}", "--output=/tmp/x"), ("ext::sh -c id", None)],
    )
    def test_an_option_shaped_url_or_ref_is_refused(self, env, tmp_path, monkeypatch, url, ref):
        """Adversary round 1: a url or ref that git reads as an option, or an ext:: url, never runs."""
        bare, _ = remote(tmp_path)
        _no_git(monkeypatch)
        with pytest.raises(catalogsources.CatalogError):
            catalogsources.add(url.format(bare=bare), ref, "x")
        assert _reg_bytes() is None

    @pytest.mark.parametrize("bad", ["a/b", "..", "x..y/", "sp ace", "semi;colon", ".hidden", ""])
    def test_s4_5_bad_names_are_refused(self, env, tmp_path, bad):
        bare, _ = remote(tmp_path)
        result = runner.invoke(launcher.app, ["catalog", "add", str(bare), "--name", bad])
        assert result.exit_code != 0
        assert _reg_bytes() is None


class TestBuildReadsTheLock:
    def test_s5_1_resolves_from_the_clone_without_git(self, env, tmp_path, monkeypatch):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        _no_git(monkeypatch)
        catalogsources.reset()
        team = paths.find_in_catalog("stacks", "team")
        assert team == env.clones / "harnessed-catalog" / "stacks" / "team"

    def test_s5_2_a_moved_remote_changes_nothing(self, env, tmp_path, monkeypatch):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), "main")
        commit(work, "second")
        push(work)
        _no_git(monkeypatch)
        paths.find_in_catalog("stacks", "team")
        assert _head(env.clones / "harnessed-catalog") == c1
        assert catalogsources.load_registry()[0]["sha"] == c1

    def test_s5_3_a_missing_clone_stops_a_build(self, env, tmp_path, monkeypatch, capsys):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        shutil.rmtree(env.clones / "harnessed-catalog")
        called = []
        monkeypatch.setattr(launcher, "app", lambda: called.append(1))
        monkeypatch.setattr(sys, "argv", ["harnessed", "build", "team", "claude"])
        with pytest.raises(SystemExit) as caught:
            launcher.main()
        assert caught.value.code not in (0, None)
        err = capsys.readouterr().err
        assert "harnessed-catalog" in err and "harnessed catalog update" in err
        assert called == []

    def test_s5_3_catalog_subcommands_skip_the_check(self, env, tmp_path, monkeypatch):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        shutil.rmtree(env.clones / "harnessed-catalog")
        called = []
        monkeypatch.setattr(launcher, "app", lambda: called.append(1))
        monkeypatch.setattr(sys, "argv", ["harnessed", "catalog", "list"])
        launcher.main()
        assert called == [1]


class TestUpdate:
    def test_s6_1_moves_the_lock(self, env, tmp_path):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), "main")
        c3 = commit(work, "third")
        push(work)
        result = runner.invoke(launcher.app, ["catalog", "update", "harnessed-catalog"])
        assert result.exit_code == 0, result.output
        assert _head(env.clones / "harnessed-catalog") == c3
        assert catalogsources.load_registry()[0]["sha"] == c3
        assert c1 in result.output and c3 in result.output

    def test_s6_2_all_in_order_and_one_failure_does_not_stop_the_rest(self, env, tmp_path):
        bare1, _ = remote(tmp_path / "a", "one")
        bare2, work2 = remote(tmp_path / "b", "two")
        catalogsources.add(str(bare1), "main")
        catalogsources.add(str(bare2), "main")
        commit(work2, "next")
        push(work2)
        shutil.rmtree(bare1)
        result = runner.invoke(launcher.app, ["catalog", "update"])
        assert result.exit_code != 0
        assert catalogsources.load_registry()[1]["sha"] == _head(work2)
        assert result.output.index("one") < result.output.index("two")

    def test_s6_3_a_full_sha_does_not_change(self, env, tmp_path):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), c1)
        commit(work, "later")
        push(work)
        result = runner.invoke(launcher.app, ["catalog", "update"])
        assert result.exit_code == 0, result.output
        assert "did not change" in result.output
        assert catalogsources.load_registry()[0]["sha"] == c1

    def test_s6_4_a_missing_clone_is_cloned_again(self, env, tmp_path):
        bare, work = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        shutil.rmtree(env.clones / "harnessed-catalog")
        c3 = commit(work, "third")
        push(work)
        result = runner.invoke(launcher.app, ["catalog", "update", "harnessed-catalog"])
        assert result.exit_code == 0, result.output
        assert _head(env.clones / "harnessed-catalog") == c3
        assert catalogsources.load_registry()[0]["sha"] == c3

    def test_s6_3_a_pinned_catalog_updates_offline(self, env, tmp_path):
        """mutmut survivor `x_update__mutmut_30`: a full-SHA ref present in the clone needs no fetch."""
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), c1)
        shutil.rmtree(bare)
        result = runner.invoke(launcher.app, ["catalog", "update"])
        assert result.exit_code == 0, result.output
        assert "did not change" in result.output

    def test_s6_4_a_reclone_keeps_the_recorded_ref(self, env, tmp_path):
        """mutmut survivor `x_update__mutmut_21`: the clone again follows the ref, not the default branch."""
        bare, work = remote(tmp_path)
        git("checkout", "-q", "-b", "side", cwd=work)
        side = commit(work, "side")
        push(work, "side")
        catalogsources.add(str(bare), "side")
        shutil.rmtree(env.clones / "harnessed-catalog")
        assert runner.invoke(launcher.app, ["catalog", "update"]).exit_code == 0
        assert _head(env.clones / "harnessed-catalog") == side

    def test_s6_5_a_failed_fetch_changes_nothing(self, env, tmp_path):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), "main")
        shutil.rmtree(bare)
        before = _reg_bytes()
        result = runner.invoke(launcher.app, ["catalog", "update"])
        assert result.exit_code != 0
        assert _reg_bytes() == before
        assert _head(env.clones / "harnessed-catalog") == c1

    def test_s6_6_an_unknown_name(self, env, tmp_path):
        before = _reg_bytes()
        result = runner.invoke(launcher.app, ["catalog", "update", "ghost"])
        assert result.exit_code != 0 and "ghost" in result.output
        assert _reg_bytes() == before

    def test_a_hand_edit_in_the_clone_is_restored(self, env, tmp_path):
        bare, work = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        y = env.clones / "harnessed-catalog" / "stacks" / "team" / "stack.yaml"
        y.write_text("edited\n")
        c3 = commit(work, "third")
        push(work)
        assert runner.invoke(launcher.app, ["catalog", "update"]).exit_code == 0
        assert _head(env.clones / "harnessed-catalog") == c3
        assert y.read_text() != "edited\n"


class TestList:
    def test_s11_1_six_rows_in_source_order(self, env, tmp_path):
        bare, work = remote(tmp_path)
        c1 = _head(work)
        catalogsources.add(str(bare), "main")
        cat = tmp_path / "cat"
        cat.mkdir()
        proj = project(tmp_path)
        catalogsources.trust(proj)
        env.overlay.mkdir(parents=True)
        env.generated.mkdir(parents=True)
        catalogsources.set_flag_sources([cat])
        result = runner.invoke(launcher.app, ["catalog", "list", "--project", str(proj)])
        assert result.exit_code == 0, result.output
        rows = [r for r in result.output.splitlines() if r.strip()]
        kinds = [r.split()[0] for r in rows]
        assert kinds == ["flag", "project", "overlay", "git", "shipped", "generated"]
        git_row = rows[3]
        assert "harnessed-catalog" in git_row and "main" in git_row and c1 in git_row
        assert "trusted" in rows[1]

    def test_s11_2_an_untrusted_project_row(self, env, tmp_path):
        proj = project(tmp_path)
        env.overlay.mkdir(parents=True)
        result = runner.invoke(launcher.app, ["catalog", "list", "--project", str(proj)])
        rows = [r for r in result.output.splitlines() if r.split()[:1] in (["project"], ["overlay"])]
        assert rows[0].split()[0] == "project" and "untrusted" in rows[0]

    def test_s11_3_the_baseline(self, env, tmp_path, monkeypatch):
        env.overlay.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(launcher.app, ["catalog", "list"])
        kinds = [r.split()[0] for r in result.output.splitlines() if r.strip()]
        assert kinds == ["overlay", "shipped"]

    def test_s11_4_list_reads_only(self, env, tmp_path, monkeypatch):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        proj = project(tmp_path)
        catalogsources.trust(proj)
        snap = {p: p.read_bytes() for p in env.tmp.rglob("*") if p.is_file() and "remotes" not in p.parts}
        _no_git(monkeypatch)
        assert runner.invoke(launcher.app, ["catalog", "list", "--project", str(proj)]).exit_code == 0
        assert {p: p.read_bytes() for p in snap} == snap


class TestRemove:
    def test_s12_1_drops_one_and_keeps_the_order(self, env, tmp_path):
        for sub, name in (("a", "first"), ("b", "harnessed-catalog"), ("c", "third")):
            bare, _ = remote(tmp_path / sub, name)
            catalogsources.add(str(bare), "main")
        heads = {n: _head(env.clones / n) for n in ("first", "third")}
        result = runner.invoke(launcher.app, ["catalog", "remove", "harnessed-catalog"])
        assert result.exit_code == 0, result.output
        assert [i["name"] for i in catalogsources.load_registry()] == ["first", "third"]
        assert not (env.clones / "harnessed-catalog").exists()
        assert {n: _head(env.clones / n) for n in heads} == heads

    def test_s12_2_a_gone_clone_still_removes(self, env, tmp_path):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        shutil.rmtree(env.clones / "harnessed-catalog")
        assert runner.invoke(launcher.app, ["catalog", "remove", "harnessed-catalog"]).exit_code == 0
        assert catalogsources.load_registry() == []

    def test_s12_3_an_unknown_name(self, env, tmp_path):
        bare, _ = remote(tmp_path)
        catalogsources.add(str(bare), "main")
        before = _reg_bytes()
        result = runner.invoke(launcher.app, ["catalog", "remove", "ghost"])
        assert result.exit_code != 0 and "ghost" in result.output
        assert _reg_bytes() == before
        assert (env.clones / "harnessed-catalog").is_dir()


def test_update_never_lists_a_clone_for_pin_rewrites(env, tmp_path):
    from harnessed import catalogseed

    catalogsources._write_registry([{"name": "g", "url": "u", "ref": "main", "sha": "a" * 40}])
    entry(env.clones / "g", "recipes", "inclone")
    entry(env.clones / "g", "agents", "agentinclone")
    shipped = entry(env.shipped, "recipes", "shipped-one")
    assert paths.find_in_catalog("recipes", "inclone").is_relative_to(env.clones)
    assert catalogseed._update_recipe_dirs() == [shipped]
    assert catalogseed._update_agent_dirs() == []


def test_the_registry_entry_is_readable_yaml(env, tmp_path):
    bare, _ = remote(tmp_path)
    catalogsources.add(str(bare), "main")
    text = catalogsources.registry_file().read_text()
    assert "catalogs:" in text and "harnessed-catalog" in text
